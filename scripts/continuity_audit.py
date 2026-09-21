"""Frame-level continuity audit - the accounting for a guarantee made elsewhere.

    python scripts/continuity_audit.py out/film.mp4 [--fps 30] [--json] [--strict]

The guarantee lives in the runtime (`assets/runtime/motion.js`): every drawn parameter retargets
from its CURRENT value over at least 4 frames, oscillators are snapped to a whole number of
frames per cycle, impacts get a >= 4 frame attack, and appearance ramps have a floor. A single-
frame step is therefore not expressible through those primitives.

This command is the accounting, not the gate. Every other measurement in this skill is an
average - `motion` is change per second at 6 fps, `content` is five sampled frames - and a film
can score 24.7/255 on the motion gate (threshold 2.2) while still being unwatchable, because
what the eye catches is the one frame that does not belong. So: decode at the DELIVERY rate,
find frames that moved far more than both neighbours, and classify each by measuring the real
global displacement around it (`exposure_step`, `jitter_aliased`, `drift_ramp`, `content_swap`).
A nonzero count means something bypassed the runtime.

Reported, not fatal by default: it exits 0 and prints. `--strict` turns the reference threshold
into an exit code for a pipeline that wants one.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import continuity, fmt, runtime                     # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="frame-level continuity audit of a finished video",
        epilog="example: python scripts/continuity_audit.py out/film.mp4 --json")
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=30.0, help="delivery frame rate to sample at")
    ap.add_argument("--max-step", type=float, default=25.0,
                    help="reference ceiling for an isolated single-frame change, 0-255 grey")
    ap.add_argument("--floor", type=float, default=12.0,
                    help="ignore steps softer than this (reporting threshold)")
    ap.add_argument("--windows", type=int, default=12,
                    help="how many events to classify by measuring displacement")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when a step is above --max-step (off by default: the "
                         "guarantee against steps is the runtime; this command is the accounting)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    fmt.configure(json=args.json, verbose=args.verbose, quiet=args.quiet)

    try:
        report = continuity.audit(args.video, runtime.find_ffmpeg(), fps=args.fps,
                                  max_step=args.max_step, floor=args.floor, windows=args.windows)
    except fmt.VsError as e:
        return fmt.report_error(e)

    human = (f"continuity: {report['event_count']} isolated step(s), worst "
             f"{report['events'][0]['change']:.1f}/255 at t={report['events'][0]['t']:.2f}s "
             f"({report['events'][0].get('kind', '?')})"
             if report["events"] else
             f"continuity: no isolated step over {args.floor:.0f}/255 in {report['frames']} frames")
    fmt.emit({**report, "which": "continuity"}, human=human)
    if not args.json and report["events"]:
        for e in report["events"][:8]:
            print(f"  t={e['t']:7.2f}s frame={e['frame']:5d} {e['change']:6.1f}/255 "
                  f"(neighbours {e['prev']:.1f} / {e['next']:.1f}, {e['ratio']:.1f}x)"
                  f"  {e.get('kind', '?')}")
            if e.get("shift_px"):
                print(f"      shift {e['shift_px'][0]:+.1f}/{e['shift_px'][1]:+.1f}px, "
                      f"alignment gain {e['alignment_gain']}, sign flips {e['sign_flips']}")
            if e.get("why"):
                print(f"      {e['why']}")
            if e.get("fix_hint"):
                print(f"      fix: {e['fix_hint']}")
    if not report["ok"] and not args.strict:
        print(f"  reported, not fatal: the worst step is above the {args.max_step:.0f}/255 "
              f"reference. Pass --strict to make it one, and route the value through "
              f"Motion.channel()/Motion.hit() instead of a hand-rolled envelope.")
    return 1 if (args.strict and not report["ok"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
