"""Locate the runtimes this skill needs: node, playwright, chromium, and a *full* ffmpeg.

The trap this module exists to avoid: Playwright ships an ffmpeg build that can only
encode VP8 and PNG. It is on PATH in some Codex environments and will silently produce
unusable output, so every candidate is verified for libx264 before it is accepted.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class ToolError(RuntimeError):
    """Raised when a required runtime is missing or unusable."""


SKILL_DIR = Path(__file__).resolve().parents[2]
VENDOR_DIR = SKILL_DIR / "vendor"

_PLAYWRIGHT_CACHE: tuple[str, str | None] | None = None
_FFMPEG_CACHE: dict[tuple, str] = {}


def _run(cmd, timeout=30, **kw):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace", **kw,
    )


def _is_file(p) -> bool:
    try:
        return bool(p) and Path(p).is_file()
    except OSError:
        return False


# --------------------------------------------------------------------------- ffmpeg
def ffmpeg_capabilities(path: str) -> set[str]:
    """Return the set of encoder/filter names a build exposes (empty on failure)."""
    caps: set[str] = set()
    try:
        enc = _run([path, "-hide_banner", "-encoders"], timeout=20)
        fil = _run([path, "-hide_banner", "-filters"], timeout=20)
    except Exception:
        return caps
    for line in enc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[VAS][A-Z.]{5}", parts[0] or ""):
            caps.add(parts[1])
    for line in fil.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[A-Z.]{3}", parts[0] or ""):
            caps.add(parts[1])
    return caps


def ffmpeg_candidates() -> list[str]:
    out: list[str] = []
    env = os.environ.get("VS_FFMPEG")
    if env:
        out.append(env)
    if VENDOR_DIR.exists():
        out += sorted(str(p) for p in VENDOR_DIR.rglob("ffmpeg*")
                      if p.is_file() and p.suffix.lower() in (".exe", ""))
    which = shutil.which("ffmpeg")
    if which:
        out.append(which)
    try:  # imageio-ffmpeg ships a full static build inside the wheel
        import imageio_ffmpeg
        out.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    out += [r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"]
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def find_ffmpeg(require=("libx264",)) -> str:
    cached = _FFMPEG_CACHE.get(tuple(require))
    if cached:
        return cached
    problems = []
    for cand in ffmpeg_candidates():
        if not _is_file(cand):
            continue
        caps = ffmpeg_capabilities(cand)
        if not caps:
            problems.append(f"{cand}: not executable")
            continue
        missing = [x for x in require if x not in caps]
        if missing:
            problems.append(f"{cand}: missing {'/'.join(missing)}")
            continue
        _FFMPEG_CACHE[tuple(require)] = cand
        return cand
    raise ToolError(
        "No usable ffmpeg found (needs " + "/".join(require) + ")."
        " Tried: " + "; ".join(problems or ["nothing"]) +
        ". Fix with `vs.py doctor --install-ffmpeg`, or set VS_FFMPEG."
    )


def install_ffmpeg(python=None) -> str:
    """Vendor a full ffmpeg binary into the skill via `pip install imageio-ffmpeg`."""
    python = python or sys.executable
    target = VENDOR_DIR / "pylibs"
    target.mkdir(parents=True, exist_ok=True)
    # Remove the pip target once, after every candidate has been tried: deleting it inside the
    # loop lost the rest of the wheel when the first binary failed the libx264 check.
    try:
        proc = _run([python, "-m", "pip", "install", "--quiet", "--target", str(target),
                     "--upgrade", "imageio-ffmpeg"], timeout=600)
        if proc.returncode != 0:
            raise ToolError(f"pip install failed:\n{proc.stdout}\n{proc.stderr}")
        for p in sorted(target.rglob("ffmpeg*")):
            if not (p.is_file() and p.suffix.lower() in (".exe", "")):
                continue
            placed = VENDOR_DIR / p.name
            shutil.copy2(p, placed)
            if not os.access(placed, os.X_OK) and os.name != "nt":
                placed.chmod(0o755)
            if "libx264" in ffmpeg_capabilities(str(placed)):
                return str(placed)
        raise ToolError("installed imageio-ffmpeg but found no libx264-capable binary")
    finally:
        shutil.rmtree(target, ignore_errors=True)


# --------------------------------------------------------------------------- node + playwright
def find_node() -> str:
    env = os.environ.get("VS_NODE")
    if _is_file(env):
        return env
    home = Path.home()
    base = home / ".cache" / "codex-runtimes"
    if base.exists():
        for p in sorted(base.glob("*/dependencies/node/bin/node.exe")) + \
                 sorted(base.glob("*/dependencies/node/bin/node")):
            if p.is_file():
                return str(p)
    which = shutil.which("node")
    if which:
        return which
    raise ToolError("No node executable found. Set VS_NODE.")


def find_playwright(node: str | None = None) -> tuple[str, str | None]:
    """Return (module reference for require(), PLAYWRIGHT_BROWSERS_PATH or None).

    Resolved once per process: `render.runtime_env()` calls this for every slice / still child,
    and each call used to walk the whole plugin cache looking for a playwright package.
    """
    global _PLAYWRIGHT_CACHE
    if _PLAYWRIGHT_CACHE is not None:
        return _PLAYWRIGHT_CACHE
    env_mod = os.environ.get("VS_PLAYWRIGHT")
    if env_mod:
        _PLAYWRIGHT_CACHE = (env_mod, os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
        return _PLAYWRIGHT_CACHE
    home = Path.home()
    mods: list[Path] = []
    base = home / ".cache" / "codex-runtimes"
    if base.exists():
        mods += sorted(base.glob("*/dependencies/node/node_modules/playwright"))
    for extra in (home / ".codex" / "plugins" / "cache", home / "AppData" / "Roaming" / "npm" / "node_modules"):
        if extra.exists():
            mods += sorted(extra.rglob("node_modules/playwright"))
    browsers = home / "AppData" / "Local" / "ms-playwright"
    if not browsers.exists():
        browsers = home / ".cache" / "ms-playwright"
    for m in mods:
        if (m / "package.json").is_file():
            _PLAYWRIGHT_CACHE = (str(m).replace("\\", "/"),
                                 str(browsers) if browsers.exists() else None)
            return _PLAYWRIGHT_CACHE
    _PLAYWRIGHT_CACHE = ("playwright", str(browsers) if browsers.exists() else None)
    return _PLAYWRIGHT_CACHE


def check_chromium(browsers_path: str | None) -> str | None:
    if not browsers_path:
        return None
    root = Path(browsers_path)
    for d in sorted(root.glob("chromium-*")) + sorted(root.glob("chromium")):
        if d.is_dir():
            return str(d)
    return None


def doctor(install=False) -> dict:
    report: dict = {"ok": True, "notes": []}
    try:
        node = find_node()
        report["node"] = {"path": node, "version": _run([node, "-v"]).stdout.strip()}
    except ToolError as e:
        report["ok"] = False
        report["node"] = {"error": str(e)}
        node = None

    if node:
        mod, browsers = find_playwright(node)
        report["playwright"] = {"module": mod, "browsers_path": browsers}
        chromium = check_chromium(browsers)
        if not chromium:
            report["ok"] = False
            report["playwright"]["error"] = "chromium not found; run: npx playwright install chromium"
        else:
            report["playwright"]["chromium"] = chromium

    try:
        path = find_ffmpeg()
    except ToolError as e:
        if install:
            report["notes"].append("installing ffmpeg via imageio-ffmpeg")
            path = install_ffmpeg()
        else:
            report["ok"] = False
            report["ffmpeg"] = {"error": str(e)}
            path = None
    if path:
        caps = ffmpeg_capabilities(path)
        report["ffmpeg"] = {
            "path": path,
            "encoders": {k: (k in caps) for k in ("libx264", "libx265", "aac", "libmp3lame")},
            "filters": {k: (k in caps) for k in (
                "xfade", "overlay", "drawtext", "subtitles", "palettegen", "paletteuse",
                "adelay", "amix", "volume", "loudnorm", "concat", "eq")},
        }
    report["python"] = {"path": sys.executable, "version": sys.version.split()[0]}
    return report
