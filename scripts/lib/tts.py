"""Offline speech synthesis through the platform TTS engine.

On Windows this drives SAPI (System.Speech) from PowerShell, which needs no network and no
API key. Voices differ per machine, so `list_voices()` is the source of truth and the CLI
reports what is actually installed instead of assuming.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class TtsError(RuntimeError):
    """Raised when no usable speech engine is available."""


def _powershell() -> str | None:
    for cand in ("pwsh", "powershell"):
        exe = shutil.which(cand)
        if exe:
            return exe
    for cand in (r"C:\Program Files\PowerShell\7\pwsh.exe",
                 r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"):
        if Path(cand).is_file():
            return cand
    return None


def available() -> bool:
    return sys.platform.startswith("win") and _powershell() is not None


def list_voices() -> list[dict]:
    ps = _powershell()
    if not ps:
        return []
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices() | ForEach-Object {"
        "  $i = $_.VoiceInfo;"
        "  [pscustomobject]@{ name=$i.Name; culture=$i.Culture.Name; gender=$i.Gender; age=$i.Age }"
        "} | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except Exception:
        return []
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return data


def pick_voice(lang: str = "zh") -> str | None:
    voices = list_voices()
    if not voices:
        return None
    preferred = [v for v in voices if lang and v.get("culture", "").lower().startswith(lang.lower())]
    pool = preferred or voices
    for v in pool:
        if "desktop" in v.get("name", "").lower():
            return v["name"]
    return pool[0].get("name")


def synthesize(text: str, out_wav: str, voice: str | None = None, rate: int = 0,
               volume: int = 100, timeout: int = 180) -> str:
    """Write `text` to `out_wav` as 16-bit PCM. Returns the path."""
    ps = _powershell()
    if not ps:
        raise TtsError("no PowerShell available for speech synthesis")
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vs-tts-") as tmp:
        text_file = Path(tmp) / "line.txt"
        # UTF-8 without BOM keeps CJK intact when PowerShell reads it back
        text_file.write_text(text, encoding="utf-8")
        script_file = Path(tmp) / "speak.ps1"
        voice_line = (f'$s.SelectVoice("{voice}")' if voice else
                      '$s.SelectVoice(($s.GetInstalledVoices() | Where-Object {'
                      ' $_.VoiceInfo.Culture.Name -like "zh*" } | Select-Object -First 1).VoiceInfo.Name)')
        script_file.write_text(
            "$ErrorActionPreference = 'Stop';\n"
            "Add-Type -AssemblyName System.Speech;\n"
            "$text = [System.IO.File]::ReadAllText($args[0], [System.Text.Encoding]::UTF8);\n"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;\n"
            f"{voice_line};\n"
            f"$s.Rate = {max(-10, min(10, int(rate)))};\n"
            f"$s.Volume = {max(0, min(100, int(volume)))};\n"
            "$s.SetOutputToWaveFile($args[1]);\n"
            "$s.Speak($text);\n"
            "$s.Dispose();\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script_file), str(text_file), str(Path(out_wav).resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    if proc.returncode != 0 or not Path(out_wav).is_file():
        raise TtsError(f"speech synthesis failed:\n{proc.stdout}\n{proc.stderr}")
    return out_wav
