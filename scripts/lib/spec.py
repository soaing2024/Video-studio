"""Project spec loading, defaults, and timeline math."""
from __future__ import annotations

import json
import re
from pathlib import Path


class SpecError(ValueError):
    """Raised for an invalid project file."""


def _strip_comments(text: str) -> str:
    """Drop // comments without touching strings (so a "//" key still works)."""
    out: list[str] = []
    for line in text.splitlines():
        buf: list[str] = []
        in_str = False
        escaped = False
        i = 0
        while i < len(line):
            ch = line[i]
            if in_str:
                buf.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                buf.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
            buf.append(ch)
            i += 1
        stripped = "".join(buf).rstrip()
        if stripped:
            out.append(stripped)
    return "\n".join(out)


def load(path) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise SpecError(f"project file not found: {p}")
    raw = _strip_comments(p.read_text(encoding="utf-8"))
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SpecError(f"invalid JSON in {p.name}: line {e.lineno} col {e.colno}: {e.msg}") from e
    return normalize(spec, p.parent)


def normalize(spec: dict, base_dir: Path) -> dict:
    spec.setdefault("name", "video")
    video = spec.setdefault("video", {})
    video.setdefault("width", 1280)
    video.setdefault("height", 720)
    video.setdefault("fps", 30)
    video.setdefault("crf", 18)
    video.setdefault("preset", "slow")
    spec.setdefault("look", {})
    spec.setdefault("render", {}).setdefault("jobs", 2)
    spec.setdefault("render", {}).setdefault("crf", 12)
    spec.setdefault("segments", [])
    # Three shapes are valid: a single take (scene + duration), the multi-shot form, or a bare
    # timeline of source clips. The single take is the documented one.
    if not spec["segments"] and not spec.get("timeline") and not spec.get("scene"):
        raise SpecError("project has neither a scene, nor segments, nor a timeline")

    # A project is one take: a scene and a duration. Nothing is cut, so there is nothing to order
    # and no timeline to assemble - which is why `segments` and `timeline` are not the documented
    # shape any more. They still work for the one case that is inherently multi-shot: a montage of
    # existing footage (`vs.py montage`), where `source` clips are the point.
    if spec.get("scene") and not spec.get("segments"):
        if not spec.get("duration"):
            raise SpecError("a single-take project needs a `duration` in seconds")
        # `"auto"` means "however long the narration takes", the same contract segments had;
        # `vs.py narrate` fills it in from what was actually spoken.
        take = 0.0 if spec["duration"] == "auto" else float(spec["duration"])
        holds = spec.get("hold") or []
        for pair in holds:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or not 0 <= float(pair[0]) < float(pair[1]) <= take):
                raise SpecError(f"hold window {pair!r} is not a [start, end] inside 0..{take}")
        spec["segments"] = [{
            "id": spec.get("take_id") or "take",
            "scene": spec["scene"],
            "duration": take,
            "data": spec.get("data") or {},
            "assets": spec.get("assets") or {},
            "hold": [list(map(float, pair)) for pair in holds],
        }]
        spec["timeline"] = [{"segment": spec["segments"][0]["id"]}]
        spec["single_take"] = True

    ids = [s.get("id") for s in spec["segments"]]
    if any(not i for i in ids):
        raise SpecError("every segment needs an id")
    if len(set(ids)) != len(ids):
        raise SpecError(f"duplicate segment ids: {ids}")
    if not spec["segments"]:
        spec["timeline"] = spec.get("timeline") or []

    for seg in spec["segments"]:
        seg["scene"] = _resolve_scene(seg, base_dir)
        seg.pop("template", None)        # legacy spelling; a shot is a file, not a name
        if "duration" not in seg:
            raise SpecError(f"segment '{seg['id']}' needs a duration in seconds")
        if isinstance(seg["duration"], str) and seg["duration"] == "auto":
            seg["duration"] = 0.0        # narration fills this in from the spoken length
        else:
            seg["duration"] = float(seg["duration"])
        seg.setdefault("data", {})
        seg.setdefault("assets", {})
        seg["assets"] = {k: _resolve(v, base_dir) for k, v in seg["assets"].items()}
        seg.setdefault("hold", [])

    timeline = spec.get("timeline")
    if not timeline:
        timeline = [{"segment": s["id"]} for s in spec["segments"]]
    for item in timeline:
        sid = item.get("segment")
        if sid is None:
            if not item.get("source"):
                raise SpecError("timeline entry needs either 'segment' or 'source'")
            item["source"] = _resolve(item["source"], base_dir)
        elif sid not in ids:
            raise SpecError(f"timeline references unknown segment '{sid}'")
        item.setdefault("transition", {"type": "cut"})
    spec["timeline"] = timeline

    audio = spec.setdefault("audio", {})
    for track in audio.get("tracks", []):
        if "src" not in track:
            raise SpecError("audio track needs a src")
        track["src"] = _resolve(track["src"], base_dir)
        track.setdefault("at", 0.0)
        track.setdefault("gain_db", -18.0)
        track.setdefault("fade_in", 0.0)
        track.setdefault("fade_out", 0.0)
        track.setdefault("loop", False)
    if audio.get("subtitles"):
        audio["subtitles"] = _resolve(audio["subtitles"], base_dir)
    if spec.get("subtitles", {}).get("src"):
        spec["subtitles"]["src"] = _resolve(spec["subtitles"]["src"], base_dir)
    if spec.get("beats", {}).get("src"):
        spec["beats"]["src"] = _resolve(spec["beats"]["src"], base_dir)
    spec["base_dir"] = str(base_dir)
    return spec


def _resolve(value, base_dir: Path) -> str:
    if not isinstance(value, str):
        return value
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return str(p)


def _resolve_scene(seg: dict, base_dir: Path) -> str:
    """A shot is the scene file its author wrote for this video.

    There is no name-to-file menu: the built-in skeletons were removed on purpose, because a
    video assembled from them is the same video for every brief. `scene` resolves against the
    project directory; the old `template:` name form resolved against the process cwd, which made
    the same project render from one directory and fail from another.
    """
    raw = seg.get("scene") or seg.get("template")
    if not raw:
        raise SpecError(
            f"segment '{seg['id']}' has no scene: write the shot, then point `scene` at it " 
            "(references/choreography.md)")
    p = Path(str(raw)).expanduser()
    if p.suffix.lower() != ".html":
        raise SpecError(
            f"segment '{seg['id']}': `scene` has to be a path to an .html scene, got '{raw}'. "
            "There are no built-in templates to pick by name any more.")
    return str(p if p.is_absolute() else (base_dir / p).resolve())


def segment_map(spec: dict) -> dict:
    return {s["id"]: s for s in spec["segments"]}


def trim_range(spec: dict, item: dict) -> tuple[float, float]:
    """Source range for a timeline item, in that item's own time base."""
    if item.get("source"):
        lo, hi = item.get("trim", [0.0, 0.0])
        lo = max(0.0, float(lo))
        hi = float(hi)
        if hi <= lo:
            span = float(item.get("duration", 0.0) or 0.0)
            if span <= 0:
                name = Path(str(item["source"])).name
                raise SpecError(f"source '{name}' needs trim: [start, end] or a duration")
            hi = lo + span
        return lo, hi

    seg = segment_map(spec)[item["segment"]]
    lo, hi = item.get("trim", [0.0, seg["duration"]])
    lo = max(0.0, float(lo))
    hi = min(float(hi), seg["duration"])
    if hi <= lo:
        raise SpecError(f"timeline trim for '{item['segment']}' is empty ({lo}..{hi})")
    return lo, hi


def item_length(spec: dict, item: dict) -> float:
    """Output length of a timeline item, after trimming and any speed change."""
    lo, hi = trim_range(spec, item)
    speed = float(item.get("speed", 1.0) or 1.0)
    return (hi - lo) / max(0.05, speed)


def segment_starts(spec: dict) -> dict:
    """Output start time of each segment's first appearance in the timeline."""
    starts: dict[str, float] = {}
    cursor = 0.0
    for i, item in enumerate(spec["timeline"]):
        if i > 0:
            tr = item.get("transition") or {}
            if tr.get("type", "cut") != "cut":
                cursor -= float(tr.get("duration", 0.5))
        sid = item.get("segment")
        if sid and sid not in starts:
            starts[sid] = round(cursor, 3)
        cursor += item_length(spec, item)
    return starts


def planned_duration(spec: dict) -> float:
    """Total output length once transitions are accounted for."""
    total = 0.0
    for i, item in enumerate(spec["timeline"]):
        length = item_length(spec, item)
        if i == 0:
            total = length
            continue
        tr = item.get("transition") or {}
        if tr.get("type", "cut") == "cut":
            total += length
        else:
            total += length - float(tr.get("duration", 0.5))
    return round(total, 3)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}

X_FADE_TYPES = {
    "fade", "fadeblack", "fadewhite", "fadegrays", "distance", "wipeleft", "wiperight",
    "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown",
    "circlecrop", "rectcrop", "circleclose", "circleopen", "vertclose", "vertopen",
    "horzclose", "horzopen", "dissolve", "pixelize", "radial", "smoothleft",
    "smoothright", "smoothup", "smoothdown", "squeezeh", "squeezev", "hlslice",
    "hrslice", "vuslice", "vdslice", "zoomin", "hlwind", "hrwind", "vuwind", "vdwind",
}


def validate(spec: dict) -> list[dict]:
    """Static problems worth reporting before a render is attempted."""
    from . import render as render_mod  # local import avoids a cycle

    issues: list[dict] = []

    def add(level: str, where: str, message: str) -> None:
        issues.append({"level": level, "where": where, "message": message})

    for seg in spec["segments"]:
        scene = render_mod.scene_path(seg)
        if not scene.is_file():
            add("error", seg["id"], f"scene not found: {scene}")
        if spec.get("single_take") and (seg.get("data") or {}).get("still"):
            add("error", seg["id"],
                "`still` would freeze the entire take at one frame; declare the static stretches "
                "with `hold: [[start, end]]` instead")
        for name, value in (seg.get("assets") or {}).items():
            if isinstance(value, dict):       # a prompt, generated before rendering
                if not value.get("prompt"):
                    add("error", seg["id"], f"asset '{name}' needs a prompt or a file path")
                continue
            if not Path(value).is_file():
                add("error", seg["id"], f"asset '{name}' not found: {value}")
        if not seg.get("duration"):
            add("error", seg["id"], "duration is 0 or missing")
        if not (seg.get("data") or {}).get("still") and float(seg.get("duration") or 0) > 30:
            add("warning", seg["id"], f"{seg['duration']}s of full animation is expensive; consider still: true")

    # Every shot being its own scene is now structural: `normalize` refuses a segment without one,
    # so there is nothing left to warn about here.

    for item in spec["timeline"]:
        where = item.get("segment") or item.get("source") or "timeline"
        if item.get("source") and not Path(item["source"]).is_file():
            add("error", where, f"source clip not found: {item['source']}")
        kind = (item.get("transition") or {}).get("type", "cut")
        if kind != "cut" and kind not in X_FADE_TYPES:
            add("error", where, f"unknown transition '{kind}' (see references/formats.md)")

    for track in (spec.get("audio") or {}).get("tracks", []):
        if not Path(track["src"]).is_file():
            add("error", "audio", f"track not found: {track['src']}")
    for key in ("subtitles", "beats"):
        src = (spec.get(key) or {}).get("src")
        if src and not Path(src).is_file():
            add("error", key, f"file not found: {src}")

    if not spec["timeline"]:
        add("error", "timeline", "timeline is empty")
    return issues
