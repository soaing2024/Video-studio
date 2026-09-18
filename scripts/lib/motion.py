"""Motion design compiler.

A slideshow is what you get when a shot enters and then holds still. This module decides, per
segment, everything that keeps moving for the whole shot: camera travel, parallax depth, drifting
particles, a light sweep, pulsing accents, kinetic typography, and impact events (flash, shake,
punch) placed either on musical beats or on the pacing profile.

Everything here is deterministic for a seed, so the same project renders the same motion.
"""
from __future__ import annotations

import hashlib
import math
import random

CAMERA_MOVES = ["push", "pull", "pan_left", "pan_right", "rise", "fall", "push_rotate", "drift"]
RAMP_EASES = ["linear", "inout", "out", "in"]

PACING_HIT_RATE = {          # impacts per second
    "punch": 0.85, "build": 0.5, "steady": 0.35, "wave": 0.28, "calm": 0.15,
}
PACING_SHAKE = {"punch": 4.2, "build": 2.6, "steady": 1.8, "wave": 1.4, "calm": 0.7}


def _seed_for(seed: int, index: int, salt: str) -> int:
    return int(hashlib.sha256(f"{seed}:{index}:{salt}".encode()).hexdigest()[:8], 16)


def plan(sig: dict, index: int, duration: float, *, beats: list[float] | None = None,
         energy: float = 1.0) -> dict:
    """Build the motion plan for one segment. `beats` are local seconds inside this shot."""
    seed = int(sig.get("seed", 0))
    rng = random.Random(_seed_for(seed, index, "motion"))
    pacing = sig.get("pacing", "steady")
    move = CAMERA_MOVES[index % len(CAMERA_MOVES)]
    if rng.random() < 0.25:
        move = rng.choice(CAMERA_MOVES)

    # ---- camera travel: always moving, never a still frame ----
    strength = {"punch": 1.35, "build": 1.1, "steady": 0.85, "wave": 1.0, "calm": 0.6}.get(pacing, 1.0)
    strength *= max(0.4, min(2.5, energy))
    span = max(1.0, duration)
    zoom = 0.035 + 0.05 * strength * rng.uniform(0.7, 1.3)
    shift = 14.0 * strength * rng.uniform(0.6, 1.4)
    rot = 0.5 * strength * rng.uniform(0.4, 1.5)

    camera = {
        "move": move,
        "scale_from": 1.0, "scale_to": 1.0,
        "x_from": 0.0, "x_to": 0.0, "y_from": 0.0, "y_to": 0.0,
        "rot_from": 0.0, "rot_to": 0.0,
        "ease": rng.choice(RAMP_EASES),
    }
    if move == "push":
        camera["scale_to"] = 1.0 + zoom
    elif move == "pull":
        camera["scale_from"] = 1.0 + zoom
        camera["scale_to"] = 1.0
    elif move == "pan_left":
        camera["x_from"] = shift
        camera["x_to"] = -shift
        camera["scale_to"] = 1.0 + zoom * 0.5
    elif move == "pan_right":
        camera["x_from"] = -shift
        camera["x_to"] = shift
        camera["scale_to"] = 1.0 + zoom * 0.5
    elif move == "rise":
        camera["y_from"] = shift * 0.7
        camera["y_to"] = -shift * 0.7
        camera["scale_to"] = 1.0 + zoom * 0.6
    elif move == "fall":
        camera["y_from"] = -shift * 0.7
        camera["y_to"] = shift * 0.7
        camera["scale_to"] = 1.0 + zoom * 0.6
    elif move == "push_rotate":
        camera["scale_to"] = 1.0 + zoom * 0.8
        camera["rot_from"] = -rot
        camera["rot_to"] = rot
    else:  # drift
        camera["x_from"] = -shift * 0.5
        camera["x_to"] = shift * 0.5
        camera["y_from"] = shift * 0.3
        camera["y_to"] = -shift * 0.3
        camera["scale_from"] = 1.0 + zoom * 0.4
        camera["scale_to"] = 1.0 + zoom


    # ---- impacts: on the music when we have it, otherwise from the pacing profile ----
    hits: list[float] = []
    if beats:
        hits = [round(b, 3) for b in beats if 0.15 < b < duration - 0.1]
    if not hits:
        rate = PACING_HIT_RATE.get(pacing, 0.4) * max(0.5, energy)
        t = rng.uniform(0.5, 1.1)
        while t < duration - 0.35:
            hits.append(round(t, 3))
            t += (1.0 / max(0.12, rate)) * rng.uniform(0.75, 1.25)
    hits = hits[:14]

    shake = {
        "amp": round(PACING_SHAKE.get(pacing, 1.8) * energy * rng.uniform(0.7, 1.3), 2),
        "decay": round(rng.uniform(0.18, 0.42), 3),
        "freq": round(rng.uniform(11.0, 20.0), 2),
    }

    # ---- depth ----
    # Background and subject carry the camera travel. The text plate barely moves with it, on
    # purpose: these layouts run edge to edge, so any travel at all would clip the type. Its life
    # comes from the drift above and from the beat sheet instead.
    depth = {"bg": round(rng.uniform(0.30, 0.45), 3),
             "mid": round(rng.uniform(0.55, 0.68), 3),
             "fg": round(rng.uniform(0.06, 0.13), 3)}

    # ---- ambient motion ----
    particles = {
        # A sparse shot has little ink, so whatever motion it has has to be legible: more, bigger
        # and brighter specks than a dense layout needs.
        "count": int(rng.uniform(34, 76) * max(0.5, energy)),
        "speed": round(rng.uniform(26, 92) * strength, 2),
        "size": round(rng.uniform(1.8, 4.6), 2),
        "opacity": round(rng.uniform(0.26, 0.62), 3),
        "vertical": round(rng.uniform(-26, 26), 2),
        "mode": rng.choice(["dust", "streak", "dots"]),
    }
    sweep = {
        "period": round(rng.uniform(3.2, 6.5), 2),
        "angle": round(rng.uniform(-24, 24), 1),
        "width": int(rng.uniform(140, 320)),
        "speed": round(rng.uniform(260, 620), 1),
        "opacity": round(rng.uniform(0.06, 0.18), 3),
    }
    pulse = {"freq": round(rng.uniform(0.6, 1.8), 2), "amount": round(rng.uniform(0.008, 0.03), 4)}
    ghost = {"text": None, "speed": round(rng.uniform(14, 42), 1),
             "scale": round(rng.uniform(3.2, 6.0), 2),
             "opacity": round(rng.uniform(0.03, 0.09), 3),
             "dir": rng.choice([1, -1])}

    # ---- kinetic typography ----
    text_motion = {
        "mode": rng.choice(["words", "words", "lines"]),
        "per_word": round(rng.uniform(0.05, 0.12) / max(0.6, strength), 3),
        "pop": round(rng.uniform(1.03, 1.12), 3),
        "swap_at": round(min(duration * 0.55, rng.uniform(2.2, 4.0)), 2),
        "drift": round(rng.uniform(0.6, 2.4), 2),
    }

    return {
        "camera": camera, "shake": shake, "hits": hits, "depth": depth,
        "particles": particles, "sweep": sweep, "pulse": pulse, "ghost": ghost,
        "text_motion": text_motion,
        "energy": round(energy, 3),
    }


def hits_from_beats(spec: dict, starts: dict[str, float]) -> dict[str, list[float]]:
    """Convert absolute musical beats into per-segment local hit times."""
    beats = spec.get("beats")
    if not beats:
        return {}
    times = beats.get("times") if isinstance(beats, dict) else beats
    if not times:
        return {}
    out: dict[str, list[float]] = {}
    seg_by_id = {s["id"]: s for s in spec.get("segments", [])}
    for item in spec.get("timeline", []):
        sid = item.get("segment")
        if not sid or sid not in seg_by_id:
            continue
        start = starts.get(sid, 0.0)
        dur = float(seg_by_id[sid]["duration"])
        local = [round(t - start, 3) for t in times if start < t < start + dur]
        if local:
            out[sid] = local
    return out


def inject(spec: dict, log=print) -> dict:
    """Attach a motion plan to every segment, with impacts aligned to the music when present."""
    sig = (spec.get("style") or {}).get("signature") or {}
    if not sig or (spec.get("look") or {}).get("motion") == "off":
        return {"applied": False}
    segments = spec.get("segments") or []
    if not segments:
        return {"applied": False}
    starts = specmod_segment_starts(spec)
    local_beats = hits_from_beats(spec, starts)
    total_hits = 0
    total_cuts = 0
    for i, seg in enumerate(segments):
        data = seg.setdefault("data", {})
        plan_data = plan(sig, i, float(seg["duration"]),
                         beats=local_beats.get(seg["id"]), energy=energy_of(spec, seg))
        # The beat sheet is compiled before this module runs (see vs.load_spec), so the camera is
        # keyed to the same events the actors are: one timeline, not two that drift apart.
        sheet = (data.get("choreography") or {}).get("beats") or []
        strength = max(0.45, min(1.9, PACING_CAMERA.get(sig.get("pacing", "steady"), 1.0) *
                          max(0.4, min(2.5, energy_of(spec, seg)))))
        cam_rng = random.Random(_seed_for(int(sig.get("seed", 0)), i, "camera"))
        plan_data["camera_keys"], plan_data["cuts"] = camera_keys(
            float(seg["duration"]),
            [b["t"] for b in sheet if b.get("kind") not in ("establish", "exit")],
            [b["t"] for b in sheet if b.get("kind") == "restage"],
            strength, cam_rng)
        plan_data.pop("camera_track", None)
        plan_data["drift"] = {
            # Big enough that a settled frame is still changing by a visible number of pixels every
            # sixth of a second: a smaller wander measures as a frozen frame even though it exists.
            "x": round(12.0 + 13.0 * strength, 2),
            "y": round(8.0 + 10.0 * strength, 2),
            "rot": round(0.10 + 0.22 * strength, 4),
            "scale": round(0.0020 + 0.0034 * strength, 5),
        }
        ghost = data.get("ghost" ) or data.get("title") or data.get("eyebrow")
        if ghost and len(str(ghost)) <= 24:
            plan_data["ghost"]["text"] = str(ghost)
        data["motion"] = plan_data
        total_hits += len(plan_data["hits"])
        total_cuts += len(plan_data["cuts"])
    return {"applied": True, "segments": len(segments), "hits": total_hits,
            "music_synced": bool(local_beats), "pacing": sig.get("pacing")}

    return {"applied": True, "segments": len(segments), "hits": total_hits,
            "reframes": total_cuts, "music_synced": bool(local_beats),
            "pacing": sig.get("pacing")}


def specmod_segment_starts(spec: dict) -> dict:
    from . import spec as specmod
    return specmod.segment_starts(spec)


def energy_of(spec: dict, seg: dict) -> float:
    """How energetic this shot should be: pacing, act, and whether it carries a hit."""
    base = {"punch": 1.3, "build": 1.1, "steady": 0.9, "wave": 1.0, "calm": 0.65}.get(
        (spec.get("style") or {}).get("signature", {}).get("pacing", "steady"), 1.0)
    data = seg.get("data") or {}
    if (data.get("visual") or {}).get("breath"):
        base *= 0.55
    if data.get("still"):
        base *= 0.35
    if (data.get("visual") or {}).get("energy"):
        base *= float(data["visual"]["energy"])
    return round(base, 3)


# ---------------------------------------------------------------------------------------------
# Camera travel.
#
# The old waypoint list eased between beats and so restarted from zero velocity at every one of
# them, and it travelled 14-20px over two seconds - about 10px/s, which the eye reads as a still
# image however smoothly it is interpolated. Two changes fix that: travel is measured in
# hundreds of pixels and whole percent of scale, and the poses go to Anim.Path, which runs one
# continuous spline through all of them.
#
# A `restage` beat becomes a hard reframe: a new composition inside the same shot. That is what
# stops a long segment from being one page held too long, which no amount of extra motion on the
# old composition can fix.
# ---------------------------------------------------------------------------------------------

# (dx, dy, dscale, drot) across one piece of the track, in 1280x720 units.
CAM_PIECES = {
    "push":        (0.0, 0.0, 0.085, 0.0),
    "pull":        (0.0, 0.0, -0.065, 0.0),
    "pan_left":    (-124.0, 0.0, 0.022, 0.0),
    "pan_right":   (124.0, 0.0, 0.022, 0.0),
    "rise":        (0.0, -82.0, 0.030, 0.0),
    "fall":        (0.0, 82.0, 0.030, 0.0),
    "push_rotate": (0.0, 0.0, 0.060, 1.5),
    "drift":       (66.0, -44.0, 0.040, 0.0),
}
MOVE_SEQ = ["push", "pan_left", "pull", "pan_right", "rise", "push_rotate", "fall", "drift"]
# Bounded by what the layouts can survive, not by taste: the foreground layer is the deepest one,
# and a text column spanning 200..1080 cannot take 200px of travel plus a 1.4x scale without its
# own edge leaving the frame. 120px at the deepest layer is still an order of magnitude more
# movement than the version this replaced, and the layout audit holds the line.
CAM_LIMITS = {"x": 100.0, "y": 70.0, "scale": (0.95, 1.16), "rot": 2.0}
CAM_GRID = 0.4          # seconds between camera keys when reproducing the sweep
PACING_CAMERA = {"punch": 1.45, "build": 1.20, "steady": 0.95, "wave": 1.05, "calm": 0.70}


def _fold(v: float, lo: float, hi: float) -> float:
    """Keep a value inside a range without ever letting it stop moving.

    Clipping looks equivalent but is not: a camera parked against its limit emits identical frames
    for as long as the piece lasts, which is exactly the still image this module exists to avoid.
    Folding reflects the run-out instead, so the travel stays continuous and only its direction
    changes.
    """
    if hi <= lo:
        return lo
    span = hi - lo
    x = (v - lo) % (2 * span)
    return lo + (x if x <= span else 2 * span - x)


def _pick_signed(centre: float, reach: float, rng: random.Random) -> float:
    """A new value for one axis, chosen to move away from where it was.

    A reframe that sometimes lands back on a similar framing is not a reframe, so the sign follows
    whichever way the axis is already leaning.
    """
    if centre > reach * 0.15:
        sign = -1
    elif centre < -reach * 0.15:
        sign = 1
    else:
        sign = rng.choice([-1, 1])
    return sign * reach * rng.uniform(0.75, 1.35)
def camera_keys(duration: float, waypoints: list[float] | None, restages: list[float] | None,
                strength: float, rng: random.Random) -> tuple[list[dict], list[float]]:
    """A spline through the camera poses, with a hard reframe at every restage.

    Returns (keys, cuts). Keys are absolute shot times; a key flagged `cut` starts a new piece, so
    the sample jumps there - the reframe. The camera opens already travelling, because a shot that
    begins from a standstill reads as a still even if it moves a moment later.
    """
    duration = max(0.6, float(duration))
    cuts = sorted({round(float(r), 3) for r in (restages or [])
                   if 0.5 < float(r) < duration - 0.45})

    # The sweep: always moving, never leaving the envelope. Amplitude and the per-page offset
    # divide the same budget, so a big reframe automatically means a smaller surrounding sweep.
    ease = min(1.25, max(0.6, strength))
    amp = {"x": CAM_LIMITS["x"] * 0.60 * ease,
           "y": CAM_LIMITS["y"] * 0.60 * ease,
           "scale": 0.036 * min(1.4, strength),
           "rot": CAM_LIMITS["rot"] * 0.60 * ease}
    half_scale = (CAM_LIMITS["scale"][1] - CAM_LIMITS["scale"][0]) / 2.0
    margin = {"x": max(0.0, CAM_LIMITS["x"] - amp["x"]),
              "y": max(0.0, CAM_LIMITS["y"] - amp["y"]),
              "scale": max(0.0, half_scale - amp["scale"])}
    # A full sweep every three to five seconds: slow enough to read as a camera, fast enough that a
    # sixth of a second of it is a visible number of pixels.
    freq = 0.16 + 0.075 * min(1.6, strength)
    phase = {k: rng.uniform(0.0, 6.283) for k in ("x", "y", "scale", "rot")}

    # One framing per page, each chosen to differ from the one before it.
    bounds = [0.0] + list(cuts) + [duration]
    pages = []
    for i in range(len(bounds) - 1):
        if i == 0:
            pages.append((rng.uniform(-1, 1) * margin["x"] * 0.9,
                          rng.uniform(-1, 1) * margin["y"] * 0.9,
                          rng.uniform(-1, 1) * margin["scale"] * 0.9,
                          rng.uniform(-1, 1) * 0.6))
            continue
        px, py, ps, pr = pages[-1]
        pages.append((px + _pick_signed(px, margin["x"], rng),
                      py + _pick_signed(py, margin["y"], rng),
                      ps + _pick_signed(ps, margin["scale"], rng),
                      pr + _pick_signed(pr, 0.6, rng)))

    def pose_at(t: float) -> dict:
        page = 0
        for i, b in enumerate(bounds[:-1]):
            if t >= b:
                page = i
        cx, cy, cs, cr = pages[page]
        return {
            "x": cx + amp["x"] * math.sin(2 * math.pi * freq * t + phase["x"]),
            "y": cy + amp["y"] * math.sin(2 * math.pi * freq * 0.77 * t + phase["y"]),
            "scale": (1.0 + cs + amp["scale"] *
                      math.sin(2 * math.pi * freq * 0.63 * t + phase["scale"])),
            "rot": cr + amp["rot"] * math.sin(2 * math.pi * freq * 0.51 * t + phase["rot"]),
        }

    times = {round(min(duration, i * CAM_GRID), 3)
             for i in range(int(duration / CAM_GRID) + 2)}
    for c in cuts:
        # The pair is the cut: the outgoing framing, then the incoming one a millisecond later.
        # Without the exact instant the jump would be smeared across the next grid step.
        times.add(round(max(0.0, c - 0.001), 4))
        times.add(round(c, 3))
    times.add(round(duration, 3))

    keys = []
    for t in sorted(times):
        pose = pose_at(t)
        entry = {"t": t, "x": round(pose["x"], 2), "y": round(pose["y"], 2),
                 "scale": round(pose["scale"], 4), "rot": round(pose["rot"], 3)}
        if any(abs(t - c) < 1e-6 for c in cuts):
            entry["cut"] = True
        keys.append(entry)
    return keys, cuts
