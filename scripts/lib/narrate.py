"""Narration: synthesize each line, time the visuals to the voice, and write subtitles.

The point is to remove the usual manual labour of a explainer video: you write the script,
the tool measures how long each line actually takes to speak, sets the segment durations to
match, splices one continuous voice track, and emits an SRT in sync.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from . import probe, render, spec as specmod, tts

SR = 44100


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _normalise_wav(ffmpeg: str, src: Path, dst: Path) -> None:
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", str(SR),
                    "-c:a", "pcm_s16le", str(dst)], check=True)


def _silence(ffmpeg: str, seconds: float, dst: Path) -> None:
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"anullsrc=r={SR}:cl=mono", "-t", f"{max(0.0, seconds):.3f}",
                    "-c:a", "pcm_s16le", str(dst)], check=True)


def _concat(ffmpeg: str, parts: list[Path], dst: Path, work: Path) -> None:
    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c:a", "pcm_s16le", str(dst)], check=True)


def configured(spec: dict) -> bool:
    return bool((spec.get("narration") or {}).get("lines"))


def apply(spec: dict, ffmpeg: str, force: bool = False, log=print) -> dict:
    """Synthesize (if needed), then rewrite durations, audio and subtitles in place."""
    cfg = spec.get("narration") or {}
    if not cfg.get("lines"):
        return {"applied": False}

    build = render.build_dir(spec)
    voice_dir = build / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    voice = cfg.get("voice") or tts.pick_voice(cfg.get("lang", "zh"))
    if not voice:
        raise RuntimeError("narration is configured but no speech voice is available; "
                           "run `vs.py doctor` or set narration.voice")
    rate = int(cfg.get("rate", 0))
    lead_in = float(cfg.get("lead_in", 0.4))
    tail = float(cfg.get("tail", 0.5))
    gap = float(cfg.get("gap", 0.0))
    min_duration = float(cfg.get("min_duration", 3.0))

    lines = {l["segment"]: l["text"] for l in cfg["lines"]}
    segs = specmod.segment_map(spec)
    unknown = [s for s in lines if s not in segs]
    if unknown:
        raise ValueError(f"narration references unknown segments: {unknown}")

    # 1. synthesize each line once
    clips: dict[str, tuple[Path, float]] = {}
    for sid, text in lines.items():
        raw = voice_dir / f"{sid}.raw.wav"
        wav = voice_dir / f"{sid}.wav"
        stamp = voice_dir / f"{sid}.stamp"
        want = _hash(f"{voice}|{rate}|{text}")
        if force or not wav.is_file() or not stamp.is_file() or stamp.read_text().strip() != want:
            log(f"  tts {sid} ({len(text)} chars, voice {voice})")
            tts.synthesize(text, str(raw), voice=voice, rate=rate)
            _normalise_wav(ffmpeg, raw, wav)
            stamp.write_text(want)
        info = probe.media(ffmpeg, str(wav))
        clips[sid] = (wav, float(info.get("duration") or 0.0))

    # 2. durations follow the voice
    for sid in lines:
        seg = segs[sid]
        needed = lead_in + clips[sid][1] + tail + gap
        declared = seg.get("duration")
        if isinstance(declared, (int, float)) or (isinstance(declared, str) and declared.replace('.', '', 1).isdigit()):
            seg["duration"] = round(max(float(declared), needed), 3)
        else:
            seg["duration"] = round(max(min_duration, needed), 3)

    # 3. where does each timeline item start, and when does the voice speak
    starts = specmod.segment_starts(spec)
    total = specmod.planned_duration(spec)

    # 4. one continuous voice track: silence, line, silence, line ...
    parts: list[Path] = []
    written = 0.0
    cue_times: list[tuple[float, float, str]] = []
    seen: dict[str, int] = {}
    sil_cache: dict[int, Path] = {}

    def silence_for(seconds: float) -> Path:
        key = round(seconds * 1000)
        if key not in sil_cache:
            path = voice_dir / f"sil-{key}.wav"
            if not path.is_file() or force:
                _silence(ffmpeg, key / 1000.0, path)
            sil_cache[key] = path
        return sil_cache[key]

    for item in spec["timeline"]:
        sid = item.get("segment")
        if sid not in lines:
            continue
        idx = seen.get(sid, 0)
        seen[sid] = idx + 1
        clip_path, clip_len = clips[sid]
        if idx == 0:
            start = starts.get(sid, written)
            speak_at = start + lead_in
            if speak_at > written + 0.005:
                parts.append(silence_for(speak_at - written))
                written = speak_at
            parts.append(clip_path)
            written += clip_len
            cue_times.append((speak_at, speak_at + clip_len, lines[sid]))

    if total > written + 0.01:
        parts.append(silence_for(total - written))

    voice_track = voice_dir / "voice.wav"
    _concat(ffmpeg, parts, voice_track, voice_dir)

    # 5. subtitles
    srt = None
    if not (spec.get("subtitles") or {}).get("src"):
        srt = voice_dir / "narration.srt"
        srt.write_text(_srt(cue_times), encoding="utf-8")
        spec.setdefault("subtitles", {})["src"] = str(srt)
        spec["subtitles"].setdefault(
            "style", "FontName=Microsoft YaHei,FontSize=24,OutlineColour=&H80000000,"
                     "BorderStyle=1,Outline=2,Shadow=0,MarginV=40")

    # 6. mix the voice in as its own track
    tracks = spec.setdefault("audio", {}).setdefault("tracks", [])
    voice_gain = float(cfg.get("gain_db", 0))
    tracks.insert(0, {"src": str(voice_track), "at": 0.0, "gain_db": voice_gain,
                      "fade_in": 0.0, "fade_out": 0.0, "loop": False,
                      "_role": "voice"})
    spec.setdefault("audio", {})["voice_track"] = str(voice_track)

    manifest = {
        "voice": voice, "rate": rate, "total": round(total, 3),
        "lines": [{"segment": s, "text": t, "chars": len(t),
                   "seconds": round(clips[s][1], 3)} for s, t in lines.items()],
        "voice_track": str(voice_track), "subtitles": str(srt) if srt else None,
    }
    (voice_dir / "narration.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"applied": True, **manifest}


def _srt(cues: list[tuple[float, float, str]]) -> str:
    def stamp(t: float) -> str:
        t = max(0.0, t)
        h, rem = divmod(t, 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

    out = []
    for i, (start, end, text) in enumerate(cues, 1):
        out.append(f"{i}\n{stamp(start)} --> {stamp(max(end, start + 0.4))}\n{_wrap(text)}\n")
    return "\n".join(out)


def _wrap(text: str, width: int = 18) -> str:
    """Break CJK-heavy lines so subtitles stay two rows tall at most."""
    text = text.strip()
    if len(text) <= width:
        return text
    mid = len(text) // 2
    best = mid
    for offset in range(mid, min(len(text), mid + 8)):
        if text[offset] in " 、，。；：— ":
            best = offset + 1
            break
    return text[:best].rstrip() + "\n" + text[best:].lstrip()
