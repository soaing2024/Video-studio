"""Auto-montage: a folder of media plus a music track becomes a beat-cut project spec.

This is the "swiss army knife" entry point for high-energy montages: it probes every clip,
finds the beats, assigns shots to beats, gives stills a Ken Burns move, and writes a normal
project file. Everything after that is the same pipeline as a hand-authored project.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import beats, probe, spec as specmod

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_SUFFIXES = specmod.IMAGE_SUFFIXES

STYLES = {
    "energy": {"min_len": 0.8, "max_len": 3.2, "sensitivity": 1.35, "grade": {"saturation": 1.14, "contrast": 1.06},
               "transition_every": 4, "transition": {"type": "fadeblack", "duration": 0.18}},
    "calm":   {"min_len": 2.5, "max_len": 6.0, "sensitivity": 1.8, "grade": {"saturation": 1.04},
               "transition_every": 2, "transition": {"type": "fade", "duration": 0.5}},
    "punch":  {"min_len": 0.6, "max_len": 2.0, "sensitivity": 1.2, "grade": {"saturation": 1.2, "contrast": 1.1},
               "transition_every": 6, "transition": {"type": "fadeblack", "duration": 0.12}},
}


def collect(folder: str | Path) -> list[dict]:
    """Every usable image or video in a folder, sorted by name for reproducibility."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a folder: {root}")
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            out.append({"path": str(path), "kind": "image"})
        elif suffix in VIDEO_SUFFIXES:
            out.append({"path": str(path), "kind": "video"})
    return out


def _offset(seed: str, span: float) -> float:
    if span <= 0:
        return 0.0
    h = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return round((h % 1000) / 1000.0 * span, 3)


def build(ffmpeg: str, media_dir: str, music: str, out: str,
          duration: float | None = None, style: str = "energy",
          title: str | None = None, width: int = 1920, height: int = 1080,
          fps: int = 30, max_shots: int = 400) -> dict:
    # everything written into the spec is absolute: the project file may live elsewhere
    music = str(Path(music).expanduser().resolve())
    media = collect(media_dir)
    if not media:
        raise ValueError(f"no images or videos found in {media_dir}")
    cfg = STYLES.get(style, STYLES["energy"])

    music_info = probe.media(ffmpeg, music)
    music_len = float(music_info.get("duration") or 0.0)
    detection = beats.detect(ffmpeg, music, sensitivity=cfg["sensitivity"],
                             min_gap=cfg["min_len"] * 0.8)
    beats_list = detection.get("beats", [])

    target = float(duration or music_len or 60.0)
    if music_len:
        target = min(target, music_len)
    cuts = beats.cut_points(beats_list, target, min_len=cfg["min_len"], max_len=cfg["max_len"])
    if not cuts or cuts[-1] < target - 0.2:
        cuts.append(round(target, 3))

    timeline: list[dict] = []
    marks = [0.0] + cuts
    for i in range(min(len(marks) - 1, max_shots)):
        start, end = marks[i], marks[i + 1]
        shot = round(end - start, 3)
        if shot < 0.3:
            continue
        item: dict = {}
        entry = media[i % len(media)]
        if entry["kind"] == "image":
            item["source"] = entry["path"]
            item["trim"] = [0.0, shot]
            pan = ["left", "right", "up", "down"][i % 4]
            zoom = cfg.get("zoom", {"from": 1.02, "to": 1.12})
            item["zoom"] = {"from": zoom["from"], "to": zoom["to"], "pan": pan}
        else:
            info = probe.media(ffmpeg, entry["path"])
            clip_len = float(info.get("duration") or 0.0)
            if clip_len <= shot + 0.2:
                trim = [0.0, max(0.3, clip_len - 0.05)]
            else:
                span = clip_len - shot - 0.1
                trim = [round(_offset(f"{entry['path']}-{i}", span), 3)]
                trim.append(round(trim[0] + shot, 3))
            item["source"] = entry["path"]
            item["trim"] = trim
            if i % 3 == 2:
                item["speed"] = 1.25 if style != "calm" else 1.0
        if i and i % cfg["transition_every"] == 0:
            item["transition"] = dict(cfg["transition"])
        timeline.append(item)

    spec = {
        "name": Path(out).stem,
        "video": {"width": width, "height": height, "fps": fps, "crf": 20, "preset": "medium"},
        "render": {"jobs": 2, "crf": 12},
        "look": {"accent": "#e0455f", "fade_in": 0.4, "fade_out": 0.8,
                 "grade": cfg["grade"], "progress_bar": {"height": 3, "color": "#e0455f"}},
        "segments": [],
        "timeline": timeline,
        "audio": {
            "tracks": [{"src": music, "at": 0.0, "gain_db": 0.0,
                        "fade_in": 0.6, "fade_out": min(2.0, max(0.4, target * 0.05)),
                        "loop": bool(music_len and music_len < target)}],
            "loudnorm": {"i": -14, "tp": -1.5, "lra": 11},
        },
    }

    if title:
        spec["segments"] = [
            {"id": "card-in", "template": "kinetic", "duration": max(2.5, cfg["min_len"] * 2),
             "data": {"eyebrow": "MONTAGE", "title": title, "subtitle": f"{len(timeline)} cuts",
                      "footer": f"{style} - {fps} fps"}},
            {"id": "card-out", "template": "kinetic", "duration": 3.0,
             "data": {"eyebrow": "END", "title": title, "subtitle": "thanks for watching"}},
        ]
        spec["timeline"].insert(0, {"segment": "card-in",
                                    "transition": {"type": "fade", "duration": 0.4}})
        spec["timeline"].append({"segment": "card-out",
                                 "transition": {"type": "fade", "duration": 0.5}})

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "project": str(path),
        "media": len(media),
        "shots": len(timeline),
        "target_seconds": round(target, 2),
        "music_bpm": detection.get("bpm"),
        "beats": len(beats_list),
        "style": style,
    }
