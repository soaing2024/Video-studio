"""Vendor icon sets into a catalog that templates can load with a plain <script src>.

This is the build-time half of the icon support: rendering never touches the network. The
catalog is a self-contained `window.ICONS = {...}` script holding the package's own node
form ([[tag, attrs], ...]), which the runtime helper turns into SVG elements for DOM
templates and into Path2D for canvas templates.

Only the icons actually asked for are kept: the full Lucide package is 48 MB / 1848 icons,
while a curated core set is ~31 KB, and that difference is what makes vendoring sane.
"""
from __future__ import annotations

import json
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".video-studio" / "icon-cache"

SETS: dict[str, dict] = {
    "lucide": {
        "package": "lucide-static",
        "license": "ISC",
        "homepage": "https://lucide.dev",
        "nodes": "package/icon-nodes.json",
        "tags": "package/tags.json",
        "viewBox": 24,
        "style": "stroke",
    },
    "tabler": {
        "package": "@tabler/icons",
        "license": "MIT",
        "homepage": "https://tabler.io/icons",
        "nodes": "package/tabler-nodes-outline.json",
        "tags": "package/icons.json",
        "tag_field": "tags",
        "viewBox": 24,
        "style": "stroke",
    },
}

# What a video/graphics tool actually reaches for: media, process, data, status, craft, UI.
PRESETS: dict[str, list[str]] = {
    "core": [
        "film", "clapperboard", "video", "play", "pause", "circle-play", "square", "scissors",
        "camera", "image", "images", "music", "headphones", "mic", "volume-2", "monitor",
        "smartphone", "laptop", "crop", "captions",
        "file-code", "file-json", "file-text", "folder", "folder-open", "braces", "terminal",
        "code", "binary", "cpu", "database", "server", "cloud", "git-branch", "bug", "package",
        "wrench", "hammer", "settings", "sliders-horizontal", "workflow", "boxes", "layers",
        "chart-bar", "chart-line", "chart-pie", "chart-column", "trending-up", "activity",
        "gauge", "timer", "clock", "calendar", "hash", "percent", "sigma", "target",
        "check", "circle-check", "badge-check", "list-checks", "clipboard-check", "shield-check",
        "award", "trophy", "medal", "flag", "bookmark", "star", "thumbs-up", "heart",
        "triangle-alert", "info", "circle-x", "ban",
        "pen-tool", "pencil", "paintbrush", "palette", "ruler", "stamp", "sparkles",
        "wand-sparkles", "lightbulb", "zap", "flame", "rocket", "puzzle", "brush",
        "arrow-right", "arrow-up-right", "chevron-right", "plus", "minus", "x", "search",
        "zoom-in", "download", "upload", "share-2", "link", "external-link",
        "eye", "lock", "key", "users", "user", "message-circle", "type", "layout-grid",
        "grid-3x3", "columns-3", "rows-3", "sun", "moon", "infinity", "repeat",
    ],
}


class IconError(RuntimeError):
    pass


def _get(url: str, timeout: int = 60) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return res.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IconError(f"could not reach {url}: {exc}") from exc


def _tarball(set_name: str, cache: Path = CACHE, refresh: bool = False) -> tuple[Path, str]:
    """Download (once) the icon package for a set. Build-time only, never during a render."""
    spec = SETS.get(set_name)
    if not spec:
        raise IconError(f"unknown icon set '{set_name}' (have: {', '.join(sorted(SETS))})")
    cache.mkdir(parents=True, exist_ok=True)
    meta_path = cache / f"{spec['package'].replace('/', '_')}.version"
    tarball = cache / f"{spec['package'].replace('/', '_')}.tgz"
    cached = tarball.is_file() and meta_path.is_file()
    if cached and not refresh:
        return tarball, meta_path.read_text().strip()      # already vendored: no network at all
    try:
        meta = json.loads(_get(f"https://registry.npmjs.org/{spec['package']}/latest"))
        version = meta["version"]
        if not (cached and meta_path.read_text().strip() == version):
            tarball.write_bytes(_get(meta["dist"]["tarball"], timeout=180))
            meta_path.write_text(version)
    except IconError:
        if not cached:
            raise IconError(
                f"icon set '{set_name}' is not cached and the registry is unreachable - only the "
                f"first fetch needs network, everything after it runs offline") from None
        # a flaky registry must not break a vendoring step that already succeeded once
    return tarball, meta_path.read_text().strip()


def load_set(set_name: str, cache: Path = CACHE, refresh: bool = False) -> dict:
    """Nodes + tags for one set, trimmed to the icon names we keep."""
    spec = SETS[set_name]
    tarball, version = _tarball(set_name, cache, refresh)
    nodes, tags, lic = None, {}, spec["license"]
    with tarfile.open(tarball, "r:gz") as tar:
        for member in (spec["nodes"], spec["tags"]):
            try:
                fh = tar.extractfile(member)
            except KeyError:
                continue
            if fh is None:
                continue
            data = json.loads(fh.read().decode("utf-8"))
            if member == spec["nodes"]:
                nodes = data
            else:
                field = spec.get("tag_field")
                if field:      # tabler: {name: {tags: [...]}} -> {name: [tags]}
                    data = {k: (v.get(field) or []) for k, v in data.items() if isinstance(v, dict)}
                tags = data
    if nodes is None:
        raise IconError(f"{spec['package']} v{version} did not contain {spec['nodes']}")
    return {"set": set_name, "version": version, "license": lic, "viewBox": spec["viewBox"],
            "homepage": spec["homepage"], "icons": nodes, "tags": tags}


def search(loaded: dict, query: str, limit: int = 40) -> list[str]:
    q = (query or "").lower().strip()
    names = sorted(loaded["icons"])
    if not q:
        return names[:limit]
    hits = [n for n in names if q in n]
    if len(hits) < limit:
        for n in names:
            if n in hits:
                continue
            if any(q in str(t).lower() for t in loaded["tags"].get(n, [])):
                hits.append(n)
            if len(hits) >= limit:
                break
    return hits[:limit]


def catalog_text(set_name: str, loaded: dict, names: list[str], existing: dict | None = None) -> str:
    """Assemble the JS catalog, merging with whatever the target already had."""
    icons = dict((existing or {}).get("icons") or {})
    tags = dict((existing or {}).get("tags") or {})
    missing = []
    for name in names:
        if name in loaded["icons"]:
            icons[name] = loaded["icons"][name]
            if name in loaded["tags"]:
                tags[name] = loaded["tags"][name]
        else:
            missing.append(name)
    catalog = {
        "set": set_name,
        "version": loaded["version"],
        "license": loaded["license"],
        "source": loaded["homepage"],
        "viewBox": loaded["viewBox"],
        "icons": {k: icons[k] for k in sorted(icons)},
        "tags": {k: tags[k] for k in sorted(tags) if k in icons},
    }
    body = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    text = (
        "/* Icon catalog vendored by `vs.py icons add` - do not edit by hand.\n"
        f" * set: {catalog['set']} v{catalog['version']} - {catalog['license']} licence"
        f" ({catalog['source']})\n"
        " * Nodes are the package's own [[tag, attrs], ...] form, so one catalog serves both\n"
        " * DOM templates (Icons.el/svg) and canvas templates (Icons.draw/Path2D).\n"
        " */\n"
        f"window.ICONS = {body};\n"
    )
    return text, missing


def read_catalog(path: Path) -> dict:
    """Parse an existing catalog script back into data, so `add` never drops icons."""
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    marker = "window.ICONS"
    if marker not in raw:
        return {}
    try:
        return json.loads(raw[raw.index(marker) + len(marker):].lstrip().lstrip("=").strip().rstrip(";"))
    except json.JSONDecodeError as exc:
        raise IconError(f"{path} is not a catalog this tool wrote: {exc}") from exc


def default_catalog(set_name: str) -> Path:
    from . import runtime
    return runtime.SKILL_DIR / "assets" / "icons" / f"{set_name}.js"


def add(set_names: list[str], set_name: str = "lucide", catalog: Path | None = None,
        preset: str | None = None, refresh: bool = False, log=print) -> dict:
    """Vendor `set_names` (or a preset) into the catalog file, keeping the existing icons."""
    if preset:
        if preset not in PRESETS:
            raise IconError(f"unknown preset '{preset}' (have: {', '.join(sorted(PRESETS))})")
        set_names = list(dict.fromkeys(list(set_names) + PRESETS[preset]))
    if not set_names:
        raise IconError("nothing to add: pass icon names or --preset")
    loaded = load_set(set_name, refresh=refresh)
    target = Path(catalog) if catalog else default_catalog(set_name)
    existing = read_catalog(target)
    text, missing = catalog_text(set_name, loaded, set_names, existing)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    kept = json.loads(text[text.index("window.ICONS") + len("window.ICONS"):].lstrip().lstrip("=").strip().rstrip(";"))
    added = sorted(set(kept["icons"]) - set(existing.get("icons") or {}))
    log(f"  {target.name}: {len(kept['icons'])} icons "
        f"({len(added)} new), {len(text) / 1024:.1f} KB, {loaded['set']} v{loaded['version']} "
        f"{loaded['license']}")
    if missing:
        log(f"  not in {loaded['set']} v{loaded['version']}: {', '.join(missing)}")
    return {"catalog": str(target), "icons": len(kept["icons"]), "added": added,
            "missing": missing, "set": loaded["set"], "version": loaded["version"],
            "license": loaded["license"], "bytes": len(text),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S")}
