"""Cheap rehearsal: watch the timing before the delivery render exists.

The skill's discipline is one delivery render per version, which is right - but it left
timing with nothing to look at except paper, and timing is where motion actually fails.
This module is the missing middle: a draft that is deliberately *not* a deliverable.

    * a fraction of the pixels (`--scale 0.35` on a 1080p take is ~380p, still the full CSS
      layout, so composition is honest)
    * a third of the frames (`--fps 12`)
    * JPEG frames instead of lossless PNG, x264 ultrafast, CRF 30
    * a contact sheet of the whole take in one image

Measured on the selftest scene, a 30s 1080p take costs ~14 s of wall clock as a draft versus
~4 minutes as a delivery render. A draft never touches `build/<name>/segments/`, so no cache
key is invalidated and the delivery render is still the first and only real one.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import render, runtime, spec as specmod

# Two rehearsals live here: `draft` renders a cheap video you can watch, `scrub_html` writes a


def parse_range(text: str | None, seg: dict) -> tuple[float, float]:
    """`--at 3:7.5` -> (3.0, 7.5); no `--at` -> the whole shot."""
    if not text:
        return 0.0, float(seg["duration"])
    parts = str(text).replace(",", ":").split(":")
    a = float(parts[0] or 0.0)
    b = float(parts[1]) if len(parts) > 1 and parts[1] else float(seg["duration"])
    if b <= a:
        raise ValueError(f"rehearsal range {text!r} is empty")
    return a, b


def draft(spec: dict, ffmpeg: str, node: str, *, at: str | None = None, scale: float = 0.35,
          fps: int = 12, jpeg: int = 85, sheet: bool = True, cols: int = 6, log=print) -> dict:
    segs = render.pending(spec)
    if not segs:
        raise ValueError("project has no segments to rehearse")
    seg = segs[0]
    a, b = parse_range(at, seg)
    duration = max(0.2, b - a)

    out_dir = render.build_dir(spec) / "rehearsal"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"draft-{seg['id']}-{a:g}-{b:g}.mp4"

    payload = render.prepare_assets(spec, seg, log=log)
    # The window start is a CHANNEL fact: it goes to the renderer, which shifts window.seek.
    # A draft is addressed by absolute take time, so the scene never sees it (see API.md §契约).
    data_file = out.with_suffix(".data.json")
    data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    w, h, _ = render.work_size(spec)
    holds = [f"{max(0.0, x - a):.3f}-{min(duration, y - a):.3f}"
             for x, y in (seg.get("hold") or []) if y > a and x < b]
    # Chromium hands back *progressive* JPEGs when deviceScaleFactor is below 1, and ffmpeg's
    # image2pipe probe cannot detect those (it parses, it does not decode), so a scaled draft
    # has to stay PNG. Full-size drafts may use JPEG: there the frames are baseline.
    scaled = abs(float(scale) - 1.0) > 1e-6
    cmd = [node, str(runtime.SKILL_DIR / "scripts" / "render_segment.mjs"),
           "--scene", str(render.scene_path(seg)), "--out", str(out), "--data", str(data_file),
           "--fps", str(int(fps)), "--duration", f"{duration:.3f}",
           "--width", str(w), "--height", str(h), "--ffmpeg", ffmpeg,
           "--crf", "30", "--preset", "ultrafast", "--offset", f"{a:.3f}"]
    if scaled:
        cmd += ["--scale", f"{float(scale):.4f}", "--png-compression", "fast"]
    else:
        cmd += ["--jpeg", str(int(jpeg))]
    if holds:
        cmd += ["--hold", ",".join(holds)]
    cmd += render.runtime_args(spec, seg)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=render.runtime_env())
    if proc.returncode != 0 or not out.is_file():
        detail = (proc.stdout or proc.stderr).strip()[-500:]
        raise RuntimeError(f"rehearsal draft failed for '{seg['id']}': {detail}")
    info = {}
    try:
        info = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        pass
    log(f"  rehearsal: {seg['id']} {a:g}-{b:g}s -> {out.name} "
        f"({info.get('ms_per_frame', '?')} ms/frame, JPEG q{jpeg}, {fps} fps)")

    result = {"ok": True, "which": "rehearse", "draft": str(out), "segment": seg["id"],
              "range": [a, b], "scale": float(scale), "fps": int(fps), "jpeg": int(jpeg),
              "draft_frames": info.get("frames"), "ms_per_frame": info.get("ms_per_frame"),
              "delivery_render_still_needed": True}

    if sheet:
        tiles = max(1, int(cols) * 4)
        sheet_path = out_dir / f"sheet-{seg['id']}-{a:g}-{b:g}.png"
        step = max(1e-3, duration / tiles)
        vf = (f"fps=1/{step:.4f},scale=320:-2,"
              f"tile={int(cols)}x4:margin=8:padding=4:color=#111111")
        proc = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                               "-i", str(out), "-vf", vf, "-frames:v", "1", str(sheet_path)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0 and sheet_path.is_file():
            result["sheet"] = str(sheet_path)
            result["sheet_interval"] = round(step, 3)
            log(f"  rehearsal: contact sheet -> {sheet_path.name} "
                f"(one frame every {step:.2f}s)")
        else:
            result["sheet_error"] = proc.stderr.strip()[-200:]
    return result


def summary_line(report: dict) -> str:
    a, b = report.get("range", [0, 0])
    return (f"draft {a:g}-{b:g}s @ {report.get('scale')}x, {report.get('fps')} fps -> "
            f"{Path(report.get('draft', '')).name}"
            + (f" + {Path(report['sheet']).name}" if report.get("sheet") else ""))
SCRUB_UI = r'''<div id="vs-scrub" style="position:fixed;left:0;right:0;bottom:0;z-index:99999;
font:12px/1.5 system-ui;background:#111c;color:#eee;padding:6px 10px;display:flex;gap:10px;align-items:center">
<button id="vs-play">pause</button>
<input id="vs-seek" type="range" min="0" max="1000" value="0" style="flex:1">
<span id="vs-read" style="width:160px;text-align:right"></span>
<select id="vs-speed"><option value="0.25">0.25x</option><option value="0.5">0.5x</option>
<option value="1" selected>1x</option><option value="2">2x</option></select>
<button id="vs-stepm">-1f</button><button id="vs-stepp">+1f</button>
<label><input id="vs-safe" type="checkbox">safe</label></div>
<script>
(function(){
  var P = window.SCENE || {}, D = P.duration || 10, FPS = P.fps || 30, seek = window.seek;
  var bar = document.getElementById('vs-seek'), read = document.getElementById('vs-read');
  var play = document.getElementById('vs-play'), speed = document.getElementById('vs-speed');
  if (typeof seek !== 'function') { read.textContent = 'no seek(t)'; return; }
  var t = 0, running = true, last = performance.now();
  var safe = document.getElementById('vs-safe'), box = document.createElement('div');
  box.style.cssText = 'position:fixed;inset:0;pointer-events:none;display:none;z-index:99998';
  box.innerHTML = '<div style="position:absolute;inset:5% 4% 8%;border:1px dashed #ff4d6d88"></div><div style="position:absolute;inset:12% 6% 20%;border:1px dashed #4dc3ff88"></div>';
  document.body.appendChild(box);
  safe.addEventListener('change', function(){ box.style.display = safe.checked ? 'block' : 'none'; });
  function set(v, user){ t = Math.max(0, Math.min(D, v)); seek(t);
    if (!user) bar.value = String(Math.round(t / D * 1000));
    read.textContent = t.toFixed(2) + 's / ' + D.toFixed(2) + 's  f' + Math.round(t * FPS); }
  bar.addEventListener('input', function(){ set(bar.value / 1000 * D, true); });
  play.addEventListener('click', function(){ running = !running; play.textContent = running ? 'pause' : 'play'; last = performance.now(); });
  document.getElementById('vs-stepm').addEventListener('click', function(){ running = false; play.textContent = 'play'; set(t - 1 / FPS, false); });
  document.getElementById('vs-stepp').addEventListener('click', function(){ running = false; play.textContent = 'play'; set(t + 1 / FPS, false); });
  document.addEventListener('keydown', function(e){
    if (e.code === 'Space') { e.preventDefault(); play.click(); }
    if (e.code === 'ArrowRight') { e.preventDefault(); set(t + (e.shiftKey ? 1 : 1 / FPS), false); }
    if (e.code === 'ArrowLeft') { e.preventDefault(); set(t - (e.shiftKey ? 1 : 1 / FPS), false); } });
  (function loop(now){ var dt = (now - last) / 1000; last = now;
    if (running) set(t + dt * Number(speed.value), false); requestAnimationFrame(loop); })(performance.now());
  set(0, false);
})();
</script>'''


def scrub_html(spec: dict, out: str | Path | None = None, log=print) -> dict:
    """Write a standalone page that scrubs the real scene. No rendering at all.

    The scene's own script runs after the runtimes are injected, exactly as in a render,
    so what you scrub is what the renderer sees - including `Phys` bakes."""
    seg = render.pending(spec)[0]
    payload = render.prepare_assets(spec, seg, log=log)
    # The transport drives absolute take time, so the shim adds 0; it is installed anyway so
    # that every entry point runs the scene through exactly the same channel.
    payload["fps"] = spec["video"]["fps"]
    payload["duration"] = float(seg["duration"])
    scene = render.scene_path(seg).read_text(encoding="utf-8")
    rt = runtime.SKILL_DIR / "assets" / "runtime"
    injected = ['<script>window.__TAKE_OFFSET = 0;</script>']
    injected += [f'<script src="{render._file_url(rt / n)}"></script>' for n in render.RUNTIME_FILES]
    injected += [f'<script src="{render._file_url(p)}"></script>' for p in render.libs_for(spec, seg)]
    injected.append("<script>window.SCENE = " + json.dumps(payload, ensure_ascii=False) + ";</script>")
    block = "\n".join(injected)
    if "<head" in scene:
        j = scene.index(">", scene.index("<head")) + 1
        html = scene[:j] + "\n" + block + scene[j:]
    else:
        html = block + "\n" + scene
    html = html[:html.rindex("</body")] + SCRUB_UI + "\n" + html[html.rindex("</body"):] if "</body" in html else html + SCRUB_UI
    target = Path(out) if out else render.build_dir(spec) / "scrub.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    log(f"  scrub: {target}")
    return {"ok": True, "which": "scrub", "html": str(target), "segment": seg["id"],
            "duration": float(seg["duration"]), "bytes": len(html.encode("utf-8")),
            "hint": "open in a browser: space plays, arrows step one frame, shift+arrow jumps a second"}
