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


def _declared_seconds(value):
    """The duration a segment already declares, or None when it is `auto`/missing."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.replace(".", "", 1).isdigit():
        return float(value)
    return None


def _entries(cfg: dict, segs: dict) -> list[dict]:
    """Normalise narration.lines into synthesis entries with stable ids.

    A segment may now carry several lines (one per chapter of a brief). Each entry gets its
    own file stamp id, so the TTS cache still only re-synthesizes the lines whose text changed.
    """
    entries: list[dict] = []
    for i, line in enumerate(cfg.get("lines") or []):
        sid = line.get("segment")
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        if sid not in segs:
            raise ValueError(f"narration references unknown segment: {sid!r}")
        at = line.get("at")
        entries.append({
            "segment": sid,
            "text": text,
            "at": None if at is None else float(at),
            "chapter": line.get("chapter"),
            "index": i,
        })
    per_segment: dict[str, int] = {}
    for e in entries:
        per_segment[e["segment"]] = per_segment.get(e["segment"], 0) + 1
    for e in entries:
        e["id"] = (e["segment"] if per_segment[e["segment"]] == 1
                   else f"{e['segment']}-{e['index']:02d}")
    return entries


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
    entries = _entries(cfg, segs)
    if not entries:
        return {"applied": False}

    # 1. synthesize each line once
    clips: dict[str, tuple[Path, float]] = {}
    # per line, not per segment, so one edited chapter does not invalidate the rest of the voice.
    for e in entries:
        raw = voice_dir / f"{e['id']}.raw.wav"
        wav = voice_dir / f"{e['id']}.wav"
        stamp = voice_dir / f"{e['id']}.stamp"
        want = _hash(f"{voice}|{rate}|{e['text']}")
        if force or not wav.is_file() or not stamp.is_file() or stamp.read_text().strip() != want:
            log(f"  tts {e['id']} ({len(e['text'])} chars, voice {voice})")
            tts.synthesize(e["text"], str(raw), voice=voice, rate=rate)
            _normalise_wav(ffmpeg, raw, wav)
            stamp.write_text(want)
        info = probe.media(ffmpeg, str(wav))
        clips[e["id"]] = (wav, float(info.get("duration") or 0.0))

    # 2. durations follow the voice

    # 2. place every line on the absolute take clock, then let the durations follow the voice
    starts = specmod.segment_starts(spec)
    events: list[dict] = []
    for e in entries:
        start = starts.get(e["segment"], 0.0)
        place = start + lead_in if e["at"] is None else float(e["at"])
        events.append({**e, "start": start, "place": place,
                       "clip": clips[e["id"]][0], "seconds": clips[e["id"]][1]})
    events.sort(key=lambda e: (e["place"], e["id"]))

    for e in events:
        seg = segs[e["segment"]]
        needed = (e["place"] - e["start"]) + e["seconds"] + tail + gap
        declared = _declared_seconds(seg.get("duration"))
        seg["duration"] = (round(max(declared, needed), 3) if declared is not None
                           else round(max(min_duration, needed), 3))

    starts = specmod.segment_starts(spec)
    total = specmod.planned_duration(spec)

    # 4. one continuous voice track: silence, line, silence, line ...
    parts: list[Path] = []
    written = 0.0
    cue_times: list[tuple[float, float, str]] = []
    sil_cache: dict[int, Path] = {}

    def silence_for(seconds: float) -> Path:
        key = round(seconds * 1000)
        if key not in sil_cache:
            path = voice_dir / f"sil-{key}.wav"
            if not path.is_file() or force:
                _silence(ffmpeg, key / 1000.0, path)
            sil_cache[key] = path
        return sil_cache[key]

    for e in events:
        if e["place"] > written + 0.005:
            parts.append(silence_for(e["place"] - written))
            written = e["place"]
        elif e["place"] < written - 0.005:
            # The voice cannot be in two places at once. Chapters are authored before the TTS
            # durations are known, so a slow reading can overrun its slot; push this line to
            # the first free moment and say so rather than writing overlapping samples.
            log(f"  narration: '{e['id']}' overruns its slot by {written - e['place']:.2f}s; "
                f"pushed to {written:.2f}s")
            e["place"] = written
        parts.append(e["clip"])
        written += e["seconds"]
        cue_times.append((max(0.0, e["place"]), e["place"] + e["seconds"], e["text"]))

    if total > written + 0.01:
        parts.append(silence_for(total - written))

    voice_track = voice_dir / "voice.wav"
    _concat(ffmpeg, parts, voice_track, voice_dir)

    # 5. if the scene was compiled from a brief, its chapter table is what the picture follows.
    #    Rewrite it from the actual voice placement so picture, voice and subtitles agree.
    chapters_updated = 0
    for e in events:
        seg = segs.get(e["segment"]) or {}
        timeline = (seg.get("data") or {}).get("timeline")
        if not isinstance(timeline, list) or not timeline:
            continue
        row = None
        if e.get("chapter") is not None:
            row = next((c for c in timeline if c.get("index") == e["chapter"]), None)
        if row is None:
            row = next((c for c in timeline
                        if c.get("at") is not None
                        and abs(float(c.get("at")) - float(e["place"])) < 0.001), None)
        if row is not None:
            row["at"] = round(float(e["place"]), 3)
            row["seconds"] = round(float(e["seconds"]) + tail, 3)
            chapters_updated += 1
    if chapters_updated:
        for seg in segs.values():
            timeline = (seg.get("data") or {}).get("timeline")
            if not isinstance(timeline, list) or not timeline:
                continue
            rows = sorted((c for c in timeline if c.get("at") is not None),
                          key=lambda c: float(c["at"]))
            for i, row in enumerate(rows):
                end = float(rows[i + 1]["at"]) if i + 1 < len(rows) else total
                row["seconds"] = round(max(0.5, end - float(row["at"])), 3)

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
        "lines": [{"segment": e["segment"], "text": e["text"], "chars": len(e["text"]),
                   "seconds": round(e["seconds"], 3), "at": round(e["place"], 3)}
                  for e in events],
        "voice_track": str(voice_track), "subtitles": str(srt) if srt else None,
        "chapters_updated": chapters_updated,
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
