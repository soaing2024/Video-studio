#!/usr/bin/env python
"""Measure a rendered video (or a project's stills) without being able to see it.

    # frames from a finished file, with named regions:
    python qc_video.py out/video.mp4 --times 1.5,8,19.6,33 \
        --regions "matrix=900,280,1460,840;caption=130,845,1300,915;rail=700,340,850,780"

    # from a project directory (finds <dir>/<name>.mp4 via its project.json):
    python qc_video.py --project <dir> --times 2,6,20 --keep <dir>/qc

    # print an ASCII map of one frame (this is how an agent "looks" at a frame):
    python qc_video.py out/video.mp4 --times 33 --map 33

Exit code is non-zero when a sampled frame is blank (no ink / black), which is the failure mode
that a render can hide behind a clean-looking JSON summary.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BLANK_INK = 200


def ffmpeg_path() -> str:
    """The skill's runtime resolver, with a PATH fallback for standalone use.

    Hardcoding the win-x86_64 filename silently fell back to PATH on any other build, which is
    where the Playwright ffmpeg (VP8/PNG only) lives.
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


def parse_regions(raw: str | None) -> dict[str, tuple[int, int, int, int]]:
    out: dict[str, tuple[int, int, int, int]] = {}
    if not raw:
        return out
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        try:
            name, box = part.split("=", 1)
            x0, y0, x1, y1 = (int(v) for v in box.split(","))
        except ValueError:
            raise SystemExit(f"error: bad region '{part}' (want name=x0,y0,x1,y1)")
        out[name.strip()] = (x0, y0, x1, y1)
    return out


def grab(ffmpeg: str, video: Path, t: float, out: Path) -> Path:
    if out.exists():
        out.unlink()
    subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)
    if not out.is_file():
        raise SystemExit(f"error: could not extract a frame at {t}s")
    return out


def ascii_map(arr, x0: int, x1: int, y0: int, y1: int, bx: int, by: int) -> list[str]:
    lines = []
    for j in range(y0, min(y1, arr.shape[0]), by):
        row = ""
        for i in range(x0, min(x1, arr.shape[1]), bx):
            mn = int(arr[j:j + by, i:i + bx].min())
            row += "#" if mn < 80 else ("+" if mn < 150 else ("." if mn < 232 else " "))
        lines.append(f"{j:5d} {row}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", help="an mp4 (or use --project)")
    ap.add_argument("--project", help="project directory containing project.json")
    ap.add_argument("--times", required=True, help="comma-separated seconds, or N samples like 6x")
    ap.add_argument("--regions", help="name=x0,y0,x1,y1;name=...")
    ap.add_argument("--map", help="seconds to print an ASCII map for")
    ap.add_argument("--keep", help="directory to keep extracted PNGs in")
    a = ap.parse_args()

    import numpy as np
    from PIL import Image

    if a.project:
        base = Path(a.project).expanduser().resolve()
        spec = json.loads((base / "project.json").read_text(encoding="utf-8"))
        video = base / f"{spec.get('name', 'video')}.mp4"
    elif a.video:
        video = Path(a.video).expanduser().resolve()
    else:
        raise SystemExit("error: pass a video path or --project <dir>")
    if not video.is_file():
        raise SystemExit(f"error: video not found: {video}")

    if a.times.endswith("x") and a.times[:-1].isdigit():
        # even sampling across the file, useful as a first look
        n = max(1, int(a.times[:-1]))
        probe = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(video)],
                               capture_output=True, text=True)
        dur = 20.0
        if "Duration:" in probe.stderr:
            hms = probe.stderr.split("Duration:")[1].strip().split(",")[0].strip().split(":")
            try:
                dur = int(hms[0]) * 3600 + int(hms[1]) * 60 + float(hms[2])
            except (ValueError, IndexError):
                pass
        times = [dur * (i + 0.5) / n for i in range(n)]
    else:
        times = [float(x) for x in a.times.replace(" ", "").split(",") if x]

    regions = parse_regions(a.regions)
    maps = {round(float(x), 3) for x in a.map.replace(" ", "").split(",")} if a.map else set()
    for m in sorted(maps):                      # a map time is sampled even if --times omits it
        if not any(abs(m - t) < 1e-6 for t in times):
            times.append(m)
    times = sorted(times)

    ffmpeg = ffmpeg_path()
    tmp = Path(a.keep).expanduser().resolve() if a.keep else Path(tempfile.mkdtemp(prefix="mvk-qc-"))
    tmp.mkdir(parents=True, exist_ok=True)

    blank, rows = [], []
    for t in times:
        png = grab(ffmpeg, video, t, tmp / f"f{t:07.2f}.png")
        arr = np.asarray(Image.open(png).convert("L"), dtype=np.int16)
        ink = int((arr < 150).sum())
        reg = {k: int((arr[y0:y1, x0:x1] < 150).sum()) for k, (x0, y0, x1, y1) in regions.items()}
        rows.append((t, round(float(arr.mean()), 1), ink, reg))
        if ink < BLANK_INK:
            blank.append(t)
        if any(abs(t - m) < 1e-6 for m in maps):
            print(f"--- map @ {t:.2f}s (each char = 16x16 px, '#'<80, '+'<150, '.'<232) ---")
            for line in ascii_map(arr, 0, arr.shape[1], 0, arr.shape[0], 16, 16):
                print(line)

    width = max((len(k) for k in regions), default=4)
    print(f"video: {video}")
    print(f"{'t(s)':>8} {'luma':>6} {'ink':>7}  " + "  ".join(f"{k:>{width}}" for k in regions))
    for t, luma, ink, reg in rows:
        cells = "  ".join(f"{reg[k]:>{width}}" for k in regions)
        print(f"{t:8.2f} {luma:6.1f} {ink:7d}  {cells}")

    if blank:
        print(f"\nFAIL: {len(blank)} sampled frame(s) look blank (ink < {BLANK_INK}): "
              f"{', '.join(f'{t:.2f}s' for t in blank)}")
        print("      a clean render with missing content is the failure this check exists for")
        return 1

    dead = [k for k in regions if rows and max(r[3][k] for r in rows) == 0]
    if dead:
        print(f"\nWARN: region(s) never carry ink: {', '.join(dead)}")
    print("\nok: every sampled frame carries content")
    if not a.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"frames kept in {tmp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
