"""Verify a finished video with measurements instead of eyes.

Catches the failures that matter: wrong length, missing content, broken fades,
threshold (not nearest-neighbour) upscaling, unbounded palettes, silent audio.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from . import probe, spec as specmod


class Verifier:
    def __init__(self, spec: dict, ffmpeg: str):
        self.spec = spec
        self.ffmpeg = ffmpeg
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str):
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})

    def _frame(self, path: str, t: float, out: Path):
        """Grab one frame. Seeking right at the end can land past the last video frame, so
        step back and retry instead of reporting a bogus failure."""
        from PIL import Image
        attempt = max(0.0, t)
        for _ in range(4):
            if out.exists():
                out.unlink()
            subprocess.run([self.ffmpeg, "-y", "-v", "error", "-ss", f"{attempt:.3f}",
                            "-i", path, "-frames:v", "1", str(out)], check=True)
            if out.is_file():
                return Image.open(out).convert("RGB")
            attempt -= 0.1
        raise RuntimeError(f"could not extract a frame near {t:.2f}s from {path}")

    def _tail_frames(self, path: str, seconds: float, tmp: Path) -> list[float]:
        """Mean luma of the last few frames, decoded as a run so no seek can overshoot."""
        import numpy as np
        from PIL import Image
        out = tmp / "tail"
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run([self.ffmpeg, "-y", "-v", "error", "-sseof", f"-{seconds:.3f}",
                        "-i", path, "-vf", "fps=8", str(out / "f%02d.png")], check=True)
        return [float(np.asarray(Image.open(p).convert("RGB"), dtype=np.int16).mean())
                for p in sorted(out.glob("f*.png"))]


    def run(self, video: str, samples: int = 5) -> dict:
        import numpy as np
        from PIL import Image

        spec, ffmpeg = self.spec, self.ffmpeg
        info = probe.media(ffmpeg, video)
        duration = info.get("duration") or 0.0
        planned = specmod.planned_duration(spec)
        self.add("duration", abs(duration - planned) <= max(0.25, planned * 0.02),
                 f"video {duration:.2f}s vs planned {planned:.2f}s")
        self.add("resolution", info.get("size") == [spec["video"]["width"], spec["video"]["height"]],
                 f"{info.get('size')} vs {spec['video']['width']}x{spec['video']['height']}")

        look = spec.get("look") or {}
        px = look.get("pixelate")
        tmp = Path(tempfile.mkdtemp(prefix="vs-verify-"))
        try:
            luma, colors, block, qerr = [], [], [], []
            times = [duration * (i + 0.5) / samples for i in range(samples)]
            for i, t in enumerate(times):
                im = self._frame(video, t, tmp / f"f{i}.png")
                arr = np.asarray(im, dtype=np.int16)
                luma.append(round(float(arr.mean()), 2))
                colors.append(len(set(im.getdata())))
                if px:
                    s = max(1, int(px.get("scale", 4)))
                    blk = arr[::s, ::s]
                    up = np.repeat(np.repeat(blk, s, axis=0), s, axis=1)[:arr.shape[0], :arr.shape[1]]
                    block.append(round(float(np.abs(arr - up).mean()), 2))
                    want = max(1, int(px.get("colors", 16)))
                    q = im.quantize(colors=want, method=Image.MEDIANCUT).convert("RGB")
                    qerr.append(round(float(np.abs(np.asarray(q, dtype=np.int16) - arr).mean()), 2))

            # a fade-to-black transition legitimately passes through black, so require most
            # samples to carry picture rather than all of them
            lit = [v for v in luma if v > 2.0]
            needed = max(1, samples // 2)
            self.add("content", len(lit) >= needed,
                     f"{len(lit)}/{samples} sampled frames carry picture "
                     f"(need {needed}): luma {luma}")
            # Fades are judged against the video's own brightness. An absolute cutoff is wrong
            # twice over: at 30fps a seek to "just after 0" lands on frame two (already part-way
            # into the ramp), and a bright grade would fail a fixed dark threshold.
            body = float(np.median(lit)) if lit else 0.0
            cutoff = max(6.0, 0.15 * body)
            if float(look.get("fade_in", 0) or 0) > 0:
                first = self._frame(video, 0.0, tmp / "first.png")
                m = float(np.asarray(first, dtype=np.int16).mean())
                self.add("fade_in", m <= cutoff,
                         f"first frame luma {m:.1f} vs body {body:.1f} (cutoff {cutoff:.1f})")
            fo = float(look.get("fade_out", 0) or 0)
            if fo > 0 and duration > fo + 0.4:
                # The literal last frame is awkward to grab, and the content itself may still be
                # animating, so compare the darkest tail frame against the level just before the
                # ramp began.
                before = self._frame(video, max(0.0, duration - fo - 0.2), tmp / "pre.png")
                m_before = float(np.asarray(before, dtype=np.int16).mean())
                tail = self._tail_frames(video, max(0.3, fo * 0.4), tmp)
                m_tail = min(tail) if tail else m_before
                self.add("fade_out", m_tail <= max(6.0, 0.5 * m_before),
                         f"darkest tail frame {m_tail:.1f} vs {m_before:.1f} before the fade")

            if px:
                worst = max(block) if block else 0.0
                self.add("pixel_blocks", worst < 6.0,
                         f"block consistency mean diff {block} (0 = perfect "
                         f"{int(px.get('scale', 4))}x blocks)")
                # Lossy video encoding smears every palette entry into a cloud of nearby RGB
                # values, so raw colour counts are meaningless here. Instead: re-quantise each
                # frame down to the requested palette size and measure how much that loses.
                want = int(px.get("colors", 16))
                self.add("palette", max(qerr or [0]) < 6.0,
                         f"mean error when re-quantising to {want} colours: {qerr}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        tracks = (spec.get("audio") or {}).get("tracks", [])
        if tracks:
            loud = probe.loudness(ffmpeg, video)
            mean = loud.get("mean_volume")
            self.add("audio_present", mean is not None and mean > -60,
                     f"mean {mean} dB, peak {loud.get('max_volume')} dB")
            self.add("audio_level", mean is None or -45 < mean < -10,
                     f"mean {mean} dB should sit between -45 and -10 for a background bed")
        else:
            self.add("audio_present", not any(s["kind"] == "audio" for s in info.get("streams", [])),
                     "no audio configured, so none expected")

        ok = all(c["ok"] for c in self.checks)
        return {"ok": ok, "video": video, "duration": duration, "checks": self.checks}


def verify(spec: dict, ffmpeg: str, video: str | None = None, samples: int = 5) -> dict:
    out = video or str(Path(spec["base_dir"]) / f"{spec['name']}.mp4")
    return Verifier(spec, ffmpeg).run(out, samples=samples)
