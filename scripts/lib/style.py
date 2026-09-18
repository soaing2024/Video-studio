"""Seeded style engine.

The problem this solves: a template with fixed choreography makes every video look the same.
Here a seed becomes a concrete visual direction - palette, type scale, composition, motion
family, texture, transitions, pacing - and each segment gets its own resolved variant, with
adjacency guaranteed to differ. Same seed reproduces exactly; a new seed is a new look.
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import math
import random
from pathlib import Path

# ---------------------------------------------------------------- colour helpers


def _hsl(h: float, s: float, l: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return round(r * 255), round(g * 255), round(b * 255)


def hexc(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, c))) for c in rgb)


def _luminance(rgb) -> float:
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg, bg, target=7.0, dark_bg=True):
    """Push foreground lightness until the pair clears `target` contrast."""
    # rgb_to_hls returns (hue, lightness, saturation) - unpacking it as (h, s, l) swaps two of the
    # three and turns body text into a saturated mid-tone instead of near-white.
    h, l, s = colorsys.rgb_to_hls(*[c / 255.0 for c in fg])
    for _ in range(60):
        if contrast(_hsl(h * 360, s, l), bg) >= target:
            break
        l = min(1.0, l + 0.02) if dark_bg else max(0.0, l - 0.02)
    return _hsl(h * 360, s, l)


# ---------------------------------------------------------------- vocabularies

PALETTES = [
    {"name": "midnight", "hue": 222, "sat": 0.55, "mood": "冷静、专业"},
    {"name": "ember", "hue": 14, "sat": 0.62, "mood": "热烈、紧张"},
    {"name": "forest", "hue": 152, "sat": 0.48, "mood": "自然、可信"},
    {"name": "violet", "hue": 268, "sat": 0.52, "mood": "未来、神秘"},
    {"name": "sand", "hue": 36, "sat": 0.45, "mood": "温和、人文"},
    {"name": "ice", "hue": 192, "sat": 0.50, "mood": "清晰、科技"},
]

HARMONIES = {
    "analogous": [0, 24, -24, 48],
    "complementary": [0, 180, 20, 200],
    "triadic": [0, 120, 240, 60],
    "split": [0, 150, 210, 30],
}

LAYOUTS = {
    "kinetic": ["editorial", "split", "center", "corner", "fullbleed", "banner"],
    "caption": ["panel-right", "panel-left", "full-bleed", "stacked", "framed"],
    "pixel": ["classic", "compact", "wide"],
    "chart": ["left-axis", "full-width"],
    "stat": ["center", "offset"],
    "quote": ["left-bar", "centered"],
    "terminal": ["window", "frameless"],
}

MOTIONS = {
    "rise": {"from": {"y": 42, "opacity": 0}, "ease": "cubic", "scale": 0},
    "scale": {"from": {"scale": 0.9, "opacity": 0}, "ease": "back", "scale": 1},
    "wipe": {"from": {"clip": 100, "opacity": 1}, "ease": "quint", "scale": 0},
    "blur": {"from": {"blur": 14, "opacity": 0}, "ease": "expo", "scale": 0},
    "slide": {"from": {"x": -64, "opacity": 0}, "ease": "quint", "scale": 0},
    "zoom": {"from": {"scale": 1.06, "opacity": 0}, "ease": "expo", "scale": 1},
}

TEXTURES = ["none", "grain", "dots", "scanlines", "grid"]
PACING = {
    "steady": {"speed": 1.0, "breath_every": 0, "cut_bias": 0.5},
    "build": {"speed": 1.05, "breath_every": 4, "cut_bias": 0.55},
    "punch": {"speed": 1.25, "breath_every": 3, "cut_bias": 0.75},
    "wave": {"speed": 0.95, "breath_every": 5, "cut_bias": 0.35},
    "calm": {"speed": 0.85, "breath_every": 2, "cut_bias": 0.15},
}

TRANSITIONS = ["fade", "fadeblack", "wipeleft", "slideleft", "circleopen",
               "smoothleft", "dissolve", "radial", "vertopen", "hlslice"]


def seed_from_text(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


# ---------------------------------------------------------------- signature

def make_signature(seed: int | None = None, overrides: dict | None = None,
                   topic: str | None = None) -> dict:
    """Build one concrete visual direction. Deterministic for a given seed."""
    if seed is None:
        seed = seed_from_text(topic) if topic else random.randrange(1, 2**31)
    seed = int(seed)
    rng = random.Random(seed)
    ov = dict(overrides or {})

    base = rng.choice(PALETTES)
    harmony = HARMONIES[rng.choice(list(HARMONIES))]
    hue = (base["hue"] + rng.uniform(-12, 12)) % 360
    sat = min(0.85, max(0.30, base["sat"] + rng.uniform(-0.10, 0.12)))
    dark = rng.random() < 0.78            # most directions are dark; some are light

    if dark:
        bg = _hsl(hue, sat * 0.35, rng.uniform(0.045, 0.085))
        surface = _hsl(hue, sat * 0.32, rng.uniform(0.10, 0.15))
        border = _hsl(hue, sat * 0.30, rng.uniform(0.20, 0.28))
        text = _hsl(hue, 0.10, rng.uniform(0.95, 0.99))
        dim = _hsl(hue, 0.14, rng.uniform(0.58, 0.68))
    else:
        bg = _hsl(hue, sat * 0.16, rng.uniform(0.93, 0.97))
        surface = _hsl(hue, sat * 0.14, rng.uniform(0.87, 0.92))
        border = _hsl(hue, sat * 0.20, rng.uniform(0.74, 0.82))
        text = _hsl(hue, 0.14, rng.uniform(0.10, 0.16))
        dim = _hsl(hue, 0.12, rng.uniform(0.34, 0.44))

    text = ensure_contrast(text, bg, target=8.0, dark_bg=dark)
    dim = ensure_contrast(dim, bg, target=4.0, dark_bg=dark)
    accent_l = 0.58 if dark else 0.42
    accent = _hsl(hue + harmony[0], min(0.9, sat + 0.18), accent_l + rng.uniform(-0.05, 0.05))
    accent2 = _hsl(hue + harmony[1], sat, accent_l + rng.uniform(-0.04, 0.06))
    accent3 = _hsl(hue + harmony[2], sat * 0.9, accent_l + rng.uniform(-0.06, 0.04))

    series = [_hsl(hue + harmony[i % len(harmony)], sat, accent_l) for i in range(4)]

    type_scale = round(rng.uniform(0.92, 1.14), 3)
    tracking = round(rng.uniform(-0.4, 1.6), 2)

    layout_orders = {}
    for name, options in LAYOUTS.items():
        pool = list(options)
        rng.shuffle(pool)
        layout_orders[name] = pool
    motion_pool = list(MOTIONS)
    rng.shuffle(motion_pool)
    transition_pool = list(TRANSITIONS)
    rng.shuffle(transition_pool)

    signature = {
        "seed": seed,
        "palette_name": base["name"],
        "harmony": rng.choice(list(HARMONIES)),
        "hue": round(hue, 1),
        "dark": dark,
        "mood": base["mood"],
        "colors": {
            "bg": hexc(bg), "surface": hexc(surface), "border": hexc(border),
            "text": hexc(text), "dim": hexc(dim),
            "accent": hexc(accent), "accent2": hexc(accent2), "accent3": hexc(accent3),
            "series": [hexc(c) for c in series],
        },
        "type": {"scale": type_scale, "tracking": tracking,
                 "weight": rng.choice([400, 500]), "case": rng.choice(["normal", "normal", "upper"])},
        "layouts": layout_orders,
        "motions": motion_pool,
        "transitions": transition_pool,
        "texture": rng.choice(TEXTURES),
        "texture_amount": round(rng.uniform(0.05, 0.22), 3),
        "pacing": rng.choice(list(PACING)),
        "radius": round(rng.uniform(0.0, 16.0), 1),
        "vignette": round(rng.uniform(0.0, 0.55), 3),
        "subject_scale": round(rng.uniform(0.86, 1.06), 3),
        "rule_style": rng.choice(["bar", "bar", "bracket", "dot"]),
        "image_style": _image_style(base, dark, ov),
    }
    for key, value in ov.items():
        if key in ("palette", "colors", "type", "motion", "layout", "texture", "pacing"):
            signature[key] = value
    return signature


def _image_style(base: dict, dark: bool, ov: dict) -> str:
    """A style clause prepended to every generated image so a set looks cohesive."""
    if ov.get("image_style"):
        return ov["image_style"]
    light = ("soft natural light, bright airy palette" if not dark else
             "dramatic low-key lighting, deep shadows, subtle rim light")
    return (f"{base['name']} colour direction, {light}, "
            "cinematic composition, shallow depth of field, no text, no watermark")


# ---------------------------------------------------------------- per-segment resolution

def resolve_visual(sig: dict, index: int, total: int, seg: dict | None = None) -> dict:
    """Concrete instructions for one segment: layout, motion, accent, texture, pace."""
    seg = seg or {}
    data = seg.get("data") or {}
    template = seg.get("template", "kinetic")
    explicit = data.get("visual") or {}

    layouts = sig["layouts"].get(template) or list(LAYOUTS["kinetic"])
    motions = sig["motions"]
    pace = PACING.get(sig["pacing"], PACING["steady"])

    layout = explicit.get("layout") or layouts[index % len(layouts)]
    motion = explicit.get("entrance") or motions[index % len(motions)]
    motion_spec = dict(MOTIONS.get(motion, MOTIONS["rise"]))

    breath_every = pace["breath_every"]
    is_breath = bool(breath_every) and index > 0 and index % breath_every == 0

    accent_cycle = [sig["colors"]["accent"], sig["colors"]["accent2"], sig["colors"]["accent3"]]
    accent = explicit.get("accent") or accent_cycle[index % len(accent_cycle)]

    density = explicit.get("density") or ("minimal" if index % 5 == 4 else "full")

    speed = float(pace["speed"]) * (0.82 if is_breath else 1.0)
    if explicit.get("speed"):
        speed = float(explicit["speed"])

    return {
        "index": index,
        "total": total,
        "layout": layout,
        "motion": motion,
        "motion_spec": motion_spec,
        "accent": accent,
        "density": density,
        "breath": is_breath,
        "speed": round(speed, 3),
        "stagger": round(0.10 + 0.09 * (speed - 0.8), 3),
        "texture": explicit.get("texture", sig["texture"]),
        "texture_amount": sig["texture_amount"],
        "radius": sig["radius"],
        "rule_style": explicit.get("rule_style", sig["rule_style"]),
        "subject_scale": sig["subject_scale"],
        "type_scale": sig["type"]["scale"],
        "tracking": sig["type"]["tracking"],
        "colors": dict(sig["colors"], accent=accent),
        "pacing": sig["pacing"],
    }


def inject(spec: dict, seed: int | None = None, force: bool = False) -> dict:
    """Attach a style signature to the spec and resolve each segment's visual instructions."""
    style_cfg = spec.setdefault("style", {})
    if style_cfg.get("off"):
        return {"applied": False}
    if "signature" not in style_cfg or force:
        style_cfg["signature"] = make_signature(
            seed if seed is not None else style_cfg.get("seed"),
            style_cfg.get("overrides"),
            topic=style_cfg.get("topic") or spec.get("name"),
        )
    sig = style_cfg["signature"]
    segments = spec.get("segments", [])
    total = max(1, len(segments))
    for i, seg in enumerate(segments):
        seg.setdefault("data", {})["visual"] = resolve_visual(sig, i, total, seg)
    spec["style"] = style_cfg
    return {"applied": True, "seed": sig["seed"], "palette": sig["palette_name"],
            "pacing": sig["pacing"], "texture": sig["texture"]}


# ---------------------------------------------------------------- distinctiveness

def _jaccard(a, b) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, len(sa | sb))


def similarity(a: dict, b: dict) -> float:
    """Rough 0..1 similarity between two signatures. 1 means 'visually the same direction'."""
    if not a or not b:
        return 0.0
    hue_gap = abs(((a["hue"] - b["hue"] + 180) % 360) - 180) / 180.0
    score = 0.0
    score += 0.30 * (1.0 - hue_gap)
    score += 0.20 * (a["palette_name"] == b["palette_name"])
    score += 0.15 * (a["pacing"] == b["pacing"])
    score += 0.10 * (a["texture"] == b["texture"])
    score += 0.10 * _jaccard(a["motions"][:3], b["motions"][:3])
    score += 0.15 * _jaccard(a["layouts"].get("kinetic", []), b["layouts"].get("kinetic", []))
    return round(min(1.0, score), 3)


def history_path() -> Path:
    return Path.home() / ".video-studio" / "history.json"


def load_history() -> list[dict]:
    p = history_path()
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def remember(entry: dict) -> None:
    p = history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    history = load_history()
    history.append(entry)
    p.write_text(json.dumps(history[-200:], ensure_ascii=False, indent=2), encoding="utf-8")


def report(spec: dict) -> dict:
    """Measure how varied this project actually is, and how close it sits to past work."""
    sig = (spec.get("style") or {}).get("signature") or {}
    segs = spec.get("segments", [])
    visuals = [(s.get("data") or {}).get("visual") or {} for s in segs]
    layouts = [v.get("layout") for v in visuals if v]
    motions = [v.get("motion") for v in visuals if v]
    transitions = [(item.get("transition") or {}).get("type", "cut") for item in spec.get("timeline", [])]
    adjacent_repeat = sum(1 for i in range(1, len(layouts)) if layouts[i] == layouts[i - 1])
    past = load_history()
    closest = None
    if sig and past:
        scored = [(similarity(sig, e.get("signature") or {}), e.get("name", "?")) for e in past]
        scored.sort(reverse=True)
        closest = {"name": scored[0][1], "similarity": scored[0][0]}
    return {
        "seed": sig.get("seed"),
        "palette": sig.get("palette_name"),
        "pacing": sig.get("pacing"),
        "texture": sig.get("texture"),
        "segments": len(segs),
        "distinct_layouts": len(set(layouts)),
        "distinct_motions": len(set(motions)),
        "distinct_transitions": len({t for t in transitions if t != "cut"}),
        "adjacent_layout_repeats": adjacent_repeat,
        "closest_past_project": closest,
        "verdict": ("ok" if adjacent_repeat == 0 and len(set(layouts)) >= max(2, len(segs) // 3)
                    else "too repetitive"),
    }
