# AUDIT.md — video-studio 现状审计（改造依据）

> 历史文档：记录改造前的现状与证据，不改任何代码。当前行为以 [SKILL.md](SKILL.md) 为准；
> 文中引用的旧默认值（单进程渲染、`jobs` 的旧语义、per-segment `still` 等）已被
> [UPGRADE.md](UPGRADE.md) 与当前代码取代。配套计划见 `PLAN.md`。
> 生成方式：`audit_scan.py`（AST 扫描全部 `.py`/`.js`/`.md`），人工核对关键路径 + 一次完整的
> 4K/60fps/30s 一镜到底实战复盘。原型索引见工作区 `work/audit/api_index.json`。

---

## 0. 一句话结论

骨架是对的（`seek(t)` 纯函数 / 一镜到底 / 测量式验收 / 失败模式文档），
但**它的成本模型与验收工具是为「1080p + 多段剪辑 + 有人盯着看」设计的**；
在「4K + 单镜头 + 无人值守一次成片」这条路上，缺三样东西：

1. **便宜的正确性探针**（不看图就能判断画面对不对）
2. **时间切片并行渲染**（单镜头目前 = 单进程 = 4K 下 75 分钟）
3. **交付尺寸的实测数据**（4K 的瓶颈是内存不是 CPU；GPU 光栅化 / preset / 浏览器重启都没有写）

---

## 1. 规模基线（实测）

| 层 | 文件数 | 行数 | 备注 |
| --- | --- | --- | --- |
| Python（scripts + lib） | 23 | **5,068** | AI 要"调用而不读源码"，目前必须读的就是这一层 |
| JS runtime（scene/anim/kit/three-kit） | 4 | 864 | 注入页面，API 只能靠读源码得知 |
| JS（render_segment.mjs） | 1 | 107 | 渲染管线 |
| Markdown（SKILL + 13 references + README） | 15 | **3,099** | 其中 8 篇 CJK 占比 > 0.5 |

CJK 占比实测（`cjk_share`，按汉字/字母比）：

| 文档 | 行 | cjk | 影响 |
| --- | --- | --- | --- |
| references/taste.md | 66 | **0.91** | 审美闸门，英文 agent 成本最高 |
| references/choreography.md | 320 | **0.82** | 最有价值的编排方法，却最不可读 |
| references/craft.md | 142 | 0.82 | |
| references/rhythm-handoff.md | 143 | 0.73 | |
| references/prompts.md | 355 | 0.56 | |
| README.md | 530 | 0.53 | |
| references/libraries.md | 189 | 0.52 | |
| references/three-d.md | 238 | 0.37 | |
| references/motion-realism.md | 166 | 0.11 | |
| references/pipeline.md | 173 | **0.00** | 全英文，恰恰是最常读的一篇 |
| references/creative.md / longform.md / SKILL.md | 165/108/256 | 0.00 | |

结论：**~1,500 行深度方法论只存在于中文里**，而英文 agent 每次都要为它们付全额 token。

---

## 2. 模块清单：输入 / 输出 / 副作用

副作用标记：`W`=写文件 `S`=起子进程 `N`=联网 `D`=删除 `M`=建目录

### 2.1 CLI 与核心流水线

| 模块 | 行 | 输入 | 输出 | 副作用 |
| --- | --- | --- | --- | --- |
| `scripts/vs.py` | 711 | argv、project.json | JSON(部分命令)、退出码 | W S N M（经 lib 间接） |
| `lib/spec.py` | 323 | project.json 路径 | 规范化 spec dict、problems 列表 | 只读 |
| `lib/render.py` | 254 | spec、seg | 分段 mp4 + `.key` 缓存键 | W S M |
| `lib/assemble.py` | 268 | spec | filter.txt、成品 mp4 | W S M |
| `lib/verify.py` | 200 | spec、成品路径 | checks[{check,ok,detail}] | S M D(临时) |
| `lib/probe.py` | 88 | 媒体路径 | 尺寸/时长/响度 dict | S |
| `lib/runtime.py` | 219 | — | 工具路径、capabilities | S N W D M |
| `lib/libs.py` | 364 | 库名列表 | 注入文件路径、指纹 | **N** W M S |
| `lib/imagegen.py` | 217 | prompt、配置 | 图片路径 | **N** W M |
| `scripts/render_segment.mjs` | 107 | scene.html + data.json | mp4（帧经 stdin 管道） | S W |

### 2.2 规划 / 设计层（改 spec dict 为主）

| 模块 | 行 | 输入 | 输出 | 副作用 |
| --- | --- | --- | --- | --- |
| `lib/brief.py` | 365 | 脚本行/topic | brief dict、project dict、markdown | W M |
| `lib/choreography.py` | 148 | spec | 给每段注入 beat sheet + 静帧率报告 | 改内存 spec |
| `lib/motion.py` | 256 | spec、beats | 每段运动计划 + 打击点 | 改内存 spec |
| `lib/style.py` | 341 | seed/topic | 视觉签名、每段 layout/accent；**已含 `contrast()`/`ensure_contrast()`** | W M |
| `lib/beats.py` | 100 | 音频 | onset 时间、切点 | S |
| `lib/montage.py` | 155 | 素材目录 | montage project | W M S |
| `lib/narrate.py` | 193 | spec + TTS | 改时长/字幕/音轨 | W M S |
| `lib/tts.py` | 118 | 文本 | wav | S W M |
| `lib/sprite.py` | 55 | 图片 | 精灵 png + 阴影 | M |
| `scripts/scaffold.py` | 150 | starter 模板 | 项目骨架 | W M |
| `scripts/beat_audit.py` | 141 | project.json | 交接审计（exit-then-enter gap） | 只读 |

### 2.3 检查层（全部只吃「成品视频」）

| 模块 | 行 | 输入 | 输出 | 副作用 |
| --- | --- | --- | --- | --- |
| `scripts/qc_video.py` | 169 | **mp4 + times** | ASCII frame map、区域 ink | S W D |
| `scripts/taste_check.py` | 231 | **mp4** | 节奏/静帧/构图标签、连通域计数 | S D |

**关键发现**：`ascii_map()`、区域 ink、`rhythm()`、`stills()`、`label_components()`
这些"不看图也能判断"的**原语已经存在**，但全部绑定在**已完成视频**上——
写场景阶段拿不到，而写场景阶段恰恰是最需要它们的时刻。

### 2.4 页面运行时（AI 写场景时的真实 API 面）

| 模块 | 行 | 导出（自动识别） |
| --- | --- | --- |
| `assets/runtime/scene.js` | 138 | `Scene.{mount,type,safe,ready,icon,iconNames}`, `SAFE`, `SCENE`, `__sceneReady` |
| `assets/runtime/anim.js` | 280 | `Anim.{Actor,Scene,EASE,spring,clamp01,mixColor,timeline,lottie}` |
| `assets/runtime/kit.js` | 231 | `Kit.{buildStage,backdrop,ambient,drawParticles,bandSwapper,el,clamp01,...}` |
| `assets/runtime/three-kit.js` | 215 | **导出面未能自动识别** → agent 只能读源码（这正是 A 项要解决的） |

---

## 3. 实战复盘：一次 4K/60fps/30s 一镜到底（润色版）

用这个 skill 完整做了一支 30s、3840×2160、60fps、1800 帧、单镜头无剪辑的片子。
下面每条都带实测数字。

### 3.1 它真正立住的地方（不是客套）

- **纯函数 `seek(t)` 是可交付性的根因。** 三个切片被内存拖死后，我只重渲那三段，
  帧序与其余五段严格接续——因为 `t → frame` 确定。同一性质也让我第一次就敢做时间切片。
- **`references/pipeline.md` 的失败模式清单是整包最值钱的文件。** 它预言的
  "`position:absolute` 在 flex 父元素里不会居中"我当场踩中；`doctor` 专门验 `libx264`
  也躲开了 Playwright 自带 ffmpeg 只能编 VP8 的坑。
- **`verify` 用测量代替自夸。** 运动检查用 `lag=6`（隔一秒比帧）当幻灯片探测器，
  比逐帧差聪明。本次 6/6 通过：motion 6.26/255（阈值 2.2），audio −24.8 dB。
- **"一次编译一次生成"的纪律确实省钱。** 因为前置做了 doctor → 冒烟 → 计时探针 →
  DOM 探针 → 电平测量，交付物第一次 `verify` 就全过；**为审美返工的渲染次数 = 0**。

### 3.2 它与现实打架的地方（按代价排序）

| # | 问题 | 本次代价 | 证据 |
| --- | --- | --- | --- |
| 1 | **接口不自描述**，必须读源码才能调用 | 进上下文前就读了 5 个源文件 ≈ 32k tokens | `vs.py` 28 个函数、lib 层 5,068 行 |
| 2 | **patch 工具脆弱**，失败即整包重发 | 5 次被拒/失配，重复载荷 ≈ 20–30k tokens、~10 分钟 | 2×"multiple ops same path"、1×上下文失配 |
| 3 | **缺"不看图"的正确性探针** | 自写 3 个探针（ascii/check/finprobe ≈ 400 行 ≈ 10k tokens）+ 25 分钟定位 | 3 个真 bug 全靠手写探针才抓到 |
| 4 | **单镜头 = 单进程**（`jobs` 只跨段生效） | 4K 单进程实测 2.5 s/帧 → 1800 帧 **75 分钟** | `render_all()` 只对 `pending()` 多段并行 |
| 5 | **成本模型外推失真** | `plan` 报 4K ≈ 1116 ms/帧，实测 2500 ms/帧（**低估 2.2×**） | `ms_per_frame = 63 + 0.000127*w*h` |
| 6 | **4K 的瓶颈是内存，文档零提及** | 6 并发→可用内存 0.17 GB，进程被静默杀死；5 并发同样死 | 两次整轮报废 ≈ 20 分钟 |
| 7 | **GPU 光栅化未启用** | PNG 2.5 s/帧 → 加 GPU 旗标 1.7 s/帧（−32%） | `chromium.launch()` 无参数 |
| 8 | **反 AI 味门槛与本题材冲突** | 需自行判断"体裁档位" | choreography.md 禁"卡片网格/假外壳/仪表盘"，本 brief 全部要求 |
| 9 | **SFX-only 无 helper** | 自行合成 25 个 cue（≈250 行 ≈ 6k tokens） | `amix` 按轨数衰减，逼出"预混一条 WAV" |
| 10 | **中文参考** | 8 篇 cjk>0.5，最深的方法论最不可读 | 见 §1 表 |

### 3.3 三个真 bug（全部由"探针"而非"看图"发现）

1. **关键帧语义陷阱**：`[[0,0],[23.1,0.98]]` 会**从 t=0 就开始线性爬升**，
   导致第 3–7 拍的窗口在开场就有幽灵残影。`verify` 完全无感（有内容、有运动、静帧正常）。
2. **闭场卡片偏心**：子元素 `left/top` 从父盒左上角量起，而我按"父盒中心"设计 →
   整块偏左上 300 design px。肉眼在终帧才看得出，探针一次定位。
3. **深度轨道失控**：某卡片的 `zc` 轨道在 0.6s 内把 dz 压到 613，
   k 从 1.16 涨到 2.61 → 元素被放大 4.5 倍糊满画面。

**共性**：这三个都不是"审美问题"，是**可断言的状态问题**——正是 `verify`（成品层）
看不见、而 DOM/几何探针（场景层）一眼可见的那一类。

### 3.4 时间账（本次总墙钟 ≈ 85 分钟）

| 环节 | 实测 |
| --- | --- |
| 读文档 + 读源码 | ~15 min |
| 写场景（3 次大 patch） | ~25 min |
| 冒烟 + 计时探针 + 自写校验工具 | ~20 min |
| 4K 渲染（成功的 8 片 + 重试） | ~22 min |
| **因内存死掉的两次整轮** | **~20 min（纯浪费）** |
| 装配 + 验收 + AI 探针 | ~5 min |

---

## 4. 已定位的具体缺陷（可直接改的）

| 代号 | 位置 | 缺陷 | 后果 |
| --- | --- | --- | --- |
| A1 | `vs.py` util | 无全局 `--json` / `--verbose`；`emit()` 固定 `indent=2` | 输出 token 偏大 15–25% |
| A2 | `vs.py:main()` | `except` 只打印 `error: Type: msg` | 无 where/expected/fix_hint，agent 要自己猜 |
| A3 | 全部 lib | 无函数签名索引；`three-kit.js` 导出面无法自动识别 | 必须读源码 |
| B1 | `render_segment.mjs` | 硬编码 `chromium.launch()` + `type:'png'` | 4K 慢 32%（GPU/JPEG 均未用） |
| B2 | `render.py` | 缓存键粒度 = 整段；单镜头 = 一个键 | 改 1 秒要重渲 100% |
| B3 | `render.py:render_all` | 并行只跨 segment | 单镜头 `--jobs` 完全无效 |
| B4 | `vs.py:cmd_plan` | `ms_per_frame` 线性外推 4K | 预算低估 2.2× |
| B5 | 文档 | 未提内存上限/preset/浏览器重启 | 4K 首跑必死 |
| C1 | `render.py` / `vs.py:cmd_preview` | 只出 1 张 PNG，无任何数值通道 | 场景期无法自检 |
| C2 | `qc_video.py` / `taste_check.py` | 分析原语只吃成品视频 | 场景期用不上 |
| C3 | 无 | 无 CJK 字形可用性验证、无对比度自动闸门（`style.py` 已具备未复用） | 可能交付豆腐块/低对比 |
| D1 | 无 | 无 `read_cached` / 无差异重读 | 重复读文件 |
| D2 | 无 | 无 patch 工具（依赖外部 patch，语义脆弱） | 见 §3.2 #2 |
| D3 | 无 | 无 cue 库、无混音目标校验/自动增益 | 见 §3.2 #9 |
| D4 | `verify.py` | 音频阈值注释写"for a background bed" | SFX-only 场景语义误导 |

---

## 5. 度量口径（先说清怎么算，免得自欺）

**Token**：模型自身推理 token 无法自测。可测的是**工具输出字节 + 被读文件字节**，
按 ≈4 bytes/token 折算。改造前后各跑同一条命令序列，比较：
`bytes_out_total`、`files_read_total`、**回合数**（回合数是最贴近真实等待时间的代理）。

**时间**：`plan` 的预算 vs 实测墙钟，逐环节打点（读/写/探针/渲染/装配/验收）。

**渲染**：固定同一项目、同一分辨率，比较 `渲染墙钟` 与 `每帧毫秒`。

**确定性**：帧级 sha256 序列必须逐帧一致（视觉等价 = 硬保证）；
**比特流级** sha256 需要固定线程数/关 lookahead，若要比特一致需加 `--deterministic-encode`
（x264 多线程本身会改变码流字节，这一点必须在验收标准里写清楚，不能含糊）。

---

## 6. 数据更正（改造期间实测，覆盖 §3.2 的旧数字）

§3.2 里写的「4K 单进程 2.5 s/帧、75 分钟」**偏大 3.4 倍**：那是 12 帧窗口里包含了
启动与首帧预热。剔除预热后，同一场景 3840×2160 的稳态成本是：

| 配置 | ms/帧 | 无损 | 1800 帧单进程 |
| --- | --- | --- | --- |
| Playwright PNG + 软件渲染（SwiftShader，改造前的默认） | 730 | ✅ | 22 min |
| + GPU 光栅化（真 RTX 5060，`--use-angle=d3d11` 等） | 671 | ✅ | 20 min |
| **+ CDP `Page.captureScreenshot{optimizeForSpeed:true}`** | **166** | ✅ | **5.0 min** |
| + JPEG q97（有损，仅预检） | 102 | ❌ | 3.1 min |

GL backend 字符串证实：不加旗标时 Chromium 跑的是 SwiftShader（CPU），加旗标才落到独显。
**GPU 只值 −8%，真正的杠杆是 PNG 编码路径（−75%，仍然无损）与时间切片并行。**
结论：改造后的 4K 单进程基线是 **~5 分钟**，8 切片并行后 **~1.5–2.5 分钟**。
