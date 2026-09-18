"""Inspect source assets: images, audio, and video, without ffprobe."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

DURATION = re.compile(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)")
STREAM = re.compile(r"Stream #\d+:\d+.*?: (Video|Audio): ([a-z0-9_]+)")
SIZE = re.compile(r"(\d{2,5})x(\d{2,5})")


def _ffmpeg_info(ffmpeg: str, path: str) -> dict:
    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    text = proc.stderr
    info: dict = {"path": path, "duration": None, "streams": [], "size": None}
    m = DURATION.search(text)
    if m:
        h, mm, ss = m.groups()
        info["duration"] = round(int(h) * 3600 + int(mm) * 60 + float(ss), 3)
    for kind, codec in STREAM.findall(text):
        info["streams"].append({"kind": kind.lower(), "codec": codec})
        if kind == "Video" and info["size"] is None:
            sm = SIZE.search(text)
            if sm:
                info["size"] = [int(sm.group(1)), int(sm.group(2))]
    return info


def image(path: str) -> dict:
    from PIL import Image
    import numpy as np

    im = Image.open(path)
    out = {
        "path": str(path), "kind": "image", "format": im.format, "mode": im.mode,
        "size": list(im.size),
    }
    rgba = im.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[:, :, 3]
    out["alpha"] = {
        "has_alpha": im.mode in ("RGBA", "LA", "PA") or bool((alpha < 250).any()),
        "transparent_pct": round(float((alpha < 8).mean()) * 100, 1),
        "opaque_pct": round(float((alpha > 247).mean()) * 100, 1),
    }
    if out["alpha"]["opaque_pct"] > 0.5:
        ys, xs = np.nonzero(alpha > 127)
        out["subject_bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        rgb = arr[:, :, :3].reshape(-1, 3)[alpha.reshape(-1) > 127]
        q = Image.fromarray(rgb.reshape(1, -1, 3)).quantize(colors=8)
        pal = list(q.getpalette() or [])
        out["dominant_colors"] = [
            "#%02x%02x%02x" % tuple(pal[i:i + 3])
            for i in range(0, min(len(pal), 24), 3) if len(pal[i:i + 3]) == 3
        ]
    small = rgba.resize((160, 160))
    out["mean_luma"] = round(float(np.asarray(small.convert("L")).mean()), 1)
    return out


def media(ffmpeg: str, path: str) -> dict:
    info = _ffmpeg_info(ffmpeg, path)
    info["kind"] = "video" if any(s["kind"] == "video" for s in info["streams"]) else "audio"
    if info["kind"] == "audio":
        info["loudness"] = loudness(ffmpeg, path)
    return info


def loudness(ffmpeg: str, path: str) -> dict:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = {}
    for key in ("mean_volume", "max_volume"):
        m = re.search(key + r": (-?[\d.]+) dB", proc.stderr)
        if m:
            out[key] = float(m.group(1))
    return out


def any_file(ffmpeg: str, path: str) -> dict:
    suffix = Path(path).suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"):
        return image(path)
    return media(ffmpeg, path)
