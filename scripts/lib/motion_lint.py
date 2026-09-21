"""Motion representability: refuse to render a scene whose motion the delivery rate cannot carry.

The guarantee, not the detector
------------------------------
A finished-file audit can only tell you *after* a 25-minute render that a value was
unrepresentable. The invariant below is cheaper to enforce than to check, because it is a
property of the *source* against the *spec*:

    No value may change faster than the delivery frame rate can carry.
    Anything the eye is meant to read as motion needs >= 5 frames per cycle
    (<= fps/5 Hz = 2*pi*fps/5 rad/s). Any global exposure or opacity change
    needs an attack of >= 4 frames.

Why 5 frames per cycle: at 3 frames per cycle consecutive frames land on opposite extremes of
the oscillation, so a "shake" is read as a jump, not as a vibration - the sampled sequence is
not a different taste, it is a different phenomenon. A 61 rad/s carrier at 30 fps is 9.7 Hz =
3.09 frames per cycle: one frame is +14 px, the next is -14 px, and the eye sees a cut.

Two rules, both decidable on the source:
  * temporal_carrier_too_fast   - sin/cos of a time variable with a literal carrier above the band
  * impact_attack_too_short     - an envelope that ramps 0..1 in fewer than 4 frames

Deliberate strobing is still possible, but it has to be declared: put
`// vs:ok-fast-oscillator <reason>` on the line (or the line above), or list the rule in
`data.motion_exempt` with a `data.motion_reason`. Declared exemptions are reported as warnings,
so the decision stays visible instead of silent.

This module REPORTS; it never blocks. The guarantee lives in the runtime
(`assets/runtime/motion.js`), where every parameter is evaluated as a continuous path, so a
step cannot be expressed in the first place. What remains here is the honest audit of the
sources that go around that path: the numbers ride along with `check` and with the delivery
report, naming the line and the primitive that replaces it. A deliberate strobe declares
itself with `// vs:ok-fast-oscillator <reason>` and becomes a warning.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import fmt

SCAN_EXTS = {".html", ".htm", ".js", ".mjs", ".glsl", ".json"}
SKIP_DIRS = {"build", "node_modules", ".git", "work"}
MAX_BYTES = 2_000_000
ALLOW_RE = re.compile(r"vs:ok-fast-oscillator", re.I)

# Identifiers that mean "time in seconds" in this skill's scenes: the contract is window.seek(t).
TIME_VARS = r"(?:u?[tT]|time|uTime|iTime|now|elapsed|seconds|sec|clock)"
# Rule 2 accepts a bare time name too (t / uT / time). The only way to trip it is a divisor
# under 4 frames, and that is a step in every unit system plausibly in play: 0.05 of a second
# is 1.5 frames, while 0.05 of a normalised 0..1 progress is a different bug entirely.
TIME_DELTAS = (r"(?:d[tT]|delta|elapsed|age|since|[A-Za-z_]*Since|[A-Za-z_]*Delta|"
                r"u?[tT]|time|uTime|iTime|now|clock)")
CALL_RE = re.compile(r"(?:Math\.)?(sin|cos)\s*\(")
MIN_FRAMES_PER_CYCLE = 5.0
MIN_ATTACK_FRAMES = 4.0


def _resolve(spec: dict, value) -> Path:
    p = Path(str(value or ""))
    return p if p.is_absolute() else Path(str(spec.get("base_dir") or ".")) / p


def scene_sources(spec: dict) -> list[tuple[Path, str]]:
    """The scene file plus every sibling source it can pull in (acts, shaders, helpers).

    A scene is a file, not a name: what it pulls in lives next to it, which is exactly the
    set of sources whose motion has to be representable at the delivery rate.
    """
    scenes = [spec.get("scene")]
    for seg in spec.get("segments") or []:
        scenes.append(seg.get("scene"))
    roots: list[Path] = []
    for s in scenes:
        p = _resolve(spec, s)
        if p.is_file() and p.parent not in roots:
            roots.append(p.parent)
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in SCAN_EXTS or p in seen:
                continue
            # Skip directories BELOW the scene, not names anywhere in the absolute path: a
            # project that happens to live under a folder called `work` (as every scratch
            # project does) was being skipped in full, which made this check silently
            # vacuous - the worst possible failure mode for an accounting rule.
            try:
                rel_parts = p.relative_to(root).parts
            except ValueError:
                continue
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                out.append((p, p.read_text(encoding="utf-8", errors="replace")))
                seen.add(p)
            except OSError:
                continue
    return out


def _balanced(text: str, open_idx: int, limit: int = 400) -> str:
    """The argument text of a call whose '(' sits at open_idx."""
    depth = 0
    for i in range(open_idx, min(len(text), open_idx + limit)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i]
    return text[open_idx + 1:open_idx + limit]


def _exempt(lines: list[str], idx: int, rule: str, exempt_rules: set[str]) -> str | None:
    if rule in exempt_rules:
        return "declared in data.motion_exempt"
    for j in (idx, idx - 1):
        if 0 <= j < len(lines) and ALLOW_RE.search(lines[j]):
            return "vs:ok-fast-oscillator on the line"
    return None


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def lint(spec: dict) -> dict:
    """Structured findings for every motion value this delivery rate cannot represent."""
    fps = float((spec.get("video") or {}).get("fps") or 30)
    band_hz = fps / MIN_FRAMES_PER_CYCLE
    band_w = 2 * 3.141592653589793 * band_hz
    data = spec.get("data") or {}
    exempt_rules = set(data.get("motion_exempt") or [])
    problems: list[dict] = []
    warnings: list[dict] = []
    files = scene_sources(spec)

    for path, text in files:
        lines = text.split("\n")
        rel = path.name if path.parent.name == "scenes" else f"{path.parent.name}/{path.name}"
        # ---- rule 1: an oscillator carrier the frame rate cannot carry
        for m in CALL_RE.finditer(text):
            arg = _balanced(text, text.index("(", m.start()))
            for tm in re.finditer(TIME_VARS + r"\s*\*\s*([0-9]*\.?[0-9]+)", arg):
                coef = float(tm.group(1))
                hz = coef / (2 * 3.141592653589793)
                if hz <= band_hz + 1e-9:
                    continue
                ln = _line_of(text, m.start())
                frames = fps / max(hz, 1e-9)
                item = {"kind": "temporal_carrier_too_fast", "where": f"{rel}:{ln}",
                        "detail": f"{m.group(1)}(... {tm.group(0)}): {coef:g} rad/s = {hz:.2f} Hz "
                                  f"= {frames:.2f} frames per cycle at {fps:g} fps",
                        "fix_hint": f"keep carriers <= {band_hz:.1f} Hz (= {band_w:.0f} rad/s) for "
                                    f"{fps:g} fps, or use Motion.shake()/Motion.hit() which derive a "
                                    f"safe rate from the delivery fps; for deliberate strobing put "
                                    f"// vs:ok-fast-oscillator <reason> on the line"}
                (warnings if _exempt(lines, ln - 1, item["kind"], exempt_rules) else problems).append(item)
        # ---- rule 2: an envelope that ramps 0..1 in fewer than 4 frames
        for m in re.finditer(r"(?:Math\.)?(?:min|clamp|saturate)\s*\(\s*1(?:\.0)?\s*,", text):
            arg = _balanced(text, text.index("(", m.start()))
            for tm in re.finditer(TIME_DELTAS + r"\s*/\s*([0-9]*\.?[0-9]+)", arg):
                attack = float(tm.group(1))
                frames = attack * fps
                if frames >= MIN_ATTACK_FRAMES - 1e-9:
                    continue
                ln = _line_of(text, m.start())
                item = {"kind": "impact_attack_too_short", "where": f"{rel}:{ln}",
                        "detail": f"envelope ramps 0..1 in {attack:g}s = {frames:.1f} frame(s) at "
                                  f"{fps:g} fps ({tm.group(0)})",
                        "fix_hint": f"an exposure or opacity change with an attack under "
                                    f"{MIN_ATTACK_FRAMES:.0f} frames is a single-frame step however "
                                    f"intentional it feels: use >= {MIN_ATTACK_FRAMES/fps:.3f}s, or "
                                    f"Motion.hit() which builds the envelope for the delivery fps"}
                (warnings if _exempt(lines, ln - 1, item["kind"], exempt_rules) else problems).append(item)

    return {"ok": not problems, "fps": fps, "band_hz": round(band_hz, 2),
            "band_rad": round(band_w, 1), "min_attack_s": round(MIN_ATTACK_FRAMES / fps, 4),
            "files_scanned": [str(p) for p, _ in files],
            "problems": problems, "warnings": warnings}


def summary(report: dict) -> str:
    """One line for a report: what went around the runtime, and where."""
    if not report["problems"]:
        return (f"every oscillator is inside {report['band_hz']:.1f} Hz and every impact ramp "
                f"is at least {report['min_attack_s']:.3f}s "
                f"({len(report['files_scanned'])} source files scanned)")
    worst = report["problems"][0]
    more = "" if len(report["problems"]) == 1 else f" (+{len(report['problems']) - 1} more)"
    return (f"{len(report['problems'])} value(s) outside the {report['fps']:g} fps band: "
            f"{worst['where']} {worst['detail']}{more}")
