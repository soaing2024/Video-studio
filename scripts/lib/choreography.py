"""Choreography compiler: what actually happens inside a shot.

The failure this fixes is architectural. A shot built as "elements enter, then hold, then cut" has
exactly one state change, so most of its runtime is a still frame with nice typography - a slide.
Here every shot gets a beat sheet: a sequence of state changes spread across its full duration, each
one moving the material that is already on screen rather than fading something new in. The compiler
also reports the longest gap between changes, so "this shot sits still for 4 seconds" is caught at
planning time, before anything renders.
"""
from __future__ import annotations

import hashlib
import random

from . import spec as specmod

# Motion vocabulary. Each kind is a different way for the frame to change.
KINDS = ["build", "transform", "swap", "emphasis", "parallax_drift", "reveal", "count", "shuffle"]

BEAT_PERIOD = {"punch": 1.7, "build": 2.0, "steady": 2.6, "wave": 2.3, "calm": 3.4}
ENERGY_SCALE = {"punch": 1.45, "build": 1.15, "steady": 0.9, "wave": 1.0, "calm": 0.6}

# A change every this many seconds keeps a shot alive; beyond it the eye reads a still.
MAX_GAP_TARGET = 2.4


def _rng(sig: dict, index: int) -> random.Random:
    seed = f"{sig.get('seed', 0)}:{index}:choreo"
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))


def plan(sig: dict, index: int, duration: float, *, beats: list[float] | None = None,
         energy: float = 1.0, has_alt: bool = False, has_counter: bool = False) -> dict:
    rng = _rng(sig, index)
    pacing = sig.get("pacing", "steady")
    period = BEAT_PERIOD.get(pacing, 2.4) / max(0.5, energy)
    period = max(1.1, min(4.0, period))

    # Beat times: spread across the whole shot, always including a cold open and an exit beat.
    times = []
    t = rng.uniform(0.35, 0.7)
    while t < duration - 0.55:
        times.append(round(t, 3))
        t += period * rng.uniform(0.78, 1.24)

    # Musical accents, when there is music, take priority for the emphatic beats.
    if beats:
        merged = sorted({round(b, 3) for b in beats if 0.3 < b < duration - 0.4} | set(times))
        times = merged

    beats_out = [{"t": 0.0, "kind": "establish", "intensity": 1.0}]
    pool = list(KINDS)
    rng.shuffle(pool)
    for i, when in enumerate(times):
        kind = pool[i % len(pool)]
        if has_alt and kind == "swap":
            pass
        elif kind == "swap" and not has_alt:
            kind = "emphasis"
        if kind == "count" and not has_counter:
            kind = "transform"
        near_beat = bool(beats) and any(abs(when - b) < 0.12 for b in beats)
        intensity = round(min(1.6, (0.75 + 0.45 * rng.random()) * (1.25 if near_beat else 1.0)), 3)
        beats_out.append({"t": when, "kind": kind, "intensity": intensity,
                          "on_beat": near_beat})

    exit_at = round(max(0.3, duration - 0.42), 3)
    if exit_at > beats_out[-1]["t"] + 0.15:
        beats_out.append({"t": exit_at, "kind": "exit", "intensity": 0.8})

    swap = None
    if has_alt:
        swap_at = next((b["t"] for b in beats_out if b["kind"] == "swap"), None)
        if swap_at is None:
            swap_at = round(min(duration * 0.55, max(1.8, duration * 0.5)), 2)
            beats_out.append({"t": swap_at, "kind": "swap", "intensity": 1.0})
            beats_out.sort(key=lambda b: b["t"])
        swap = {"at": swap_at}

    gaps = [round(beats_out[i + 1]["t"] - beats_out[i]["t"], 3)
            for i in range(len(beats_out) - 1)]
    return {
        "beats": beats_out,
        "swap": swap,
        "states": len(beats_out),
        "max_gap": max(gaps) if gaps else duration,
        "gaps": gaps,
        "period": round(period, 2),
        "pattern": [b["kind"] for b in beats_out],
    }


def inject(spec: dict, log=print) -> dict:
    """Attach a beat sheet to every segment and report the stillness profile."""
    segments = spec.get("segments") or []
    if not segments:
        return {"applied": False}
    sig = (spec.get("style") or {}).get("signature") or {}
    starts = specmod.segment_starts(spec)
    times = []
    beats_cfg = spec.get("beats") or {}
    if isinstance(beats_cfg, dict):
        times = beats_cfg.get("times") or []
    elif isinstance(beats_cfg, list):
        times = beats_cfg

    rows = []
    worst = 0.0
    total_states = 0
    for i, seg in enumerate(segments):
        data = seg.setdefault("data", {})
        local_beats = []
        if times:
            start = starts.get(seg["id"], 0.0)
            local_beats = [t - start for t in times if start < t < start + float(seg["duration"])]
        motion_energy = ((data.get("motion") or {}).get("energy"))
        energy = float(motion_energy) if motion_energy else ENERGY_SCALE.get(sig.get("pacing", "steady"), 1.0)
        if data.get("still"):
            energy *= 0.5
        choreo = plan(sig, i, float(seg["duration"]), beats=local_beats, energy=energy,
                      has_alt=bool(data.get("titleAlt") or data.get("quoteAlt")

                                    or data.get("captionVariants")),
                      has_counter=bool(data.get("counter")))
        data["choreography"] = choreo
        total_states += choreo["states"]
        worst = max(worst, choreo["max_gap"])
        rows.append({"id": seg["id"], "seconds": seg["duration"], "states": choreo["states"],
                     "max_gap": choreo["max_gap"], "pattern": choreo["pattern"]})

    return {"applied": True, "segments": rows, "total_states": total_states,
            "worst_gap": round(worst, 3),
            "verdict": "alive" if worst <= MAX_GAP_TARGET else "too_still"}


def report(spec: dict) -> dict:
    rows = [{"id": s["id"], "seconds": s["duration"],
             "states": (s.get("data", {}).get("choreography") or {}).get("states"),
             "max_gap": (s.get("data", {}).get("choreography") or {}).get("max_gap")}
            for s in spec.get("segments", [])]
    rows = [r for r in rows if r["states"]]
    if not rows:
        return {}
    worst = max(r["max_gap"] for r in rows)
    return {
        "segments": rows,
        "total_state_changes": sum(r["states"] for r in rows),
        "worst_gap": round(worst, 3),
        "verdict": "alive" if worst <= MAX_GAP_TARGET else "too_still",
    }
