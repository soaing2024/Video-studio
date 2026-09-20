"""Freesound: find a sound effect, fetch it, and keep the licence paper trail.

The asset rule this skill enforces: automation may only reach sources whose licence is
confidently safe for the deliverable, so search defaults to CC0-only. Attribution (CC BY)
is an explicit opt-in that writes a CREDITS.md row; BY-SA, NonCommercial and Sampling+
are refused at fetch time unless `--allow-risky` says the piece is personal or the terms
are accepted on purpose.

    python scripts/vs.py sfx "whoosh transition" --top 8
    python scripts/vs.py sfx --get 12345 --out assets/sfx --name whoosh-01
    python scripts/vs.py sfx --token <APIKEY> --test

Token: VS_FREESOUND_TOKEN, or ~/.video-studio/freesound.json (written by --token).
Freesound serves original uploads over OAuth2 only; without VS_FREESOUND_ACCESS_TOKEN the
fetch takes the HQ preview MP3, which is what a mix needs anyway.

Nothing here runs during a render: the file lands in the project and the assembler mixes
it from disk like any other track.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:  # imported as lib.sfx by the CLI
    from . import fmt, probe, runtime
except ImportError:  # run directly, e.g. python scripts/lib/sfx.py "whoosh"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib import fmt, probe, runtime  # type: ignore

API = "https://freesound.org/apiv2"
APPLY_URL = "https://freesound.org/apiv2/apply/"
CONFIG_PATH = Path.home() / ".video-studio" / "freesound.json"
UA = "video-studio/1.0 (codex skill; offline render pipeline)"

SEARCH_FIELDS = ("id,name,tags,username,license,duration,previews,filesize,samplerate,"
                 "channels,type,description")
DETAIL_FIELDS = SEARCH_FIELDS + ",download"
SORTS = ("score", "rating_desc", "downloads_desc", "created_desc", "duration_asc",
         "duration_desc")

# Freesound reports a licence as a URL. cc0/by are the two this skill automates; by-sa
# (viral), by-nc (non-commercial) and Sampling+ are flagged and refused by default.
_LICENCES = {
    "cc0": {"label": "CC0", "commercial": True, "attribution": False, "auto": True},
    "by": {"label": "CC BY", "commercial": True, "attribution": True, "auto": True},
    "by-sa": {"label": "CC BY-SA", "commercial": True, "attribution": True, "auto": False},
    "by-nc": {"label": "CC BY-NC", "commercial": False, "attribution": True, "auto": False},
    "sampling+": {"label": "Sampling+", "commercial": False, "attribution": True, "auto": False},
    "unknown": {"label": "unknown", "commercial": False, "attribution": True, "auto": False},
}

_CREDITS_HEAD = ("| file | sound | author | licence | source | attribution |\n"
                 "| --- | --- | --- | --- | --- | --- |\n")


# --------------------------------------------------------------------------- licence
def classify(url: str) -> str:
    u = (url or "").lower()
    if "publicdomain/zero" in u or "cc0" in u:
        return "cc0"
    if "by-nc" in u or "noncommercial" in u:
        return "by-nc"
    if "sampling" in u:
        return "sampling+"
    if "by-sa" in u:
        return "by-sa"
    if "licenses/by" in u or "/by/" in u:
        return "by"
    return "unknown"


def licence(url: str) -> dict:
    key = classify(url)
    return {"id": key, **_LICENCES[key], "url": url or ""}


def keep(row: dict, mode: str, min_dur=None, max_dur=None) -> bool:
    """Client-side gate: the server filter is an optimisation, this is the truth."""
    if mode == "cc0" and row["licence"]["id"] != "cc0":
        return False
    if mode == "by" and row["licence"]["id"] not in ("cc0", "by"):
        return False
    if min_dur is not None and row["duration"] < float(min_dur):
        return False
    if max_dur is not None and row["duration"] > float(max_dur):
        return False
    return True


def build_filter(mode: str, min_dur=None, max_dur=None) -> str:
    parts = []
    if mode == "cc0":
        parts.append('license:"Creative Commons 0"')
    elif mode == "by":
        parts.append('license:("Creative Commons 0" OR "Attribution")')
    if min_dur is not None or max_dur is not None:
        lo = "0" if min_dur is None else f"{float(min_dur):g}"
        hi = "3600" if max_dur is None else f"{float(max_dur):g}"
        parts.append(f"duration:[{lo} TO {hi}]")
    return " ".join(parts)


# --------------------------------------------------------------------------- config
def load_config() -> dict:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_token(token: str = "", access_token: str | None = None) -> dict:
    cfg = load_config()
    if token:
        cfg["token"] = token.strip()
    if access_token:
        cfg["access_token"] = access_token.strip()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:  # keep the key readable only by this user
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    return cfg


def api_token() -> str:
    t = (os.environ.get("VS_FREESOUND_TOKEN") or load_config().get("token") or "").strip()
    if not t:
        raise fmt.fail("NO_FREESOUND_TOKEN", str(CONFIG_PATH), "a Freesound API key",
                       "not configured",
                       f"get a free key at {APPLY_URL}, then run: vs.py sfx --token <APIKEY>")
    return t


def oauth_token() -> str:
    return (os.environ.get("VS_FREESOUND_ACCESS_TOKEN")
            or load_config().get("access_token") or "").strip()


def mask(text: str) -> str:
    return re.sub(r"(token=)[^&\s]+", r"\1***", text or "")


# --------------------------------------------------------------------------- http
def _fetch_json(url: str, headers: dict | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].strip()
        raise fmt.fail("FREESOUND_HTTP", mask(url.split("?")[0]), "HTTP 200",
                       f"HTTP {e.code}: {body}",
                       "check the token (vs.py sfx --token <APIKEY>) and the query")
    except urllib.error.URLError as e:
        raise fmt.fail("FREESOUND_UNREACHABLE", "freesound.org", "a reachable Freesound API",
                       str(e.reason)[:200], "this is a fetch-time step; renders stay offline")


def _is_400(err) -> bool:
    return str(err.payload.get("error", {}).get("got", "")).startswith("HTTP 400")


def _download(url: str, dest: Path, headers: dict | None = None, timeout: int = 60,
              log=fmt.note) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, dest.open("wb") as f:
            shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        raise fmt.fail("FREESOUND_DOWNLOAD", mask(url.split("?")[0]), "HTTP 200",
                       f"HTTP {e.code}",
                       "the HQ preview needs no auth; original quality needs "
                       "VS_FREESOUND_ACCESS_TOKEN (OAuth2)")
    except urllib.error.URLError as e:
        raise fmt.fail("FREESOUND_UNREACHABLE", "freesound.org", "a reachable file",
                       str(e.reason)[:200], "check the network; the render itself stays offline")
    size = dest.stat().st_size if dest.is_file() else 0
    if size < 1024:
        raise fmt.fail("FREESOUND_DOWNLOAD", str(dest), "a non-empty audio file",
                       f"{size} bytes", "the API answered with an error page; re-check the id")
    log(f"  downloaded {dest.name} ({size // 1024} KB)")
    return str(dest)


# --------------------------------------------------------------------------- shapes
def _row(s: dict) -> dict:
    prev = s.get("previews") or {}
    return {
        "id": s.get("id"),
        "name": (s.get("name") or "").strip(),
        "duration": round(float(s.get("duration") or 0.0), 2),
        "licence": licence(s.get("license", "")),
        "username": s.get("username") or "",
        "tags": list(s.get("tags") or [])[:8],
        "samplerate": s.get("samplerate"),
        "channels": s.get("channels"),
        "filesize": s.get("filesize"),
        "type": s.get("type"),
        "preview_hq": prev.get("preview-hq-mp3") or prev.get("preview-hq-ogg"),
        "page": f"https://freesound.org/s/{s.get('id')}/",
        "description": " ".join((s.get("description") or "").split())[:220],
    }


def parse_id(value) -> int:
    m = re.search(r"(\d{3,})", str(value or ""))
    if not m:
        raise fmt.fail("BAD_SOUND_ID", str(value), "a Freesound sound id or URL", "no digits",
                       'pass the number from `vs.py sfx "<query>"`, e.g. --get 12345')
    return int(m.group(1))


def slug(text: str, fallback: str = "sfx") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:48] or fallback


# --------------------------------------------------------------------------- search
def search(query: str, mode: str = "cc0", top: int = 12, sort: str = "score",
           min_dur=None, max_dur=None, token: str | None = None, timeout: int = 30,
           log=fmt.note) -> dict:
    tok = token or api_token()
    params = {"query": query, "fields": SEARCH_FIELDS, "sort": sort,
              "page_size": min(150, max(int(top) * 3, int(top)))}
    flt = build_filter(mode, min_dur, max_dur)
    if flt:
        params["filter"] = flt
    url = f"{API}/search/text/?" + urllib.parse.urlencode({**params, "token": tok},
                                                          quote_via=urllib.parse.quote)
    try:
        doc = _fetch_json(url, timeout=timeout)
    except fmt.VsError as e:
        if not flt or not _is_400(e):
            raise
        log("  freesound rejected the server-side filter; filtering locally instead")
        params.pop("filter", None)
        url = f"{API}/search/text/?" + urllib.parse.urlencode({**params, "token": tok},
                                                              quote_via=urllib.parse.quote)
        doc = _fetch_json(url, timeout=timeout)
    rows = [_row(s) for s in doc.get("results", [])]
    kept = [r for r in rows if keep(r, mode, min_dur, max_dur)]
    return {"ok": True, "which": "sfx", "mode": "search", "query": query, "licence": mode,
            "sort": sort, "count": len(kept[:top]), "total_matches": doc.get("count"),
            "results": kept[:top], "request": mask(url)}


# --------------------------------------------------------------------------- fetch
def _to_wav(src: Path, dest: Path, log=fmt.note) -> str:
    ffmpeg = runtime.find_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-vn", "-ar", "48000", "-c:a", "pcm_s16le", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not dest.is_file():
        raise fmt.fail("TRANSCODE_FAILED", str(dest), "a 48 kHz wav",
                       (proc.stderr or "").strip()[-200:],
                       "run `vs.py doctor` to check the bundled ffmpeg")
    log(f"  wav 48k -> {dest.name} ({dest.stat().st_size // 1024} KB)")
    return str(dest)


def append_credits(path: Path, rel: str, row: dict) -> str:
    lic = row["licence"]
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if "| file | sound | author | licence |" not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n## Freesound\n\n" if text.strip() else "# CREDITS\n\n## Freesound\n\n"
        text += _CREDITS_HEAD
    need = "required" if lic["attribution"] else "not required (CC0)"
    text += (f"| `{rel}` | {row['name']} | {row['username'] or 'unknown'} | {lic['label']} | "
             f"https://freesound.org/s/{row['id']}/ | {need} |\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _default_credits(out_dir: Path) -> Path:
    return (out_dir.parent if out_dir.parent != Path(".") else Path(".")) / "CREDITS.md"


def fetch(sound_id, out="assets/sfx", name=None, quality="preview", kind="wav",
          credits=None, allow_risky=False, token=None, timeout=60, log=fmt.note) -> dict:
    sid = parse_id(sound_id)
    tok = token or api_token()
    url = f"{API}/sounds/{sid}/?" + urllib.parse.urlencode({"fields": DETAIL_FIELDS, "token": tok},
                                                          quote_via=urllib.parse.quote)
    row = _row(_fetch_json(url, timeout=30))
    lic = row["licence"]
    if not lic["auto"] and not allow_risky:
        raise fmt.fail("LICENCE_NOT_AUTO_SAFE", f"freesound.org/s/{sid}",
                       "CC0 or CC BY (what this skill automates)", lic["label"],
                       "pick another result, or pass --allow-risky if the piece is personal or "
                       "you accept the share-alike / non-commercial terms on purpose")
    if not lic["auto"]:
        log(f"  caution: {lic['label']} is outside the commercial-safe list - check the terms")

    access = oauth_token()
    if str(quality).lower() == "original":
        if not access:
            raise fmt.fail("NO_OAUTH_TOKEN", f"freesound.org/s/{sid}/download/",
                           "an OAuth2 access token for original quality",
                           "VS_FREESOUND_ACCESS_TOKEN is not set",
                           "Freesound serves original uploads over OAuth2 only; use "
                           "--quality preview (default), or store an access token")
        src_url = f"{API}/sounds/{sid}/download/"
        headers = {"Authorization": f"Bearer {access}"}
        suffix = ".bin"          # ffmpeg sniffs the container
    else:
        src_url = row["preview_hq"]
        if not src_url:
            raise fmt.fail("NO_PREVIEW", f"freesound.org/s/{sid}", "an HQ preview URL", "missing",
                           "this sound carries no preview; try --quality original with OAuth2")
        headers = {}
        suffix = Path(urllib.parse.urlparse(src_url).path).suffix or ".mp3"

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = slug(name or row["name"], f"sfx-{sid}")
    want_wav = str(kind).lower() == "wav"
    with tempfile.TemporaryDirectory(prefix="vs-sfx-") as tmp:
        raw = Path(tmp) / ("download" + suffix)
        _download(src_url, raw, headers=headers, timeout=timeout, log=log)
        if want_wav:
            dest = out_dir / (base + ".wav")
            _to_wav(raw, dest, log=log)
        else:
            dest = out_dir / (base + (suffix if suffix != ".bin" else ".mp3"))
            shutil.copy2(raw, dest)

    info = probe.any_file(runtime.find_ffmpeg(), str(dest))
    rel = os.path.relpath(dest, Path.cwd()).replace("\\", "/")
    credit = (f'"{row["name"]}" by {row["username"] or "unknown"} - {lic["label"]} - '
              f'https://freesound.org/s/{sid}/')
    credits_path = Path(credits) if credits else _default_credits(out_dir)
    append_credits(credits_path, rel, row)
    return {"ok": True, "which": "sfx", "mode": "get", "sound": row, "quality": quality,
            "file": str(dest), "rel": rel, "probe": info, "credit": credit,
            "credits_file": str(credits_path),
            "track": {"src": rel, "at": 0.0, "gain_db": 0}}


# --------------------------------------------------------------------------- entry
def run(query=None, get=None, token=None, access_token=None, test=False, mode="cc0",
        top=12, sort="score", min_dur=None, max_dur=None, out="assets/sfx", name=None,
        quality="preview", kind="wav", credits=None, allow_risky=False, dry_run=False,
        log=fmt.note) -> dict:
    if token or access_token:
        save_token(token or "", access_token)
        log(f"  token stored in {CONFIG_PATH}")
        if not query and not get and not test:
            return {"ok": True, "which": "sfx", "mode": "config", "config": str(CONFIG_PATH)}
    if get:
        return fetch(get, out=out, name=name, quality=quality, kind=kind, credits=credits,
                     allow_risky=allow_risky, token=token or None, log=log)
    q = query or ("whoosh" if test else None)
    if not q:
        raise fmt.fail("NO_QUERY", "vs.py sfx", "a search query or --get <id>", "neither given",
                       'try: vs.py sfx "whoosh transition" --top 8')
    if dry_run:
        return {"ok": True, "which": "sfx", "mode": "dry-run",
                "request": mask(_search_url(q, mode, top, sort, min_dur, max_dur, api_token()))}
    return search(q, mode=mode, top=top, sort=sort, min_dur=min_dur, max_dur=max_dur, log=log)


def _search_url(query, mode, top, sort, min_dur, max_dur, tok) -> str:
    params = {"query": query, "fields": SEARCH_FIELDS, "sort": sort,
              "page_size": min(150, max(int(top) * 3, int(top)))}
    flt = build_filter(mode, min_dur, max_dur)
    if flt:
        params["filter"] = flt
    return f"{API}/search/text/?" + urllib.parse.urlencode({**params, "token": tok},
                                                           quote_via=urllib.parse.quote)


def human(rep: dict) -> str:
    mode = rep.get("mode")
    if mode == "search":
        lines = [f'{rep["count"]} of {rep.get("total_matches", "?")} matches for '
                 f'"{rep["query"]}" ({rep["licence"]})']
        for r in rep["results"]:
            lines.append(f'  {str(r["id"]):>8}  {r["duration"]:>6.2f}s  '
                         f'{r["licence"]["label"]:<9} {r["name"][:48]:<48} by {r["username"]}')
        lines.append("  fetch one: vs.py sfx --get <id> --out assets/sfx --name <slug>")
        return "\n".join(lines)
    if mode == "get":
        loud = (rep["probe"].get("loudness") or {}).get("mean_volume")
        head = (f'{rep["file"]}  {rep["sound"]["duration"]:.2f}s  '
                f'{rep["sound"]["licence"]["label"]}')
        if loud is not None:
            head += f"  mean {loud} dB"
        return (head + f'\n  credit: {rep["credit"]}'
                + f'\n  track: {json.dumps(rep["track"], ensure_ascii=False)}'
                + f'\n  credits: {rep["credits_file"]}')
    if mode == "config":
        return f'freesound token stored: {rep["config"]}'
    if mode == "dry-run":
        return rep["request"]
    return json.dumps(rep, ensure_ascii=False)[:400]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sfx", description="search or fetch a Freesound effect")
    ap.add_argument("query", nargs="?")
    ap.add_argument("--get", metavar="ID|URL")
    ap.add_argument("--token", help="store a Freesound API key outside the repo")
    ap.add_argument("--access-token", help="store an OAuth2 token for original-quality downloads")
    ap.add_argument("--test", action="store_true", help="run a one-result search to verify the key")
    ap.add_argument("--licence", "--license", dest="mode", choices=("cc0", "by", "all"),
                    default="cc0", help="cc0 (default) | by (adds attribution) | all (flagged)")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--sort", default="score", choices=SORTS)
    ap.add_argument("--min-dur", type=float)
    ap.add_argument("--max-dur", type=float)
    ap.add_argument("--out", default="assets/sfx")
    ap.add_argument("--name")
    ap.add_argument("--quality", choices=("preview", "original"), default="preview")
    ap.add_argument("--kind", choices=("wav", "source"), default="wav")
    ap.add_argument("--credits", help="CREDITS.md to append to (default: <out>/../CREDITS.md)")
    ap.add_argument("--allow-risky", action="store_true",
                    help="accept BY-SA / NC / Sampling+ (not for a commercial deliverable)")
    ap.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    fmt.configure(json=a.json, verbose=a.verbose, quiet=a.quiet)
    rep = run(query=a.query, get=a.get, token=a.token, access_token=a.access_token, test=a.test,
              mode=a.mode, top=a.top, sort=a.sort, min_dur=a.min_dur, max_dur=a.max_dur,
              out=a.out, name=a.name, quality=a.quality, kind=a.kind, credits=a.credits,
              allow_risky=a.allow_risky, dry_run=a.dry_run)
    fmt.emit(rep, human=human(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
