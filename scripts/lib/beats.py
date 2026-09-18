"""Beat / onset detection, so montage cuts can land on the music.

Decode with ffmpeg, then spectral-flux onset detection with numpy. No extra deps.
"""
from __future__ import annotations

import subprocess

import numpy as np

SR = 22050
N_FFT = 1024
HOP = 512


def _decode(ffmpeg: str, path: str) -> np.ndarray:
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR),
         "-f", "s16le", "-"],
        capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode audio: {proc.stderr[:400].decode('utf-8', 'replace')}")
    return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0


def detect(ffmpeg: str, path: str, sensitivity: float = 1.5, min_gap: float = 0.30,
           smooth: int = 3) -> dict:
    y = _decode(ffmpeg, path)
    duration = len(y) / SR
    if len(y) < N_FFT * 2:
        return {"path": path, "duration": round(duration, 3), "beats": [], "bpm": None}

    window = np.hanning(N_FFT).astype(np.float32)
    frames = 1 + (len(y) - N_FFT) // HOP
    spec = np.empty((frames, N_FFT // 2 + 1), dtype=np.float32)
    for i in range(frames):
        seg = y[i * HOP: i * HOP + N_FFT] * window
        spec[i] = np.abs(np.fft.rfft(seg))

    flux = np.diff(spec, axis=0)
    flux = np.maximum(flux, 0).sum(axis=1)
    if smooth > 1:
        kernel = np.ones(smooth, dtype=np.float32) / smooth
        flux = np.convolve(flux, kernel, mode="same")

    times = (np.arange(1, len(flux) + 1) * HOP + N_FFT / 2) / SR
    thresh = flux.mean() + sensitivity * flux.std()
    candidates = np.where(flux > thresh)[0]

    beats: list[float] = []
    for idx in candidates:
        if flux[idx] < flux[max(0, idx - 1)] or flux[idx] < flux[min(len(flux) - 1, idx + 1)]:
            continue
        t = float(times[idx])
        if beats and t - beats[-1] < min_gap:
            if flux[idx] > flux[_nearest(times, beats[-1])]:
                beats[-1] = t
            continue
        beats.append(t)

    bpm = None
    if len(beats) > 3:
        gaps = np.diff(beats)
        gaps = gaps[(gaps > 0.25) & (gaps < 1.5)]
        if len(gaps):
            bpm = round(60.0 / float(np.median(gaps)), 1)

    return {
        "path": path,
        "duration": round(duration, 3),
        "bpm": bpm,
        "count": len(beats),
        "beats": [round(b, 3) for b in beats],
    }


def _nearest(times: np.ndarray, t: float) -> int:
    return int(np.argmin(np.abs(times - t)))


def cut_points(beats: list[float], target_len: float, min_len: float = 1.2,
               max_len: float = 8.0) -> list[float]:
    """Beat-aligned cut points that always keep shots inside [min_len, max_len].

    Taking the next beat after `min_len` alone breaks down on sparse or irregular beats (a
    drone, a spoken track, a bad detection) and collapses to a handful of very long shots.
    This walks window by window instead: prefer the first beat inside the window, otherwise cut
    at the window edge."""
    marks = sorted(b for b in beats if 0.0 < b < target_len)
    cuts: list[float] = []
    last = 0.0
    while target_len - last > min_len:
        window_end = min(last + max_len, target_len)
        candidate = next((b for b in marks if last + min_len <= b <= window_end), None)
        if candidate is None:
            candidate = min(window_end, max(last + min_len, last + max_len))
        cuts.append(round(min(candidate, target_len), 3))
        last = cuts[-1]
    return cuts
