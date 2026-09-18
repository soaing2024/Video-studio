"""Convert a source image into a pixel-art sprite: hard alpha, limited palette, 1px outline."""
from __future__ import annotations

from pathlib import Path


def make_sprite(src: str, out: str, width: int = 64, height: int = 96, colors: int = 12,
                alpha_cutoff: int = 115, outline: str = "#0a0810",
                shadow: str = "#05070d", trim: bool = False) -> dict:
    """Return a report describing what was written."""
    from PIL import Image, ImageChops, ImageFilter

    src_img = Image.open(src).convert("RGBA")
    small = src_img.resize((width, height), Image.BOX)
    alpha = small.getchannel("A").point(lambda v: 255 if v >= alpha_cutoff else 0)
    rgb = small.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT).convert("RGB")
    body = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    body.paste(rgb, (0, 0), alpha)

    pad = Image.new("RGBA", (width + 2, height + 2), (0, 0, 0, 0))
    pad.paste(body, (1, 1), body)
    mask = pad.getchannel("A").point(lambda v: 255 if v > 0 else 0)
    ring = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(3)), mask)
    out_img = Image.composite(Image.new("RGBA", pad.size, _rgba(outline)), pad, ring)

    if trim:
        box = out_img.getchannel("A").getbbox()
        if box:
            out_img = out_img.crop(box)

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_path = out_path.with_name(out_path.stem + "-shadow" + out_path.suffix)
    out_img.save(out_path)
    sh = Image.new("RGBA", out_img.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", out_img.size, _rgba(shadow)), (0, 0), out_img.getchannel("A"))
    sh.save(shadow_path)

    vis = out_img.getchannel("A")
    return {
        "sprite": str(out_path), "shadow": str(shadow_path), "size": list(out_img.size),
        "colors": len({c for c in out_img.convert("RGB").get_flattened_data()}),
        "visible_pixels": sum(1 for v in vis.get_flattened_data() if v),
        "outline_pixels": sum(1 for v in ring.get_flattened_data() if v),
    }


def _rgba(color: str):
    color = color.lstrip("#")
    if len(color) == 6:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
    if len(color) == 3:
        return tuple(int(c * 2, 16) for c in color) + (255,)
    raise ValueError(f"bad color: {color}")
