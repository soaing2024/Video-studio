"""Optical finishing: the lens-and-emulsion layer that sits after the grade.

Everything up to this point in the pipeline is vector-accurate: flat colour fields, hard
edges, no light behaviour. That is why an otherwise well-designed piece can still read as
"software output" rather than "photographed". This module is the one place where the whole
frame gets light behaviour applied to it as a single image:

    lut -> tone -> halation/bloom -> chroma (lateral CA) -> vignette -> grain -> sharpen

All of it is optional and off by default (`finish` absent, or `preset: "clean"`). A preset
expands to conservative numbers; every key can be overridden by writing it explicitly.

    "look": {
      "finish": {
        "preset": "film",                    // clean | film | analog | print
        "halation": { "amount": 0.16, "sigma": 18, "threshold": 0.72, "warmth": 0.35 },
        "grain":    { "amount": 5, "chroma": 0.3, "seed": 20260920 },
        "chroma":   { "px": 1 },
        "vignette": { "angle": 0.5 },
        "lut":      "assets/grade.cube"
      }
    }

Two rules the numbers here follow, taken from the taste gate: an effect nobody can name
when it is removed is the right dose, and grain must never be the thing that carries the
picture. Grain is skipped automatically on a `pixelate` project (it fights the block grid)
unless it is asked for by name.
"""
from __future__ import annotations

import math
from pathlib import Path


class FinishError(ValueError):
    """Raised for an unusable finish configuration."""


# preset -> the parameters it expands to. Deliberately subtle: these are finishing, not filters.
PRESETS: dict[str, dict] = {
    "clean": {},
    # measured on a flat grey field: angle 0.30 leaves corners at 83% of centre luma,
    # 0.55 at 52%, 0.75 at 25%. Anything past ~0.5 stops being exposure and becomes a filter.
    "film": {
        "halation": {"amount": 0.14, "sigma": 16, "threshold": 0.70, "warmth": 0.35},
        "grain": {"amount": 3, "chroma": 0.30, "seed": 20260920},
        "chroma": {"px": 1},
        "vignette": {"angle": 0.30},
        "tone": {"lift": 0.012, "roll": 0.985, "gamma": 1.0, "saturation": 1.03},
    },
    "analog": {
        "halation": {"amount": 0.24, "sigma": 26, "threshold": 0.62, "warmth": 0.55},
        "grain": {"amount": 8, "chroma": 0.55, "seed": 20260920},
        "chroma": {"px": 1},
        "vignette": {"angle": 0.42},
        "tone": {"lift": 0.02, "roll": 0.97, "gamma": 0.98, "saturation": 0.97},
    },
    "print": {
        "halation": {"amount": 0.10, "sigma": 14, "threshold": 0.74, "warmth": 0.25},
        "grain": {"amount": 2, "chroma": 0.25, "seed": 20260920},
        "vignette": {"angle": 0.22},
        "tone": {"lift": 0.008, "roll": 0.99, "gamma": 1.02, "saturation": 1.08},
        "sharpen": 0.35,
    },
}

_BOOL_KEYS = ("halation", "grain", "chroma", "vignette", "tone", "sharpen", "lut")


def _num(value, default: float, lo: float, hi: float, where: str) -> float:
    try:
        out = default if value is None else float(value)
    except (TypeError, ValueError):
        raise FinishError(f"{where} needs a number, got {value!r}") from None
    if not math.isfinite(out):
        raise FinishError(f"{where} needs a finite number, got {value!r}")
    return max(lo, min(hi, out))


def resolve(look: dict, pixelate: bool = False) -> dict:
    """Expand a preset + explicit overrides into the flat config the filter chain consumes."""
    cfg = (look or {}).get("finish") or {}
    if cfg is False or (not cfg and cfg != {}):
        return {"enabled": False, "preset": None}
    if not isinstance(cfg, dict):
        raise FinishError("look.finish needs an object")
    if cfg.get("enabled") is False:
        return {"enabled": False, "preset": None}

    preset = str(cfg.get("preset", "clean")).lower()
    if preset not in PRESETS:
        raise FinishError(f"unknown finish preset '{preset}'; choose from {sorted(PRESETS)}")
    merged: dict = {k: dict(v) for k, v in PRESETS[preset].items()}

    for key in _BOOL_KEYS:
        if key not in cfg:
            continue
        if key == "lut":
            merged["lut"] = str(cfg["lut"]) if cfg["lut"] else None
            continue
        value = cfg[key]
        if value in (None, False):
            merged.pop(key, None)
            continue
        if value is True:
            merged.setdefault(key, {})
            continue
        if not isinstance(value, dict):
            raise FinishError(f"look.finish.{key} needs an object (or true/false), got {value!r}")
        base = dict(merged.get(key) or {})
        base.update({k: v for k, v in value.items() if v is not None})
        merged[key] = base

    # grain on a block grid reads as a broken palette, not as emulsion
    if pixelate and "grain" in merged and not (cfg.get("grain") or cfg.get("preset_grain")):
        merged.pop("grain", None)

    if "grain" in merged:
        g = merged["grain"]
        merged["grain"] = {
            "amount": _num(g.get("amount"), 5, 0, 40, "finish.grain.amount"),
            "chroma": _num(g.get("chroma"), 0.3, 0, 1.5, "finish.grain.chroma"),
            "seed": int(_num(g.get("seed"), 20260920, 0, 2 ** 31 - 1, "finish.grain.seed")),
            "temporal": bool(g.get("temporal", True)),
        }
        if merged["grain"]["amount"] <= 0:
            merged.pop("grain")
    if "halation" in merged:
        h = merged["halation"]
        merged["halation"] = {
            "amount": _num(h.get("amount"), 0.14, 0, 0.8, "finish.halation.amount"),
            "sigma": _num(h.get("sigma"), 16, 0.5, 80, "finish.halation.sigma"),
            "threshold": _num(h.get("threshold"), 0.70, 0.0, 0.95, "finish.halation.threshold"),
            "warmth": _num(h.get("warmth"), 0.35, 0, 1, "finish.halation.warmth"),
        }
        if merged["halation"]["amount"] <= 0:
            merged.pop("halation")
    if "chroma" in merged:
        c = merged["chroma"]
        merged["chroma"] = {"px": int(_num(c.get("px"), 1, 0, 6, "finish.chroma.px"))}
        if merged["chroma"]["px"] <= 0:
            merged.pop("chroma")
    if "vignette" in merged:
        v = merged["vignette"]
        merged["vignette"] = {"angle": _num(v.get("angle"), 0.55, 0.05, 1.5, "finish.vignette.angle")}
    if "tone" in merged:
        t = merged["tone"]
        merged["tone"] = {
            "lift": _num(t.get("lift"), 0.012, 0, 0.12, "finish.tone.lift"),
            "roll": _num(t.get("roll"), 0.985, 0.85, 1.0, "finish.tone.roll"),
            "gamma": _num(t.get("gamma"), 1.0, 0.6, 1.6, "finish.tone.gamma"),
            "saturation": _num(t.get("saturation"), 1.0, 0.4, 1.6, "finish.tone.saturation"),
        }
    if "sharpen" in merged:
        s = merged["sharpen"]
        if isinstance(s, dict):
            s = s.get("amount", 0.0)
        merged["sharpen"] = _num(s, 0.0, 0, 1.5, "finish.sharpen")
        if merged["sharpen"] <= 0:
            merged.pop("sharpen")

    enabled = bool(merged)
    return {"enabled": enabled, "preset": preset, **merged}


def _esc(path: str) -> str:
    s = str(Path(path).resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def chain(cfg: dict, in_label: str, out_label: str, start: int = 0) -> tuple[list[str], str]:
    """Filter lines that turn [in_label] into [out_label].

    Returns (lines, last_label). Nothing is emitted for a no-op config, in which case the
    caller keeps its own label.
    """
    if not cfg or not cfg.get("enabled"):
        return [], in_label

    lines: list[str] = []
    stage = in_label
    n = start

    def nxt() -> str:
        nonlocal n
        n += 1
        return f"fx{n}"

    lut = cfg.get("lut")
    if lut:
        label = nxt()
        lines.append(f"[{stage}]lut3d=file='{_esc(lut)}':interp=tetrahedral[{label}]")
        stage = label

    tone = cfg.get("tone")
    if tone:
        label = nxt()
        lo = tone["lift"]
        hi = tone["roll"]
        eq = [f"contrast={1.0 + (1.0 - hi):.3f}"] if hi < 1.0 else []
        eq.append(f"saturation={tone['saturation']:.3f}")
        eq.append(f"gamma={tone['gamma']:.3f}")
        lines.append(f"[{stage}]colorlevels=rimin={lo:.4f}:gimin={lo:.4f}:bimin={lo:.4f}"
                     f":rimax={hi:.4f}:gimax={hi:.4f}:bimax={hi:.4f}[{label}]")
        stage = label
        label = nxt()
        lines.append(f"[{stage}]eq={':'.join(eq)}[{label}]")
        stage = label

    hal = cfg.get("halation")
    if hal:
        # Screen-blended blur of the highlights. Warmth biases the glow toward red, which is
        # what halation actually is: light that scattered inside the emulsion.
        w = hal["warmth"]
        thr = hal["threshold"]
        out = nxt()
        rr = 1.0 + 0.25 * w
        gg = 1.0 - 0.06 * w
        bb = 1.0 - 0.30 * w
        lines.append(f"[{stage}]format=gbrp,split=2[halbase][halglow]")
        # colorlevels tops out at rimax=1, so the glow is re-expanded with a gamma curve instead
        lines.append(f"[halglow]colorlevels=rimin={thr:.3f}:gimin={thr:.3f}:bimin={thr:.3f}"
                     f",gblur=sigma={hal['sigma']:.2f}"
                     f",colorchannelmixer=rr={rr:.3f}:gg={gg:.3f}:bb={bb:.3f}"
                     f",curves=all='0/0 0.35/0.62 1/1'[halglowb]")
        lines.append(f"[halbase][halglowb]blend=all_mode=screen"
                     f":all_opacity={hal['amount']:.3f}:shortest=1[{out}]")
        stage = out

    chroma = cfg.get("chroma")
    if chroma:
        px = int(chroma["px"])
        label = nxt()
        lines.append(f"[{stage}]rgbashift=rh={px}:bh={-px}:edge=smear[{label}]")
        stage = label

    vig = cfg.get("vignette")
    if vig:
        label = nxt()
        lines.append(f"[{stage}]vignette=angle={vig['angle']:.3f}:mode=forward[{label}]")
        stage = label

    grain = cfg.get("grain")
    if grain:
        label = nxt()
        flags = "t+u" if grain.get("temporal") else "u"
        amount = int(round(grain["amount"]))
        chroma_amt = int(round(grain["amount"] * grain["chroma"]))
        opts = [f"all_seed={grain['seed']}", f"alls={amount}", f"allf={flags}"]
        if chroma_amt > 0:
            opts += [f"c1_seed={grain['seed'] + 1}", f"c1s={chroma_amt}", f"c1f={flags}",
                     f"c2_seed={grain['seed'] + 2}", f"c2s={chroma_amt}", f"c2f={flags}"]
        lines.append(f"[{stage}]noise={':'.join(opts)}[{label}]")
        stage = label

    if cfg.get("sharpen"):
        label = nxt()
        amt = cfg["sharpen"]
        lines.append(f"[{stage}]unsharp=5:5:{amt:.2f}:5:5:0.0[{label}]")
        stage = label

    if stage == in_label:
        return [], in_label
    if stage != out_label:
        lines.append(f"[{stage}]null[{out_label}]")
    return lines, out_label


def describe(cfg: dict) -> dict:
    """Compact report for `plan` - what the look will actually do to the pixels."""
    if not cfg or not cfg.get("enabled"):
        return {"enabled": False, "preset": (cfg or {}).get("preset")}
    return {
        "enabled": True,
        "preset": cfg.get("preset"),
        "halation": bool(cfg.get("halation")),
        "grain": (cfg.get("grain") or {}).get("amount"),
        "chroma_px": (cfg.get("chroma") or {}).get("px"),
        "vignette": bool(cfg.get("vignette")),
        "lut": Path(cfg["lut"]).name if cfg.get("lut") else None,
        "tone": bool(cfg.get("tone")),
        "sharpen": cfg.get("sharpen") or 0,
    }


def summary(cfg: dict) -> str:
    if not cfg or not cfg.get("enabled"):
        return "finish: none"
    bits = []
    if cfg.get("lut"):
        bits.append(f"lut={Path(cfg['lut']).name}")
    if cfg.get("halation"):
        bits.append(f"halation {cfg['halation']['amount']:.2f}")
    if cfg.get("chroma"):
        bits.append(f"ca {cfg['chroma']['px']}px")
    if cfg.get("vignette"):
        bits.append("vignette")
    if cfg.get("grain"):
        bits.append(f"grain {cfg['grain']['amount']}")
    if cfg.get("sharpen"):
        bits.append(f"sharpen {cfg['sharpen']}")
    return f"finish({cfg.get('preset')}): " + ", ".join(bits or ["tone only"])
