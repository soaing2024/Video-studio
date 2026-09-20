#!/usr/bin/env python
"""Two aesthetic checks that can be measured instead of argued about.

    # rhythm: is this edit nimble, or does it read like slides?
    python taste_check.py out/video.mp4 --rhythm [--window 0.5]

    # composition: what is the still frame doing?
    python taste_check.py out/video.mp4 --stills --samples 5
    python taste_check.py out/video.mp4 --stills --times 2,6,20

Thresholds come from references/rhythm-handoff.md (rhythm) and references/taste.md
(composition). Output is ASCII on purpose: a Windows console in a CJK locale mangles
UTF-8 stdout, and a measurement nobody can read is not a measurement.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FROZEN_DELTA = 1.0      # 0-255 grey levels between adjacent frames
INK = 245               # anything below this counts as ink


def ffmpeg_path() -> str:
    """The skill's runtime resolver, with a PATH fallback for standalone use.

    This used to hardcode `vendor/ffmpeg-win-x86_64-v7.1.exe`, so any other build name or
    platform silently fell back to PATH - which is exactly where the Playwright ffmpeg (VP8 and
    PNG only) lives, the trap runtime.py exists to avoid.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib import runtime
        return runtime.find_ffmpeg()
    except Exception:
        found = shutil.which("ffmpeg")
        if not found:
            raise SystemExit("error: no ffmpeg found (checked the skill vendor folder and PATH)")
        return found


def tag_low(value: float, good: float, ok: float, unit: str = "") -> str:
    """Lower is better."""
    t = "nimble" if value <= good else ("ok" if value <= ok else "SLIDES-ISH")
    return "%6.2f%s  %-11s" % (value, unit, t)


def tag_high(value: float, good: float, ok: float) -> str:
    """Higher is better."""
    t = "nimble" if value >= good else ("ok" if value >= ok else "FLAT")
    return "%6.2f   %-11s" % (value, t)


def rhythm(video: Path, window: float, ffmpeg: str) -> int:
    import numpy as np
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(video),
                           "-vf", "fps=30,scale=192:108", "-f", "rawvideo",
                           "-pix_fmt", "gray", "-"], capture_output=True)
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    frame_px = 192 * 108
    n = buf.size // frame_px
    if n < 3:
        raise SystemExit("error: could not decode enough frames")
    fr = buf[:n * frame_px].reshape(n, 108, 192).astype(np.int16)
    fps = 30.0
    lag = int(fps)                                     # one second: the scale an eye reads
    micro = np.abs(fr[1:] - fr[:-1]).mean(axis=(1, 2))          # per-frame change @30fps
    d = np.abs(fr[lag:] - fr[:-lag]).mean(axis=(1, 2))          # change across one second

    # share of frames that are near-identical: ~50% reads as alive, ~13% reads as floaty,
    # and a much higher share is the slides signature (see choreography.md, timeline law 11)
    frozen = float((micro < 0.10).mean())
    cur = best = 0
    start = best_at = 0
    for i, v in enumerate(d):
        if v < FROZEN_DELTA:                           # nothing changes across a whole second
            if cur == 0:
                start = i
            cur += 1
            if cur > best:
                best, best_at = cur, start / fps
        else:
            cur = 0
    dead = best / fps

    step = max(1, int(round(window * fps)))
    series = [float(d[i:i + step].mean()) for i in range(0, len(d) - step + 1, step)]
    per_sec = float(sum(series) / len(series)) if series else 0.0
    peak = float(sorted(series)[int(len(series) * 0.9)]) if series else 0.0
    undulation = peak / per_sec if per_sec > 1e-6 else 0.0

    print("video: %s" % video)
    print("decoded %d frames @%dfps, window %gs\n" % (n, int(fps), window))
    print("%-16s%-26s%s" % ("metric", "value", "reference"))
    print("%-16s%-26s%s" % ("static frames", tag_low(frozen * 100, 65, 70, "%"),
                            "35-65% alive, >70% slides, <35% floaty"))
    print("%-16s%-26s%s" % ("longest dead run", tag_low(dead, 0.5, 0.8, "s"),
                            "<=0.5s nimble, >0.8s slides"))
    print("%-16s%-26s%s" % ("change per second", tag_high(per_sec, 3.0, 2.2),
                            ">=3.0 nimble, must clear 2.2 to pass verify"))
    print("%-16s%-26s%s" % ("p90 / mean", tag_high(undulation, 1.5, 1.25),
                            ">=1.5 has swells, <1.25 is one flat line"))
    if dead > 0.5:
        print("\nlongest dead run starts near %.2fs -- look for an exit-then-enter gap there" % best_at)

    print("\nrhythm chart (picture change per %gs; longer bar = more happening)" % window)
    top = max(series) if series else 1.0
    for i, v in enumerate(series):
        bar = int(round(v / top * 48)) if top > 0 else 0
        flag = "  <- almost nothing here" if v < 1.0 else ""
        print("%6.1fs |%s%s| %4.2f%s" % (i * window, "#" * bar, " " * (48 - bar), v, flag))
    empty = sum(1 for v in series if v < 1.0)
    if empty:
        print("\n%d window(s) of %gs are nearly empty; bars should swell and fall with no blank run."
              % (empty, window))
    return 0


def label_components(mask, gw=48, gh=27):
    """Count ink blobs on a coarse grid (flood fill; enough for a layout sanity check)."""
    import numpy as np
    h, w = mask.shape
    small = mask[:(h // gh) * gh, :(w // gw) * gw].reshape(gh, h // gh, gw, w // gw).mean(axis=(1, 3)) > 0.02
    seen = np.zeros_like(small, dtype=bool)
    n = 0
    for y0 in range(gh):
        for x0 in range(gw):
            if not small[y0, x0] or seen[y0, x0]:
                continue
            n += 1
            stack = [(y0, x0)]
            seen[y0, x0] = True
            while stack:
                y, x = stack.pop()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < gh and 0 <= nx < gw and small[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
    return n


def stills(video: Path, times: list, ffmpeg: str) -> int:
    import numpy as np
    from PIL import Image
    tmp = Path(tempfile.mkdtemp(prefix="mvk-taste-"))
    print("video: %s\n" % video)
    print("%7s %8s %9s %6s %5s %6s %7s  %s" %
          ("t(s)", "margin", "centroid", "symm", "blobs", "colors", "darkest", "notes"))
    try:
        for t in times:
            png = tmp / ("f%07.2f.png" % t)
            subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", "%.3f" % t, "-i", str(video),
                            "-frames:v", "1", str(png)], check=True)
            im = Image.open(png).convert("RGB")
            a = np.asarray(im, dtype=np.int16)
            g = np.asarray(im.convert("L"), dtype=np.int16)
            h, w = g.shape
            mask = g < INK
            ys, xs = np.nonzero(mask)
            if len(xs) == 0:
                print("%7.2f %8s %9s %6s %5s %6s %7s  blank frame" % (t, "-", "-", "-", "-", "-", "-"))
                continue
            cov = float(mask.mean())
            cx, cy = xs.mean() / w, ys.mean() / h
            off = float(np.hypot(cx - 0.5, cy - 0.5) * 2)
            sym = float((mask & mask[:, ::-1]).sum() / max(1, (mask | mask[:, ::-1]).sum()))
            nblob = label_components(mask)
            colors = len({tuple(int(v) >> 3 for v in a[y, x]) for y, x in zip(ys[::7], xs[::7])})
            dark = int(g[mask].min())
            notes = []
            if sym > 0.85 and off < 0.02 and nblob <= 3:
                notes.append("centred-default layout")
            # a raw shade count on an encoded frame is noise, so it is reported but not judged;
            # the palette is judged from the scene (references/taste.md)
            if dark > 120:
                notes.append("too washed out to read")
            strong = g < 150                   # a faint ambient field is not content
            strong[-14:, :] = False            # the assembler's progress bar is an overlay
            strong[:4, :] = False
            if (strong[:int(h * 0.05)].any() or strong[int(h * 0.92):].any()
                    or strong[:, :int(w * 0.04)].any() or strong[:, int(w * 0.96):].any()):
                notes.append("marks outside safe area")
            if cov > 0.55:
                notes.append("very dense")
            print("%7.2f %8.1f%% %9.2f %6.2f %5d %6d %7d  %s" %
                  (t, (1 - cov) * 100, off, sym, nblob, colors, dark,
                   "; ".join(notes) if notes else "no default-layout tells"))
        print("\nmargin = non-ink share; centroid = visual mass offset from centre (0 = dead centre);")
        print("symm = horizontal mirror Jaccard of the ink; blobs = connected ink groups on a coarse grid.")
        print("shades = raw unique quantised colours, for reference only (noise on an encoded frame).")
        print("A centred-default hit means change the structure, not the parameters.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--rhythm", action="store_true", help="temporal check: slides or nimble")
    ap.add_argument("--stills", action="store_true", help="composition check on still frames")
    ap.add_argument("--times", help="comma-separated seconds (with --stills)")
    ap.add_argument("--samples", type=int, default=5, help="even samples when --times is absent")
    ap.add_argument("--window", type=float, default=0.5, help="rhythm chart window, seconds")
    a = ap.parse_args()
    video = Path(a.video).expanduser().resolve()
    if not video.is_file():
        raise SystemExit("error: video not found: %s" % video)
    if not (a.rhythm or a.stills):
        a.rhythm = a.stills = True
    ff = ffmpeg_path()
    if a.rhythm:
        rhythm(video, a.window, ff)
        if a.stills:
            print()
    if a.stills:
        if a.times:
            times = [float(x) for x in a.times.replace(" ", "").split(",") if x]
        else:
            probe = subprocess.run([ff, "-hide_banner", "-i", str(video)], capture_output=True, text=True)
            dur = 10.0
            if "Duration:" in probe.stderr:
                hms = probe.stderr.split("Duration:")[1].strip().split(",")[0].strip().split(":")
                try:
                    dur = int(hms[0]) * 3600 + int(hms[1]) * 60 + float(hms[2])
                except (ValueError, IndexError):
                    pass
            times = [dur * (i + 0.5) / a.samples for i in range(a.samples)]
        stills(video, times, ff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
