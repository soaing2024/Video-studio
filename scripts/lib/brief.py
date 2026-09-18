"""Pre-production: a complete, reviewable plan before a single frame is rendered.

The failure mode this exists to stop is jumping straight from "make me a video" to rendering,
which produces the same video every time. `brief` lays out the whole design - premise, acts,
per-beat intent, on-screen text versus spoken text, visual device, image prompts, pacing,
audio plan, and the anti-repetition plan - and `compile` refuses to turn an incomplete brief
into a project.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from . import style

PLATFORMS = {
    "youtube": {"width": 1920, "height": 1080, "fps": 30, "chars_per_second": 4.0},
    "bilibili": {"width": 1920, "height": 1080, "fps": 30, "chars_per_second": 4.0},
    "douyin": {"width": 1080, "height": 1920, "fps": 30, "chars_per_second": 4.6},
    "xiaohongshu": {"width": 1080, "height": 1440, "fps": 30, "chars_per_second": 4.6},
    "square": {"width": 1080, "height": 1080, "fps": 30, "chars_per_second": 4.2},
}

ACT_ORDER = ["hook", "context", "body", "proof", "turn", "close"]
TEMPLATE_POOL = {
    "hook":    ["kinetic", "stat"],
    "context": ["caption", "chart"],
    "body":    ["caption", "terminal", "chart"],
    "proof":   ["chart", "stat", "caption"],
    "turn":    ["quote", "caption"],
    "close":   ["kinetic", "quote"],
}
DEVICE = {
    "kinetic": ["大标题 + 数据条", "左文右图", "居中宣言", "角落留白", "整屏压图"],
    "caption": ["左文右图面板", "章节面板", "全幅配文", "上下分栏"],
    "chart": ["条形对比", "趋势条形", "排名条形"],
    "stat": ["大数字计数", "偏置大数字"],
    "quote": ["引文卡", "金句停顿"],
    "terminal": ["终端演示", "逐行代码"],
    "pixel": ["像素精灵", "像素标题"],
}
PURPOSE = {
    "hook": "3 秒内给出结论，让人知道看完能拿到什么",
    "context": "交代问题从哪来，给一个具体的时间或数字",
    "body": "展开一个要点，只讲一件事",
    "proof": "给出证据：数据、对比或案例",
    "turn": "转折或反面，避免全篇一个调子",
    "close": "回到开头那句话，给出行动指引",
}


def _act_for(index: int, total: int) -> str:
    if index == 0:
        return "hook"
    if index == total - 1:
        return "close"
    pos = index / max(1, total - 1)
    if pos < 0.35:
        return "context"
    if pos < 0.70:
        return "body"
    if pos < 0.88:
        return "proof"
    return "turn"


def _key_phrase(text: str, limit: int = 14) -> str:
    text = text.strip().rstrip("。！？!?.")
    for sep in ("，", ",", "、", "：", ":", " "):
        head = text.split(sep)[0]
        if 4 <= len(head) <= limit:
            return head
    return text[:limit]


def from_script(lines: list[str], *, name: str = "untitled", duration: float | None = None,
                platform: str = "youtube", tone: str = "", audience: str = "",
                want_images: bool = True, image_size: str = "1536x1024",
                seed: int | None = None, chars_per_second: float | None = None,
                music: str | None = None, voice: str | None = None) -> dict:
    """Build a full brief from narration lines (one line per beat)."""
    lines = [ln.strip() for ln in lines if ln.strip()]
    if not lines:
        raise ValueError("no narration lines supplied")
    spec_platform = PLATFORMS.get(platform, PLATFORMS["youtube"])
    cps = chars_per_second or spec_platform["chars_per_second"]
    sig = style.make_signature(seed, topic=tone or name)

    beats = []
    for i, text in enumerate(lines):
        act = _act_for(i, len(lines))
        pool = list(TEMPLATE_POOL[act])
        template = pool[i % len(pool)]
        device_pool = DEVICE.get(template, DEVICE["kinetic"])
        device = device_pool[i % len(device_pool)]
        seconds = round(len(text) / cps + 1.0, 2)     # +1s for lead-in and tail
        beats.append({
            "id": f"b{i + 1:02d}",
            "act": act,
            "intent": PURPOSE[act],
            "say": text,
            "on_screen": _key_phrase(text),
            "template": template,
            "visual_device": device,
            "seconds": seconds,
            "image_prompt": (f"{text} - {device}, 16:9 composition" if want_images else None),
            "image_size": image_size if want_images else None,
        })

    total = round(sum(b["seconds"] for b in beats), 2)
    brief = {
        "version": 1,
        "name": name,
        "goal": {
            "platform": platform,
            "size": [spec_platform["width"], spec_platform["height"]],
            "fps": spec_platform["fps"],
            "audience": audience or "(填写目标观众)",
            "tone": tone or "(填写调性：冷静专业 / 热烈 / 温和)",
            "duration_target": duration or total,
            "duration_estimated": total,
        },
        "premise": f"用 {len(beats)} 个节拍讲清一件事，开场给结论，结尾回到结论。",
        "promise": "(填写：观众看完能得到什么)",
        "structure": beats,
        "style": {"seed": sig["seed"], "signature": sig},
        "visual_plan": [style.resolve_visual(sig, i, len(beats),
                                             {"template": b["template"], "data": {}})
                        for i, b in enumerate(beats)],
        "assets": [{"id": b["id"], "prompt": b["image_prompt"], "size": b["image_size"],
                    "used_by": [b["id"]]} for b in beats if b["image_prompt"]],
        "audio": {
            "voice": {"engine": "sapi", "name": voice or "auto", "rate": 0,
                      "lead_in": 0.5, "tail": 0.6, "gain_db": 0},
            "music": {"src": music, "mood": "(填写：紧张 / 温暖 / 中性)", "gain_db": -22,
                      "duck": True, "fade_in": 1.5, "fade_out": 2.0},
            "loudnorm": {"i": -16, "tp": -1.5, "lra": 11},
        },
        "pacing": sig["pacing"],
        "images_enabled": bool(want_images),
        "checklist": [
            "开场 3 秒内出现结论",
            "每个节拍只讲一件事",
            "相邻节拍的画面设备不重复",
            "至少出现 3 种不同构图",
            "数字与年份要有出处，不用形容词替代",
            "结尾回到开场那句话",
            "字幕单行不超过 18 字",
            "配乐比人声低 15-20 dB",
        ],
    }
    return brief


def skeleton(topic: str, *, beats: int = 6, duration: float = 60, platform: str = "youtube",
             want_images: bool = True, seed: int | None = None) -> dict:
    """A brief with the structure decided and the writing left to the author (or the agent)."""
    lines = [f"TODO：第 {i + 1} 段要讲的内容（一句话，{int(duration / beats)} 秒左右）"
             for i in range(beats)]
    brief = from_script(lines, name=topic, duration=duration, platform=platform,
                        want_images=want_images, seed=seed)
    brief["premise"] = f"TODO：用一句话说清《{topic}》的核心结论"
    brief["promise"] = "TODO：观众看完能拿走什么"
    return brief


def validate(brief: dict) -> list[dict]:
    issues: list[dict] = []

    def add(level, where, message):
        issues.append({"level": level, "where": where, "message": message})

    beats = brief.get("structure") or []
    if not beats:
        add("error", "structure", "brief has no beats")
        return issues
    if beats[0].get("act") != "hook":
        add("warning", beats[0].get("id", "?"), "first beat should carry the hook")
    if beats[-1].get("act") != "close":
        add("warning", beats[-1].get("id", "?"), "last beat should close the loop")

    for b in beats:
        where = b.get("id", "?")
        for field in ("intent", "say", "on_screen", "template", "visual_device", "seconds"):
            if not b.get(field):
                add("error", where, f"missing {field}")
        if str(b.get("say", "")).startswith("TODO") or str(b.get("on_screen", "")).startswith("TODO"):
            add("error", where, "placeholder text still present")
        if b.get("visual_device") == "TODO":
            add("error", where, "visual device not chosen")
        if brief.get("images_enabled") and not b.get("image_prompt"):
            add("warning", where, "images are enabled but this beat has no image prompt")
        if len(str(b.get("on_screen", ""))) > 18:
            add("warning", where, "on-screen phrase is long for a subtitle line")

    for a, b in zip(beats, beats[1:]):
        if a.get("template") == b.get("template") and a.get("visual_device") == b.get("visual_device"):
            add("error", f"{a.get('id')}->{b.get('id')}",
                "adjacent beats use the same template and device")

    plan = brief.get("visual_plan") or []
    layouts = {p.get("layout") for p in plan}
    motions = {p.get("motion") for p in plan}
    if len(beats) >= 3 and len(layouts) < min(3, len(beats)):
        add("warning", "visual_plan", f"only {len(layouts)} distinct layouts planned")
    if len(beats) >= 4 and len(motions) < 3:
        add("warning", "visual_plan", f"only {len(motions)} distinct motion families planned")

    goal = brief.get("goal") or {}
    target = float(goal.get("duration_target") or 0)
    estimated = float(goal.get("duration_estimated") or 0)
    if target and estimated and abs(estimated - target) / target > 0.25:
        add("warning", "goal", f"estimated {estimated}s vs target {target}s — add or cut a beat")

    for key in ("premise", "promise"):
        if str(brief.get(key, "")).startswith("TODO") or not brief.get(key):
            add("error", key, "not written yet")

    return issues


def to_markdown(brief: dict) -> str:
    goal = brief.get("goal", {})
    lines = [f"# {brief.get('name', 'brief')}", "",
             f"- 平台 / 画幅：{goal.get('platform')} · {goal.get('size', ['?', '?'])[0]}x"
             f"{goal.get('size', ['?', '?'])[1]} · {goal.get('fps')}fps",
             f"- 目标时长：{goal.get('duration_target')}s（估算 {goal.get('duration_estimated')}s）",
             f"- 观众：{goal.get('audience')}", f"- 调性：{goal.get('tone')}", "",
             f"**前提**：{brief.get('premise', '')}", f"**承诺**：{brief.get('promise', '')}", "",
             "## 分镜", "",
             "| # | 段落 | 目的 | 说什么 | 屏上文字 | 模板 | 视觉手段 | 时长 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for b in brief.get("structure", []):
        lines.append(f"| {b['id']} | {b.get('act')} | {b.get('intent')} | {b.get('say')} | "
                     f"{b.get('on_screen')} | {b.get('template')} | {b.get('visual_device')} | "
                     f"{b.get('seconds')}s |")
    sig = (brief.get("style") or {}).get("signature") or {}
    lines += ["", "## 视觉方向", "",
              f"- 种子 {sig.get('seed')} · 配色 {sig.get('palette_name')} · 节奏 {sig.get('pacing')} "
              f"· 纹理 {sig.get('texture')}",
              f"- 构图池：{', '.join(sig.get('layouts', {}).get('kinetic', []))}",
              f"- 动态池：{', '.join(sig.get('motions', []))}",
              f"- 图片风格：{sig.get('image_style', '(未启用)')}"]
    plan = brief.get("visual_plan") or []
    if plan:
        lines += ["", "| 节拍 | 构图 | 入场 | 强调色 |", "| --- | --- | --- | --- |"]
        for b, p in zip(brief.get("structure", []), plan):
            lines.append(f"| {b['id']} | {p.get('layout')} | {p.get('motion')} | {p.get('accent')} |")
    if brief.get("assets"):
        lines += ["", "## 需要生成的图片", ""]
        for a in brief["assets"]:
            lines.append(f"- `{a['id']}` [{a.get('size')}] {a.get('prompt')}")
    lines += ["", "## 验收清单", ""] + [f"- [ ] {c}" for c in brief.get("checklist", [])]
    return "\n".join(lines) + "\n"


def load(path: str | Path) -> dict:
    p = Path(path).expanduser().resolve()
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".md", ".markdown"):
        raise ValueError("brief must be JSON; write .md only as a human-readable rendering")
    return json.loads(raw)


def save(brief: dict, path: str | Path) -> dict:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    md = p.with_suffix(".md")
    md.write_text(to_markdown(brief), encoding="utf-8")
    return {"brief": str(p), "markdown": str(md)}


def compile_brief(brief: dict, *, music: str | None = None, subtitles: bool = True,
                  progress_bar: bool = True) -> dict:
    """Turn a validated brief into a renderable project spec."""
    problems = [i for i in validate(brief) if i["level"] == "error"]
    if problems:
        raise ValueError("brief is incomplete: " + "; ".join(f"{p['where']}: {p['message']}"
                                                             for p in problems))
    goal = brief.get("goal", {})
    sig = (brief.get("style") or {}).get("signature") or {}
    name = brief.get("name") or "video"
    beats = brief["structure"]

    segments = []
    for b in beats:
        data = {
            "eyebrow": f"{b['act'].upper()} · {b['id']}",
            "title": b["on_screen"],
            "subtitle": b.get("subcaption") or "",
            "footer": brief.get("name", ""),
        }
        if b["template"] in ("caption", "kinetic"):
            data["caption"] = b.get("on_screen", "")
            data["rows"] = [{"value": b["on_screen"], "color": sig.get("colors", {}).get("accent")}]
        if b["template"] == "stat":
            data.update({"value": b.get("number", 100), "label": b["on_screen"],
                         "subtitle": b.get("on_screen", "")})
        if b["template"] == "quote":
            data.update({"quote": b.get("say", ""), "author": b.get("on_screen", "")})
        if b["template"] == "terminal":
            data.update({"windowTitle": b["id"],
                         "lines": [{"text": b.get("say", ""), "kind": "cmd"}]})
        if b["template"] == "chart":
            data.update({"title": b["on_screen"], "series": b.get("series") or [
                {"label": "A", "value": 60}, {"label": "B", "value": 100}]})

        seg = {"id": b["id"], "template": b["template"], "duration": "auto",
               "data": data, "assets": {}}
        if b.get("image_prompt"):
            seg["assets"]["subject"] = {"prompt": b["image_prompt"],
                                        "size": b.get("image_size") or "1536x1024"}
        if b.get("act") in ("context", "proof") and b["template"] in ("caption", "chart"):
            seg["data"]["still"] = False
        segments.append(seg)

    transitions = sig.get("transitions") or ["fade"]
    timeline = []
    for i, b in enumerate(beats):
        item = {"segment": b["id"]}
        if i:
            kind = "cut" if i % 3 else transitions[i % len(transitions)]
            item["transition"] = {"type": kind,
                                  "duration": 0.0 if kind == "cut" else 0.45}
        timeline.append(item)

    spec = {
        "name": name,
        "video": {"width": goal["size"][0], "height": goal["size"][1],
                  "fps": goal.get("fps", 30), "crf": 20, "preset": "medium"},
        "render": {"jobs": 3, "crf": 12},
        "style": {"seed": sig.get("seed")},
        "look": {"accent": sig.get("colors", {}).get("accent", "#e0455f"),
                 "fade_in": 0.6, "fade_out": 0.9},
        "segments": segments,
        "timeline": timeline,
    }
    if progress_bar:
        spec["look"]["progress_bar"] = {"height": 4, "color": sig.get("colors", {}).get("accent", "#e0455f")}

    voice = (brief.get("audio") or {}).get("voice") or {}
    spec["narration"] = {
        "voice": None if voice.get("name") in (None, "", "auto") else voice["name"],
        "rate": int(voice.get("rate", 0)),
        "lead_in": float(voice.get("lead_in", 0.5)),
        "tail": float(voice.get("tail", 0.6)),
        "gap": 0.2,
        "min_duration": 3.0,
        "gain_db": float(voice.get("gain_db", 0)),
        "lines": [{"segment": b["id"], "text": b["say"]} for b in beats],
    }

    tracks = []
    music_src = music or ((brief.get("audio") or {}).get("music") or {}).get("src")
    if music_src:
        m = brief.get("audio", {}).get("music", {})
        tracks.append({"src": music_src, "gain_db": m.get("gain_db", -22),
                       "fade_in": m.get("fade_in", 1.5), "fade_out": m.get("fade_out", 2.0),
                       "loop": True, "duck": bool(m.get("duck", True))})
    if tracks:
        spec["audio"] = {"tracks": tracks,
                         "duck": {"threshold": 0.03, "ratio": 8, "attack": 150, "release": 600},
                         "loudnorm": (brief.get("audio") or {}).get("loudnorm",
                                                                    {"i": -16, "tp": -1.5, "lra": 11})}
    if subtitles:
        spec["subtitles"] = {"style": "FontName=Microsoft YaHei,FontSize=24,"
                                      "OutlineColour=&H80000000,BorderStyle=1,Outline=2,"
                                      "Shadow=0,MarginV=40"}
    return spec


def plan_report(brief: dict) -> dict:
    """What the plan promises, in numbers - shown before rendering."""
    beats = brief.get("structure") or []
    goal = brief.get("goal") or {}
    return {
        "beats": len(beats),
        "estimated_seconds": goal.get("duration_estimated"),
        "target_seconds": goal.get("duration_target"),
        "templates_used": sorted({b.get("template") for b in beats}),
        "devices_used": sorted({b.get("visual_device") for b in beats}),
        "acts": [b.get("act") for b in beats],
        "images_to_generate": len(brief.get("assets") or []),
        "issues": validate(brief),
    }


def signature_of(brief: dict) -> dict:
    return (brief.get("style") or {}).get("signature") or {}


def digest(brief: dict) -> str:
    payload = json.dumps([[b.get("id"), b.get("template"), b.get("visual_device"),
                           b.get("say")] for b in brief.get("structure", [])],
                          ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
