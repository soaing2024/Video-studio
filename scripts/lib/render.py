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


def template_path(name: str) -> Path:
    p = Path(name)
    if p.suffix == ".html":
        return p if p.is_absolute() else (Path.cwd() / p)
    return TEMPLATES / f"{name}.html"


def build_dir(spec: dict) -> Path:
    d = Path(spec["base_dir"]) / "build" / spec["name"]
    (d / "segments").mkdir(parents=True, exist_ok=True)
    return d


def segment_path(spec: dict, sid: str) -> Path:
    return build_dir(spec) / "segments" / f"{sid}.mp4"


def segment_fps(spec: dict, seg: dict) -> int:
    """Frames per second to render one segment at.

    Long projects cannot afford the project frame rate for every shot, which is why the old
    pipeline rendered those shots as a single held frame - and why the result read as a slide
    deck. Rendering at a lower rate keeps the cost down without making the shot static: the
    assembly step duplicates frames back up to the project rate.
    """
    project = int(spec["video"]["fps"])
    want = (seg.get("data") or {}).get("anim_fps") or (spec.get("render") or {}).get("anim_fps")
    if not want:
        return project
    return max(4, min(project, int(want)))


def _key(spec: dict, seg: dict, w: int, h: int) -> str:
    hsh = hashlib.sha256()
    tpl = template_path(seg["template"])
    hsh.update(tpl.read_bytes() if tpl.is_file() else b"missing-template")
    hsh.update(json.dumps(seg.get("data", {}), sort_keys=True, ensure_ascii=False).encode())
    for name, value in sorted(seg.get("assets", {}).items()):
        hsh.update(f"{name}:{value}:".encode())
        p = Path(str(value))
        if p.is_file():
            st = p.stat()
            hsh.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    hsh.update(f"{w}x{h}@{segment_fps(spec, seg)}:{float(seg['duration'])}".encode())
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
    payload.setdefault("accent", (spec.get("look") or {}).get("accent", "#e0455f"))
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

    tpl = template_path(seg["template"])
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
           "--fps", str(segment_fps(spec, seg)), "--duration", str(seg["duration"]),
           "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
           "--crf", str((spec.get("render") or {}).get("crf", 12))]
    env = runtime_env()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"segment '{seg['id']}' failed:\n{proc.stdout}\n{proc.stderr}")
    keyfile.write_text(key)
    audit = _audit_of(proc.stdout)
    warnings = _audit_warnings(audit)
    if audit:
        audit_dir = build_dir(spec) / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / f"{seg['id']}.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  rendered {seg['id']} ({seg['duration']}s @ {w}x{h})")
    for message in warnings:
        log(f"    ! {seg['id']}: {message}")
    return {"segment": seg["id"], "path": str(out), "cached": False,
            "audit": audit, "warnings": warnings}


def _render_still_segment(spec: dict, seg: dict, ffmpeg: str, node: str, out: Path,
                          keyfile: Path, key: str, log=print) -> dict:
    w, h, _ = work_size(spec)
    tpl = template_path(seg["template"])
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


def _audit_of(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line).get("audit") or {}
            except json.JSONDecodeError:
                continue
    return {}


def _audit_warnings(audit: dict) -> list[str]:
    """Turn the renderer's layout audit into messages a person can act on."""
    out: list[str] = []
    if not audit:
        return out
    if audit.get("error"):
        return ["layout audit failed: " + str(audit["error"])]
    if audit.get("serifRisk"):
        out.append("body font is a serif fallback (" + str(audit.get("font"))[:48] +
                   ") - declare font-family")
    text_nodes = audit.get("textNodes") or 0
    visible = audit.get("visible") or 0
    if text_nodes and visible == 0:
        out.append("no text is visible at all - are the scene actors being rendered?")
    elif audit.get("invisible"):
        out.append(str(audit["invisible"]) + " text nodes never became visible, e.g. " +
                   ", ".join(audit.get("invisibleSamples") or []))
    if audit.get("offscreen"):
        out.append(str(audit["offscreen"]) + " text nodes sit outside the frame, e.g. " +
                   ", ".join(audit.get("offscreenSamples") or []))
    if audit.get("overlaps"):
        out.append(str(audit["overlaps"]) + " text blocks overlap, e.g. " +
                   "; ".join(audit.get("overlapSamples") or []))
    return out


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
