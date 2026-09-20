"""JSON with // comments: one stripper, shared by every reader of a project or brief.

There used to be three hand-rolled copies (spec.py, scaffold.py, and a defensive import inside
design_audit.py). They disagreed on blank lines and each fix had to be made in three places.

Blank lines are preserved so a JSONDecodeError still points at the line the author actually
wrote; the older versions collapsed them and reported a shifted line number.
"""
from __future__ import annotations


def strip_comments(text: str) -> str:
    """Drop // comments without touching strings (so a "//" key still works)."""
    out: list[str] = []
    for line in text.splitlines():
        buf: list[str] = []
        in_str = False
        escaped = False
        i = 0
        while i < len(line):
            ch = line[i]
            if in_str:
                buf.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                buf.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
            buf.append(ch)
            i += 1
        out.append("".join(buf).rstrip())
    return "\n".join(out)
