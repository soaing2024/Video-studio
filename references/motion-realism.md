# Motion prompts — how to get rich, physical movement instead of decoration

Three things live here: the motion spec to write before touching code, prompt blocks a user can
paste to demand better motion, and the concrete vocabulary that turns a feeling into numbers.

---

## 1. The motion spec (write this first, ~200 tokens)

Before writing any scene code, write these seven lines. If a line cannot be filled, the shot is
not designed yet.

```
主体动作：谁在动，动的是什么物理量（位移/面积/密度/温度…）
惯性：动作怎么开始、怎么停（预备 / 过冲 / 回稳的幅度与时长）
次级：主体动了之后，画面里还有什么被带着动（≥2 个）
环境：全片一直在走、且带面积的那件事（周期 ≠ 1s 的整数倍）
介质：这个主题的物理是什么（纸、蜂蜜、真空、磁场…），它如何抵抗动作
节奏：停留在哪、连续在哪（哪几秒是刻意的静止，写进 hold）
不完美：三处刻意的不对称 / 偏移 / 呼吸，避免"参数生成的整齐"
```

Worked example (a 2×2 payoff matrix explainer, 34s):

```
主体动作：四个数字与一把读取带；带子扫过矩阵时改变的是"被选中"的状态
惯性：带子进入用 ease-out-expo（快进软着陆），换行用 in-out-quart；极值被选中时过冲 15% 再回稳
次级：被排除的数字退成灰；括号跟着补上；页眉与字幕各滚一行
环境：白纸的呼吸（约 7 个灰阶、6.1s 周期）+ 纸面 7px 的 Lissajous 漂移，全片不停
介质：白纸与墨 —— 一切是"画上去"的：线自己画出来，括号后到，笔来回一次
节奏：每章开头 0.4s 密集，中段连续运动，章末 1.2s 只留环境动
不完美：纸上漂移不是整数周期；数字各自相位不同（±3.2px / ±2.4px）；过冲幅度每格差 0.01
```

---

## 2. Copy-ready prompt block (paste this into a video request)

> 用 `$video-studio` + `$motion-video-kit` 做一支 <时长> 的 <主题> 视频。
> 要求：先写 7 行"运动设定"再动手；每个章节必须有 1 个主体动作、≥2 个次级动作、1 个带面积的环境持续运动；全片不允许所有元素同时停住；位移一律走弧线而不是直线；每个到达点都要有过冲与回稳；至少三处刻意的不对称。
> 交付前先用一次批量测量确认：每秒画面变化 ≥ 2.2/255、目标帧都有内容、收尾帧不是空帧。渲染只跑一次。

That block is the whole difference between "more effects" and "physically believable": it forces
the spec, the secondary reactions, the ambient layer and the measurement.

---

## 3. Vocabulary — feeling to numbers

### Durations

| band | value | use |
| --- | --- | --- |
| instant | 80–100 ms | micro feedback |
| fast | 150–200 ms | state switch, highlight |
| standard | 280–350 ms | expand, move |
| medium | 400–500 ms | reveal a block |
| slow | 600–800 ms | entry of the protagonist |
| cinematic | 1000–1400 ms | cold open, curtain, a big transformation |
| ambient | continuous | background, breathing, drift |

### Easing (put these on elements, never on the timeline itself)

| name | character | implementation |
| --- | --- | --- |
| ease-out-expo | fast in, soft landing — **the default for reveals** | `x>=1?1:1-2^(-10x)` |
| ease-in-out-quart | symmetric, smooth — transformations, re-orientations | `x<.5?8x⁴:1-(-2x+2)⁴/2` |
| ease-in-out-quint | heavier symmetry — big moves, reversals | same with exponent 5 |
| ease-out-cubic | quick decel, mechanical | `1-(1-x)³` |
| ease-in-quart | slow start, hard exit — **departures only** | `x⁴` |
| spring | overshoot then settle — arrivals with weight | `Anim.spring(p, stiffness, damping)` |
| quantized | stepped — hand-drawn / stop-motion | `floor(t*RATE)/RATE`, RATE 11–15 |

Springs worth remembering: gentle 100/15, default 200/22, snappy 350/28, bouncy 200/10,
heavy 150/35, stiff 500/40.

### Stagger

dense grid 0.04s · list 0.07–0.08s · lines of text 0.08–0.1s · dramatic staircase 0.12–0.18s ·
one decisive action 0s. Stagger in reading order, and let the lightest element land last.

### Transform budget

cheap: `transform`, `opacity`. medium: `filter: blur`, `clip-path` on small areas. expensive:
`width/height/top/left` — animate `scaleX`/`scaleY` instead. never animate large `box-shadow` or a
`border-radius` mid-scale.

---

## 4. Realism hooks (each is a code move, not a vibe)

1. **Anticipation** — dip the opposite way before the move: `withAnticipation(p, 0.06)`.
2. **Overshoot and settle** — never land on the target directly; overshoot 8–18% and return.
3. **Follow-through** — a trailing element arrives 0.06–0.15s after its leader.
4. **Arcs** — displace along a curve, not a straight line: an offset perpendicular to the motion
   that peaks mid-travel.
5. **Secondary reactions** — when the subject moves, something else changes state because of it
   (a bracket closes, a neighbour dims, a counter ticks). Two per shot minimum.
6. **Nothing stops together** — stagger the settle times so the frame dies out in layers.
7. **Weight** — heavier things move slower and overshoot less; mass shows up in the decay.
8. **Asymmetry** — hand-place three offsets that are not mirrored. Perfect symmetry reads as
   generated.
9. **Ambient with area** — one large element that never stops, with a period that is not a whole
   number of seconds (7.3s, 6.1s). This is also what keeps the motion gate green.
10. **Breathing** — a global brightness or scale oscillation of a few grey levels, slow enough to
    be felt rather than seen.
11. **Medium** — decide how the medium resists: paper skids, honey lags, vacuum has no rebound,
    a magnetic field repels. Encode one friction rule and apply it everywhere.
12. **Quantized clock** — for hand-drawn or stop-motion, quantize the subject's time, not the
    camera's.

---

## 5. Anti-slop gates (motion)

- one easing and one duration across the whole piece;
- everything starting and stopping on the same beat;
- straight-line motion only, no arcs and no anticipation;
- perfectly centred, perfectly symmetric composition;
- motion that exists as decoration: floating particles, a scanning line, a glowing halo that
  encodes nothing;
- only thin strokes moving — measured as a still frame;
- a timeline that eases (time should be linear; only elements ease);
- an "effect" whose mechanism would work just as well on an unrelated topic.

---

## 6. Per-feeling patterns

**丝滑 / premium.** Reveals on ease-out-expo with 0.6–1.2s durations; transformations on
in-out-quart; one continuous ambient layer; holds at the moments when everything is in place;
never more than two things competing for attention; accents used only at state changes.

**物理真实.** Anticipation before every major move; overshoot then settle; secondary elements
late; arcs for all travel; weight differences visible in the decay; a ground plane or contact
that reacts (a shadow, a neighbouring mark).

**手绘 / 定格.** Quantize the subject's clock (RATE 11–15); keep the environment smooth so the
contrast reads as intentional; let lines be drawn by a travelling pen; a 1–2px irregularity per
stroke.

**科技冷机器.** ease-out-circ for arrivals (very fast decel); tiny overshoots (≤4%); uniform
stagger 0.04s; no arcs; monospaced or tabular figures; a single hairline as the only ambient.

**温暖自然.** Longer durations (0.8–1.4s), gentle springs, larger overshoot on soft matter,
breathing light, drift in two axes at incommensurate periods, warm off-white canvas.

---

## 7. From prompt clause to measurement

| clause | how it shows up in `verify` / QC |
| --- | --- |
| 环境持续带面积 | motion mean change per second ≥ 2.2/255 at lag 1s |
| 不是所有东西同时停 | per-frame motion profile has no long run of near-zero deltas |
| 次级动作 / 落点 | sampled money frames carry ink in the regions that must hold content |
| 停留是刻意的 | `hold` windows declared, so stillness is budgeted rather than accidental |
| 节奏有快有慢 | p90 of the per-second change clearly above the mean |

## 8. Changing one shot later

Ask for the beat, not the file: name the second-range and the intent ("换第 3 拍：让列扫描的
带子在转轴后先停 0.3s 再走"). Then patch only that block of the scene and re-`preview` a single
stamp. A re-render is not needed while only the scene changes if the segment cache key is
invalidated correctly — but re-check one still before spending the render.
