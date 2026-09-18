"""Motion design compiler.

A slideshow is what you get when a shot enters and then holds still. This module decides, per
segment, everything that keeps moving for the whole shot: camera travel, parallax depth, drifting
particles, a light sweep, pulsing accents, kinetic typography, and impact events (flash, shake,
punch) placed either on musical beats or on the pacing profile.

Everything here is deterministic for a seed, so the same project renders the same motion.
"""
from __future__ import annotations

import hashlib
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

    # ---- camera track: waypoints tied to the beat sheet, so the frame never coasts ----
    beat_times = [b for b in (beats or []) if 0.2 < b < duration - 0.2]
    waypoints = [0.0] + beat_times + [duration]
    if len(waypoints) < 3:
        step = max(1.2, duration / max(2, int(duration / 2.2)) or 2.2)
        waypoints = [i * step for i in range(int(duration / step) + 1)] + [duration]
        waypoints = sorted(set(round(w, 3) for w in waypoints if w < duration)) + [duration]
    move_seq = ["push", "pan_left", "pull", "pan_right", "rise", "push_rotate", "fall", "drift"]
    rng2 = random.Random(_seed_for(seed, index, "camera"))
    start = rng2.randrange(len(move_seq))
    track = []
    scale, x, y, rot = 1.0, 0.0, 0.0, 0.0
    for i in range(len(waypoints) - 1):
        t0, t1 = waypoints[i], waypoints[i + 1]
        kind = move_seq[(start + i) % len(move_seq)]
        amp = strength * rng2.uniform(0.85, 1.25)
        d_scale = x2 = y2 = rot2 = 0.0
        if kind == "push":
            d_scale = 0.045 * amp
        elif kind == "pull":
            d_scale = -0.035 * amp
        elif kind == "pan_left":
            x2 = -22 * amp
        elif kind == "pan_right":
            x2 = 22 * amp
        elif kind == "rise":
            y2 = -18 * amp
        elif kind == "fall":
            y2 = 18 * amp
        elif kind == "push_rotate":
            d_scale = 0.035 * amp
            rot2 = 1.1 * amp
        else:
            x2 = 14 * amp
            y2 = -10 * amp
        scale = max(0.95, min(1.22, scale + d_scale))
        x = max(-70.0, min(70.0, x + x2))
        y = max(-48.0, min(48.0, y + y2))
        rot = max(-2.5, min(2.5, rot + rot2))
        track.append({"t": round(t0, 3), "dur": round(max(0.45, t1 - t0), 3),
                      "scale": round(scale, 4), "x": round(x, 2), "y": round(y, 2),
                      "rot": round(rot, 3), "ease": rng2.choice(["inout", "out", "linear"]),
                      "arc": round(rng2.uniform(6, 26), 1), "kind": kind})

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
    depth = {"bg": round(rng.uniform(0.18, 0.4), 3),
             "mid": round(rng.uniform(0.6, 0.85), 3),
             "fg": round(rng.uniform(1.05, 1.35), 3)}

    # ---- ambient motion ----
    particles = {
        "count": int(rng.uniform(18, 44) * max(0.5, energy)),
        "speed": round(rng.uniform(10, 46) * strength, 2),
        "size": round(rng.uniform(1.2, 3.4), 2),
        "opacity": round(rng.uniform(0.14, 0.5), 3),
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
        "camera_track": track,
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
    for i, seg in enumerate(segments):
        data = seg.setdefault("data", {})
        plan_data = plan(sig, i, float(seg["duration"]),
                         beats=local_beats.get(seg["id"]), energy=energy_of(spec, seg))
        ghost = data.get("ghost" ) or data.get("title") or data.get("eyebrow")
        if ghost and len(str(ghost)) <= 24:
            plan_data["ghost"]["text"] = str(ghost)
        data["motion"] = plan_data
        total_hits += len(plan_data["hits"])
    return {"applied": True, "segments": len(segments), "hits": total_hits,
            "music_synced": bool(local_beats), "pacing": sig.get("pacing")}


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
