"""Surgical edits that survive contact with real files.

P1-E. The external patch tools cost me ~20-30k tokens in one session: a payload that misses
by one line has to be re-sent whole, and some shapes (delete+add on the same path) are
refused outright. This tool does the opposite:

  * content-hash preconditions, so a stale edit fails loudly instead of corrupting a file
  * newline-agnostic matching (a file written on Windows is CRLF; your pattern is LF)
  * exact-occurrence counting: 0 matches -> "nearest match at line N", not a silent no-op
  * several edits in one submission, each independently checked
  * automatic syntax check (.py/.mjs/.js) + optional assertions after every patch
  * atomic write with a .bak, and full rollback of the whole batch if anything fails
  * explicit fallback: an edit that cannot match may carry the full replacement text

    python scripts/apply_patch.py edits.json [--json] [--root DIR] [--keep-on-fail]

edits.json:
{
  "edits": [
    {"path": "scripts/lib/render.py", "find": "old text", "replace": "new text", "count": 1,
     "expected_sha": "optional 64-hex of the file before the edit",
     "replace_file": "optional: full new content, used only if `find` never matches"},
    {"path": "scenes/x.html", "find": "<div id=\"a\">", "replace": "<div id=\"a\" class=\"p\">",
     "count": 1}
  ],
  "verify": ["python -c \"import ast;ast.parse(open('x.py').read())\""],
  "assert": [{"path": "scenes/x.html", "contains": "window.__sceneReady"}]
}
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import fmt  # noqa: E402


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dominant_newline(raw: str) -> str:
    return "\r\n" if raw.count("\r\n") >= raw.count("\n") - raw.count("\r\n") else "\n"


def nearest(raw: str, find: str) -> dict:
    """Where a missed pattern came closest - so the retry can be surgical instead of a rewrite."""
    lines = raw.splitlines()
    probe = [l for l in find.splitlines() if l.strip()][:3]
    best, best_i = 0.0, 0
    for i in range(len(lines)):
        for cand in probe:
            r = difflib.SequenceMatcher(None, cand.strip(), lines[i].strip()).ratio()
            if r > best:
                best, best_i = r, i + 1
    return {"line": best_i, "similarity": round(best, 2),
            "text": lines[best_i - 1][:120] if 0 < best_i <= len(lines) else ""}


def apply_edits(doc: dict, root: Path, keep_on_fail: bool) -> dict:
    edits = doc.get("edits") or []
    if not edits:
        raise fmt.fail("NO_EDITS", "edits.json", "at least one edit", "empty list",
                       "see the docstring of scripts/apply_patch.py")
    # same-path delete+add is refused by the other tool for good reason: it is a rewrite
    # wearing a patch costume. Detect it and say so instead of failing downstream.
    paths = [str(e.get("path")) for e in edits]
    if len(paths) != len(set(paths)):
        fmt.warn("several edits touch the same file; they are applied in order, "
                 "which is fine - but do NOT express a rewrite as delete+add")

    backups: dict[Path, str] = {}
    applied, degraded = [], []
    try:
        for i, e in enumerate(edits):
            p = Path(e["path"])
            if not p.is_absolute():
                p = root / p
            raw = p.read_text(encoding="utf-8")
            backups.setdefault(p, raw)
            want = e.get("count", 1)
            if e.get("expected_sha") and sha(raw) != e["expected_sha"]:
                raise fmt.fail("STALE_EDIT", str(p), f"sha256 {e['expected_sha'][:12]}...",
                               f"file is {sha(raw)[:12]}...",
                               "re-read the current text and rebuild this edit")
            find, repl, mode = e.get("find", ""), e.get("replace", ""), "find"
            new, n = raw.replace(find, repl, want if want else -1), raw.count(find)
            if n == 0 and e.get("replace_file") is not None:
                new, mode, n = e["replace_file"], "replace_file", 1
                degraded.append(str(p.name))
            nl = dominant_newline(raw)
            if mode == "find":
                if n == 0:
                    # newline-agnostic retry
                    norm = raw.replace("\r\n", "\n")
                    n2 = norm.count(find.replace("\r\n", "\n"))
                    if n2:
                        new = norm.replace(find.replace("\r\n", "\n"),
                                           repl.replace("\r\n", "\n"), want)
                        mode = "find(normalised)"
                    else:
                        raise fmt.fail("EDIT_NOT_FOUND", f"{p}:{i}",
                                       f"{want} occurrence(s) of the pattern",
                                       "0 matches",
                                       f"nearest match at line {nearest(raw, find)['line']} "
                                       f"({nearest(raw, find)['text']!r}); re-read that line or "
                                       f"supply replace_file with the whole new content",
                                       find[:400])
                elif want and n != want:
                    raise fmt.fail("EDIT_AMBIGUOUS", f"{p}:{i}",
                                   f"exactly {want} occurrence(s)", f"{n} matches",
                                   "narrow the pattern or set count to the real number",
                                   find[:400])
            if e.get("replace_file") is None:
                new = new if mode.startswith("find") else new
            tmp = p.with_suffix(p.suffix + ".vstmp")
            tmp.write_text(new, encoding="utf-8", newline=nl)
            shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
            os.replace(tmp, p)
            changed = sum(1 for a, b in zip(raw.splitlines(), new.splitlines()) if a != b) \
                + abs(len(raw.splitlines()) - len(new.splitlines()))
            applied.append({"path": str(p), "mode": mode, "occurrences": n,
                            "lines_changed": changed, "bytes": [len(raw.encode()), len(new.encode())]})

        results = verify(doc, root)
        bad = [r for r in results if not r["ok"]]
        if bad:
            raise fmt.fail("VERIFY_FAILED", bad[0]["cmd"], "exit 0", fmt.truncate(bad[0]["output"], 6, 6),
                           "the batch was rolled back; fix the edit and resubmit",
                           "\n".join(r["output"][-200:] for r in bad[:2]))
        # Syntax check inside the transaction: a file that no longer parses must be rolled back,
        # and this used to run in main() *after* apply_edits had already committed, so the
        # SYNTAX_FAILED message said "rolled back" while the broken file stayed on disk.
        syn = syntax_check([Path(a["path"]) if Path(a["path"]).is_absolute() else root / a["path"]
                           for a in applied])
        bad_syn = [s for s in syn if not s["ok"]]
        if bad_syn:
            raise fmt.fail("SYNTAX_FAILED", bad_syn[0]["path"], "the file parses",
                           bad_syn[0].get("detail", ""),
                           "the batch was rolled back; fix the replacement text and resubmit")
        return {"ok": True, "applied": applied, "degraded_to_full_rewrite": degraded,
                "verify": results, "syntax": syn, "rolled_back": False}
    except Exception as e:
        rolled = rollback(backups) if not keep_on_fail else []
        if isinstance(e, fmt.VsError):
            e.payload["error"]["rolled_back"] = rolled
            raise
        raise fmt.fail("PATCH_FAILED", str(e)[:80], "the batch applies cleanly", str(e)[:200],
                       "the batch was rolled back; re-read the file and retry",
                       str(e)) from None


def rollback(backups: dict[Path, str]) -> list[str]:
    done = []
    for p, raw in backups.items():
        try:
            p.write_text(raw, encoding="utf-8")
            done.append(str(p.name))
        except OSError:
            pass
    return done


def verify(doc: dict, root: Path) -> list[dict]:
    out = []
    for a in doc.get("assert", []):
        p = Path(a["path"]) if Path(a["path"]).is_absolute() else root / a["path"]
        text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        ok = a.get("contains", "") in text
        if a.get("not_contains"):
            ok = ok and a["not_contains"] not in text
        out.append({"cmd": f"assert {a['path']} contains {a.get('contains','')[:30]!r}", "ok": ok,
                    "output": "" if ok else f"missing in {p}"})
    for cmd in doc.get("verify", []):
        r = subprocess.run(cmd, shell=True, cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out.append({"cmd": cmd, "ok": r.returncode == 0,
                    "output": (r.stdout + r.stderr).strip()[-400:]})
    return out


def syntax_check(paths: list[Path]) -> list[dict]:
    """Cheap parse check so a broken file is caught here, not three commands later."""
    out = []
    for p in paths:
        if not p.is_file():
            continue
        if p.suffix == ".py":
            import ast
            try:
                ast.parse(p.read_text(encoding="utf-8", errors="replace"))
                out.append({"path": str(p), "ok": True})
            except SyntaxError as e:
                out.append({"path": str(p), "ok": False, "detail": f"line {e.lineno}: {e.msg}"})
        elif p.suffix in (".js", ".mjs"):
            r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
            out.append({"path": str(p), "ok": r.returncode == 0,
                        "detail": (r.stderr or "").strip()[-200:]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="hash-checked multi-edit patcher",
                                 epilog='example: python scripts/apply_patch.py edits.json --json')
    ap.add_argument("edits", help="JSON file (see module docstring) or - to read stdin")
    ap.add_argument("--root", default=".", help="base directory for relative paths")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--keep-on-fail", action="store_true", help="do not roll back")
    args = ap.parse_args(argv)
    fmt.configure(json=args.json, verbose=args.verbose)
    doc = json.loads(sys.stdin.read()) if args.edits == "-" else json.loads(Path(args.edits).read_text(encoding="utf-8"))
    root = Path(args.root).resolve()
    try:
        res = apply_edits(doc, root, args.keep_on_fail)
        fmt.emit({**res, "which": "apply_patch"},
                 human=f"patched {len(res['applied'])} edit(s) in "
                       f"{len(set(a['path'] for a in res['applied']))} file(s); "
                       f"{len(res['verify'])} check(s) passed"
                       + (f"; {len(res['degraded_to_full_rewrite'])} fell back to a full rewrite"
                          if res["degraded_to_full_rewrite"] else ""))
        return 0
    except fmt.VsError as e:
        return fmt.report_error(e)


if __name__ == "__main__":
    raise SystemExit(main())
