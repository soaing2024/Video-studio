"""Plan a single take before rendering it.

A project is one shot, so the plan is not a shot list - it is the **internal timeline of one take**:
what happens at 0-6s, 6-13s, and so on, what the viewer reads there, and how the frame *changes* at
each boundary (there are no cuts, so a boundary has to be a transformation inside the picture).

`compile` turns a validated plan into a renderable spec: one scene, one duration, and the hold
windows the plan declared.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import style as stylemod

PLATFORMS = {
    "youtube": {"width": 1920, "height": 1080, "fps": 30, "chars_per_second": 4.0},
    "bilibili": {"width": 1920, "height": 1080, "fps": 30, "chars_per_second": 4.0},
    "douyin": {"width": 1080, "height": 1920, "fps": 30, "chars_per_second": 4.6},
    "xiaohongshu": {"width": 1080, "height": 1440, "fps": 30, "chars_per_second": 4.6},
    "square": {"width": 1080, "height": 1080, "fps": 30, "chars_per_second": 4.2},
}

# How this chapter *changes the frame*. With no cuts these are the only transitions available;
# the first three are the workhorses (see references/formats.md).
DEVICES = ["移出 / 移入", "变换", "横扫", "推进 / 拉远", "并置对照", "尺度突变", "明暗呼吸", "定格"]

# A starting vocabulary per position in the take - prompts for inventing the chapter, not a menu.
DEVICE_POOL = {
    "open": ["单个巨大元素占满画面", "反直觉的物理动作", "一句断言 + 一个证物", "从异常状态开始"],
    "body": ["单一机制的慢速演示", "分层展开的结构图", "两个状态的前后对照", "把代价画出来"],
    "close": ["回到开场那一帧但变了", "一条命令 / 一个动作", "把结论压成一行", "留一个可执行的下一步"],
}

PURPOSE = {
    "open": "开场就给出结论，让人知道看完能拿到什么",
    "body": "推进一个要点，只讲一件事；信息块用替换而不是堆叠",
    "close": "回到开场那句话，给出行动指引",
}


def _role(index: int, total: int) -> str:
    if index == 0:
        return "open"
    if index >= total - 1:
        return "close"
    return "body"


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
    """Build a plan from narration lines: one line becomes one chapter of the take."""
    lines = [ln.strip() for ln in lines if ln.strip()]
    if not lines:
        raise ValueError("no narration lines supplied")
    spec_platform = PLATFORMS.get(platform, PLATFORMS["youtube"])
    cps = chars_per_second or spec_platform["chars_per_second"]
    sig = stylemod.make_signature(seed, topic=tone or name)

    cues, at = [], 0.0
    for i, text in enumerate(lines):
        role = _role(i, len(lines))
        pool = DEVICE_POOL[role]
        seconds = round(len(text) / cps + 1.0, 2)      # +1s for the lead-in and the tail
        cues.append({
            "index": i + 1,
            "role": role,
            "at": round(at, 2),
            "seconds": seconds,
            "intent": PURPOSE[role],
            "say": text,
            "on_screen": _key_phrase(text),
            "device": DEVICES[i % len(DEVICES)],       # how this chapter changes the frame
            "chapter": pool[i % len(pool)],            # what this chapter is made of
            "static": False,                           # True -> this stretch becomes a hold window
            "image_prompt": (f"{text} - {pool[i % len(pool)]}, 16:9 composition" if want_images else None),
            "image_size": image_size if want_images else None,
        })
        at += seconds

    total = round(at, 2)
    return {
        "version": 2,
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
        "premise": f"一个镜头讲清一件事，{len(cues)} 个内部章节，开场给结论，结尾回到结论。",
        "promise": "(填写：观众看完能得到什么)",
        "take": {"chapters": len(cues), "timeline": cues, "duration": total},
        "style": {"seed": sig["seed"], "signature": sig},
        "visual_plan": [stylemod.resolve_visual(sig, i, len(cues), {"data": {}})
                        for i in range(len(cues))],
        "assets": [{"id": f"c{i + 1:02d}", "prompt": c["image_prompt"], "size": c["image_size"],
                    "used_by": [f"c{i + 1:02d}"]} for i, c in enumerate(cues) if c["image_prompt"]],
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
            "每个章节只讲一件事，信息块用替换而不是堆叠",
            "相邻章节不重复使用同一个换场手法",
            "每一章至少有一处「全部到位」的画面（money frame）",
            "数字与年份要有出处，不用形容词替代",
            "结尾回到开场那句话",
            "不动的时间写进 hold，别让验收判成死拍",
        ],
    }


def skeleton(topic: str, *, beats: int = 6, duration: float = 60, platform: str = "youtube",
             want_images: bool = True, seed: int | None = None) -> dict:
    """A plan with the timeline slots filled in and the words left as TODO."""
    lines = [f"TODO：第 {i + 1} 章要说的一句话" for i in range(max(1, beats))]
    brief = from_script(lines, name=topic, duration=duration, platform=platform,
                        want_images=want_images, seed=seed)
    brief["premise"] = f"TODO：用一句话说清《{topic}》的核心结论"
    brief["promise"] = "TODO：观众看完能拿走什么"
    return brief


def _cues(brief: dict) -> list[dict]:
    return (brief.get("take") or {}).get("timeline") or brief.get("structure") or []


def holds_of(brief: dict) -> list[list[float]]:
    """Stretches the plan declared static, as [[start, end], ...] for the renderer."""
    out = []
    for cue in _cues(brief):
        if cue.get("static"):
            start = float(cue.get("at") or 0.0)
            out.append([round(start, 3), round(start + float(cue.get("seconds") or 0.0), 3)])
    return out


def validate(brief: dict) -> list[dict]:
    issues: list[dict] = []

    def add(level: str, where: str, message: str) -> None:
        issues.append({"level": level, "where": where, "message": message})

    cues = _cues(brief)
    if not cues:
        add("error", "take", "the take has no chapters")
        return issues

    target = float((brief.get("goal") or {}).get("duration_target") or 0)
    estimated = float((brief.get("goal") or {}).get("duration_estimated") or 0)

    for cue in cues:
        idx = cue.get("index")
        where = f"c{idx:02d}" if isinstance(idx, int) else "cue"
        for field in ("intent", "say", "on_screen", "device", "seconds"):
            if not cue.get(field):
                add("error", where, f"missing {field}")
        if str(cue.get("say", "")).startswith("TODO") or str(cue.get("on_screen", "")).startswith("TODO"):
            add("error", where, "placeholder text still present")
        if len(str(cue.get("on_screen", ""))) > 18:
            add("warning", where, "on-screen phrase is long for one line")
        if float(cue.get("seconds") or 0) > 20:
            add("warning", where, f"{cue['seconds']}s in one chapter without a frame change; "
                                  "split it or declare that stretch with `static`")

    for a, b in zip(cues, cues[1:]):
        if a.get("device") and a.get("device") == b.get("device"):
            add("error", f"{a.get('index')}->{b.get('index')}",
                f"two chapters in a row change the frame with '{a['device']}'; with no cuts that "
                "reads as a repeat")

    if len(cues) >= 4 and len({c.get("device") for c in cues}) < 3:
        add("warning", "take", "fewer than 3 distinct frame changes planned")

    if cues and float(cues[0].get("seconds") or 0) > 6:
        add("warning", "c01", "the first chapter is long for a hook; the conclusion should land by 3s")

    if target and estimated and abs(estimated - target) / target > 0.25:
        add("warning", "goal", f"planned {estimated}s vs target {target}s - add or cut a chapter")

    for key in ("premise", "promise"):
        value = str(brief.get(key, ""))
        if not value or value.startswith("TODO") or value.startswith("(填写"):
            add("error", key, "write this before rendering")
    return issues


def to_markdown(brief: dict) -> str:
    cues = _cues(brief)
    goal = brief.get("goal") or {}
    sig = (brief.get("style") or {}).get("signature") or {}
    size = goal.get("size", ["?", "?"])
    lines = [
        f"# {brief.get('name', 'untitled')}",
        "",
        f"- 平台 / 画幅：{goal.get('platform')} · {size[0]}x{size[1]} · {goal.get('fps')}fps",
        f"- 目标时长：{goal.get('duration_target')}s（估算 {goal.get('duration_estimated')}s）",
        f"- 观众：{goal.get('audience')}",
        f"- 调性：{goal.get('tone')}",
        "",
        f"**前提**：{brief.get('premise', '')}",
        f"**承诺**：{brief.get('promise', '')}",
        "",
        "## 一个镜头的内部时间轴",
        "",
        "| # | 时间 | 时长 | 目的 | 口播 | 屏上文字 | 换场手法 | 这一章是什么 | 静止 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in cues:
        lines.append(
            f"| {c.get('index')} | {c.get('at')}s | {c.get('seconds')}s | {c.get('intent')} | "
            f"{c.get('say')} | {c.get('on_screen')} | {c.get('device')} | {c.get('chapter')} | "
            f"{'是' if c.get('static') else ''} |")
    holds = holds_of(brief)
    lines += ["", "## 静止区间（渲染器复用一帧，成本与时长无关）", ""]
    lines.append("、".join(f"{a}s-{b}s" for a, b in holds) if holds
                 else "（未声明；不动的时间会被验收算成死拍）")
    lines += ["", "## 视觉方向", "",
              f"- 种子 {sig.get('seed')} · 配色 {sig.get('palette_name')} · 节奏 {sig.get('pacing')} "
              f"· 纹理 {sig.get('texture')}",
              f"- 构图词汇：{', '.join(sig.get('compositions', []))}",
              f"- 动态池：{', '.join(sig.get('motions', []))}",
              f"- 图片风格：{sig.get('image_style', '(未启用)')}"]
    plan = brief.get("visual_plan") or []
    if plan:
        lines += ["", "| 章节 | 构图 | 入场 | 强调色 |", "| --- | --- | --- | --- |"]
        for c, v in zip(cues, plan):
            lines.append(f"| {c.get('index')} | {v.get('layout')} | {v.get('motion')} | {v.get('accent')} |")
    lines += ["", "## 验收清单", ""] + [f"- [ ] {item}" for item in brief.get("checklist", [])]
    return "\n".join(lines) + "\n"


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(brief: dict, path: str | Path) -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    md = p.with_suffix(".md")
    md.write_text(to_markdown(brief), encoding="utf-8")
    return {"brief": str(p), "markdown": str(md)}


def compile_brief(brief: dict, *, music: str | None = None, subtitles: bool = True,
                 progress_bar: bool = True, force: bool = False) -> dict:
    """Turn a validated plan into one renderable take."""
    problems = [i for i in validate(brief) if i["level"] == "error"]
    # `--force` has to mean "compile anyway": re-validating here made the flag a no-op.
    if problems and not force:
        raise ValueError("plan is incomplete: " + "; ".join(f"{p['where']}: {p['message']}"
                                                            for p in problems))
    goal = brief.get("goal", {})
    sig = (brief.get("style") or {}).get("signature") or {}
    name = brief.get("name") or "video"
    cues = _cues(brief)

    # The scene receives the whole internal timeline as data: it places its own cues against these
    # timings, instead of being handed clips to play in order.
    timeline = [{"index": c.get("index"), "at": c.get("at"), "seconds": c.get("seconds"),
                 "role": c.get("role"), "intent": c.get("intent"), "on_screen": c.get("on_screen"),
                 "device": c.get("device"), "static": bool(c.get("static"))} for c in cues]

    spec = {
        "name": name,
        "video": {"width": goal["size"][0], "height": goal["size"][1],
                  "fps": goal.get("fps", 30), "crf": 20, "preset": "medium"},
        "render": {"jobs": 3, "crf": 12},
        "style": {"seed": sig.get("seed")},
        "duration": round(sum(float(c.get("seconds") or 0) for c in cues), 2),
        "scene": "scenes/take.html",
        "hold": holds_of(brief),
        "data": {"timeline": timeline, "premise": brief.get("premise"),
                 "promise": brief.get("promise")},
        "look": {"fade_in": 0.6, "fade_out": 0.9},
    }
    if progress_bar:
        spec["look"]["progress_bar"] = {"height": 4,
                                        "color": sig.get("colors", {}).get("accent", "#e0455f")}

    # Narration is one continuous line for the take, so `vs.py narrate` decides the total length.
    voice = (brief.get("audio") or {}).get("voice") or {}
    # One narration line per chapter, anchored to the chapter's own start time. `vs.py narrate`
    # measures each line, places it at that anchor, and rewrites this chapter table if the
    # reading runs long - so picture, voice and subtitles share one clock. The old shape joined
    # the whole script into a single line, which produced one take-long subtitle and a chapter
    # table that no longer described where the voice actually was.
    spec["narration"] = {
        "voice": None if voice.get("name") in (None, "", "auto") else voice["name"],
        "rate": int(voice.get("rate", 0)),
        "lead_in": float(voice.get("lead_in", 0.5)),
        "tail": float(voice.get("tail", 0.6)),
        "gap": 0.2,
        "min_duration": 3.0,
        "gain_db": float(voice.get("gain_db", 0)),
        "lines": [{"segment": "take",
                   "at": float(c.get("at") or 0.0),
                   "chapter": c.get("index"),
                   "text": str(c.get("say") or "").strip()}
                  for c in cues if str(c.get("say") or "").strip()],
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
                         "loudnorm": (brief.get("audio") or {}).get(
                             "loudnorm", {"i": -16, "tp": -1.5, "lra": 11})}
    if subtitles:
        spec["subtitles"] = {"style": "FontName=Microsoft YaHei,FontSize=24,"
                                      "OutlineColour=&H80000000,BorderStyle=1,Outline=2,"
                                      "Shadow=0,MarginV=40"}
    return spec


def plan_report(brief: dict) -> dict:
    """What the plan promises, in numbers - shown before rendering."""
    cues = _cues(brief)
    goal = brief.get("goal") or {}
    holds = holds_of(brief)
    held = sum(b - a for a, b in holds)
    total = float(goal.get("duration_estimated") or 0.0)
    return {
        "chapters": len(cues),
        "estimated_seconds": goal.get("duration_estimated"),
        "target_seconds": goal.get("duration_target"),
        "scene_to_write": "scenes/take.html",
        "devices_used": sorted({c.get("device") for c in cues if c.get("device")}),
        "hold_seconds": round(held, 2),
        "animated_seconds": round(max(0.0, total - held), 2),
        "images_to_generate": len(brief.get("assets") or []),
        "issues": validate(brief),
    }


def signature_of(brief: dict) -> dict:
    return (brief.get("style") or {}).get("signature") or {}


def digest(brief: dict) -> str:
    payload = json.dumps([[c.get("index"), c.get("device"), c.get("seconds"), c.get("say")]
                          for c in _cues(brief)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
