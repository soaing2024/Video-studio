"""Frame-level continuity: the defect class every other gate in this skill is blind to.

Every other measurement here is an average. `motion` is change per second at 6 fps, `content`
is five sampled frames, `design_audit` is per-beat ink mass. A film can score 24.7/255 on the
motion gate (threshold 2.2) and still be unwatchable, because what the eye catches is not the
average - it is the single frame that does not belong:

  * an exposure/opacity step with a 1-2 frame attack ("瞬时压暗" done literally),
  * a global displacement that reverses every 1-3 frames: an oscillator whose carrier is too
    fast for the delivery frame rate (61 rad/s = 9.7 Hz = 3.09 frames per cycle at 30 fps, so
    consecutive frames land on opposite extremes and a "shake" reads as a jump),
  * a dropped or repeated frame,
  * a hand-off that happens in one frame behind a mask that looks smooth.

The audit decodes at the DELIVERY frame rate, isolates frames that moved far more than both
neighbours, and classifies each by measuring the real global displacement in a small window
around it: a shake shows a large shift with a small residual, an exposure step shows neither,
and shifts that alternate in sign name the aliasing failure.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import fmt

ANALYSIS_W, ANALYSIS_H = 192, 108        # pass 1: full rate, tiny
WINDOW_W, WINDOW_H = 640, 360            # pass 2: only around flagged frames
SEARCH = 6                               # alignment search, in window pixels


def _decode(video: str, ffmpeg: str, fps: float, w: int, h: int,
            start: float | None = None, frames: int | None = None):
    """Raw grey frames; a window decode uses an accurate input seek."""
    cmd = [ffmpeg, "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.3f}"]
    cmd += ["-i", video, "-vf", f"fps={fps},scale={w}:{h}"]
    if frames is not None:
        cmd += ["-frames:v", str(frames)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise fmt.VsError(code="DECODE_FAILED", where=Path(video).name,
                          expected="ffmpeg decodes the video to raw grey frames",
                          got=(proc.stderr or b"").decode("utf-8", "replace")[-200:],
                          fix_hint="check the file plays: ffmpeg -i <video>")
    import numpy as np
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    return buf[:n * w * h].reshape(n, h, w).astype(np.int16)


def per_frame_change(video: str, ffmpeg: str, fps: float):
    """Mean |delta| between consecutive frames, in 0-255 grey levels, at delivery fps."""
    import numpy as np
    f = _decode(video, ffmpeg, fps, ANALYSIS_W, ANALYSIS_H)
    if len(f) < 3:
        raise fmt.VsError(code="TOO_SHORT", where=Path(video).name,
                          expected="at least 3 frames at the delivery fps",
                          got=f"{len(f)} frame(s)",
                          fix_hint="run the audit on the assembled take, not on a still")
    return np.abs(f[1:] - f[:-1]).reshape(len(f) - 1, -1).mean(axis=1)


def isolate_steps(d, floor: float = 12.0, ratio: float = 2.5):
    """Frames that moved far more than BOTH neighbours: the signature of a one-frame step.

    A cut is not isolated - it changes the picture and the change persists - so this selects
    pops, not edits. Requiring both neighbours to be quiet is what keeps a legitimately fast
    passage out of the list.
    """
    events = []
    for i in range(1, len(d) - 1):
        nb = max(float(d[i - 1]), float(d[i + 1]))
        if d[i] >= floor and d[i] > ratio * max(nb, 1e-6):
            events.append({"frame": i + 1, "t": (i + 1) / 30.0,
                           "change": round(float(d[i]), 2),
                           "prev": round(float(d[i - 1]), 2),
                           "next": round(float(d[i + 1]), 2),
                           "ratio": round(float(d[i] / max(nb, 1e-6)), 2)})
    return events


def _align(a, b):
    """Integer global shift (dx, dy) minimising |a - b|, plus the residual and the raw diff."""
    h, w = a.shape
    best = (0, 0, 1e9)
    raw = float(abs(a - b).mean())
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            ya0, ya1 = max(0, dy), h + min(0, dy)
            yb0, yb1 = max(0, -dy), h + min(0, -dy)
            xa0, xa1 = max(0, dx), w + min(0, dx)
            xb0, xb1 = max(0, -dx), w + min(0, -dx)
            d = float(abs(a[ya0:ya1, xa0:xa1] - b[yb0:yb1, xb0:xb1]).mean())
            if d < best[2]:
                best = (dx, dy, d)
    return best[0], best[1], best[2], raw


def classify(video: str, ffmpeg: str, fps: float, event: dict, tall: int):
    """Name the mechanism behind one step: exposure / jitter / drift / content swap."""
    import numpy as np
    t = event["t"]
    start = max(0.0, t - 5.0 / fps)
    n = min(tall, 10)
    win = _decode(video, ffmpeg, fps, WINDOW_W, WINDOW_H, start=start, frames=n)
    if len(win) < 3:
        return event
    sx, sy = WINDOW_W / 2560.0, WINDOW_H / 1440.0      # window px -> 1440p px
    shifts, resids, raws = [], [], []
    for i in range(len(win) - 1):
        dx, dy, res, raw = _align(win[i], win[i + 1])
        shifts.append((dx / sx, dy / sy))
        resids.append(res)
        raws.append(raw)
    step = np.abs(win[1:].astype(np.int32) - win[:-1].astype(np.int32))
    k = int(np.argmax(step.reshape(len(win) - 1, -1).mean(axis=1)))
    k = min(k, len(shifts) - 1)
    dx, dy = shifts[k]
    raw, res = raws[k], resids[k]
    explained = 1.0 - (res / max(raw, 1e-6))
    peak = max(abs(dx), abs(dy))
    flips = sum(1 for i in range(1, len(shifts))
                if shifts[i][0] * shifts[i - 1][0] < 0 or shifts[i][1] * shifts[i - 1][1] < 0)
    if peak < 3.0 and explained < 0.15:
        kind = "exposure_step"
        why = ("no global displacement and no alignment gain: the picture jumped in brightness "
               "or opacity, not in position")
        fix = ("give the exposure change an attack of >= 0.12 s (>= 4 frames) and ease it, or move "
               "the discontinuity into a seam: a 1-2 frame attack on a 0.4+ amplitude is a visible "
               "single-frame step, however good the still frame looks")
    elif explained >= 0.35 and flips >= 2 and peak >= 4.0:
        kind = "jitter_aliased"
        why = (f"global displacement up to {peak:.1f}px that reverses direction between consecutive "
               f"frames ({flips} sign flips in {len(shifts)} steps)")
        fix = (f"the oscillator's carrier is too fast for {fps:g} fps: keep >= 5 frames per cycle "
               f"(<= {fps/5:.1f} Hz = {2*3.14159265*fps/5:.0f} rad/s). Lower the frequency, or drive "
               f"the shake from smoothed noise instead of a sine")
    elif explained >= 0.35:
        kind = "drift_ramp"
        why = f"a consistent {peak:.1f}px displacement that ramps instead of alternating"
        fix = "check for an accumulating offset: a camera term that never returns to zero"
    else:
        kind = "content_swap"
        why = f"content changed with at most {explained*100:.0f}% of it explained by a global shift"
        fix = ("if the step is meant to be one continuous take, the hand-off is happening in one "
               "frame - grow the incoming element out of the outgoing one over >= 0.4 s")
    event.update(kind=kind, why=why, fix_hint=fix, shift_px=[round(dx, 1), round(dy, 1)],
                 alignment_gain=round(explained, 3), sign_flips=flips)
    return event


def audit(video: str, ffmpeg: str, fps: float = 30.0, max_step: float = 25.0,
          floor: float = 12.0, windows: int = 12) -> dict:
    """The measurement behind `vs.py continuity` and verify's `continuity` check."""
    import numpy as np
    d = per_frame_change(video, ffmpeg, fps)
    events = isolate_steps(d, floor=floor)
    events.sort(key=lambda e: -e["change"])
    for e in events[:windows]:
        try:
            classify(video, ffmpeg, fps, e, len(d))
        except fmt.VsError:
            raise
        except Exception as exc:                      # a failed classification is not a verdict
            e.update(kind="unclassified", why=str(exc)[:120], fix_hint="")
    worst = events[0] if events else None
    kinds: dict[str, int] = {}
    for e in events:
        k = e.get("kind", "unclassified")
        kinds[k] = kinds.get(k, 0) + 1
    detail = (f"{len(events)} isolated single-frame step(s) at {fps:g} fps; median change "
              f"{float(np.median(d)):.2f}/255, p99 {float(np.percentile(d, 99)):.2f}"
              + (f"; worst {worst['change']:.1f}/255 at t={worst['t']:.2f}s "
                 f"({worst.get('kind')}: {worst.get('why', '')[:90]})" if worst else
                 " - no frame stands out from its neighbours"))
    return {"ok": worst is None or worst["change"] <= max_step,
            "video": str(video), "fps": fps, "frames": len(d) + 1,
            "median_change": round(float(np.median(d)), 3),
            "p99_change": round(float(np.percentile(d, 99)), 3),
            "max_change": round(float(d.max()), 3), "max_allowed_step": max_step,
            "events": events[:max(windows, 24)], "event_count": len(events),
            "kinds": kinds, "detail": detail}
