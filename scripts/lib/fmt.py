"""Every command's output contract, in one place: structured results, structured errors,
one truncation policy, and a hash-keyed read cache.

P0-B. Why one module: an agent should never have to parse prose, and a failure should
carry enough to act on without another round trip.

    from . import fmt            # lib modules
    import fmt                   # scripts/ (sys.path already has scripts/)

    fmt.configure(json=args.json, verbose=args.verbose)
    fmt.emit({"ok": True, ...}, human="rendered 1 segment")   # JSON or one line
    fmt.note("frame 120/1800")                                # verbose only
    raise fmt.VsError(code="SCENE_NOT_READY", where="scene.html:218",
                      expected="window.__sceneReady === true",
                      got="seek() never signalled ready after 30s",
                      fix_hint="call Scene.ready() at the end of the scene, or check "
                               "for a page error with: vs.py preview --report")
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# ------------------------------------------------------------------ output contract

_STATE = {"json": False, "verbose": False, "quiet": False, "limit": 20, "emitted": 0}


def configure(json: bool = False, verbose: bool = False, quiet: bool = False, limit: int = 20) -> None:
    _STATE.update(json=bool(json), verbose=bool(verbose), quiet=bool(quiet),
                  limit=int(limit or 20))


def is_json() -> bool:
    return _STATE["json"]


def verbose() -> bool:
    return _STATE["verbose"]


def emit(obj: dict, human: str | None = None) -> None:
    """One machine-readable result, or one human line. Never both."""
    _STATE["emitted"] += 1
    if _STATE["json"]:
        # compact: pretty-printing costs ~15-25% of an agent's input tokens for nothing
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        return
    if human and not _STATE["quiet"]:
        print(human)
    elif not _STATE["quiet"]:
        ok = obj.get("ok")
        head = "ok" if ok else "failed"
        key = obj.get("what") or obj.get("output") or obj.get("video") or ""
        print(f"{head} {key}".rstrip())


def note(msg: str) -> None:
    """Progress detail: only when --verbose, so a normal run stays one line per step."""
    if _STATE["verbose"] and not _STATE["quiet"]:
        print(msg)


def warn(msg: str) -> None:
    if not _STATE["quiet"]:
        print(f"warn: {msg}", file=sys.stderr)


def truncate(text: str, head: int | None = None, tail: int | None = None) -> str:
    """Head+tail with a counted elision - the default for any third-party output.

    A 400-line Playwright stack trace costs tokens and answers nothing; the first and
    last lines are where the cause and the exit code live.
    """
    head = _STATE["limit"] if head is None else head
    tail = _STATE["limit"] if tail is None else tail
    lines = text.rstrip("\n").splitlines()
    if len(lines) <= head + tail + 1:
        return "\n".join(lines)
    omitted = len(lines) - head - tail
    return "\n".join(lines[:head] + [f"... [{omitted} lines omitted; --verbose for all] ..."]
                     + lines[-tail:])


# ------------------------------------------------------------------ error contract

class VsError(Exception):
    """A failure with a shape an agent can act on in one step."""

    def __init__(self, code: str, where: str, expected: str = "", got: str = "",
                 fix_hint: str = "", detail: str = ""):
        super().__init__(f"{code} @ {where}: {got or expected}")
        self.payload = {"ok": False, "error": {"code": code, "where": where,
                                              "expected": expected, "got": got,
                                              "fix_hint": fix_hint}}
        if detail:
            self.payload["error"]["detail"] = truncate(detail)


def fail(code: str, where: str, expected: str = "", got: str = "", fix_hint: str = "",
         detail: str = "") -> VsError:
    return VsError(code, where, expected, got, fix_hint, detail)


def report_error(err: VsError) -> int:
    if _STATE["json"]:
        sys.stdout.write(json.dumps(err.payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    else:
        e = err.payload["error"]
        print(f"error[{e['code']}] at {e['where']}", file=sys.stderr)
        if e.get("expected"):
            print(f"  expected: {e['expected']}", file=sys.stderr)
        if e.get("got"):
            print(f"  got:      {e['got']}", file=sys.stderr)
        if e.get("fix_hint"):
            print(f"  fix:      {e['fix_hint']}", file=sys.stderr)
        if e.get("detail") and _STATE["verbose"]:
            print(truncate(e["detail"]), file=sys.stderr)
    return 2


# ------------------------------------------------------------------ read cache

_MEM: dict[str, tuple[str, str]] = {}


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    st = path.stat()
    h.update(f"{st.st_size}:{int(st.st_mtime)}:".encode())
    h.update(path.read_bytes()[:1 << 20])
    return h.hexdigest()[:16]


def read_cached(path: str | Path, cache_dir: str | Path | None = None) -> str:
    """Read a file once per (path, content-hash) for the whole session.

    Cross-process by design: each `vs.py` call is a new process, so the cache lives on
    disk next to the build dir, not in memory.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        raise fail("FILE_NOT_FOUND", str(p), expected="an existing file", got="missing",
                   fix_hint="check the path; `vs.py plan <project>` lists every file a project needs")
    key = _hash(p)
    mem = _MEM.get(str(p))
    if mem and mem[0] == key:
        return mem[1]
    store = Path(cache_dir) if cache_dir else p.parent / ".vs_cache"
    blob = None
    if store:
        try:
            f = store / "reads" / f"{key}.txt"
            if f.is_file():
                blob = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            blob = None
    if blob is None:
        blob = p.read_text(encoding="utf-8", errors="replace")
        try:
            (store / "reads").mkdir(parents=True, exist_ok=True)
            (store / "reads" / f"{key}.txt").write_text(blob, encoding="utf-8")
        except OSError:
            pass
    _MEM[str(p)] = (key, blob)
    return blob


def diff_lines(path: str | Path, cache_dir: str | Path | None = None) -> dict:
    """Which line ranges changed since the last read - so a re-read can be a diff, not a file.

    Stores the previous body beside the read cache; returns the changed ranges plus the
    text of merely those ranges.
    """
    p = Path(path).expanduser()
    key = _hash(p)
    store = Path(cache_dir) if cache_dir else p.parent / ".vs_cache"
    prev_f = store / "prev" / f"{p.name}.prev"
    new = p.read_text(encoding="utf-8", errors="replace").splitlines()
    old = prev_f.read_text(encoding="utf-8", errors="replace").splitlines() if prev_f.is_file() else []
    ranges, buf = [], []
    n = max(len(old), len(new))
    i = 0
    while i < n:
        a = old[i] if i < len(old) else None
        b = new[i] if i < len(new) else None
        if a != b:
            j = i
            while j < n and ((old[j] if j < len(old) else None) != (new[j] if j < len(new) else None)):
                j += 1
            ranges.append([i + 1, j])
            buf += [f"{k + 1:>5}| {new[k]}" for k in range(i, min(j, len(new)))]
            i = j
        else:
            i += 1
    try:
        (store / "prev").mkdir(parents=True, exist_ok=True)
        prev_f.write_text("\n".join(new), encoding="utf-8")
    except OSError:
        pass
    return {"path": str(p), "hash": key, "changed": ranges,
            "lines": truncate("\n".join(buf), 40, 40) if buf else ""}


def clear(scope: str | Path | None = None) -> None:
    import shutil
    _MEM.clear()
    if scope:
        shutil.rmtree(Path(scope) / ".vs_cache", ignore_errors=True)


def env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")
