"""Vendored browser libraries: what a scene may use, and how it gets onto the page.

The renderer pipes a page full of `seek(t)` calls straight into ffmpeg, so a library is only
usable here if it can be (a) driven from `t`, (b) loaded with no network at render time, and
(c) shipped as one file that survives being copied into a project. That rules out CDNs, ESM-only
packages (there is no module loader on the injection path) and anything with a license that
forbids redistribution.

`assets/lib/<name>/` holds the vendored file plus its LICENSE - the same shape the docs ask for.
A project opts in with `"libs": ["lucide"]`; `render.runtime_args` then injects the file through
Playwright's `addInitScript`, which is how the skill's own runtimes already reach a scene. No
relative `<script src>` is involved, so a scene stays portable.

Vendoring is a build-time step, not a render-time one: `vs.py libs --install <name>` runs
`npm pack` once and records what it took (package, version, license, sha256) in the manifest.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from . import runtime


class LibError(RuntimeError):
    """Raised when a project asks for a library that is unknown or not vendored."""


LIB_DIR = runtime.SKILL_DIR / "assets" / "lib"

# Known-good browser builds. Every entry was checked to expose a global that a scene can use,
# and every one is license-clean for redistribution (MIT / ISC / Apache-2.0 / BSD / CC0).
# `files` maps the path inside the npm package to the filename kept on disk here.
REGISTRY: dict[str, dict] = {
    "lucide": {
        "package": "lucide",
        "version": "1.47.0",
        "license": "ISC",
        "kind": "icons",
        "global": "lucide",
        "files": {"dist/umd/lucide.min.js": "lucide.min.js"},
        "provides": "2108 stroke icons as SVG node data; drives Scene.icon()",
        "drive": "build the <svg> once, then animate it with any t-derived transform",
    },
    "lottie": {
        "package": "lottie-web",
        "version": "5.13.0",
        "license": "MIT",
        "kind": "motion",
        "global": "lottie",
        "files": {"build/player/lottie_light.min.js": "lottie_light.min.js"},
        "provides": "After Effects / Bodymovin JSON playback (SVG renderer, light build)",
        "drive": "animation.goToAndStop(t * fps, true) - never play()",
    },
    "anime": {
        "package": "animejs",
        "version": "4.5.0",
        "license": "MIT",
        "kind": "motion",
        "global": "anime",
        "files": {"dist/bundles/anime.umd.min.js": "anime.umd.min.js"},
        "provides": "timelines and tweens with an explicit seek()",
        "drive": "createTimeline({autoplay:false}); timeline.seek(t) - no engine ticker",
    },
    "d3-scale": {
        "package": "d3-scale",
        "version": "4.0.2",
        "license": "ISC",
        "kind": "math",
        "global": "d3",
        "files": {"dist/d3-scale.min.js": "d3-scale.min.js"},
        "provides": "linear / band / log / ordinal scales and ticks - pure functions",
        "drive": "no clock at all: value at t is just f(t)",
    },
}

ALIASES = {
    "lucide-icons": "lucide",
    "lottie-web": "lottie",
    "animejs": "anime",
    "anime.js": "anime",
    "d3": "d3-scale",
    "d3scale": "d3-scale",
}


def normalize(name: str) -> str:
    key = str(name or "").strip().lower()
    return ALIASES.get(key, key)


def manifest_of(name: str) -> dict | None:
    p = LIB_DIR / normalize(name) / "manifest.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def installed() -> dict[str, dict]:
    """Vendored libraries, keyed by name, in registry order first."""
    found: dict[str, dict] = {}
    if LIB_DIR.is_dir():
        for d in sorted(LIB_DIR.iterdir()):
            if d.is_dir():
                m = manifest_of(d.name)
                if m:
                    found[d.name] = m
    return found


def entry_path(name: str) -> Path:
    m = manifest_of(name)
    if not m:
        raise LibError(_missing_message(normalize(name)))
    p = LIB_DIR / normalize(name) / str(m.get("entry") or "")
    if not p.is_file():
        raise LibError(
            f"library '{normalize(name)}' is recorded but its file is missing: {p}\n"
            f"Re-vendor with: python vs.py libs --install {normalize(name)}"
        )
    return p


def resolve(names) -> list[Path]:
    """Names from a project spec -> injected files, de-duplicated, registry order preserved."""
    out: list[Path] = []
    seen: set[str] = set()
    for raw in names or []:
        key = normalize(raw)
        if not key or key in seen:
            continue
        if key not in REGISTRY and not manifest_of(key):
            raise LibError(_missing_message(key))
        seen.add(key)
        out.append(entry_path(key))
    return out


def _missing_message(key: str) -> str:
    have = ", ".join(sorted(installed())) or "none"
    known = ", ".join(sorted(REGISTRY))
    if key in REGISTRY:
        return (f"library '{key}' is known but not vendored yet (installed: {have}).\n"
                f"Vendor it once with: python vs.py libs --install {key}")
    return (f"unknown library '{key}' (installed: {have}; known: {known}).\n"
            f"See references/libraries.md for the full list and what fits this pipeline.")


def describe() -> dict:
    """Everything `vs.py libs` prints: what is vendored and what could be."""
    have = installed()
    items = []
    for name in sorted(set(REGISTRY) | set(have)):
        reg = REGISTRY.get(name, {})
        man = have.get(name)
        items.append({
            "name": name,
            "installed": bool(man),
            "kind": reg.get("kind") or (man or {}).get("kind"),
            "package": reg.get("package") or (man or {}).get("package"),
            "version": (man or {}).get("version") or reg.get("version"),
            "license": (man or {}).get("license") or reg.get("license"),
            "global": reg.get("global") or (man or {}).get("global"),
            "provides": reg.get("provides") or (man or {}).get("provides"),
            "drive": reg.get("drive") or (man or {}).get("drive"),
            "entry": (man or {}).get("entry") or ",".join(reg.get("files", {}).values()),
            "path": str(LIB_DIR / name / str((man or {}).get("entry") or "")) if man else None,
        })
    return {"lib_dir": str(LIB_DIR), "libraries": items}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def fingerprint(names) -> str:
    """Cache-key fragment: a segment must re-render when a vendored library changes."""
    parts = []
    for p in resolve(names):
        try:
            st = p.stat()
            parts.append(f"{p.parent.name}/{p.name}:{st.st_size}:{int(st.st_mtime)}")
        except OSError:
            parts.append(f"{p.name}:missing")
    return "|".join(parts)


# --------------------------------------------------------------------------- vendoring
def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 600):
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def install(names, log=print) -> list[dict]:
    """Vendor libraries from npm, per references/libraries.md: pack, keep the build + LICENSE."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise LibError("npm not found. Vendoring needs npm once; the render itself never does.")
    done = []
    for raw in names:
        key = normalize(raw)
        reg = REGISTRY.get(key)
        if not reg:
            raise LibError(_missing_message(key))
        done.append(_install_one(npm, key, reg, log))
    return done


def _install_one(npm: str, key: str, reg: dict, log) -> dict:
    dest = LIB_DIR / key
    dest.mkdir(parents=True, exist_ok=True)
    spec = f"{reg['package']}@{reg['version']}"
    with tempfile.TemporaryDirectory(prefix="vs-lib-") as tmp:
        tmpdir = Path(tmp)
        log(f"  npm pack {spec}")
        proc = _run([npm, "pack", spec, "--pack-destination", str(tmpdir)])
        if proc.returncode != 0:
            raise LibError(f"npm pack {spec} failed:\n{proc.stdout}\n{proc.stderr}")
        tgz = next(iter(sorted(tmpdir.glob("*.tgz"))), None)
        if not tgz:
            raise LibError(f"npm pack {spec} produced no tarball")
        with tarfile.open(tgz) as tf:
            tf.extractall(tmpdir)
        pkg = tmpdir / "package"
        files = {}
        for src, name in reg["files"].items():
            s = pkg / src
            if not s.is_file():
                raise LibError(f"{spec} has no {src}; the registry entry needs updating")
            shutil.copy2(s, dest / name)
            files[name] = {"from": src, "sha256": sha256(dest / name),
                           "bytes": (dest / name).stat().st_size}
        license_src = next((p for p in pkg.glob("LICENSE*") if p.is_file()), None)
        if not license_src:
            raise LibError(f"{spec} ships no LICENSE file; refusing to vendor it")
        shutil.copy2(license_src, dest / "LICENSE")
    manifest = {
        "name": key,
        "package": reg["package"],
        "version": reg["version"],
        "license": reg["license"],
        "kind": reg["kind"],
        "global": reg["global"],
        "provides": reg["provides"],
        "drive": reg["drive"],
        "entry": next(iter(reg["files"].values())),
        "files": files,
        "source": f"https://www.npmjs.com/package/{reg['package']}/v/{reg['version']}",
        "note": "Vendored build-time with `vs.py libs --install`. Renders never fetch this.",
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"  vendored {key} {reg['version']} ({reg['license']}) -> {dest}")
    return manifest


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print("usage: python scripts/lib/libs.py [--install name...]")
        return 0
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    if argv and argv[0] == "--install":
        install(argv[1:], log=log)
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
