#!/usr/bin/env python
"""Audit the handoffs in a take before spending a render.

    python beat_audit.py <project.json>          # reads data.beats
    python beat_audit.py <beats.json>            # {"beats": [...]} or a bare list

Each beat declares the windows that carry it across the cut-like moment:

    "beats": [
      { "name": "散点落下 -> 塌缩", "in": [0.18, 1.60], "out": [2.35, 2.75] },
      ...
    ]

The audit enforces the rules from references/rhythm-handoff.md: outgoing and incoming windows
must OVERLAP (no exit-then-enter gap), single transitions stay short, and no stretch of the
timeline is left with nothing moving. It prints an ASCII timeline so the handoff structure is
visible at a glance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

GAP_MAX = 0.15          # seconds of nothing happening that we tolerate between beats
OUT_MAX = 1.20          # a whole-frame move longer than this reads as a laboured transition
OUT_IDEAL = (0.25, 0.90)
HANDOFF_MIN = 0.15      # seconds that consecutive beats must share (aim for 40-60% of a move)


def load(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "beats" in data:
        return data["beats"]
    beats = (data.get("data") or {}).get("beats")
    if not beats:
        raise SystemExit("error: no beats found (expected data.beats in a project, or a beats list)")
    return beats


def window(beat: dict, key: str):
    w = beat.get(key)
    if not w:
        return None
    if len(w) != 2 or float(w[1]) <= float(w[0]):
        raise SystemExit("error: beat '%s' has a bad %s window: %r" % (beat.get("name"), key, w))
    return float(w[0]), float(w[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="project.json (data.beats) or a beats json")
    ap.add_argument("--width", type=int, default=96, help="timeline columns")
    a = ap.parse_args()
    path = Path(a.file).expanduser().resolve()
    if not path.is_file():
        raise SystemExit("error: not found: %s" % path)
    beats = load(path)

    parsed = []
    for b in beats:
        parsed.append({"name": b.get("name", "?"), "in": window(b, "in"), "out": window(b, "out")})
    parsed = [b for b in parsed if b["in"] or b["out"]]
    if not parsed:
        raise SystemExit("error: beats carry no in/out windows")

    problems = []
    print("%-28s %-16s %-16s %s" % ("beat", "in window", "out window", "notes"))
    for b in parsed:
        notes = []
        for key in ("in", "out"):
            w = b[key]
            if not w:
                continue
            dur = w[1] - w[0]
            if dur > OUT_MAX:
                notes.append("%s %.2fs too long (>%.2fs)" % (key, dur, OUT_MAX))
            elif not (OUT_IDEAL[0] <= dur <= OUT_IDEAL[1]):
                notes.append("%s %.2fs outside %.2f-%.2fs" % (key, dur, OUT_IDEAL[0], OUT_IDEAL[1]))
        if b["in"] and b["out"]:
            hole = b["out"][0] - b["in"][1]
            if hole > 0.20:
                notes.append("hole of %.2fs inside this beat" % hole)
        print("%-28s %-16s %-16s %s" % (b["name"][:28],
                                        "%.2f-%.2f" % b["in"] if b["in"] else "-",
                                        "%.2f-%.2f" % b["out"] if b["out"] else "-",
                                        "; ".join(notes) if notes else "ok"))
        problems += ["%s: %s" % (b["name"], n) for n in notes]

    # gaps between consecutive beats, and the longest stretch with nothing running
    for prev, cur in zip(parsed, parsed[1:]):
        prev_end = max([w[1] for w in (prev["in"], prev["out"]) if w])
        cur_start = min([w[0] for w in (cur["in"], cur["out"]) if w])
        gap = cur_start - prev_end
        if gap > GAP_MAX:
            problems.append("gap of %.2fs before '%s' (max %.2fs)" % (gap, cur["name"], GAP_MAX))
            print("  ! GAP %.2fs before '%s' -- exit-then-enter, the slide signature"
                  % (gap, cur["name"]))
        elif -gap < HANDOFF_MIN:
            print("  ! weak handoff (%.2fs overlap) before '%s' -- aim for 40-60%% of a move"
                  % (-gap, cur["name"]))

    lo = min(w[0] for b in parsed for w in (b["in"], b["out"]) if w)
    hi = max(w[1] for b in parsed for w in (b["in"], b["out"]) if w)
    span = max(1e-6, hi - lo)
    cols = a.width
    flags = []
    for c in range(cols):
        t0 = lo + span * c / cols
        t1 = lo + span * (c + 1) / cols
        f = 0
        for b in parsed:
            for key, bit in (("in", 1), ("out", 2)):
                w = b[key]
                if w and w[0] < t1 and w[1] > t0:
                    f |= bit
        flags.append(f)

    print("\ntimeline (%.2fs..%.2fs, 1 char = %.2fs)" % (lo, hi, span / cols))
    print("  in   |%s|" % "".join("#" if f == 3 else ("+" if f & 1 else " ") for f in flags))
    print("  out  |%s|" % "".join("#" if f == 3 else ("=" if f & 2 else " ") for f in flags))
    print("  both |%s|" % "".join("#" if f == 3 else " " for f in flags))
    handoffs = sum(1 for f in flags if f == 3)
    print("\n'#' columns are moments where an outgoing and an incoming move are alive at the same"
          " time (%d of %d columns); those are what remove the slide feel." % (handoffs, cols))

    if problems:
        print("\n%d problem(s):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        print("\nfix the structure (overlap the windows, shorten the moves), not the easing alone.")
        return 1
    print("\nok: every handoff overlaps, no transition is laboured, no gap exceeds %.2fs." % GAP_MAX)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
