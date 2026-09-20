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


RUNTIME_FILES = ("scene.js", "anim.js", "phys.js", "look.js", "kit.js", "three-kit.js", "director.js")


def shutter_samples(spec: dict) -> int:
    """Oversampling factor for shutter-angle motion blur (look.finish.shutter).

    Frames are rendered N times denser and averaged, so a fast move smears across the
    exposure the way a real shutter would. Cost is linear in N: this is a delivery
    decision, not a default. 1 means off."""
    fin = (spec.get("look") or {}).get("finish") or {}
    if not isinstance(fin, dict):
        return 1
    sh = fin.get("shutter")
    if sh in (None, False):
        return 1
    if sh is True:
        n = 2
    elif isinstance(sh, dict):
        n = int(sh.get("samples", 2) or 2)
    else:
        n = int(sh)
    return max(1, min(4, n))


def render_fps(spec: dict) -> int:
    """Frames per second the scene is actually seeked at (target fps x shutter samples)."""
    return int(spec["video"]["fps"]) * shutter_samples(spec)


def render_span(spec: dict, seg: dict) -> float:
    """Clip length to render for a take: the shot plus the frames the shutter fold eats."""
    n = shutter_samples(spec)
    extra = (n - 1) / float(render_fps(spec)) if n > 1 else 0.0
    return float(seg["duration"]) + extra


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
    hsh.update(f"shutter={shutter_samples(spec)}".encode())
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
           "--fps", str(render_fps(spec)), "--duration", f"{render_span(spec, seg):.6f}",
           "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
           "--crf", str((spec.get("render") or {}).get("crf", 12))]
    cmd += hold_args(seg) + encode_args(spec, seg, w, h) + runtime_args(spec, seg)
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
               force: bool = False, slices: int | None = None,
               incremental: bool | None = None, log=print) -> list[dict]:
    jobs = jobs or int((spec.get("render") or {}).get("jobs", 2))
    slices = slices or int((spec.get("render") or {}).get("slices", 1) or 1)
    if incremental is not None:
        spec.setdefault("render", {})["incremental"] = bool(incremental)
    segs = pending(spec)
    if not segs:
        return []
    # A single take is one segment, so segment-level parallelism does nothing for it.
    # Slicing the take in time is exactly equivalent - seek(t) is a pure function - and it
    # is the only lever that makes 4K affordable. Still one export: slices are re-joined
    # losslessly into the same segment file the assembler expects.
    if len(segs) == 1 and slices > 1:
        return [render_sliced(spec, segs[0], ffmpeg, node, slices, jobs, force, log)]
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


# --------------------------------------------------------------------------- delivery size

# Measured on a 4K scene (3840x2160), 12-frame windows, one process, one Chromium:
#   playwright png (software GL) 730 ms/frame | + GPU 671 | + CDP optimizeForSpeed 166 (lossless)
#   | jpeg q97 102. Cost tracks megapixels closely, so the model is per-megapixel.
RATE_MS_PER_MPX = {"png": 88.0, "png_fast": 20.0, "jpeg": 12.0}
_GPU_MEM_GB_PER_JOB = {True: 1.6, False: 0.7}      # 4K vs <=1080p, measured


def png_kind(spec: dict) -> str:
    r = spec.get("render") or {}
    if r.get("jpeg"):
        return "jpeg"
    return "png" if str(r.get("png-compression", "fast")) == "default" else "png_fast"


def frame_cost_ms(spec: dict, w: int, h: int) -> float:
    """Steady-state milliseconds per frame at this size and pixel format."""
    return RATE_MS_PER_MPX[png_kind(spec)] * (w * h / 1e6)


def free_gb() -> float | None:
    """Available physical memory, without adding a dependency."""
    try:
        import psutil
        return psutil.virtual_memory().available / 2 ** 30
    except Exception:
        pass
    try:
        import os
        if os.name == "nt":
            import ctypes

            class _M(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _M()
            m.dwLength = ctypes.sizeof(_M)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullAvailPhys / 2 ** 30
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 2 ** 20
    except Exception:
        return None
    return None


def safe_jobs(w: int, h: int, jobs: int, log=print) -> int:
    """Clamp concurrency to what the machine can actually hold.

    This is the failure that wastes whole renders: at 4K each Chromium + x264 pair needs
    ~1.5 GB, so six of them take a 16 GB machine to 0.2 GB free and processes die
    silently while their parent waits forever.
    """
    gb = free_gb()
    if gb is None:
        return jobs
    per = _GPU_MEM_GB_PER_JOB[w * h >= 4_000_000]
    cap = max(1, int(gb / per))
    if cap < jobs:
        log(f"  memory guard: {gb:.1f} GB free at {w}x{h} -> {cap} job(s) instead of {jobs}")
        return cap
    return jobs


def encode_args(spec: dict, seg: dict | None = None, w: int = 0, h: int = 0) -> list[str]:
    """Renderer flags that decide speed and memory at delivery size."""
    r = spec.get("render") or {}
    accel = spec.get("accel") or {}
    out: list[str] = []
    out += ["--preset", str(r.get("preset") or "ultrafast")]
    if r.get("jpeg"):
        out += ["--jpeg", str(int(r["jpeg"]))]
    if r.get("png-compression"):
        out += ["--png-compression", str(r["png-compression"])]
    if r.get("gpu") is False or accel.get("gpu") is False:
        out += ["--gpu", "false"]
    if r.get("reboot"):
        out += ["--reboot", str(int(r["reboot"]))]
    elif w * h >= 4_000_000:
        out += ["--reboot", "90"]        # cap browser memory over a long 4K take
    return out


def slice_ranges(duration: float, fps: int, slices: int) -> list[tuple[int, float, float]]:
    n = max(1, min(int(slices), max(1, int(round(duration * fps)))))
    span = duration / n
    return [(i, i * span, span) for i in range(n)]


def count_frames(ffmpeg: str, path: str) -> int:
    """Frame count without decoding (there is no ffprobe in the vendored build)."""
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
                           "-map", "0:v", "-c", "copy", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    last = -1
    for line in proc.stderr.splitlines():
        if "frame=" in line:
            try:
                last = int(line.split("frame=")[1].split()[0])
            except ValueError:
                pass
    return last


def signature_pass(spec: dict, seg: dict, ffmpeg: str, node: str, stride: int = 1,
                    log=print) -> dict:
    """Per-frame state hashes without taking a screenshot (~10-20 s for a 30 s take).

    The signature covers everything that decides the picture - element transforms,
    opacities, text, and a downscaled canvas readback - so two frames with equal
    signatures are equal frames.
    """
    w, h, _ = work_size(spec)
    out = build_dir(spec) / "sig" / f"{seg['id']}.json"
    data_file = out.with_suffix(".data.json")
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(seg.get("data") or {}, ensure_ascii=False), encoding="utf-8")
    cmd = [node, str(runtime.SKILL_DIR / "scripts" / "render_segment.mjs"),
           "--scene", str(scene_path(seg)), "--out", str(out.with_suffix(".mp4")),
           "--data", str(data_file), "--fps", str(spec["video"]["fps"]),
           "--duration", str(seg["duration"]), "--width", str(min(w, 1920)),
           "--height", str(min(h, 1080)), "--ffmpeg", ffmpeg,
           "--sig", str(out), "--sig-stride", str(stride),
           "--sig-canvas", str(int(bool((spec.get("render") or {}).get("sig_canvas", False))))]
    cmd += runtime_args(spec, seg)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=runtime_env())
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"signature pass failed for '{seg['id']}': "
                           f"{(proc.stdout or proc.stderr)[-300:]}")
    doc = json.loads(out.read_text(encoding="utf-8"))
    doc["scene_hash"] = hashlib.sha256(scene_path(seg).read_bytes()).hexdigest()[:16]
    log(f"  signature: {doc['frames']} frames, {len(set(doc['sigs']))} distinct states")
    return doc


def changed_slices(prev: dict | None, cur: dict, durations: list[tuple[float, float]],
                   fps: int) -> list[int]:
    """Which slices contain a frame whose state changed (or that never rendered)."""
    if not prev or "sigs" not in prev:
        return list(range(len(durations)))
    if prev.get("scene_hash") == cur.get("scene_hash"):
        return []
    a, b, stride = prev["sigs"], cur["sigs"], cur.get("stride", 1)
    hit = []
    for i, (start, span) in enumerate(durations):
        f0, f1 = int(start * fps), int((start + span) * fps)
        for f in range(f0, min(f1, len(b))):
            j = f // stride
            if j >= len(a) or j >= len(b) or a[j] != b[j]:
                hit.append(i)
                break
    return hit


def render_sliced(spec: dict, seg: dict, ffmpeg: str, node: str, slices: int, jobs: int,
                  force: bool = False, log=print) -> dict:
    """Render one take as N parallel time slices, then re-join them losslessly.

    Slice cache keys mean a re-run after a crash only renders the slices that are missing,
    and an unchanged project re-uses everything (the segment .key is still written, so the
    existing segment-level cache keeps working too).
    """
    w, h, _ = work_size(spec)
    fps = int(spec["video"]["fps"])
    duration = float(seg["duration"])
    if shutter_samples(spec) > 1 and slices > 1:
        # Every slice would average across its own boundary, and the seam would show; the
        # shutter path renders as one process and says so instead of failing silently.
        log("  shutter: slices forced to 1 (motion blur needs neighbouring frames)")
        slices = 1
    out = segment_path(spec, seg["id"])
    if not force and out.is_file() and out.with_suffix(".key").is_file():
        key = _key(spec, seg, w, h)
        if out.with_suffix(".key").read_text().strip() == key:
            return {"segment": seg["id"], "path": str(out), "cached": True}
    parts = build_dir(spec) / "slices"
    parts.mkdir(parents=True, exist_ok=True)
    holds = [tuple(map(float, x)) for x in (seg.get("hold") or [])]
    payload = prepare_assets(spec, seg)
    jobs = safe_jobs(w, h, jobs, log=log)
    plan = slice_ranges(duration, fps, slices)
    incremental = bool((spec.get("render") or {}).get("incremental"))
    sig_path = build_dir(spec) / "sig" / f"{seg['id']}.prev.json"
    if incremental:
        # cheap pass first: which frames actually changed since the last render?
        prev = json.loads(sig_path.read_text(encoding="utf-8")) if sig_path.is_file() else None
        cur = signature_pass(spec, seg, ffmpeg, node, log=log)
        n_prev = len(prev["sigs"]) if prev else 0
        n_diff = (sum(1 for i in range(min(n_prev, len(cur["sigs"])))
                  if prev["sigs"][i] != cur["sigs"][i]) if prev else -1)
        log(f"  incremental: prev={prev.get('scene_hash') if prev else None} "
            f"cur={cur.get('scene_hash')} frames_diff={n_diff}/{n_prev}")
        keep = [i for i in range(len(plan)) if i not in changed_slices(prev, cur, [(p[1], p[2]) for p in plan], fps)]
        sidx = {p[0]: p for p in plan}
        for i in keep:
            k, start, span = sidx[i]
            part = parts / f"{seg['id']}.{i:03d}.mp4"
            keyf = part.with_suffix(".key")
            if part.is_file() and keyf.is_file():
                keyf.write_text(_slice_key(spec, seg, payload, i, start, span, w, h))
        plan = [p for p in plan if p[0] not in keep]
        log(f"  incremental: {len(keep)}/{len(plan) + len(keep)} slice(s) reused, {len(plan)} to render")
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        sig_path.write_text(json.dumps(cur), encoding="utf-8")
        if not plan:
            # nothing changed: re-join from the cached slices and stop
            plan = sorted([(i, i * (duration / slices_), duration / slices_)
                           for i, slices_ in [(0, slices)]][0] for i in range(0))
    log(f"  take: {duration:g}s @ {w}x{h} -> {len(plan)} slice(s) to render, {jobs} job(s), "
        f"{RATE_MS_PER_MPX[png_kind(spec)]:.0f} ms/mpx")

    def one(item):
        i, start, span = item
        part = parts / f"{seg['id']}.{i:03d}.mp4"
        keyf = part.with_suffix(".key")
        key = _slice_key(spec, seg, payload, i, start, span, w, h)
        if not force and part.is_file() and keyf.is_file() and keyf.read_text().strip() == key:
            return {"part": str(part), "cached": True, "index": i}
        d = dict(payload)
        # The take offset is a property of the CHANNEL, not of the scene. It travels to the
        # renderer on --offset, which shifts window.seek itself; window.SCENE must never carry
        # it. A scene therefore knows nothing about slicing and still gets absolute take time.
        data_file = part.with_suffix(".data.json")
        data_file.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        take_offset = ["--offset", f"{start:.6f}"]
        local_holds = ",".join(f"{max(0.0, a - start):.3f}-{min(span, b - start):.3f}"
                               for a, b in holds if b > start and a < start + span)
        cmd = [node, str(runtime.SKILL_DIR / "scripts" / "render_segment.mjs"),
               "--scene", str(scene_path(seg)), "--out", str(part), "--data", str(data_file),
               "--fps", str(render_fps(spec)), "--duration", f"{span:.6f}",
               "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
               "--crf", str((spec.get("render") or {}).get("crf", 12))] + take_offset
        if local_holds:
            cmd += ["--hold", local_holds]
        cmd += encode_args(spec, seg, w, h) + runtime_args(spec, seg)
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=runtime_env())
        if proc.returncode != 0:
            detail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr
            raise RuntimeError(f"slice {i} of '{seg['id']}' failed: {detail[:400]}")
        keyf.write_text(key)
        info = {}
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception:
            pass
        return {"part": str(part), "cached": False, "index": i,
                "ms_per_frame": info.get("ms_per_frame")}

    want_all = slice_ranges(duration, fps, slices)
    # Keep what each worker actually reported. Rebuilding this list from want_all with
    # `cached: True` hardcoded made "N freshly rendered" print 0 on every run and threw away the
    # per-slice ms/frame - the two numbers an agent uses to decide whether the cache worked and
    # what a re-render will cost.
    done = {}
    if plan:
        with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(plan)))) as pool:
            for r in pool.map(one, plan):
                done[r["index"]] = r
    results = []
    for i, start, span in want_all:
        part = parts / f"{seg['id']}.{i:03d}.mp4"
        results.append(done.get(i) or {"part": str(part), "index": i, "cached": True})

    lst = parts / f"{seg['id']}.txt"
    lines = ["file '" + Path(r["part"]).as_posix() + "'\n" for r in results]
    lst.write_text("".join(lines), encoding="utf-8")
    proc = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
                           "-safe", "0", "-i", str(lst), "-c", "copy",
                           "-movflags", "+faststart", str(out)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"joining slices for '{seg['id']}' failed: {proc.stderr[-300:]}")
    want = int(round(duration * fps))
    got = count_frames(ffmpeg, str(out))
    if got != want:
        raise RuntimeError(f"joined take has {got} frames, expected {want} "
                           f"({len(plan)} slices of a {duration:g}s take)")
    out.with_suffix(".key").write_text(_key(spec, seg, w, h))
    fresh = sum(1 for r in results if not r["cached"])
    ms = [r["ms_per_frame"] for r in results if r.get("ms_per_frame")]
    log(f"  rendered {seg['id']} ({duration:g}s @ {w}x{h}, {len(plan)} slices, "
        f"{fresh} freshly rendered{', ' + str(round(sum(ms) / len(ms))) + ' ms/frame' if ms else ''})")
    return {"segment": seg["id"], "path": str(out), "cached": False, "slices": len(plan),
            "slices_rendered": fresh, "frames": got}


def _slice_key(spec: dict, seg: dict, payload: dict, i: int, start: float, span: float,
               w: int, h: int) -> str:
    hsh = hashlib.sha256()
    hsh.update(scene_path(seg).read_bytes())
    hsh.update(json.dumps({**payload, "offset": start}, sort_keys=True, ensure_ascii=False).encode())
    for name, value in sorted((seg.get("assets") or {}).items()):
        pth = Path(str(value))
        if pth.is_file():
            st = pth.stat()
            hsh.update(f"{name}:{st.st_size}:{int(st.st_mtime)}".encode())
    hsh.update(f"{w}x{h}@{spec['video']['fps']}:{span:.6f}:{i}".encode())
    hsh.update(json.dumps(encode_args(spec, seg, w, h)).encode())
    # The injected runtimes decide the picture just as much as the scene does - the take-offset
    # shim lives in scene.js. Without them in the key, editing a runtime reuses stale slices and
    # the delivered take silently mixes two versions of the pipeline.
    for name in RUNTIME_FILES:
        rt = runtime.SKILL_DIR / "assets" / "runtime" / name
        if rt.is_file():
            st = rt.stat()
            hsh.update(f"rt:{name}:{st.st_size}:{int(st.st_mtime)}".encode())
    hsh.update(libs.fingerprint(list(spec.get("libs") or []) + list(seg.get("libs") or [])).encode())
    return hsh.hexdigest()[:16]


def probe_frames(spec: dict, seg: dict, ffmpeg: str, node: str, times: list[float],
                 out_dir, w: int | None = None, h: int | None = None, jobs: int = 3,
                 log=print) -> list[dict]:
    """One still + one DOM probe per time point. The data channel behind `preview --report`."""
    ww, hh, _ = work_size(spec)
    w = w or ww
    h = h or hh
    payload = prepare_assets(spec, seg)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def one(t):
        png = out_dir / f"t{t:07.3f}.png"
        pj = out_dir / f"t{t:07.3f}.probe.json"
        d = dict(payload)
        # Stills are addressed by ABSOLUTE take time, exactly like a slice's frames are once the
        # channel has shifted them. No offset on this path at all.
        data_file = out_dir / f"t{t:07.3f}.data.json"
        data_file.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        cmd = [node, str(runtime.SKILL_DIR / "scripts" / "render_segment.mjs"),
               "--scene", str(scene_path(seg)), "--out", str(out_dir / f"t{t:07.3f}.mp4"),
               "--data", str(data_file), "--fps", str(spec["video"]["fps"]), "--duration", "0.05",
               "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
               "--still", f"{t:.3f}", "--still-out", str(png), "--probe", str(pj)]
        cmd += encode_args(spec, seg, w, h) + runtime_args(spec, seg)
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=runtime_env())
        ok = proc.returncode == 0 and png.is_file()
        info = {}
        if proc.stdout.strip():
            try:
                info = json.loads(proc.stdout.strip().splitlines()[-1])
            except Exception:
                info = {"raw": proc.stdout.strip()[-200:]}
        return {"t": t, "ok": ok, "png": str(png) if ok else None,
                "probe": str(pj) if pj.is_file() else None, "result": info}

    with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(times)))) as pool:
        rows = list(pool.map(one, times))
    rows.sort(key=lambda r: r["t"])
    return rows
