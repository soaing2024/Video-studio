"""Orchestrate segment rendering: templates + data -> cached intermediate clips.

Long-form safety: each segment is rendered straight into its own mp4 through a pipe,
so no PNG sequence ever reaches disk, and a 5-minute project is 30-40 small files
instead of tens of thousands of frames.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import imagegen, runtime, spec as specmod
from .sprite import make_sprite

TEMPLATES = runtime.SKILL_DIR / "assets" / "templates"


def work_size(spec: dict) -> tuple[int, int, int]:
    """Render resolution and the integer upscale factor applied at assembly time."""
    look = spec.get("look") or {}
    px = look.get("pixelate")
    if px:
        s = max(1, int(px.get("scale", 4)))
        return spec["video"]["width"] // s, spec["video"]["height"] // s, s
    return spec["video"]["width"], spec["video"]["height"], 1


def template_path(name: str, base_dir=None) -> Path:
    """Resolve a segment template to a file.

    A `.html` value is a project file, so a relative one resolves next to the project spec -
    the same rule assets follow. Anything else is a built-in template name. `base_dir` is only
    a fallback for callers that did not go through spec.normalize (which already resolves).
    """
    p = Path(name)
    if p.suffix.lower() == ".html":
        if p.is_absolute():
            return p
        return (Path(base_dir) if base_dir else Path.cwd()) / p
    if p.is_absolute() or len(p.parts) > 1:
        return p            # a path without the .html suffix, e.g. templates/my-card
    return TEMPLATES / f"{name}.html"


def build_dir(spec: dict) -> Path:
    d = Path(spec["base_dir"]) / "build" / spec["name"]
    (d / "segments").mkdir(parents=True, exist_ok=True)
    return d


def segment_path(spec: dict, sid: str) -> Path:
    return build_dir(spec) / "segments" / f"{sid}.mp4"


def scene_globals(spec: dict) -> dict:
    """Spec-level values injected into every scene payload.

    Whatever reaches a template must also reach the cache key: a change the key cannot see is
    served from cache as a stale clip. Keep this in step with prepare_assets().
    """
    look = spec.get("look") or {}
    return {"accent": look.get("accent", "#e0455f")}


def last_report(stdout: str) -> dict:
    """The JSON report render_segment.mjs prints on its last line (empty dict if absent).

    Callers use it to see page errors on the paths that still exit 0, e.g. a still preview.
    """
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def _key(spec: dict, seg: dict, w: int, h: int) -> str:
    hsh = hashlib.sha256()
    tpl = template_path(seg["template"], spec.get("base_dir"))
    hsh.update(tpl.read_bytes() if tpl.is_file() else b"missing-template")
    hsh.update(json.dumps(seg.get("data", {}), sort_keys=True, ensure_ascii=False).encode())
    hsh.update(json.dumps(scene_globals(spec), sort_keys=True, ensure_ascii=False).encode())
    for name, value in sorted(seg.get("assets", {}).items()):
        hsh.update(f"{name}:{value}:".encode())
        p = Path(str(value))
        if p.is_file():
            st = p.stat()
            hsh.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    crf = float((spec.get("render") or {}).get("crf", 12))
    # id and template name reach the scene as well (a template seeds itself on S.id), and two
    # different missing templates must not end up sharing one cached clip.
    hsh.update(f"{seg.get('id', '')}|{seg.get('template', '')}|"
               f"{w}x{h}@{spec['video']['fps']}:{float(seg['duration'])}:crf{crf}".encode())
    return hsh.hexdigest()[:16]


def cache_key(spec: dict, seg: dict) -> str:
    """Public wrapper so `plan` can report cache hits without rendering."""
    w, h, _ = work_size(spec)
    return _key(spec, seg, w, h)


def prepare_assets(spec: dict, seg: dict, log=print) -> dict:
    """Resolve every asset this segment needs: generated images, then pixel sprites."""
    assets = dict(seg.get("assets", {}))
    data = dict(seg.get("data", {}))

    # {"hero": {"prompt": "..."}} -> generate once, cached by prompt hash
    for name, value in list(assets.items()):
        if isinstance(value, dict) and value.get("prompt"):
            made = imagegen.resolve_prompt(spec, seg["id"], name, value, log=log)
            assets[name] = made
    if seg["template"] == "pixel" and "sprite" not in assets and "subject" in assets:
        cfg = data.get("sprite", {})
        out = build_dir(spec) / "sprites" / f"{seg['id']}.png"
        report = make_sprite(
            assets["subject"], str(out),
            width=int(cfg.get("width", 64)), height=int(cfg.get("height", 96)),
            colors=int(cfg.get("colors", 12)), alpha_cutoff=int(cfg.get("alpha_cutoff", 115)),
        )
        assets["sprite"] = report["sprite"]
        assets["spriteShadow"] = report["shadow"]
        data.setdefault("spriteSize", report["size"])

    payload = dict(data)
    payload["assets"] = {k: _file_url(v) for k, v in assets.items()}
    payload["duration"] = float(seg["duration"])
    payload["id"] = seg["id"]
    for key, value in scene_globals(spec).items():
        payload.setdefault(key, value)      # segment data may still override a global
    return payload


def _file_url(value) -> str:
    p = Path(str(value)).resolve()
    return "file:///" + str(p).replace("\\", "/")


def render_segment(spec: dict, seg: dict, ffmpeg: str, node: str, force: bool = False,
                   log=print) -> dict:
    w, h, _ = work_size(spec)
    out = segment_path(spec, seg["id"])
    key = _key(spec, seg, w, h)
    keyfile = out.with_suffix(".key")
    if not force and out.is_file() and keyfile.is_file() and keyfile.read_text().strip() == key:
        return {"segment": seg["id"], "path": str(out), "cached": True}

    tpl = template_path(seg["template"], spec.get("base_dir"))
    if not tpl.is_file():
        raise FileNotFoundError(f"template not found for segment '{seg['id']}': {tpl}")

    if seg.get("data", {}).get("still"):
        # A held shot: render one frame past the entrance animations, then let ffmpeg hold it.
        # Cost becomes independent of duration, which is what makes 5-minute videos cheap.
        return _render_still_segment(spec, seg, ffmpeg, node, out, keyfile, key, log)

    payload = prepare_assets(spec, seg)
    data_file = out.with_suffix(".scene.json")
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [node, str(runtime.SKILL_DIR / "scripts" / "render_segment.mjs"),
           "--scene", str(tpl), "--out", str(out), "--data", str(data_file),
           "--fps", str(spec["video"]["fps"]), "--duration", str(seg["duration"]),
           "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
           "--crf", str((spec.get("render") or {}).get("crf", 12))]
    env = runtime_env()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"segment '{seg['id']}' failed:\n{proc.stdout}\n{proc.stderr}")
    keyfile.write_text(key)
    log(f"  rendered {seg['id']} ({seg['duration']}s @ {w}x{h})")
    return {"segment": seg["id"], "path": str(out), "cached": False}


def _render_still_segment(spec: dict, seg: dict, ffmpeg: str, node: str, out: Path,
                          keyfile: Path, key: str, log=print) -> dict:
    w, h, _ = work_size(spec)
    tpl = template_path(seg["template"], spec.get("base_dir"))
    payload = prepare_assets(spec, seg)
    data_file = out.with_suffix(".scene.json")
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    still = out.with_suffix(".png")
    at = min(max(1.2, seg["duration"] * 0.6), max(1.2, seg["duration"] - 0.1))
    cmd = [node, str(runtime.SKILL_DIR / "scripts" / "render_segment.mjs"),
           "--scene", str(tpl), "--out", str(out), "--data", str(data_file),
           "--fps", str(spec["video"]["fps"]), "--duration", str(seg["duration"]),
           "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
           "--still", str(round(at, 3)), "--still-out", str(still)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=runtime_env())
    if proc.returncode != 0:
        raise RuntimeError(f"still for '{seg['id']}' failed:\n{proc.stdout}\n{proc.stderr}")

    fps = spec["video"]["fps"]
    enc = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1",
           "-framerate", str(fps), "-i", str(still), "-t", f"{float(seg['duration']):.3f}",
           "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    enc_proc = subprocess.run(enc, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if enc_proc.returncode != 0:
        raise RuntimeError(f"holding still for '{seg['id']}' failed:\n{enc_proc.stderr[-2000:]}")
    keyfile.write_text(key)
    log(f"  still {seg['id']} ({seg['duration']}s @ {w}x{h}, 1 frame rendered)")
    return {"segment": seg["id"], "path": str(out), "cached": False, "still": True}


def runtime_env() -> dict:
    import os
    env = dict(os.environ)
    module, browsers = runtime.find_playwright()
    env["VS_PLAYWRIGHT"] = module
    if browsers:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browsers
    return env


def pending(spec: dict) -> list[dict]:
    """Segments that the timeline actually uses (unused segments are not rendered)."""
    used = {item["segment"] for item in spec["timeline"] if not item.get("source")}
    return [s for s in spec["segments"] if s["id"] in used]


def render_all(spec: dict, ffmpeg: str, node: str, jobs: int | None = None,
               force: bool = False, log=print) -> list[dict]:
    jobs = jobs or int((spec.get("render") or {}).get("jobs", 2))
    segs = pending(spec)
    if not segs:
        return []
    results = []
    if jobs <= 1:
        for seg in segs:
            results.append(render_segment(spec, seg, ffmpeg, node, force, log))
        return results
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(render_segment, spec, s, ffmpeg, node, force, log): s["id"]
                   for s in segs}
        for fut in as_completed(futures):
            results.append(fut.result())
    return results
