"""Choreography compiler: what actually happens inside a shot.

The failure this fixes is architectural. A shot built as "elements enter, then hold, then cut" has
exactly one state change, so most of its runtime is a still frame with nice typography - a slide.
Here every shot gets a beat sheet: a sequence of state changes spread across its full duration, each
one moving the material that is already on screen rather than fading something new in. The compiler
also reports the longest gap between changes, so "this shot sits still for 4 seconds" is caught at
planning time, before anything renders.
"""
from __future__ import annotations

import hashlib
import random

from . import spec as specmod

# Motion vocabulary. Each kind is a different way for the frame to change.
KINDS = ["build", "transform", "swap", "emphasis", "parallax_drift", "reveal", "count", "shuffle"]

BEAT_PERIOD = {"punch": 1.7, "build": 2.0, "steady": 2.6, "wave": 2.3, "calm": 3.4}
ENERGY_SCALE = {"punch": 1.45, "build": 1.15, "steady": 0.9, "wave": 1.0, "calm": 0.6}

# A change every this many seconds keeps a shot alive; beyond it the eye reads a still.
MAX_GAP_TARGET = 2.4


def _rng(sig: dict, index: int) -> random.Random:
    seed = f"{sig.get('seed', 0)}:{index}:choreo"
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))


def plan(sig: dict, index: int, duration: float, *, beats: list[float] | None = None,
         energy: float = 1.0, has_alt: bool = False, has_counter: bool = False) -> dict:
    rng = _rng(sig, index)
    pacing = sig.get("pacing", "steady")
    period = BEAT_PERIOD.get(pacing, 2.4) / max(0.5, energy)
    period = max(1.1, min(4.0, period))

    # Beat times: spread across the whole shot, always including a cold open and an exit beat.
    times = []
    t = rng.uniform(0.35, 0.7)
    while t < duration - 0.55:
        times.append(round(t, 3))
        t += period * rng.uniform(0.78, 1.24)

    # Musical accents, when there is music, take priority for the emphatic beats.
    if beats:
        merged = sorted({round(b, 3) for b in beats if 0.3 < b < duration - 0.4} | set(times))
        times = merged

    beats_out = [{"t": 0.0, "kind": "establish", "intensity": 1.0}]
    pool = list(KINDS)
    rng.shuffle(pool)
    for i, when in enumerate(times):
        kind = pool[i % len(pool)]
        if has_alt and kind == "swap":
            pass
        elif kind == "swap" and not has_alt:
            kind = "emphasis"
        if kind == "count" and not has_counter:
            kind = "transform"
        near_beat = bool(beats) and any(abs(when - b) < 0.12 for b in beats)
        intensity = round(min(1.6, (0.75 + 0.45 * rng.random()) * (1.25 if near_beat else 1.0)), 3)
        beats_out.append({"t": when, "kind": kind, "intensity": intensity,
                          "on_beat": near_beat})

    exit_at = round(max(0.3, duration - 0.42), 3)
    if exit_at > beats_out[-1]["t"] + 0.15:
        beats_out.append({"t": exit_at, "kind": "exit", "intensity": 0.8})

    swap = None
    if has_alt:
        swap_at = next((b["t"] for b in beats_out if b["kind"] == "swap"), None)
        if swap_at is None:
            swap_at = round(min(duration * 0.55, max(1.8, duration * 0.5)), 2)
            beats_out.append({"t": swap_at, "kind": "swap", "intensity": 1.0})
            beats_out.sort(key=lambda b: b["t"])
        swap = {"at": swap_at}

    gaps = [round(beats_out[i + 1]["t"] - beats_out[i]["t"], 3)
            for i in range(len(beats_out) - 1)]
    return {
        "beats": beats_out,
        "swap": swap,
        "states": len(beats_out),
        "max_gap": max(gaps) if gaps else duration,
        "gaps": gaps,
        "period": round(period, 2),
        "pattern": [b["kind"] for b in beats_out],
    }


def inject(spec: dict, log=print) -> dict:
    """Attach a beat sheet to every segment and report the stillness profile."""
    segments = spec.get("segments") or []
    if not segments:
        return {"applied": False}
    sig = (spec.get("style") or {}).get("signature") or {}
    starts = specmod.segment_starts(spec)
    times = []
    beats_cfg = spec.get("beats") or {}
    if isinstance(beats_cfg, dict):
        times = beats_cfg.get("times") or []
    elif isinstance(beats_cfg, list):
        times = beats_cfg

    rows = []
    worst = 0.0
    total_states = 0
    for i, seg in enumerate(segments):
        data = seg.setdefault("data", {})
        local_beats = []
        if times:
            start = starts.get(seg["id"], 0.0)
            local_beats = [t - start for t in times if start < t < start + float(seg["duration"])]
        motion_energy = ((data.get("motion") or {}).get("energy"))
        energy = float(motion_energy) if motion_energy else ENERGY_SCALE.get(sig.get("pacing", "steady"), 1.0)
        if data.get("still"):
            energy *= 0.5
        choreo = plan(sig, i, float(seg["duration"]), beats=local_beats, energy=energy,
                      has_alt=bool(data.get("titleAlt")), has_counter=bool(data.get("counter")))
        data["choreography"] = choreo
        total_states += choreo["states"]
        worst = max(worst, choreo["max_gap"])
        rows.append({"id": seg["id"], "seconds": seg["duration"], "states": choreo["states"],
                     "max_gap": choreo["max_gap"], "pattern": choreo["pattern"]})

    return {"applied": True, "segments": rows, "total_states": total_states,
            "worst_gap": round(worst, 3),
            "verdict": "alive" if worst <= MAX_GAP_TARGET else "too_still"}


def report(spec: dict) -> dict:
    rows = [{"id": s["id"], "seconds": s["duration"],
             "states": (s.get("data", {}).get("choreography") or {}).get("states"),
             "max_gap": (s.get("data", {}).get("choreography") or {}).get("max_gap")}
            for s in spec.get("segments", [])]
    rows = [r for r in rows if r["states"]]
    if not rows:
        return {}
    worst = max(r["max_gap"] for r in rows)
    return {
        "segments": rows,
        "total_state_changes": sum(r["states"] for r in rows),
        "worst_gap": round(worst, 3),
        "verdict": "alive" if worst <= MAX_GAP_TARGET else "too_still",
    }


# --------------------------------------------------------------- structure search
# One-shot generation has a high aesthetic variance, and a better prompt does not fix variance -
# a cheap search does. These candidates differ on the axes the viewer actually sees
# (macrostructure, generative operator), never on colour. PASSES is what "progressive
# composition" means here: structure first, surface last, each pass behind its own gate.

MACROSTRUCTURES = [
    {"id": "single-scene", "what": "一个空间，观众在里面移动", "motion": "场景本身就是动效"},
    {"id": "acts", "what": "3-5 段，每段一个主张 + 一张 money frame", "motion": "每幕一个机制"},
    {"id": "editorial", "what": "可读内容为主，动效只来 2-4 次", "motion": "段落之间的标点"},
    {"id": "index", "what": "可浏览的清单，每屏信息量小", "motion": "状态切换之间"},
    {"id": "instrument", "what": "一屏一个可玩的东西，没有「切」", "motion": "整个片子"},
]

OPERATORS = [
    {"id": "literal", "name": "直译物理",
     "ask": "把主题字面上的物理行为变成编排：它会被怎么压、怎么拉、怎么推？"},
    {"id": "invert", "name": "输入反转",
     "ask": "换掉「谁控制谁」：如果被推动的东西反过来推动画面呢？"},
    {"id": "remap", "name": "维度替换",
     "ask": "把一个量映射到没料到的维度：时间→色温？数量→字号？误差→抖动频率？"},
    {"id": "medium", "name": "介质想象",
     "ask": "把整支片子放进一种介质里：蜂蜜、真空、磁场，它会怎么动？"},
    {"id": "hybrid", "name": "杂交",
     "ask": "把两个不相关的原型焊在一起：翻页×重力？擦洗×音高？钟摆×打字？"},
    {"id": "break", "name": "破坏规则",
     "ask": "违反一个默认约定，并且物理化它：不是淡出，而是被抽走；不是从左生长，而是从中心塌陷？"},
]

LAYOUTS = ["fullbleed", "split", "editorial", "corner", "banner",
           "panel-left", "panel-right", "stacked", "framed"]

MOTION_DEVICES = ["移出 / 移入", "变换", "横扫", "推进 / 拉远", "并置对照", "尺度突变",
                  "明暗呼吸", "定格"]

# Progressive composition: five passes, each with a gate. Passes 3-5 are gated behind 1-2
# because surface polish cannot rescue a structure that never held.
PASSES = [
    {"pass": 1, "name": "blocking", "cn": "骨架",
     "do": "只放块面与主体位置：焦点在哪、占多大、视线怎么走。不写文字内容，不选颜色。",
     "gate": "缩到 160px 或眯眼看，结构仍然读得出来"},
    {"pass": 2, "name": "hierarchy", "cn": "层级",
     "do": "文字层级与字号跳跃（主 / 次 / 三级，跳跃 ≥ 2.5×），全部落在安全区内。",
     "gate": "第一眼落在主元素；去掉颜色层级依然成立"},
    {"pass": 3, "name": "colour", "cn": "色彩",
     "do": "三档色彩预算（底 / 主 / 强调），正文对比度 ≥ 8:1、次要 ≥ 4:1。",
     "gate": "转成灰度后层级没塌"},
    {"pass": 4, "name": "motion", "cn": "运动",
     "do": "七行动作规格、一个承担时间的元素、交接重叠 40-60%。",
     "gate": "beat_audit 通过；关掉动效静帧仍然成立"},
    {"pass": 5, "name": "finish", "cn": "质感",
     "do": "halation / grain / vignette / bloom 这类最后 5%。",
     "gate": "关掉 finish 结构不变差（它只加分，不救结构）"},
]

SEARCH_GATES = [
    {"gate": "静帧站得住", "how": "关掉动效，缩到 160px 还读得出来吗"},
    {"gate": "一句话讲得清", "how": "说不清这一拍在干什么，说明结构没想清"},
    {"gate": "不在查重表里", "how": "references/choreography.md §7 里没有它"},
    {"gate": "可实现", "how": "能用 seek(t) 的纯函数写出来"},
]


def candidates(intent: str, count: int = 3, seed: int | None = None,
               duration: float | None = None) -> dict:
    """Structurally different shots for one beat: a search, not a template.

    Deterministic for a given intent+seed, so a re-run gives the same candidates. The caller
    (an agent) sketches each candidate to pass 1 only, compares them at rehearsal scale, scores
    them on SEARCH_GATES and continues with the winner.
    """
    text = str(intent or "").strip()
    if not text:
        raise ValueError("an intent is required: one sentence, what the viewer must understand")
    n = max(2, min(int(count or 3), len(MACROSTRUCTURES)))
    base = int(seed) if seed is not None else int(
        hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(base)

    macros, operators = list(MACROSTRUCTURES), list(OPERATORS)
    layouts, devices = list(LAYOUTS), list(MOTION_DEVICES)
    for pool in (macros, operators, layouts, devices):
        rng.shuffle(pool)

    rows = []
    for i in range(n):
        macro, op = macros[i % len(macros)], operators[i % len(operators)]
        layout, device = layouts[i % len(layouts)], devices[i % len(devices)]
        axes = ["宏观结构", "生成算子"]
        if i and layout != layouts[0]:
            axes.append("版式")
        if i and device != devices[0]:
            axes.append("运动手段")
        rows.append({
            "id": "ABC"[i],
            "macrostructure": macro,
            "operator": op,
            "layout": layout,
            "motion": device,
            "differs_by": axes if i else ["baseline"],
            "ask": op["ask"],
        })
    return {
        "ok": True, "which": "shots", "intent": text, "count": len(rows), "seed": base,
        "duration": duration,
        "protocol": [
            "三个候选都只做到 pass 1（骨架）：不写内容、不选颜色、不做动效",
            "用 rehearse 或 scrub 横向比一次（廉价，不碰交付渲染）",
            "按闸门打分选一个；同分选元素更少、留白更大的那个",
            "选中的继续 pass 2-5；落选的写进 references/choreography.md §7 查重表",
        ],
        "gates": SEARCH_GATES,
        "passes": PASSES,
        "candidates": rows,
    }


def candidates_human(rep: dict) -> str:
    lines = [f'{rep["count"]} 个结构候选 · "{rep["intent"]}"']
    for c in rep["candidates"]:
        lines.append(f'  {c["id"]}  {c["macrostructure"]["id"]:<13} {c["operator"]["name"]:<5} '
                     f'{c["layout"]:<12} {c["motion"]}')
        lines.append(f'     差在：{" / ".join(c["differs_by"])}    {c["ask"]}')
    lines.append("  流程：" + "；".join(rep["protocol"]))
    lines.append("  闸门：" + "、".join(g["gate"] for g in rep["gates"]))
    return "\n".join(lines)
