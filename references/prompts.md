# 高级技法提示词库

这份文件是给 AI 代理（也给人）用的**投喂模板**，解决一个具体问题：

> AI 做不出某个效果，往往不是能力问题，而是你要的东西**没有名字**。把技法命名、把约束写死、
> 把验收标准交出去，产出就会从"大概像"变成"就是它"。

三节分别覆盖：色彩与色阶（Chroma）、外接动效动画库、设计与分镜。每节都是
**先给名字 → 再给这个流水线里的硬约束 → 最后给可直接复制的提示词**。

> 这份文件是中文写的，因为它要对着中文教程生态（B 站那一批）说话；代码标识、库名、
> 参数名保持原文，不译。

---

## 0. 三条投喂原则

1. **给技术命名**。说"用 chroma.js 在 LCh 空间插值生成 7 阶色阶"，比说"颜色弄好看点"有效十倍。
   下面每一节都先给名字和出处。
2. **给硬约束**。这个流水线有三条不能破的规则，任何技法都必须落在里面：
   - **离线**：渲染过程不联网，外部库必须 vendored（随仓库走）。
   - **`seek(t)` 是纯函数**：不能用 CSS transition、不能 `requestAnimationFrame`、不能读
     `Date.now()`。画面只能是 `t` 的函数。
   - **帧精确**：同一个 `t` 必须得到同一帧，30fps 就是 30 个确定的时刻。
3. **给验收标准**。`verify` 测什么就把什么写进要求里——`duration`、`resolution`、`content`、
   `fade_in` / `fade_out`、`motion`、`palette` / `pixel_blocks`、`audio_present` /
   `audio_level`（跑 `vs.py verify` 会列出当前版本实际启用的那几项）。让 AI 跑 `verify`
   并贴报告，而不是说"看起来对"。

---

## 1. 色彩与色阶（Chroma）

### 1.1 先命名：做色彩的那几个库

| 库 | 版本 / 授权（已核对） | 干什么用 |
| --- | --- | --- |
| **chroma-js** | 3.2.0 · `BSD-3-Clause AND Apache-2.0` | 主力。`chroma.scale()` 生成色阶、`.classes()` 离散化、`chroma.brewer` 内置 ColorBrewer 色板、`.luminance()` / `.contrast()` 做明度与对比度校验。dist 里已确认 `brewer` / `lch` / `oklch` / `contrast` / `luminance` 都在 |
| colorjs.io | 0.7.1 · MIT | 严格按 CSS Color 4 规范实现，需要 Lab / LCh / OKLCH 精确转换时用它 |
| culori | 4.0.2 · MIT | 函数式色彩：插值、色差（ΔE）、色盲模拟 |
| d3-scale + d3-scale-chromatic | ISC | 离散/连续色阶与 ColorBrewer 直接可用，和图表坐标天然搭配 |

### 1.2 色阶的三种类型（选错是最常见的翻车）

| 类型 | 什么时候用 | 怎么构造 |
| --- | --- | --- |
| sequential 连续 | 单一维度递进：时间、体量、热度 | 保持色相，走**明度阶梯**；不要只改色相 |
| diverging 双向 | 有中点：增减、正负、高低 | 两端互补色相，中点接近背景色（这样"零"看起来像零） |
| qualitative 分类 | 互不相关的类别（并列的几类东西） | 等明度、等饱和度，只靠色相区分 |

### 1.3 "技术色阶"的核心是感知均匀

RGB 空间插值出来的中间色会发脏、发灰，因为 sRGB 的数值距离和人眼感受不成比例。
正确做法是在 **Lab / LCh / OKLCH** 空间插值：

```js
// 起点深蓝、终点青，在 LCh 空间插 7 阶
const steps = chroma.scale(["#0d1b2a", "#3cd3d4"]).mode("lch").colors(7);
```

两条硬指标（本项目的 `style.py` 就是按这个卡的）：

- **对比度**：正文对背景 ≥ 8:1，次要文字 ≥ 4:1（`chroma(a).contrast(b)`）。
- **明度阶梯**：相邻两阶的 `luminance()` 差要看得出来（≥ 0.04 左右），否则打印/小屏上会糊成一片。

色盲安全：不要只用红/绿区分两类数据，同时用明度或形状（本项目的 `chart` 系列色本来就在循环色相）。

### 1.4 落进这个 skill 的位置

| 想改的东西 | 写在哪 |
| --- | --- |
| 整片强调色 / 系列色 | `style.signature.colors`（种子生成，`visual_plan` 再逐拍把强调色循环分配） |
| 图表、数据条的配色 | `chart` 模板的 `series[].color`、`rows[].color` |
| 整片调色（饱和度/对比度） | `look.grade`（ffmpeg 侧） |
| 像素风预设 | `assets/palettes.json`（`pixel16` / `gameboy` / `mono`） |

> 注意：模板读的是被 `style.inject()` 写进段落的 `visual.colors`，**不是** `look.accent`。换配色请换种子
> 或改 `style.signature.colors`，别改 `look.accent`（对内置模板基本无效）。单拍想指定，
> 写 `data.visual`（layout / motion / density 等）。

### 1.5 注意：视频侧的"色阶"是另一件事

"色阶"在视频工程里还指**编码层面的电平范围**，和 chroma.js 无关，别混：

- **有限范围 / 全范围**：`-color_range tv`（16-235）vs `pc`（0-255）。全链路要统一，否则成片发灰或死黑。
- **色彩空间与 HDR→SDR**：ffmpeg 的 `zscale`、`tonemap`、`-color_primaries` / `-color_trc`。
- 这些都在 `scripts/lib/assemble.py` 的滤镜链里做，是 ffmpeg 的活，不需要任何前端库。
- `verify` 里的 `palette` 检查针对的是**限色**（像素风把颜色数压到 16），不是色域。

### 提示词模板

**P-C1 · 生成一套感知均匀的色阶**

```
用 chroma-js 生成一套 7 阶 sequential 色阶，起点 #0d1b2a、终点 #3cd3d4，在 LCh 空间插值
（chroma.scale([...]).mode('lch').colors(7)）。验收：相邻两阶 luminance() 差 ≥ 0.04，
最后一阶对背景 #101616 的对比度 ≥ 8:1。把结果写进 project.json 的 style.colors.series。
```

**P-C2 · 给"有正负"的数据做 diverging 色阶**

```
这组数据有正负（-40 到 +60），用 diverging 色阶：中点固定在 0 并且接近背景色 #101616，
两端用互补色相（#e0455f 与 #38bdf8），在 LCh 空间插值，共 7 阶。
给出 0 刻度对应哪一阶，并说明它在画面上如何与背景区分。
```

**P-C3 · 色阶自查（贴完再交付）**

```
按顺序检查我刚给的这套颜色：1) 逐对算 chroma.contrast，列出所有 < 4.5 的组合；
2) 算相邻阶 luminance 差，标出 < 0.04 的位置；3) 描述这套配色在红绿色盲下会怎么退化。
不要直接改颜色，先把问题列出来。
```

---

## 2. 外接动效动画库

### 2.1 先过这道门，再看库

能被这个流水线使用的库，必须同时满足四条：

1. **离线可用**：dist 文件随仓库走，渲染时不联网。
2. **能"给定时间求值"**：有 `seek(t)` / `goToAndStop(t)` / `position = t` 这类接口，
   而不是自己跑一个内部时钟。
3. **同一 `t` 得到同一帧**：不能用 `requestAnimationFrame`、`Date.now()`、CSS transition。
4. **首帧不依赖网络资源**：字体、图片、wasm 都要本地。

满足不了的库不是"不好"，而是**只能用在别的环节**（比如帮你做素材、导出 JSON），
不能出现在 `seek(t)` 里。

### 2.2 库清单（授权已核对，接口以官方文档为准）

| 库 | 版本 / 授权 | 帧精确怎么驱动 | 适合 | 注意 |
| --- | --- | --- | --- | --- |
| **lottie-web** | 5.13.0 · MIT | `anim.goToAndStop(t * fps, true)`（构建产物里已核实该接口） | AE 做的 MG 动效、复杂矢量动画（JSON / dotLottie） | 一个 JSON 就是一个镜头，体积可能几 MB；`renderer: 'svg'` 与 canvas 各有取舍 |
| **Rive** | @rive-app/canvas 2.42 · MIT | 状态机 + `advance*` 系列（类型定义里已核实） | 角色、图标、交互动效 | 需要 wasm 运行时；路径在 `file://` 下要显式指定；状态机要能确定性推进 |
| **Theatre.js** | @theatre/core 0.7.2 · Apache-2.0 | `sequence.position = t`（类型定义里已核实） | 时间轴式编排、可视化调参 | 需要 `.theatre` 状态 JSON |
| **GSAP** | 3.15 · 免费但**非 OSI 开源许可** | `gsap.timeline({ paused: true }).seek(t)`（dist 里已核实 `seek`） | 复杂时间轴、SVG、逐字动画 | 必须 `paused: true` 并禁掉 ticker；商用前读官方条款 |
| anime.js | 4.5.0 · MIT | v4 是 `createTimeline()` 那套（v3 与 v4 接口不兼容），seek 接口请以官方文档为准 | 轻量补间、SVG 描边 | 本文件未逐行核实其 seek 接口 |
| Motion | 4.x · MIT | 手动传入时间；基于 WAAPI 的部分**无法** seek | DOM 微交互 | 用在渲染链里要谨慎，WAAPI 部分天然不可帧精确 |
| **Three.js** | 0.186 · MIT | 自己调 `renderer.render(scene, camera)`，用 `t` 驱动所有变换 | 3D、伪 3D、视差 | 禁自转/禁 ticker |
| **PixiJS** | 8.21 · MIT | 自己调 `renderer.render(stage)` | 2D 精灵、粒子、像素风 | 同上 |
| SplitType | 0.3.4 · ISC | 纯拆分（把文字切成 span），本身没有时钟 | 逐字/逐行动画的前置步骤 | 拆完还要自己按 `t` 写状态 |
| **d3-scale / d3-shape** | ISC | 纯函数 | 坐标、比例尺、路径生成 | 没有动画，正好天然满足 `seek` |

**选型顺序**（建议照这个顺序问，能停在前面就别往后走）：
图标库列在 [libraries.md §2](libraries.md)：Lucide（ISC，2108 个）已经落盘，`Scene.icon()` 直接可用；其余几个能不能进这条流水线，那里逐条写了原因。


1. 这只是"一张图 + 一段文字"吗？→ 用自带模板 + chroma/d3 的纯函数，**不要引入库**。
2. 是别人做好的 MG 动效吗？→ Lottie（把 AE 导出的 JSON 直接播）。
3. 需要角色/交互动效吗？→ Rive。
4. 需要复杂时间轴编排吗？→ GSAP 或 Theatre.js。
5. 需要 3D 或大量精灵吗？→ Three.js / PixiJS。

### 2.3 离线 vendor 流程

一条命令就能做完（内部就是下面那段 `npm pack`）：

```powershell
python vs.py libs                     # 看已落盘 / 可安装的库
python vs.py libs --install <名字>    # 装一次；渲染期永远不联网
```

手工流程（装不在注册表里的库时用）：

```
mkdir assets/lib/<name>
npm pack <pkg>@<version>            # 或者从 unpkg 直接取 dist 文件
tar -xzf <pkg>-<version>.tgz
cp package/dist/*.min.js assets/lib/<name>/
cp package/LICENSE      assets/lib/<name>/LICENSE     # 授权说明必须跟着走
```

模板里引本地文件：

```html
<script src="../lib/chroma-js/chroma.min.js"></script>
```

**为什么放 `assets/lib/` 而不是 `node_modules`**：这个技能要求离线可跑、目录可移植，
`node_modules` 既进不了 git，也不该进。

### 2.4 踩过的坑（这个项目自己的血泪史）

- **CSS `mask-image` 在 `file://` 下会被当成跨域**，遮罩整片失效（元素直接消失）。改用 canvas 的
  `source-atop` 合成。
- **任何 `requestAnimationFrame` 都会破坏帧精确**，包括库内部自带的 ticker。
- **wasm 与 worker 的路径**在 `file://` 下要用绝对或相对文件路径仔细核对（Rive 属于这一类）。
- **字体不要联网**：中日韩文字必须显式写字体栈，否则回退字体一换，行盒高度和排版全变。
- **体积与授权**：vendored 的库要在 `LICENSE` 里注明来源与许可；GSAP 这种"免费但非开源"的，
  商用交付前确认条款。
- **别用库自带的"自动播放"**：所有动画都应该是"我给它 `t`，它给我这一帧"。

### 提示词模板

**P-M1 · 把一段 AE 动效搬进来**

```
我有一段 AE 做的动效，导出了 data.json（Lottie）。请：1) 在模板里离线加载 lottie-web
（从 assets/lib/lottie-web/ 引，不要用 CDN）；2) 在 seek(t) 里用 goToAndStop(t * fps, true)
驱动，frame 用整数帧，保证同一 t 同一帧；3) 不要调用 play()，不要留 rAF；
4) 告诉我这个 JSON 的帧率和时长，因为段落的 duration 要和它对齐（或者明确裁到哪一帧结束）。
```

**P-M2 · 用 GSAP 做逐字动画，但保持可 seek**

```
用 GSAP 做一段逐字入场：gsap.timeline({ paused: true, repeat: 0 })，每个字 stagger 0.04s，
从 opacity 0 / y 18 到 1 / 0，ease power3.out。
然后在 window.seek(t) 里只调 tl.seek(t) —— 不允许 gsap.ticker、不允许自动播放。
把字符拆分用 SplitType 预处理。最后说明怎么保证同一 t 得到同一帧。
```

**P-M3 · 让 AI 自己判断该不该引入库**

```
这一拍要的效果是「数据条依次生长并在第 3 秒互相换位」。请先回答三个问题再动手：
1) 用项目自带的模板 + 纯函数（按 t 直接算宽度）能不能做？能的话就不引入任何库；
2) 如果不能，现成格式（Lottie / Rive）里有没有更省事的路径？
3) 引入的库体积、授权、离线可行性如何？
按 1→2→3 的顺序给出结论，选中最靠前的那条。
```

---

## 3. 设计与分镜

### 3.1 分镜表 = 这个项目的 `brief`，字段一一对应

| 分镜表里的列 | 本项目字段 | 说明 |
| --- | --- | --- |
| 段落号 | `id` / `act` | `act` 决定它在结构里的位置（hook / context / body / proof / turn / close） |
| 这一拍要干什么 | `intent` | **必填**，空着 `compile` 直接报错 |
| 口播 | `say` | 没有配音时它就是这一拍要传达的意思 |
| 屏上文字 | `on_screen` | 和口播**不是一回事**，必须更短（单行 ≤ 18 字） |
| 画面 | `scene` + `visual_device` | 这一拍的场景文件 + 视觉手段 |
| 时长 | `seconds` | 短视频 3-6s，解说 8-20s，长视频 15-45s |
| 构图 / 入场 | `visual_plan` | 种子决定，可单拍覆盖（`data.visual`） |

### 3.2 镜头语言清单（写提示词时直接用这些词）

- **景别**：建立镜头 / 中景 / 特写 / 大特写 / 过肩
- **角度**：平视 / 俯拍 / 仰拍 / 顶拍
- **运动**：推、拉、摇、移、跟、升降 —— 本项目用 `motion.camera_track` 表达，
  相机会一路走，不会停在原地
- **转场语法**：硬切 = 同一场景内推进；淡化 = 时间流逝；黑场 = 章节切换。
  **不要每拍都加转场**，那会让节奏变糊（本项目 `plan` 会给出转场种类数）

### 3.3 构图清单（和 layout 池对齐）

- `kinetic`：`center` / `split` / `editorial` / `corner` / `fullbleed` / `banner`
- `caption`：`panel-left` / `panel-right` / `stacked` / `framed` / `full-bleed`
- 铁律：一屏只有一个视觉焦点；文字不超过两行；重要信息放在安全区内
  （竖屏顶部 12%、底部 20% 会被平台界面压住）
- **相邻两拍必须换构图**：`plan` 的 `adjacent_layout_repeats` 必须为 0

### 3.4 色彩脚本与视觉母题

- **色彩脚本（color script）**：先给整片定 3-5 个色相节点，再往每一拍落色，
  这样观众会感到"情绪在走"，而不是每拍各自好看。
- **视觉母题**：让同一个图形元素（圆环、网格、扫描线、某个图标）在几拍里重复出现，
  片子立刻有"这是一支片"的整体感。本项目里最省事的载体是 `visual.texture`
  （种子给出 `none` / `grain` / `dots` / `scanlines` / `grid`）与全局的 `look.progress_bar`。

### 3.5 节奏

- 钩子在 3 秒内出现（`plan` 会对"首拍不是钩子"给警告）
- 每 4-6 个内部章节安排一次"呼吸"：把画面压到静止（写进 `hold`）、金句卡、或一次明暗呼吸
- 长视频的策略是**只让该动的地方动**：把不动的时间写进 `hold`，那几秒的成本就与时长无关

### 提示词模板

**P-S1 · 把一段脚本拆成 10 拍的分镜表**

```
把下面这段脚本拆成 10 拍的分镜表，输出成表格，每行包含：
段号 / act / 这一拍的目的(intent) / 口播(say) / 屏上文字(on_screen，单行 ≤18 字) /
模板 / 视觉手段 / 时长(秒)。
要求：钩子在第 1 拍且 3 秒内给结论；相邻两拍不得使用同一模板 + 同一视觉手段；
至少出现 3 种不同构图；总时长 50 秒左右。脚本：<粘贴>
```

**P-S2 · 给整片定色彩脚本**

```
这支片子分三幕：开场（问题）→ 中段（方法）→ 收尾（结论）。
请给一个色彩脚本：三幕各自主色相与明度走向，说明情绪如何过渡（例如冷→中性→暖），
并给出每一幕的 accent 十六进制值。要求相邻两幕的色相差 ≥ 40°，且正文对比度 ≥ 8:1。
按 chroma-js 的写法给出可执行代码。
```

**P-S3 · 审一遍分镜哪里会"看不懂"**

```
这是我已有的分镜表。请扮演第一次看这支片子的观众，逐拍回答：
1) 这一拍我能不能在 2 秒内看懂它在说什么？
2) 屏上文字和画面是不是在讲同一件事（有没有各说各话）？
3) 相邻两拍的视觉跳跃会不会让我以为出错了？
只列出真正会让人困惑的地方，按严重程度排序，最后给出最小修改建议。
```

---

## 4. 组合拳：一次完整请求

把三节拼起来，一次说清，AI 的输出质量会明显不同：

```
用 video-studio 做一支 50 秒的竖屏解说（1080×1920，无配音）：

1. 分镜：按 references/prompts.md §3.1 出分镜表，10 个内部章节，每章一次画面重构（不切镜头），
   钩子在 3 秒内，相邻两拍的模板与手段不得重复；总时长 50 秒。
2. 色彩：用 chroma-js 在 LCh 空间生成 7 阶 sequential 色阶（§1.3），
   正文对比度 ≥ 8:1；数据两拍用 d3-scale 出坐标，不要手算像素。
3. 动效：优先用自带模板；只有当某拍必须"复刻一段现成 MG"时才引入 Lottie，
   并保证 goToAndStop(t*fps, true) 驱动、离线加载（§2）。
4. 时长：整片一个 `duration`；不动的时间写进 `hold`，写清哪几秒复用了同一帧。
5. 交付：先 plan 看预算和多样性，再 run，最后把 verify 的报告贴出来。
   任何一项不过就改配置，不要改验收标准。
```

---

## 5. 与本项目硬规则的对照表

写完提示词后，拿这张表过一遍，能挡住大部分"看起来能用、跑起来翻车"的方案：

| 硬规则 | 违反会怎样 | 怎么自检 |
| --- | --- | --- |
| 渲染过程离线 | 别人 clone 后跑不起来 | 检查模板里没有 `https://` 的 script/font/src |
| `seek(t)` 是纯函数 | 帧不精确、重渲不一致 | 模板里搜 `requestAnimationFrame` / `Date.now` / `transition:` |
| 同一 t 同一帧 | 缓存与验收失效 | 同一段渲两次，比 sha256 |
| 一个章节只讲一件事 | 观众看不懂 | 每章一个 intent，超过一个就拆 |
| 相邻章节不撞构图 | 观众会觉得"又来了" | `plan` 的 `adjacent_layout_repeats` 必须为 0 |
| 交付前必过验收 | 空白/静音/黑屏发出去 | `run` 退出码为 0，报告全绿 |

---

## 6. 来源（给人看的，不是渲染依赖）

- B 站搜索入口：`Chroma`、`动效库`、`Lottie 动画`、`GSAP 动画`、`Rive`、`分镜`
  （社区教程很密；其中「不是AI做不到，是你不知道技术的名称 —— Chroma.js」那条正好是这份文件的立意）
- 库的授权与版本以 npm / 仓库为准，本文件核对时的版本：
  chroma-js 3.2.0、lottie-web 5.13.0、@rive-app/canvas 2.42.2、@theatre/core 0.7.2、
  gsap 3.15.0、animejs 4.5.0、three 0.186.0、pixi.js 8.21.0、colorjs.io 0.7.1、
  culori 4.0.2、split-type 0.3.4、d3-scale（ISC）
- 本文件只保证两件事：**授权信息已逐条核对**，以及**"能按时间求值"这条筛选标准是对的**。
  具体接口名请以各库官方文档为准。
