"""A cue library and a mix target, so UI sound stops being hand-synthesised from scratch.

P2-I. Every film that needs interface sound otherwise re-derives the same eight cues and
re-discovers two traps: `amix` divides by track count (so N tracks leave the mix ~6 dB
quieter), and a bed with no target drifts outside the level window `verify` enforces.

    python -c "from lib import audio; print(audio.CUES)"
    python scripts/vs.py audio cues.json --out work/mine/audio/mix.wav --duration 30

cues.json: {"cues": [{"t": 0.62, "cue": "click", "pan": -0.2},
                     {"t": 2.70, "cue": "whoosh", "dur": 0.8, "f0": 260, "f1": 1500},
                     {"t": 24.55, "cue": "sparkle", "count": 18}]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
TARGET_MEAN_DB = -24.0
PEAK_CEIL_DB = -4.0          # leave room for AAC
_RNG = np.random.default_rng(20260919)


def _env(n, attack=0.002, decay=0.05, curve=6.0):
    t = np.arange(n) / SR
    return np.clip(t / max(1e-5, attack), 0, 1) * np.exp(-curve * np.maximum(0.0, t - attack) / max(1e-5, decay))


def _noise(n):
    return _RNG.uniform(-1, 1, n)


def _lp(x, cut):
    a = math.exp(-2 * math.pi * cut / SR)
    out = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc
        out[i] = acc
    return out


def _hp(x, cut):
    return x - _lp(x, cut)


def _click(dur=0.045, f=2600.0, bright=0.6):
    n = int(SR * dur)
    return (np.sin(2 * np.pi * f * np.arange(n) / SR) * 0.5 + _hp(_noise(n), 3500) * bright * 0.8) * _env(n, 0.0008, dur * 0.7, 9.0)


def _tick(dur=0.03, f=1500.0):
    n = int(SR * dur)
    return (np.sin(2 * np.pi * f * np.arange(n) / SR) * 0.6 + _hp(_noise(n), 4000) * 0.4) * _env(n, 0.0006, 0.014, 12.0)


def _pop(dur=0.13, f0=420.0, f1=120.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = f0 + (f1 - f0) * (t / dur) ** 0.6
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * 0.9 + _hp(_noise(n), 2200) * 0.25) * _env(n, 0.001, dur * 0.55, 7.0)


def _whoosh(dur=0.55, f0=900.0, f1=260.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    e = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    nz = _noise(n)
    band = _lp(nz, 900) * (1 - e) + _hp(nz, 1800) * e
    f = f0 * (f1 / f0) ** (t / dur)
    return (band + np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.18) * e


def _impact(dur=0.6, f0=140.0, f1=40.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (t / dur)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.95 + _lp(_noise(n), 220) * 0.5) * _env(n, 0.0015, dur * 0.5, 5.0)


def _riser(dur=0.9, f0=300.0, f1=2400.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    e = (t / dur) ** 1.7
    f = f0 * (f1 / f0) ** (t / dur)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.35 + _hp(_noise(n), 1200) * 0.5 * e) * e


def _chime(dur=1.5, base=659.26):
    n = int(SR * dur)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for k, mult in enumerate((1.0, 1.5, 2.0)):
        m = int(k * 0.055 * SR)
        e = _env(n - m, 0.004, dur * 0.6, 4.2)
        f = base * mult
        sig[m:] += (np.sin(2 * np.pi * f * t[:n - m]) * 0.6
                    + np.sin(2 * np.pi * f * 2.01 * t[:n - m]) * 0.22) / (1 + k * 0.35)
    return sig * 0.8


def _sparkle(dur=1.6, count=14, spread=1.15):
    out = np.zeros(int(SR * dur))
    for i in range(count):
        f = 2100 + _RNG.uniform(0, 3600)
        d = spread * (i / max(1, count - 1)) ** 0.85
        n = int(SR * 0.26)
        s = np.sin(2 * np.pi * f * np.arange(n) / SR) * 0.6 * _env(n, 0.001, 0.22, 7.0)
        j = int(d * SR)
        out[j:j + n] += s[:max(0, len(out) - j)]
    return out


CUES = {"click": _click, "tick": _tick, "pop": _pop, "whoosh": _whoosh,
        "impact": _impact, "riser": _riser, "chime": _chime, "sparkle": _sparkle}


def _cue_seed(cue: dict) -> int:
    """A cue's own seed, so reordering cues cannot change any single cue's noise.

    The module RNG used to advance across the whole bed, which made the same cue sound
    different depending on what came before it."""
    payload = json.dumps({k: v for k, v in sorted(cue.items()) if not k.startswith("_")},
                        sort_keys=True, ensure_ascii=False, default=str)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8], 16)


def build_bed(spec: dict, cues: list[dict], duration: float, log=print) -> str:
    """Render the project's cue list to one cached stereo wav and return its path.

    A project declares cues as `audio.cues`; `assemble` calls this so a cue bed is part of
    the mix instead of something the author has to remember to build by hand. Cached by
    the cue list and the take length, so a re-render never pays twice."""
    digest = hashlib.sha256(json.dumps(
        {"cues": cues, "duration": round(float(duration), 3)},
        sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:12]
    out = Path(spec["base_dir"]) / "build" / spec["name"] / "audio" / f"cues-{digest}.wav"
    if out.is_file():
        return str(out)
    mix, info = render_cues(cues, duration, room=float((spec.get("audio") or {}).get("room", 0.0)))
    write_wav(mix, out)
    log(f"  cue bed: {info['cues']} cue(s) {info['by_kind']} -> {out.name}")
    return str(out)


def measure_lufs(ffmpeg: str, path: str | Path, target: float = -14.0,
                 true_peak: float = -1.0) -> dict:
    """Integrated loudness and true peak, the numbers a delivery master is judged on."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af",
         f"loudnorm=I={target}:TP={true_peak}:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not blocks:
        return {"ok": False, "error": "could not measure loudness"}
    data = json.loads(blocks[-1])
    lufs = float(data["input_i"])
    tp = float(data["input_tp"])
    return {"ok": abs(lufs - target) <= 1.5 and tp <= true_peak + 0.4,
            "lufs": lufs, "true_peak_db": tp, "target_lufs": target,
            "target_tp": true_peak, "lra": float(data.get("input_lra", 0) or 0)}


def render_cues(cues: list[dict], duration: float, gain_db: float = 0.0,
                target_mean_db: float = TARGET_MEAN_DB,
                room: float = 0.0) -> tuple[np.ndarray, dict]:
    """One pre-mixed stereo bed. One file in the project, so `amix` never sees N tracks."""
    n = int(SR * duration)
    L, R = np.zeros(n), np.zeros(n)
    used = {}
    for c in cues:
        fn = CUES.get(str(c.get("cue")))
        global _RNG
        _RNG = np.random.default_rng(_cue_seed(c))   # per-cue, order-independent
        if fn is None:
            raise ValueError(f"unknown cue {c.get('cue')!r}; available: {sorted(CUES)}")
        kw = {k: v for k, v in c.items() if k in ("dur", "f0", "f1", "f", "bright", "count", "spread", "base")}
        sig = fn(**kw) * (10 ** (float(c.get("gain_db", 0)) / 20))
        pan = max(-1.0, min(1.0, float(c.get("pan", 0.0))))
        i0 = int(float(c["t"]) * SR)
        if i0 >= n:
            continue
        m = min(len(sig), n - i0)
        L[i0:i0 + m] += sig[:m] * math.sqrt((1 - pan) / 2)
        R[i0:i0 + m] += sig[:m] * math.sqrt((1 + pan) / 2)
        used[str(c["cue"])] = used.get(str(c["cue"]), 0) + 1
    if room > 0:
        # Three early reflections, decorrelated between the channels. Not a reverb: a room
        # small enough that cues stop reading as "dry sample dropped on the timeline".
        r = max(0.0, min(1.0, float(room)))
        for delay_ms, g in ((11.0, 0.34), (23.0, 0.22), (41.0, 0.13)):
            d = int(SR * delay_ms / 1000.0)
            if d >= n:
                continue
            L[d:] += R[:n - d] * g * r
            R[d:] += L[:n - d] * g * r * 0.92
    mix = np.stack([L, R], axis=1) * (10 ** (gain_db / 20))
    peak = float(np.max(np.abs(mix))) or 1e-9
    mix *= min(1.0, (10 ** (PEAK_CEIL_DB / 20)) / peak)
    mean = float(np.sqrt(np.mean(mix ** 2)))
    # this keeps the finished mix inside verify's -45..-10 dB window by construction
    want = 10 ** (target_mean_db / 20)
    if mean > 0:
        mix *= min(4.0, want / mean)
    return mix, {"cues": len(cues), "by_kind": used}


def write_wav(mix: np.ndarray, out: str | Path, sr: int = SR) -> str:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return str(p)


def measure(ffmpeg: str, path: str | Path) -> dict:
    """Mean/peak as `verify` will measure them, plus whether they clear its window."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    mean = peak = None
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            mean = float(line.split("mean_volume:")[1].split("dB")[0])
        if "max_volume:" in line:
            peak = float(line.split("max_volume:")[1].split("dB")[0])
    return {"mean_db": mean, "peak_db": peak,
            "ok": mean is not None and -45 < mean < -10 and (peak or 0) < -1.0}


def main(argv=None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib import fmt, runtime
    ap = argparse.ArgumentParser(description="build or check the audio bed")
    ap.add_argument("cues", nargs="?", help="cues.json, or - for stdin")
    ap.add_argument("--out", default="audio/mix.wav")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--gain-db", type=float, default=0.0)
    ap.add_argument("--target-mean-db", type=float, default=TARGET_MEAN_DB)
    ap.add_argument("--check", help="measure an existing wav/mp4 instead of building")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    fmt.configure(json=args.json, verbose=args.verbose)
    ffmpeg = runtime.find_ffmpeg()
    if args.check:
        m = measure(ffmpeg, args.check)
        fmt.emit({"ok": m["ok"], "which": "audio_check", **m},
                 human=f"audio: mean {m['mean_db']} dB, peak {m['peak_db']} dB "
                       f"({'inside' if m['ok'] else 'OUTSIDE'} the -45..-10 dB window)")
        return 0 if m["ok"] else 1
    doc = json.loads(sys.stdin.read()) if args.cues in (None, "-") else json.loads(Path(args.cues).read_text(encoding="utf-8"))
    cues = doc.get("cues", doc if isinstance(doc, list) else [])
    mix, info = render_cues(cues, args.duration, args.gain_db, args.target_mean_db)
    path = write_wav(mix, args.out)
    m = measure(ffmpeg, path)
    fmt.emit({"ok": m["ok"], "which": "audio", "out": path, "duration": args.duration,
              **info, **m}, human=f"audio -> {path} ({info['cues']} cues, mean {m['mean_db']} dB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
