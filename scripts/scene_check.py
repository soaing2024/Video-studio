"""Pre-render self-check: the whole timeline in one browser pass, plus typography calibration.

P1-F + P1-H. `verify` measures the finished file and cannot see any of this:

  * an element flying out of frame at t=8.3
  * a "ghost" - a window lit from t=0 because a keyframe track ramps where it should hold
  * a transform that has gone to NaN
  * CJK glyphs silently falling back (tofu) in headless Chromium
  * a headline whose contrast is 2.1:1 on the fog-white canvas
  * a 12x type-scale jump between the English and the Chinese line

    python scripts/scene_check.py <project.json> [--stride 0.25] [--json]

Writes `<build>/scene_check.json`. Exit 1 on hard failures only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib import analyze, fmt, render, runtime, spec as specmod  # noqa: E402

CALIB_HTML = """<!doctype html><meta charset="utf-8"><style>
 body{margin:0;background:#f7f8fa;font-family:"Microsoft YaHei","Noto Sans SC",system-ui,sans-serif}
 #a{font-size:64px;color:#0b0f14;position:absolute;left:20px;top:20px;white-space:nowrap}
 #b{font-size:64px;color:#0b0f14;position:absolute;left:20px;top:120px;white-space:nowrap;
    font-family:"__missing_font_that_cannot_exist__"}
 #c{font-size:32px;color:#0b0f14;position:absolute;left:20px;top:240px;white-space:nowrap}
 .sw{position:absolute;width:120px;height:60px;left:20px}
</style><body>
 <div id="a">去点亮 Star 一次编译</div>
 <div id="b">去点亮 Star 一次编译</div>
 <div id="c">Star it. 去点亮 Star</div>
 <div class="sw" style="top:320px;background:#ffffff;color:#7c8698"><span id="d">Aa</span></div>
 <div id="fontcheck" style="position:absolute;left:20px;top:420px;font-size:12px">?</div>
</body>
<script>
 window.seek=function(){};window.__sceneReady=true;
 // Resolved locally: a font that is not installed reports false, and the width comparison below
 // then only says 'fallback', not 'tofu'. Tofu is decided from the rendered pixels.
 document.getElementById('fontcheck').textContent =
   document.fonts.check('64px "Microsoft YaHei"') ? 'font-resolved' : 'font-missing';
</script>"""


def run_scan(spec: dict, ffmpeg: str, node: str, stride: float, log=print) -> dict:
    seg = spec["segments"][0]
    w, h, _ = render.work_size(spec)
    d = render.build_dir(spec) / "scan.data.json"
    # Same payload the renderer will feed the scene (assets resolved to file URLs, duration / id /
    # accent injected). Feeding the scan only `data` meant a scene that reads SCENE.assets saw
    # undefined here and a real value at render time - so `check` could disagree with the film.
    d.write_text(json.dumps(render.prepare_assets(spec, seg)), encoding="utf-8")
    cmd = [node, str(HERE / "scan_scene.mjs"), "--scene", str(render.scene_path(seg)),
           "--data", str(d), "--duration", str(seg["duration"]), "--stride", str(stride),
           "--width", str(min(w, 1920)), "--height", str(min(h, 1080))]
    cmd += render.runtime_args(spec, seg)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=render.runtime_env())
    if proc.returncode != 0 or not proc.stdout.strip():
        raise fmt.fail("SCAN_FAILED", str(render.scene_path(seg)),
                       "scan_scene.mjs exits 0 with a JSON line",
                       (proc.stderr or proc.stdout)[-200:],
                       "run `vs.py preview <project> --report` for a single failing frame")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def calibrate(spec: dict, ffmpeg: str, node: str, log=print) -> dict:
    """CJK glyphs, contrast and bilingual scale, measured in the real headless browser."""
    """CJK glyphs, contrast and type-scale ratio, measured in the real headless browser."""
    # One mkdtemp, always cleaned in the finally below: this used to leak a directory per call.
    tmp = Path(tempfile.mkdtemp(prefix="vs-calib-"))
    try:
        html = tmp / "calib.html"
        html.write_text(CALIB_HTML, encoding="utf-8")
        png, probe = tmp / "c.png", tmp / "c.json"
        cmd = [node, str(HERE / "render_segment.mjs"), "--scene", str(html),
               "--out", str(tmp / "c.mp4"), "--fps", "30", "--duration", "0.05",
               "--width", "960", "--height", "540", "--ffmpeg", ffmpeg,
               "--still", "0", "--still-out", str(png), "--probe", str(probe)]
        cmd += render.runtime_args(spec, spec["segments"][0])
        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=render.runtime_env())
        out = {"cjk_ok": None, "fallback_delta": None, "contrast": None,
               "bilingual_scale": None, "sizes": []}
        if probe.is_file():
            els = json.loads(probe.read_text(encoding="utf-8"))["elements"]
            # Key by element id, not by text: the two 64px calibration lines carry the *same*
            # sentence, so a text-keyed dict kept only one of them and the font-fallback check
            # could never fire (it needed two widths and always found one).
            by_id = {e.get("id"): e for e in els if isinstance(e, dict) and e.get("id")}
            a, b = by_id.get("a"), by_id.get("b")
            if a and b:
                # the real font and the deliberately-missing font must not measure identically
                out["fallback_delta"] = round(abs(a["w"] - b["w"]), 1)
                out["cjk_ok"] = out["fallback_delta"] > 0.5 and a["w"] > 8
            else:
                widths = sorted((e["w"] for e in els
                                 if str(e.get("text", "")).startswith("去点亮")
                                 and e.get("fs") == 64), reverse=True)
                if len(widths) >= 2:
                    out["fallback_delta"] = round(abs(widths[0] - widths[1]), 1)
                    out["cjk_ok"] = out["fallback_delta"] > 0.5 and widths[0] > 8
            sizes = sorted({e["fs"] for e in els if e.get("fs")})
            out["sizes"] = sizes
            if len(sizes) >= 2 and sizes[0] > 0:
                out["bilingual_scale"] = round(sizes[-1] / sizes[0], 2)
            out["named_font_resolved"] = (by_id.get("fontcheck", {}) or {}).get("text") == "font-resolved"
            # Tofu or silent fallback? Measure the ink inside the headline's own box: a missing CJK
            # face that draws nothing leaves an empty box, while a working fallback still draws.
            headline = by_id.get("a")
            if headline and png.is_file():
                try:
                    from PIL import Image
                    import numpy as np
                    im = Image.open(png).convert("L")
                    x0 = max(0, int(headline["x"]))
                    y0 = max(0, int(headline["y"]))
                    x1 = min(im.width, int(headline["x"] + headline["w"]))
                    y1 = min(im.height, int(headline["y"] + headline["h"]))
                    if x1 > x0 and y1 > y0:
                        arr = np.asarray(im.crop((x0, y0, x1, y1)))
                        out["headline_ink_pct"] = round(float((arr < 200).mean()) * 100, 2)
                        out["glyphs_drawn"] = out["headline_ink_pct"] > 0.5
                except Exception as e:      # measurement must not fail the check itself
                    out["ink_error"] = str(e)[:120]
            for e in els:
                if e.get("fs") == 32:
                    fg = analyze._rgb(e.get("color"))
                    bg = (analyze._rgb(e.get("bgEff")) or analyze._rgb(e.get("bg"))
                          or (247, 248, 250))
                    if fg:
                        out["contrast"] = analyze.contrast(fg, bg)
        return out
    finally:
        # Every check used to leave a temp directory behind: %TEMP% had 77 of them.
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pre-render self-check for a scene",
                                 epilog="example: python scripts/scene_check.py work/mine/project.json --stride 0.5")
    ap.add_argument("project")
    ap.add_argument("--stride", type=float, default=0.25, help="timeline sampling step in seconds")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-calibrate", action="store_true")
    args = ap.parse_args(argv)
    fmt.configure(json=args.json, verbose=args.verbose)

    spec = specmod.load(args.project)
    ffmpeg, node = runtime.find_ffmpeg(), runtime.find_node()
    # A VsError (missing scene, unusable scan) has to come out as the structured error contract,
    # not as a traceback: the caller (vs.py check) only forwards structured output.
    try:
        scan = run_scan(spec, ffmpeg, node, args.stride)
        calib = {} if args.no_calibrate else calibrate(spec, ffmpeg, node)
    except fmt.VsError as e:
        return fmt.report_error(e)

    ghosts = [{"id": k, "tag": v["tag"], "text": v["text"], "size": v["size"], "from": v["spans"][0][0]}
              for k, v in scan.get("visibility", {}).items()
              if v["spans"] and v["spans"][0][0] <= 0.001 and v["spans"][-1][1] > 1.0]
    problems = []
    warnings: list[dict] = []
    if not scan.get("ready"):
        problems.append({"kind": "scene_not_ready", "detail": "window.seek never became ready"})
    for b in scan.get("broken", [])[:10]:
        problems.append(b)
    if scan.get("nan"):
        problems.append({"kind": "nan_transform", **scan["nan"][0]})
    if scan.get("errors"):
        problems.append({"kind": "page_error", "detail": scan["errors"][0][:200]})
    if calib and calib.get("cjk_ok") is False:
        if calib.get("glyphs_drawn") is False:
            problems.append({"kind": "cjk_font_fallback",
                             "detail": f"no glyphs drawn for the CJK headline "
                                       f"(ink {calib.get('headline_ink_pct')}%)",
                             "fix_hint": "install the named CJK font, name one that exists, or embed it"})
        else:
            # The named font did not resolve, but the fallback still draws glyphs. That is a
            # fidelity problem for this machine, not the tofu failure this gate exists to catch.
            warnings.append({"kind": "cjk_font_not_installed",
                             "detail": f"the declared CJK font did not resolve (real and missing "
                                       f"font differ by {calib.get('fallback_delta')}px); the fallback "
                                       f"still draws glyphs (headline ink {calib.get('headline_ink_pct')}%)",
                             "fix_hint": "install the named font or name one present on the render machine"})
    if calib.get("contrast") is not None and calib["contrast"] < 4.5:
        problems.append({"kind": "low_contrast", "detail": f"{calib['contrast']}:1 on the canvas",
                         "fix_hint": "darken the ink or add a white plate behind the line"})
    if calib.get("bilingual_scale") is not None and calib["bilingual_scale"] < 2.0:
        problems.append({"kind": "type_scale_collapsed",
                         "detail": f"largest/smallest text measures {calib['bilingual_scale']}x "
                                   f"(the calibration page declares at least 2x)",
                         "fix_hint": "check for a global transform/zoom that scales text away"})

    report = {"ok": not problems, "samples": scan.get("samples"), "stride": args.stride,
              "problems": problems, "warnings": warnings,
              "ghosts_visible_from_t0": ghosts[:12],
              "visibility": {k: {"text": v["text"], "size": v["size"], "spans": v["spans"][:8]}
                             for k, v in list(scan.get("visibility", {}).items())[:60]},
              "calibration": calib}
    out = render.build_dir(spec) / "scene_check.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt.emit({"ok": report["ok"], "problems": len(problems), "warnings": len(warnings),
              "samples": report["samples"], "ghosts": len(ghosts), "report": str(out),
              "which": "scene_check"},
             human=(f"check: {len(problems)} problem(s)"
                    + (f", {len(warnings)} warning(s)" if warnings else "")
                    + f" over {report['samples']} samples"
                    + (f"; {len(ghosts)} element(s) already visible at t=0" if ghosts else "")
                    + f" -> {out.name}"))
    if not args.json:
        for p in problems[:8]:
            print("  ! " + json.dumps(p, ensure_ascii=False)[:160])
        for w in warnings[:4]:
            print("  ~ " + json.dumps(w, ensure_ascii=False)[:160])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
