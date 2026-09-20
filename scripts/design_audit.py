#!/usr/bin/env python
"""Design audit: the check that catches a film whose every gate is green and still reads badly.

    python design_audit.py out/video.mp4 --project work/mine/project.json --ascii
    python design_audit.py draft.mp4 --times 4,8,12,16            # a beat skeleton, before the render

`verify` proves there is a picture and that it moves. `taste_check --rhythm` proves the picture
keeps changing. Neither can see the three failures that make a technically clean film boring:

  1. every beat wears the same composition      -> cross-beat similarity of the ink layout
  2. nothing in the film is dark                -> a white film with no dark mass has no weight
  3. the picture never stops                     -> no pause long enough to read a still frame

Run it on a `rehearse` draft of three rival beat skeletons BEFORE committing: that is the cheap
moment to find out that all three are the same picture. Thresholds and the reasoning behind them
are in references/motion-design.md.

POLARITY. "Ink" is the drawn material and "dark" is the mass at the far pole from the canvas.
Which side that is depends on the film: on a white canvas a mark is darker, on a black canvas it
is brighter. The polarity is read off the film itself (`--polarity light|dark` overrides it) and
every threshold below is applied on the correct side. Judging a dark film by the light rules makes
every beat 100% ink and identical to every other beat, so a film whose beats are all different gets
reported as one layout worn N times. A false failure is worse than a missed one: it sends you off
to fix a picture that is not broken.

SAMPLING. `--project` reads `data.timeline`, which is the skill's convention but not a requirement
- SKILL.md is explicit that `data` has no imposed vocabulary. When that key is absent the audit
used to sample nothing and then report a verdict anyway ("heaviest 0.00% ink"), which reads as a
failure of the film. It now falls back to even samples and says so.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from taste_check import ffmpeg_path, label_components

INK = 245               # light canvas: anything below this counts as drawn material
DARK = 110              # light canvas: "a dark mass", not a hairline
BRIGHT = 255 - DARK     # dark canvas: the same mass at the other pole
INK_MARGIN = 255 - INK  # dark canvas: how far off the canvas a pixel must be to count
POLARITY_SPLIT = 127    # canvas luma at or above this reads as a light film
FPS = 30.0
W, H = 192, 108         # analysis size: the scale an eye reads, not the delivery size
TW, TH = 8, 5           # ink-layout tiles used to compare one beat against another

SIM_REPEAT = 0.88       # median cross-beat layout similarity at or above this is one layout worn N times
MASS_SPREAD = 2.5       # ... unless the ink mass also varies at least this much between beats
DENSE_MASS = 12.0       # frame share that counts as a dense, full-bleed beat
DARK_MASS = 3.0         # frame share that counts as a genuinely dark beat
PAUSE_MIN = 2           # readable pauses a film of 20 s or more needs (>= 0.3 s each)
MOVE_PIX = 12           # a pixel counts as moved when it changes by this many grey levels
MOVE_FRAC = 0.002       # ...and a frame is still when under 0.2% of its pixels move
PAUSE_FRAMES = 9        # 9 frames @30fps = 0.30 s
FLAT_ADVISE = 1.70      # p90/mean a fast piece wants; 1.25 is one flat line and fails
FLAT_FAIL = 1.25
RAMP = " .:-=+*#%@"


def decode(video: Path, ff: str):
    import numpy as np
    proc = subprocess.run([ff, "-v", "error", "-i", str(video), "-vf",
                           "fps=%d,scale=%d:%d" % (int(FPS), W, H), "-f", "rawvideo",
                           "-pix_fmt", "gray", "-"], capture_output=True)
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (W * H)
    if n < 3:
        raise SystemExit("error: could not decode enough frames")
    return buf[:n * W * H].reshape(n, H, W).astype(np.int16)


def tiles(frame, polarity="light", canvas=0.0):
    import numpy as np
    small = frame[:H // TH * TH, :W // TW * TW].reshape(TH, H // TH, TW, W // TW).mean(axis=(1, 3))
    if polarity == "dark":
        top = max(1.0, 255.0 - float(canvas) - INK_MARGIN)
        return np.clip((small - float(canvas) - INK_MARGIN) / top, 0, 1).reshape(-1)
    return np.clip((INK - small) / INK, 0, 1).reshape(-1)


def detect_polarity(fr):
    """Which way is the drawn material? Read the canvas level off the film instead of assuming it.

    The canvas is the level the picture mostly sits at, so it is the median of per-frame medians
    (one bright act must not flip the reading). It is global on purpose: the beat layouts are
    compared against each other, so they all have to be measured against the same canvas.
    """
    import numpy as np
    step = max(1, fr.shape[0] // 32)
    canvas = float(np.median([float(np.median(f)) for f in fr[::step]]))
    return ("light" if canvas >= POLARITY_SPLIT else "dark"), canvas


def measure(frame, polarity="light", canvas=0.0):
    import numpy as np
    if polarity == "dark":
        mask = frame > (float(canvas) + INK_MARGIN)
        pole = frame > BRIGHT
    else:
        mask = frame < INK
        pole = frame < DARK
    cov = float(mask.mean())
    ys, xs = np.nonzero(mask)
    centroid = (float(np.hypot(xs.mean() / W - 0.5, ys.mean() / H - 0.5) * 2) if len(xs) else 0.0)
    return {
        "margin": round((1 - cov) * 100, 1),
        "ink": round(cov * 100, 2),
        "blobs": label_components(mask),
        "off": round(centroid, 2),
        "dark": round(float(pole.mean()) * 100, 2),
        "extreme": int(frame.min()) if polarity == "light" else int(frame.max()),
        "vec": tiles(frame, polarity, canvas),
    }


def cosine(a, b):
    import numpy as np
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def ascii_map(frame, cols=64, rows=18, polarity="light"):
    import numpy as np
    small = frame[:rows * (H // rows), :cols * (W // cols)].reshape(rows, H // rows, cols, W // cols)
    small = small.mean(axis=(1, 3))
    lo, hi = float(small.min()), float(small.max())
    span = max(1.0, hi - lo)
    out = []
    for r in range(rows):
        row = ""
        for c in range(cols):
            idx = int((1 - (small[r, c] - lo) / span) * (len(RAMP) - 1))
            # "@" always means "the most drawn", whichever pole the drawing lives at
            row += RAMP[len(RAMP) - 1 - idx if polarity == "dark" else idx]
        out.append(row)
    return out


def still_share(fr):
    """Share of pixels that actually changed between adjacent frames.

    The mean grey delta is the wrong instrument here. A film drawn in hairlines on white moves
    a great deal in the way it reads and almost nothing in the average pixel, so a mean-based
    test calls a moving pointer "still" and a blank field "held". Counting changed pixels is
    scale-free: 0.2% of 192x108 is about what a 2 px pointer covers, and about what a window
    edge covers as it slides."""
    import numpy as np
    return (np.abs(fr[1:] - fr[:-1]) > MOVE_PIX).mean(axis=(1, 2))


def pauses(moved):
    """Runs of >= PAUSE_FRAMES in which almost nothing on screen moved."""
    runs, cur, start = [], 0, 0
    for i, v in enumerate(moved):
        if v < MOVE_FRAC:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur >= PAUSE_FRAMES:
                runs.append((start / FPS, cur / FPS))
            cur = 0
    if cur >= PAUSE_FRAMES:
        runs.append((start / FPS, cur / FPS))
    return runs


def dur_of(video: Path, ff: str) -> float:
    probe = subprocess.run([ff, "-hide_banner", "-i", str(video)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if "Duration:" in probe.stderr:
        hms = probe.stderr.split("Duration:")[1].strip().split(",")[0].strip().split(":")
        try:
            return int(hms[0]) * 3600 + int(hms[1]) * 60 + float(hms[2])
        except (ValueError, IndexError):
            pass
    return 10.0


def beats_from(project: Path) -> list:
    # project specs allow // comments, so parse them the way the pipeline does
    text = project.read_text(encoding="utf-8")
    try:
        from lib.spec import _strip_comments
        text = _strip_comments(text)
    except Exception:
        pass
    doc = json.loads(text)
    tl = ((doc.get("data") or {}).get("timeline")) or []
    out = []
    for c in tl:
        at = float(c.get("at") or 0)
        sec = float(c.get("seconds") or 0)
        out.append((at + sec * 0.55, str(c.get("on_screen") or c.get("intent") or "")[:22]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--project", help="project.json: sample one frame per declared beat")
    ap.add_argument("--times", help="comma-separated seconds to sample instead")
    ap.add_argument("--samples", type=int, default=8, help="even samples when neither is given")
    ap.add_argument("--ascii", action="store_true", help="print the ink layout of every sampled beat")
    ap.add_argument("--polarity", choices=("auto", "light", "dark"), default="auto",
                    help="which side the drawn material sits on; auto reads it off the film")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    import numpy as np
    video = Path(a.video).expanduser().resolve()
    if not video.is_file():
        raise SystemExit("error: video not found: %s" % video)
    ff = ffmpeg_path()
    fr = decode(video, ff)
    n = fr.shape[0]
    dur = dur_of(video, ff)
    polarity, canvas = detect_polarity(fr)
    if a.polarity != "auto":
        polarity = a.polarity

    note = ""
    even = [(dur * (i + 0.5) / a.samples, "") for i in range(a.samples)]
    if a.times:
        samples = [(float(x), "") for x in a.times.replace(" ", "").split(",") if x]
        if not samples:
            samples, note = even, "--times listed no usable seconds; sampled evenly instead"
    elif a.project:
        samples = beats_from(Path(a.project).expanduser().resolve())
        if len(samples) < 4:
            # A project may legally keep its timeline under any key, so beats_from can come back
            # empty. Auditing zero frames and then printing a verdict is how this used to fail: it
            # reported "heaviest 0.00% ink" and blamed the film. Sample anyway, and say which
            # sampling was actually used.
            declared = len(samples)
            samples = even
            note = (f"--project declared {declared} beat(s) under data.timeline; audited "
                    f"{a.samples} even samples instead - pass --times to place the beats")
    else:
        samples = even

    shots = []
    for t, label in samples:
        i = min(n - 1, max(0, int(round(t * FPS))))
        m = measure(fr[i], polarity, canvas)
        m["t"] = round(t, 2)
        m["label"] = label
        shots.append(m)

    # --- rhythm: the same one-second read taste_check uses, plus the peakiness of its profile
    lag = int(FPS)
    d = np.abs(fr[lag:] - fr[:-lag]).mean(axis=(1, 2))
    micro = np.abs(fr[1:] - fr[:-1]).mean(axis=(1, 2))
    per_sec = float(d.mean()) if len(d) else 0.0
    p90 = float(np.percentile(d, 90)) if len(d) else 0.0
    undulation = p90 / per_sec if per_sec > 1e-6 else 0.0
    # a pause only counts if there is something on screen to read while it is held: an empty
    # white field is not a pause, it is an absence
    pause_runs = []
    for t0, span in pauses(still_share(fr)):
        mid = min(n - 1, int((t0 + span * 0.5) * FPS))
        if float(fr[mid].std()) >= 3.0:
            pause_runs.append((t0, span))

    # --- cross-beat layout similarity and mass spread
    sims = [cosine(shots[i]["vec"], shots[j]["vec"])
            for i in range(len(shots)) for j in range(i + 1, len(shots))]
    sim_med = float(np.median(sims)) if sims else 0.0
    masses = [s["ink"] for s in shots if s["ink"] > 0.02]
    spread = (max(masses) / min(masses)) if len(masses) > 1 else 1.0
    ink_max = max((s["ink"] for s in shots), default=0.0)
    dark_max = max((s["dark"] for s in shots), default=0.0)

    problems = []
    if len(shots) >= 4 and sim_med >= SIM_REPEAT and spread < MASS_SPREAD:
        problems.append("layout_repeat: %d beats at %.2f median layout similarity with only %.1fx"
                        " ink-mass spread -- one composition worn %d times"
                        % (len(shots), sim_med, spread, len(shots)))
    if ink_max < DENSE_MASS and dark_max < DARK_MASS:
        problems.append("no_weight_variety: heaviest beat %.2f%% ink, %.2f%% at the far pole --"
                        " every beat sits in the same band, so the film has one weight"
                        % (ink_max, dark_max))
    if dur >= 20 and len(pause_runs) < PAUSE_MIN:
        problems.append("no_pause: %d readable pause(s) in %.0fs -- with nothing held, every frame"
                        " reads as transit" % (len(pause_runs), dur))
    if undulation < FLAT_FAIL:
        problems.append("flat_rhythm: p90/mean %.2f -- one flat line" % undulation)

    if a.json:
        print(json.dumps({"ok": not problems, "polarity": polarity,
                          "canvas_luma": round(canvas, 1), "sampling_note": note,
                          "beats": [{k: v for k, v in s.items() if k != "vec"} for s in shots],
                          "median_layout_similarity": round(sim_med, 3),
                          "ink_mass_spread": round(spread, 2),
                          "ink_max": round(ink_max, 2), "dark_mass_max": round(dark_max, 2),
                          "pauses": [[round(t, 2), round(sp, 2)] for t, sp in pause_runs],
                          "change_per_second": round(per_sec, 2), "p90_over_mean": round(undulation, 2),
                          "problems": problems}, ensure_ascii=False))
        return 1 if problems else 0

    print("video: %s   %.2fs" % (video.name, dur))
    print("canvas %s (level %.0f): drawn material is %s, the mass at the far pole is %s" %
          (polarity, canvas, "brighter" if polarity == "dark" else "darker",
           "the brightest" if polarity == "dark" else "the darkest"))
    if note:
        print("note: " + note)
    print("\n%7s %7s %7s %6s %6s %6s %8s  %s" %
          ("t(s)", "margin", "ink%", "blobs", "off", "pole%", "extreme", "beat"))
    for s in shots:
        print("%7.2f %6.1f%% %6.2f%% %6d %6.2f %6.2f%% %8d  %s" %
              (s["t"], s["margin"], s["ink"], s["blobs"], s["off"], s["dark"], s["extreme"], s["label"]))
    if a.ascii:
        for s in shots:
            i = min(n - 1, max(0, int(round(s["t"] * FPS))))
            print("\n--- t=%.2fs  %s" % (s["t"], s["label"]))
            for line in ascii_map(fr[i], polarity=polarity):
                print("   |" + line + "|")

    print("\nlayout similarity between beats : median %.2f  (>= %.2f with no mass variety = one layout)"
          % (sim_med, SIM_REPEAT))
    print("ink-mass spread across beats    : %.1fx     (>= %.1fx means the film changes weight)"
          % (spread, MASS_SPREAD))
    print("weight across beats             : heaviest %.2f%% ink (drawn), %.2f%% at the far pole"
          % (ink_max, dark_max))
    print("                                  (one beat needs >= %.0f%% ink or >= %.1f%% pole mass)"
          % (DENSE_MASS, DARK_MASS))
    print("readable pauses                 : %d        (>= %d in a piece over 20 s)"
          % (len(pause_runs), PAUSE_MIN))
    for t, s in pause_runs:
        print("    pause at %5.2fs for %.2fs" % (t, s))
    print("change per second               : %.2f" % per_sec)
    print("p90 / mean                      : %.2f      (< %.2f is a flat line; a fast piece wants >= %.2f)"
          % (undulation, FLAT_FAIL, FLAT_ADVISE))
    if problems:
        print("\n%d design problem(s):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        print("\nFix the structure (references/motion-design.md), not the easing.")
        return 1
    print("\nok: the beats differ from each other, the film has weight and pauses, and the rhythm has peaks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
