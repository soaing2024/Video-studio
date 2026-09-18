#!/usr/bin/env python
"""Instantiate a renderable video project from the Motion Video Kit starter.

    python scaffold.py <out-dir> --name my-video --duration 34 [--title "..."]
                       [--width 1920 --height 1080 --fps 30] [--canvas "#FFFFFF"]
                       [--jobs 5] [--no-audio] [--force]

Writes <out-dir>/project.json and <out-dir>/scenes/take.html, then prints the next commands.
The starter carries the pipeline only; the composition is written afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

STARTER = Path(__file__).resolve().parent.parent / "assets" / "starter"


def strip_comments(text: str) -> str:
    """Drop // comments outside strings (a "//" inside a value must survive)."""
    out = []
    for line in text.splitlines():
        buf, in_str, esc, i = [], False, False, 0
        while i < len(line):
            ch = line[i]
            if in_str:
                buf.append(ch)
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
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
        out.append("".join(buf).rstrip())
    return "\n".join(l for l in out if l.strip())


def darken(hex_color: str, amount: float = 0.035) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        return hex_color
    rgb = [max(0, min(255, round(c * (1 - amount)))) for c in rgb]
    return "#%02X%02X%02X" % tuple(rgb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--name", required=True, help="slug; the output file becomes <name>.mp4")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--canvas", default="#FFFFFF")
    ap.add_argument("--jobs", type=int, default=0, help="0 = cores-3, capped at 8")
    ap.add_argument("--music", help="path to a music bed; adds the audio track block")
    ap.add_argument("--music-gain-db", type=float, default=-8.5,
                    help="bed gain; the mix should measure -45..-10 dB mean")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    if not STARTER.is_dir():
        print(f"error: starter not found at {STARTER}", file=sys.stderr)
        return 2

    out = Path(a.out_dir).expanduser().resolve()
    scene = out / "scenes" / "take.html"
    project = out / "project.json"
    if not a.force:
        for p in (scene, project):
            if p.exists():
                print(f"error: {p} exists (use --force)", file=sys.stderr)
                return 2
    (out / "scenes").mkdir(parents=True, exist_ok=True)
    (out / "assets").mkdir(parents=True, exist_ok=True)

    jobs = a.jobs or max(1, min(8, (os.cpu_count() or 4) - 3))
    subs = {
        "{{NAME}}": a.name,
        "{{TITLE}}": a.title or a.name,
        "{{DURATION}}": f"{a.duration:g}",
        "{{WIDTH}}": str(a.width),
        "{{HEIGHT}}": str(a.height),
        "{{FPS}}": str(a.fps),
        "{{JOBS}}": str(jobs),
        "{{CANVAS}}": a.canvas,
        "{{CANVAS2}}": darken(a.canvas),
    }

    def fill(text: str) -> str:
        for k, v in subs.items():
            text = text.replace(k, v)
        return text

    scene.write_text(fill((STARTER / "scene-kit.html").read_text(encoding="utf-8")), encoding="utf-8")

    raw = fill(strip_comments((STARTER / "project.template.json").read_text(encoding="utf-8")))
    spec = json.loads(raw)                      # fail loudly rather than write a broken project
    # a stable seed derived from the name: the same project renders the same every time
    spec["style"] = {"seed": int.from_bytes(a.name.encode("utf-8"), "big") % 2147483647}
    if a.music:
        spec["audio"] = {"tracks": [{"src": a.music, "gain_db": a.music_gain_db,
                                  "fade_in": 2.0, "fade_out": 3.0, "loop": True}]}
    if a.music and not (out / a.music).exists() and not Path(a.music).is_absolute():
        print(f"warning: music '{a.music}' is a relative path; it must exist inside {out}",
              file=sys.stderr)
    project.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    left = [k for k in subs if k in scene.read_text(encoding="utf-8")]
    print(json.dumps({
        "ok": True,
        "project": str(project),
        "scene": str(scene),
        "duration": a.duration,
        "jobs": jobs,
        "unfilled_placeholders": left,
        "next": [
            "write the motion spec (references/motion-prompts.md, 7 lines) before coding",
            f"python <video-studio>/scripts/vs.py preview \"{project}\" --at 2 --out <dir>/p1.png",
            f"python <video-studio>/scripts/vs.py plan \"{project}\"",
            f"python <video-studio>/scripts/vs.py run \"{project}\" --jobs {jobs}",
        ],
        "note": "the placeholder band in the scene is NOT a design; replace it before rendering",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
