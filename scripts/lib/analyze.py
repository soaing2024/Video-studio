"""Turn a rendered still + a DOM probe into numbers an agent can judge without seeing the image.

P0-C. The point is that "the composition is wrong" becomes a sentence with coordinates:
out-of-frame text, a ghost element visible from t=0, a contrast ratio of 2.1:1, an ink
budget of 0.2% (empty frame) or 38% (mud), a 12x type-scale jump.

    from . import analyze
    rep = analyze.merge(still_reports)      # still_reports from render.probe_frames()
    print(analyze.human(rep))
"""
from __future__ import annotations

import colorsys
import json
import re
from pathlib import Path

ASCII_CHARS = " .:-=+*#%@"
_WHITE = 255.0


def _rgb(text: str) -> tuple[int, int, int] | None:
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", str(text))
    if not m:
        return None
    if m.group(4) is not None and float(m.group(4)) < 0.5:
        return None                      # transparent: fall back to the canvas
    return int(float(m.group(1))), int(float(m.group(2))), int(float(m.group(3)))


def _lum(rgb) -> float:
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


def frame_stats(png: str | Path, ascii_cols: int = 96, rows: int = 0) -> dict:
    """Brightness, ink budget, 3x3 density, dominant colours and an ASCII map."""
    from PIL import Image
    import numpy as np
    im = Image.open(png).convert("RGB")
    arr = np.asarray(im, dtype=np.uint8)
    grey = np.asarray(im.convert("L"), dtype=np.uint8)
    h, w = grey.shape
    ink = {
        "lt_245": round(float((grey < 245).mean()) * 100, 2),
        "lt_225": round(float((grey < 225).mean()) * 100, 2),
        "lt_180": round(float((grey < 180).mean()) * 100, 2),
        "luma": round(float(grey.mean()), 1),
    }
    tiles = []
    for ty in range(3):
        row = []
        for tx in range(3):
            box = grey[ty * h // 3:(ty + 1) * h // 3, tx * w // 3:(tx + 1) * w // 3]
            row.append(round(255 - float(box.mean()), 1))
        tiles.append(row)
    small = im.resize((ascii_cols, rows or max(8, int(ascii_cols * h / w * 0.46))))
    px = np.asarray(small.convert("L"))
    art = "\n".join("".join(ASCII_CHARS[min(9, int((255 - v) * 3.0) // 28)] for v in line)
                    for line in px)
    q = im.convert("P", palette=Image.ADAPTIVE, colors=12).convert("RGB")
    counts: dict[tuple, int] = {}
    for c in q.getdata():
        counts[c] = counts.get(c, 0) + 1
    total = sum(counts.values()) or 1
    dom = [{"rgb": "#%02x%02x%02x" % c, "share": round(n / total, 3)}
           for c, n in sorted(counts.items(), key=lambda kv: -kv[1])[:5]]
    return {"ink": ink, "tiles_3x3": tiles, "dominant": dom, "ascii": art,
            "size": [w, h]}


def probe_stats(probe: dict) -> dict:
    """What the DOM says: framing violations, contrast, type scale, glyph sanity."""
    vw = probe.get("viewport", {}).get("w", 0)
    vh = probe.get("viewport", {}).get("h", 0)
    els = probe.get("elements", [])
    texts = [e for e in els if e.get("text")]
    out_of_frame, low_contrast, sizes, zero_width = [], [], [], []
    for e in texts:
        r, b = e.get("x", 0), e.get("y", 0)
        if r + e.get("w", 0) < 0 or b + e.get("h", 0) < 0 or r > vw or b > vh:
            out_of_frame.append({"text": e["text"][:40], "box": [r, b, e.get("w"), e.get("h")]})
        elif e.get("w", 0) < 1:
            zero_width.append(e["text"][:40])
        fg, bg = _rgb(e.get("color")), (_rgb(e.get("bg")) or (255, 255, 255))
        if fg and bg:
            ratio = contrast(fg, bg)
            if ratio < 4.5 and e.get("fs", 0) < 40:
                low_contrast.append({"text": e["text"][:32], "ratio": ratio, "fs": e.get("fs")})
        if e.get("fs"):
            sizes.append(e["fs"])
    scale = round(max(sizes) / min(sizes), 1) if sizes and min(sizes) > 0 else None
    return {"text_count": len(texts), "element_count": len(els),
            "out_of_frame": out_of_frame[:8], "low_contrast": low_contrast[:8],
            "zero_width": zero_width[:8], "type_scale": scale,
            "font_sizes": sorted(set(sizes))[-6:], "page_errors": probe.get("page_errors", [])}


def merge(rows: list[dict], ascii_cols: int = 96) -> dict:
    """Combine per-time stills + probes into one report."""
    out = {"times": [], "problems": []}
    for row in rows:
        t = row.get("t")
        item = {"t": t, "ok": bool(row.get("ok"))}
        if row.get("png") and Path(row["png"]).is_file():
            item.update(frame_stats(row["png"], ascii_cols=ascii_cols))
        if row.get("probe") and Path(row["probe"]).is_file():
            item.update(probe_stats(json.loads(Path(row["probe"]).read_text(encoding="utf-8"))))
        if not item["ok"]:
            out["problems"].append({"t": t, "kind": "render_failed",
                                    "detail": str(row.get("result"))[:300]})
            continue
        for e in item.get("out_of_frame", []):
            out["problems"].append({"t": t, "kind": "text_out_of_frame", **e})
        for e in item.get("low_contrast", []):
            out["problems"].append({"t": t, "kind": "low_contrast", **e})
        for e in item.get("zero_width", []):
            out["problems"].append({"t": t, "kind": "zero_width_text", "text": e})
        if item.get("ink", {}).get("lt_225", 0) < 0.02:
            out["problems"].append({"t": t, "kind": "frame_nearly_empty",
                                    "detail": f"only {item['ink']['lt_225']}% ink below 225"})
        out["times"].append(item)
    out["ok"] = not out["problems"]
    out["problem_count"] = len(out["problems"])
    return out


def human(rep: dict, ascii_for: float | None = None) -> str:
    """Compact text: numbers first, ASCII map only where it was asked for."""
    lines = []
    for item in rep["times"]:
        ink = item.get("ink", {})
        lines.append(f"t={item['t']:.2f}  luma {ink.get('luma')}  ink<225 {ink.get('lt_225')}%  "
                     f"text {item.get('text_count')}  type-scale {item.get('type_scale')}")
        if ascii_for is not None and abs(item["t"] - ascii_for) < 1e-6 and item.get("ascii"):
            lines.append(item["ascii"])
    for p in rep["problems"][:12]:
        lines.append(f"  ! {p['kind']} @ t={p['t']}: " +
                     (p.get("text") or p.get("detail") or json.dumps(p, ensure_ascii=False))[:110])
    if not rep["problems"]:
        lines.append("no framing/contrast/ink problems detected")
    return "\n".join(lines)
