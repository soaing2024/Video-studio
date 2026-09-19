"""Orchestrate segment rendering: an authored scene + data -> cached intermediate clips.

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

from . import imagegen, libs, runtime, spec as specmod
from .sprite import make_sprite

# The only scene the skill ships: plumbing, no design. `vs.py init` copies it as a starting file.
BLANK_SCENE = runtime.SKILL_DIR / "assets" / "scenes" / "_blank.html"


def work_size(spec: dict) -> tuple[int, int, int]:
    """Render resolution and the integer upscale factor applied at assembly time."""
    look = spec.get("look") or {}
    px = look.get("pixelate")
    if px:
        s = max(1, int(px.get("scale", 4)))
        return spec["video"]["width"] // s, spec["video"]["height"] // s, s
    return spec["video"]["width"], spec["video"]["height"], 1


def scene_path(seg: dict) -> Path:
    """The scene an author wrote for this shot. `spec.normalize` already made it absolute.

    There is no name-to-file lookup: a shot is a file, not a selection. That removes the old
    cwd-relative trap as well, since the project directory is known at load time."""
    return Path(str(seg.get("scene") or ""))


def hold_args(seg: dict) -> list[str]:
    """Stretches inside a single take where the frame does not change; the renderer reuses one frame."""
    holds = seg.get("hold") or []
    if not holds:
        return []
    return ["--hold", ",".join(f"{float(a):.3f}-{float(b):.3f}" for a, b in holds)]


RUNTIME_FILES = ("scene.js", "anim.js", "kit.js", "three-kit.js")


def libs_for(spec: dict, seg: dict | None = None) -> list[Path]:
    """Vendored libraries this project (and this segment) opted into, in load order."""
    return libs.resolve(list(spec.get("libs") or []) + list((seg or {}).get("libs") or []))


def runtime_args(spec: dict | None = None, seg: dict | None = None) -> list[str]:
    """The pure-function runtimes every scene gets injected with, in load order.

    Vendored libraries ride the same path: Playwright's addInitScript reads the file from disk
    and evaluates it in the page before any scene script runs, so a `<script src>` - and the
    relative path it would need - never appears in a scene."""
    rt = runtime.SKILL_DIR / "assets" / "runtime"
    files = [str(rt / n) for n in RUNTIME_FILES]
    if spec is not None:
        files += [str(p) for p in libs_for(spec, seg)]
    return ["--runtimes", ",".join(files)]


def build_dir(spec: dict) -> Path:
    d = Path(spec["base_dir"]) / "build" / spec["name"]
    (d / "segments").mkdir(parents=True, exist_ok=True)
    return d


def segment_path(spec: dict, sid: str) -> Path:
    return build_dir(spec) / "segments" / f"{sid}.mp4"


def _key(spec: dict, seg: dict, w: int, h: int) -> str:
    hsh = hashlib.sha256()
    tpl = scene_path(seg)
    hsh.update(tpl.read_bytes() if tpl.is_file() else b"missing-scene")
    hsh.update(json.dumps(seg.get("data", {}), sort_keys=True, ensure_ascii=False).encode())
    for name, value in sorted(seg.get("assets", {}).items()):
        hsh.update(f"{name}:{value}:".encode())
        p = Path(str(value))
        if p.is_file():
            st = p.stat()
            hsh.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    hsh.update(f"{w}x{h}@{spec['video']['fps']}:{float(seg['duration'])}".encode())
    hsh.update(json.dumps(seg.get("hold") or [], sort_keys=True).encode())
    # A vendored library is part of the picture: upgrading it must invalidate the cache.
    hsh.update(libs.fingerprint(list(spec.get("libs") or []) + list(seg.get("libs") or [])).encode())
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
        # A .json asset is data, not a URL: lottie needs the parsed animation, and a file://
        # XHR would be blocked anyway. Anything else stays a file URL the scene can load.
        if isinstance(value, str) and Path(value).suffix.lower() == ".json" and Path(value).is_file():
            try:
                assets[name] = json.loads(Path(value).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise RuntimeError(f"asset '{name}' is not valid JSON: {e}") from e

    # Sprites are opt-in by data, not by picking a template: a scene that wants one says so.
    # (This block used to sit inside the loop, unguarded: any shot whose assets had no `subject`
    # - a JSON animation, say - died with a KeyError before it rendered.)
    if "sprite" not in assets and "subject" in assets and isinstance(data.get("sprite"), dict):
        cfg = data["sprite"]
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
    payload["assets"] = {k: (_file_url(v) if isinstance(v, str) else v) for k, v in assets.items()}
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

    tpl = scene_path(seg)
    if not tpl.is_file():
        raise FileNotFoundError(f"scene not found for segment '{seg['id']}': {tpl}")

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
           "--crf", str((spec.get("render") or {}).get("crf", 12))] + hold_args(seg) + runtime_args(spec, seg)
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
    tpl = scene_path(seg)
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
           "--still", str(round(at, 3)), "--still-out", str(still)] + runtime_args(spec, seg)
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
