"""Generate api_index.json + API.md from the code itself.

P0-A. The point is that an agent can drive this skill without reading 5,000 lines of
Python: the CLI surface is introspected from the live argparse parser (so it can never
drift), the library surface from the AST, and the browser runtime from the injected
globals. Regenerate after any change:

    python scripts/api_index.py            # writes api_index.json + API.md next to SKILL.md

Never hand-edit the outputs.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../scripts
SKILL = HERE.parent
sys.path.insert(0, str(HERE))

EFFECTS = {
    "writes": [r"write_text\(", r"write_bytes\(", r"open\([^)]*['\"][wa]", r"\.write\(", r"writeFileSync"],
    "reads": [r"read_text\(", r"json\.load", r"readFileSync"],
    "subprocess": [r"subprocess\.run", r"subprocess\.Popen", r"spawn\("],
    "network": [r"urlopen", r"requests\.", r"urllib"],
    "deletes": [r"unlink\(", r"os\.remove", r"shutil\.rmtree"],
    "mkdir": [r"mkdir"],
}

# Task-oriented examples: the part a generator cannot infer.
EXAMPLES = {
    "doctor": ["vs.py doctor --install-ffmpeg"],
    "preview": ["vs.py preview work/mine/project.json --at 2.75,7.9 --report",
                "vs.py preview work/mine/project.json --at 12.9 --report --ascii 90"],
    "scene_check": ["vs.py check work/mine/project.json --json"],
    "plan": ["vs.py plan work/mine/project.json --json"],
    "render": ["vs.py render work/mine/project.json --slices 8 --jobs 4 --gpu",
               "vs.py render work/mine/project.json --incremental --json"],
    "assemble": ["vs.py assemble work/mine/project.json --out outputs/film.mp4"],
    "verify": ["vs.py verify work/mine/project.json --video outputs/film.mp4 --json"],
    "run": ["vs.py run work/mine/project.json --slices 8 --jobs 4 --gpu --json"],
    "init": ["vs.py init work/mine --duration 30"],
    "patch": ["vs.py patch work/mine/project.json --set video.fps=60",
              "python scripts/apply_patch.py edits.json --json"],
    "audio": ["vs.py audio work/mine --cues cues.json",
              "vs.py audio work/mine --check"],
    "card": ["vs.py card work/mine --title 'Star it.' --cn '去点亮 Star'"],
    "api": ["python scripts/api_index.py", "vs.py api --task preview"],
}


def py_surface(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = node.args
        args = [x.arg for x in a.posonlyargs + a.args]
        ndef = len(a.defaults)
        for i, d in enumerate(a.defaults):
            args[len(args) - ndef + i] += "=" + ast.unparse(d)
        if a.vararg:
            args.append("*" + a.vararg.arg)
        args += [k.arg + "=..." for k in a.kwonlyargs]
        if a.kwarg:
            args.append("**" + a.kwarg.arg)
        ret = ast.unparse(node.returns) if node.returns else ""
        body = ast.unparse(node)
        fx = sorted(k for k, pats in EFFECTS.items() if any(re.search(p, body) for p in pats))
        doc = (ast.get_docstring(node) or "").strip().splitlines()
        out.append({"name": node.name, "args": args, "returns": ret,
                    "effects": [f for f in fx if f in ("writes", "subprocess", "network", "deletes")],
                    "doc": doc[0] if doc else ""})
    return out


def js_surface(path: Path) -> dict:
    src = path.read_text(encoding="utf-8", errors="replace")
    out = {}
    for key in ("Scene", "Anim", "Kit"):
        m = re.search(r"global\." + key + r"\s*=\s*\{(.*?)\n\s*\};", src, re.S)
        if not m:
            m = re.search(r"global\." + key + r"\s*=\s*\{([^}]*)\}", src, re.S)
        if not m:
            continue
        keys = [x.strip().split(":")[0].strip().split("(")[0].strip()
                for x in m.group(1).split(",") if x.strip() and ":" in x]
        out[key] = sorted(set(k for k in keys if k and re.match(r"^\w+$", k)))
    return out


def command_table() -> list[dict]:
    """Introspect the live argparse parser so the index tracks --help exactly."""
    import io
    import contextlib
    import vs
    parser = vs.build_parser()
    try:                       # the new command surface is injected at parse time
        vs._inject_common(parser)
    except Exception:
        pass
    rows = []
    for action in parser._actions:
        if not isinstance(action, getattr(__import__("argparse"), "SubParsersAction", object)):
            continue
        for name, sub in (action.choices or {}).items():
            args = []
            for a in sub._actions:
                if a.dest in ("help",) or (a.option_strings and a.dest == "func"):
                    continue
                args.append({
                    "flag": (a.option_strings[0] if a.option_strings else a.dest),
                    "aliases": a.option_strings[1:],
                    "type": getattr(a.type, "__name__", "bool" if isinstance(a, (__import__("argparse")._StoreTrueAction, __import__("argparse")._StoreFalseAction)) else "str"),
                    "default": None if a.default is None else (a.default if isinstance(a.default, (int, float, str, bool)) else str(a.default)),
                    "required": bool(getattr(a, "required", False)),
                    "help": (a.help or "").strip(),
                })
            rows.append({"name": name, "summary": (sub.description or "").strip().split("\n")[0],
                         "args": args, "examples": EXAMPLES.get(name, [])})
    return rows


def main() -> int:
    py = {}
    for p in sorted(list((SKILL / "scripts").glob("*.py")) + list((SKILL / "scripts" / "lib").glob("*.py"))):
        if p.name.startswith("__"):
            continue
        rel = str(p.relative_to(SKILL)).replace("\\", "/")
        fns = py_surface(p)
        if fns:
            py[rel] = fns

    js = {}
    for n in ("scene.js", "anim.js", "kit.js", "three-kit.js", "director.js"):
        p = SKILL / "assets" / "runtime" / n
        if p.is_file():
            s = js_surface(p)
            if s:
                js[n] = s
    js["render_segment.mjs"] = render_flags()

    index = {
        "skill": "video-studio",
        "entrypoint": "python scripts/vs.py <command> [options]",
        "contract": {
            "scene": "an .html file exposing window.seek(t) as a pure function of t, then window.__sceneReady = true",
            "project": "project.json: {name, video{width,height,fps,crf,preset}, duration, scene, libs[], data{}, audio{tracks[]}}",
            "one_write_one_render": "the deliverable is rendered once; slicing `--slices N` splits ONE export across processes, it is not a second render",
        },
        "commands": command_table(),
        "python": py,
        "browser_runtime": js,
        "notes": [
            "--json on every command prints exactly one compact JSON object; failures use "
            "{ok:false,error:{code,where,expected,got,fix_hint}}",
            "long tool output is truncated head/tail 20 lines by default; --verbose restores it",
            "read a scene's own source only as a last resort: api_index.json + API.md cover the "
            "CLI, the library functions and the injected Scene/Anim/Kit surface",
        ],
    }
    (SKILL / "api_index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_api_md(index)
    n_cmd = len(index["commands"])
    n_fn = sum(len(v) for v in py.values())
    print(f"api_index.json: {n_cmd} commands, {n_fn} functions, "
          f"{sum(len(v) for v in js.values())} runtime globals "
          f"({(SKILL / 'api_index.json').stat().st_size / 1024:.0f} KB)")
    print("API.md written")
    return 0


def render_flags() -> dict:
    """The renderer's own flags (it is a script, so there is no parser to introspect)."""
    src = (SKILL / "scripts" / "render_segment.mjs").read_text(encoding="utf-8", errors="replace")
    flags = sorted(set(re.findall(r'a\.(\w+)', src)))
    return {"flags": flags}


def write_api_md(index: dict) -> None:
    c = index["contract"]
    lines = [
        "# API.md — 不读源码就能用",
        "",
        "由 `python scripts/api_index.py` 生成，请勿手改。完整签名见 `api_index.json`。",
        "",
        "## 契约",
        "",
        f"- **场景**：{c['scene']}",
        f"- **项目**：{c['project']}",
        f"- **一次生成**：{c['one_write_one_render']}",
        "",
        "## 输出契约",
        "",
        "- 任何命令加 `--json` → 恰好一个紧凑 JSON 对象。",
        "- 失败形状：`{\"ok\":false,\"error\":{\"code\",\"where\",\"expected\",\"got\",\"fix_hint\"}}`。",
        "- 长输出默认头尾各 20 行，`--verbose` 全量；`--quiet` 只留错误。",
        "",
        "## 常见任务（复制即用）",
        "",
    ]
    for name, ex in EXAMPLES.items():
        cmd = next((x for x in index["commands"] if x["name"] == name), None)
        summary = cmd["summary"] if cmd else ""
        lines.append(f"### {name} — {summary}")
        lines.append("")
        lines.append("```bash")
        lines += ex
        lines.append("```")
        lines.append("")
    lines += [
        "## 场景里可用的注入 API",
        "",
    ]
    for lib, surface in index["browser_runtime"].items():
        if isinstance(surface, dict) and surface and all(isinstance(v, list) for v in surface.values()):
            for k, keys in surface.items():
                lines.append(f"- `{k}`: `{'`, `'.join(keys)}`")
        elif isinstance(surface, dict) and "flags" in surface:
            lines.append(f"- `{lib}` flags: `{'`, `--'.join(surface['flags'])}`")
    lines += [
        "",
        "## 命令一览",
        "",
        "| 命令 | 用途 | 主要参数 |",
        "| --- | --- | --- |",
    ]
    for cmd in index["commands"]:
        flags = ", ".join(f"`{a['flag']}`" for a in cmd["args"] if a["flag"].startswith("--") and a["flag"] != "--json")
        lines.append(f"| `{cmd['name']}` | {cmd['summary']} | {flags[:150]} |")
    (SKILL / "API.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
