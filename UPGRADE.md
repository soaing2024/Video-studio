# UPGRADE.md — 这次改造改了什么、怎么用、省了多少

配套：`AUDIT.md`（现状审计 + 数据更正）、`PLAN.md`（原始计划）、`API.md` / `api_index.json`（接口索引，自动生成）。

## 1. 语义没变

`seek(t)` 纯函数、一镜到底、**一次编译一次生成** 全部保持不变。
新增的一切都是加法：老命令的默认行为不变，新行为走显式开关。

时间切片 `--slices N` 不是"渲染两次"：它是**同一次导出**在多进程里的实现——按纯函数切片、并行渲帧、
按序无损合并，并校验总帧数。合并前每片各自的缓存键独立，所以崩了只重渲缺的那几片。

## 2. 新增命令

| 命令 | 用途 |
| --- | --- |
| `vs.py api [task]` | 不读源码就能查接口：命令、参数、库函数签名、注入的 `Scene`/`Anim`/`Kit` |
| `vs.py preview --report --at 2.75,7.9` | 多时间点数值预览：ASCII 图、九宫格 ink、文字框、对比度、字号跳变、主色 |
| `vs.py check` | 渲染前自检：全时间轴扫描（幽灵元素 / 出框文字 / NaN 变换）+ CJK 字形与对比度标定 |
| `vs.py render --slices 8 --jobs 4` | 一镜到底分段并行；`--preset/--jpeg/--no-gpu/--reboot` 控制交付尺寸行为 |
| `vs.py patch edits.json` | 哈希校验的多处手术式修改；失败自动回滚；禁止同路径 delete+add |
| `vs.py audio cues.json` / `--check` | 常用 cue 库 + 混音目标（均值 −24 dB、峰值 ≤ −4 dB）+ 自动增益 |
| `vs.py card <dir>` | 独立结尾卡工程（主片保持零文字时可单独发布） |
| `vs.py cat <file> [--lines a:b]` / `vs.py diff <file>` | 会话内缓存读取 / 只回变更行区间 |

全局：`--json`（一个紧凑 JSON）、`--verbose`、`--quiet`、`--limit N`（默认头尾各 20 行）。
失败形状统一为 `{ok:false,error:{code,where,expected,got,fix_hint}}`。

## 3. 实测数字（3840×2160，单进程，12 帧窗口）

| 配置 | ms/帧 | 无损 | 1800 帧 |
| --- | --- | --- | --- |
| 改造前（Playwright PNG，软件渲染 SwiftShader） | 730 | ✅ | 22 min |
| + GPU 光栅化（`--use-angle=d3d11`，落到真 RTX 5060） | 671 | ✅ | 20 min |
| **+ CDP `optimizeForSpeed`（PNG，无损）** | **166** | ✅ | **5.0 min** |
| + JPEG q97（有损，仅预检用） | 102 | ❌ | 3.1 min |

已实测：`vs.py preview --report` 在 2.8s 帧报出 17.3% ink 并给出 burst 的 ASCII 形状，
在 1.2s 帧正确识别"近乎空白"；`vs.py check` 9 采样 0 硬问题 + 8 个 t=0 可见元素（该片按设计如此）；
`vs.py render --slices 4` 帧数校验通过，二次运行全命中缓存；`vs.py audio` 5 个 cue 混出
均值 −24.0 dB / 峰值 −6.2 dB（落在 `verify` 的 −45..−10 dB 窗口内）。

## 3.5 让 AI 少写字就能出动画：`director.js`

新增可注入运行时 `assets/runtime/director.js`（`D.scene({...})`），把"一镜到底"需要的机制变成**词汇表**
而不是模板：摄像机站点、按深度投影、关键帧几何、冲击响应、canvas FX 全部内置。

字符量对比（同一拍）：手写场景 ≈ 1,400 行 / 46 KB，用这套语言表达同一结构 ≈ 45 行 / 2.4 KB —— **约 20 倍**。

时间值按长度分三档，最短的是字符串：

```js
S.panel('win', {box:[620,392], pos:[960,540], z:2250, at:'3.0:0 s6 3.3:1 5.34:1 5.56:0 in'});
S.rows(win, 3); S.chart(win, {x:300,y:214,w:292,h:86,bars:14});
const c = S.text('h1', 'One compile. One generation.', {size:76, pos:[960,175], at:'6.4:0 s6 6.62:1 7.72:1 8.18:0 in'});
S.morph(c, {t:8.2, from:[40,40], box:[1100,120], dur:0.6});   // A 变成 B：按钮变窗口
S.fx.wave(6.02, [1220,700,2200], {r:2600});                  // 冲击波
S.fx.burst(24.55, [960,948,5100], {n:190});                  // 粒子爆发
S.fx.hud([960,540,620,380], {z:2600, from:18.4, until:23});   // HUD 线框
S.collect({t:26.9, dur:1.5, to:[960,540,5200]});              // 全片收束成一句
```

动词只有六个：`fly`（带弹簧入画）、`morph`（同元素变形）、`hit`（打击）、`cam`（站点航路）、
`fx.*`（波/粒子/HUD）、`collect`（收束）。完整示例见 `assets/examples/director-demo.html`。

## 4. 建议工作流（省 token 的顺序）

```bash
python scripts/vs.py api preview            # 1. 先查接口，别读源码
python scripts/vs.py check  work/mine/project.json --json   # 2. 全时间轴自检
python scripts/vs.py preview work/mine/project.json --report --at 2.75,7.9 --json  # 3. 看数字
python scripts/vs.py plan   work/mine/project.json --json --slices 8 --jobs 4       # 4. 预算
python scripts/vs.py run    work/mine/project.json --slices 8 --jobs 4 --json       # 5. 一次成片
python scripts/vs.py verify work/mine/project.json --video out.mp4 --json
```

## 5. 回滚

- 新文件：`scripts/lib/fmt.py`、`scripts/lib/analyze.py`、`scripts/lib/audio.py`、
  `scripts/lib/deliver.py`、`scripts/scan_scene.mjs`、`scripts/scene_check.py`、
  `scripts/apply_patch.py`、`scripts/api_index.py` —— 删掉即回到旧行为。
- 改动过的旧文件：`scripts/vs.py`、`scripts/lib/render.py`、`scripts/render_segment.mjs`
  —— 三处都有 `.bak` 副本（`apply_patch.py` 每次改动前自动留），或按 `PLAN.md` §7 逐批 revert。
- `--json/--slices/--report/--gpu` 全为显式开关；不传就是老路径。
