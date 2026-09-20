# 技法与提示词（精简版）

给 AI 投喂只有三件事有效：**给技法命名、给硬约束、给验收标准**。
"颜色弄好看点"不是要求，"用 chroma-js 在 LCh 空间插 7 阶"才是。

三条硬约束，任何技法都要落在里面：**渲染离线**（库 / 字体 / 素材先落盘）、
**`seek(t)` 是纯函数**（禁 CSS transition、`requestAnimationFrame`、`Date.now`）、
**同一 `t` 同一帧**。验收不看感觉：跑 `vs.py verify` 并把报告贴出来。
任何命令的接口都能用 `vs.py api <命令>` 查，不必读源码。

---

## 1. 色彩与色阶

**库。** chroma-js 3.2.0（BSD-3-Clause AND Apache-2.0 · **已落盘**，`"libs": ["chroma-js"]`）是主力：
`chroma.scale()` 插值、`chroma.brewer` 内置色板、`chroma.contrast(a, b)` 校验对比度、
`chroma(x).luminance()` 校验明度。需要严格 CSS Color 4 用 colorjs.io（MIT），
需要 ΔE / 色盲模拟用 culori（MIT）。

**感知均匀。** 在 sRGB 数值上插值，中间色会发脏。在 LCh / OKLCH 空间插：

```js
const steps = chroma.scale(["#0d1b2a", "#3cd3d4"]).mode("lch").colors(7);
```

两条硬指标：正文对背景 ≥ 8:1、次要 ≥ 4:1；相邻两阶的明度差 ≥ 0.04，否则小屏上糊成一片。
红绿不要单独承担区分，叠一层明度或形状。

**三种色阶别选错。** sequential（单维递进）保持色相、走明度阶梯；diverging（有正负）中点接近背景色、
两端互补色相；qualitative（并列类别）等明度等饱和，只靠色相区分。

**写在哪。** 整片强调色 / 系列色 → `style.signature.colors`；图表数据条 → 模板的 `series[].color`；
图表色阶 → `"libs": ["chroma-js"]` + `chroma.scale(...)`；整片调色 → `look.grade`（ffmpeg 侧）；
像素风 → `assets/palettes.json`。注意模板读的是 `style.inject()` 写进段落的 `visual.colors`，
不是 `look.accent`；单拍要指定就写 `data.visual`。

**别混。** 视频工程里的"色阶"还指电平范围（`-color_range tv` vs `pc`）和 HDR→SDR
（`zscale` / `tonemap` / `-color_primaries`），那是 `assemble.py` 里 ffmpeg 的活，和 chroma 无关。

**模板。**

```
用 chroma-js 生成 7 阶 sequential 色阶，起点 #0d1b2a、终点 #3cd3d4，在 LCh 空间插值。
交付前自查：逐对算 chroma.contrast 列出 < 4.5 的组合；算相邻阶 luminance 差标出 < 0.04 的位置。
只列问题，不要直接改颜色。
```

---

## 2. 外接动效库

**准入四条**，缺一不可：离线可用（dist 随仓库走）；能"给定时间求值"（`seek(t)` / `goToAndStop` /
`position = t`）；同一 `t` 同一帧（无内部 ticker）；首帧不依赖网络（字体、图片、wasm 都本地）。
不满足的库不是不好，是只能用在素材准备环节，不能进 `seek(t)`。

**清单。**

| 库 | 版本 / 授权 | 帧精确怎么驱动 |
| --- | --- | --- |
| lottie-web · **已落盘** | 5.13 · MIT | `anim.goToAndStop(t * fps, true)` |
| anime.js · **已落盘** | 4.5 · MIT | `Anim.timeline(秒数, build).seek(t)` |
| three · **已落盘** | r186 · MIT | 自己调 `renderer.render()`，`t` 驱动所有变换 |
| chroma-js · **已落盘** | 3.2 · BSD-3-Clause AND Apache-2.0 | 纯函数，没有时钟 |
| Rive | @rive-app/canvas 2.42 · MIT | 状态机 `advance*`（需要 wasm 运行时） |
| Theatre.js | @theatre/core 0.7.2 · Apache-2.0 | `sequence.position = t` |
| GSAP | 3.15 · 免费但**非 OSI 开源** | `gsap.timeline({ paused: true }).seek(t)`，商用前读条款 |
| PixiJS | 8.21 · MIT | 自己调 `renderer.render(stage)` |
| d3-scale / d3-shape | ISC | 纯函数，没有动画 |
| SplitType | 0.3.4 · ISC | 只做拆分，本身没有时钟 |

**选型顺序**（能停在前一步就别往后走）：① 纯函数能算就不引库 → ② 别人做好的 MG 用 Lottie →
③ 角色 / 交互用 Rive → ④ 复杂时间轴用 GSAP / Theatre → ⑤ 3D 或大量精灵用 three / PixiJS。

**vendor。**

```powershell
python vs.py libs                   # 看已落盘 / 可安装
python vs.py libs --install <名字>   # 装一次；渲染期永远不联网
```

不在注册表里的库：`npm pack <pkg>@<version>` → 解包 → 只留 `dist/*.min.js` + `LICENSE` →
放进 `assets/lib/<name>/` → 工程里写 `"libs": ["<name>"]`。
不要 CDN，不要 `node_modules`，场景里不要写 `<script src>`。

**坑（都踩过）。** 任何 rAF（含库自带的 ticker）都会破坏帧精确；`file://` 下 CSS `mask-image`
会被当成跨域、遮罩直接失效，改用 canvas `source-atop`；wasm / worker 路径要显式核对；
中日韩文字必须写死字体栈，回退字体一换行盒就变；只发 ESM 的包要用 esbuild 打成 IIFE 并在
entry 里挂 `window.*`（three 与 chroma-js 就是这么接的），footer 里不要出现 `|` `&` 这类
shell 元字符。

---

## 3. 设计与分镜

**分镜表就是 `brief`。** `intent`（必填，空着 `compile` 直接报错）· `say`（口播，没有配音时
它就是这一拍要传达的意思）· `on_screen`（和口播不是一回事，单行 ≤ 18 字）· `device`（视觉手段）·
`seconds`（短视频 3-6s、解说 8-20s、长视频 15-45s）· `act`（hook / context / body / proof / turn / close）。

**构图铁律。** 一屏一个焦点；文字不超过两行，重要信息在安全区内（竖屏顶部 12%、底部 20%
会被平台界面压住）；相邻两拍的版式必须换（`plan` 的 `adjacent_layout_repeats` 必须为 0）；
避开"居中标题 + 副标题 + 两行说明"这个默认值——那是默认值，不是选择。

**镜头与节奏。** 运动词汇用推 / 拉 / 摇 / 移 / 跟 / 升降（对应 `motion.camera_track`）；
钩子 3 秒内出现；每 4-6 个章节安排一次呼吸（写进 `hold`、金句卡或一次明暗呼吸）；
长视频只让该动的地方动，不动的时间写进 `hold`。

**色彩脚本与母题。** 先给整片定 3-5 个色相节点，再往每一拍落色，观众才感到"情绪在走"；
让同一个图形元素（圆环 / 网格 / 扫描线 / 某个图标）重复出现几次，片子立刻有整体感——
最省事的载体是 `visual.texture` 与全局 `look.progress_bar`。

**模板。**

```
把这段脚本拆成 10 拍的分镜表：段号 / act / intent / say / on_screen（≤18 字）/ 视觉手段 / 时长。
要求：钩子在第 1 拍且 3 秒内给结论；相邻两拍不得使用同一版式 + 同一手段；总时长 50 秒左右。
```

---

## 4. 硬规则对照表

| 硬规则 | 违反会怎样 | 怎么自检 |
| --- | --- | --- |
| 渲染过程离线 | 别人 clone 后跑不起来 | 模板里没有 `https://` 的 script / font / src |
| `seek(t)` 是纯函数 | 帧不精确、重渲不一致 | 搜 `requestAnimationFrame` / `Date.now` / `transition:` |
| 同一 `t` 同一帧 | 缓存与验收失效 | 同一帧渲两次，比 sha256 |
| 一章只讲一件事 | 观众看不懂 | 每章一个 `intent`，多一个就拆 |
| 相邻章节不撞构图 | 观众觉得"又来了" | `plan` 的 `adjacent_layout_repeats` 为 0 |
| 交付前必过验收 | 黑屏 / 静音发出去 | `run` 退出码为 0，报告全绿 |
| 结构先于皮肤 | 加颗粒也救不回来 | 关掉动效与 finish，静帧仍然站得住 |
