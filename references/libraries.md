# 素材库、动效库、音效库

写一支片子要三类外部资源：**动效库**（怎么动）、**素材库**（画面从哪来）、**音效库**（声音从哪来）。
这份文件给每类一份"能用/不能用/怎么取"的清单，以及一条硬约束：**渲染过程必须离线**，
所以任何外部资源都要在渲染前落到工程目录里。

> 标注说明：**✔ 已核实** = 本机实测过 API 响应、npm 授权字段或仓库构建产物；
> **§ 待核** = 来自平台官方许可页的通行说法，本机网络不可达/需要账号，采用前请点开官方页面确认。

---

## 0. 三条取用通则

1. **先看授权，再看质量。** 取每个素材时把来源、授权、作者、链接记进工程的
   `assets/CREDITS.md`。CC-BY 类必须署名；CC-BY-NC 不能商用；CC-BY-SA 会传染到你的成片。
2. **取回来就要落盘。** 渲染时不能联网，所以图片/音频/字体/库文件都要复制进工程（或技能的 `vendor/`）。
   远端 URL 只出现在"取用"这一步，不出现在 `project.json` 里。
3. **只对"有把握免费商用"的源做自动化。** 需要账号、按素材单独授权、或仅限个人教育的源，
   一律走人工确认，不要写进脚本自动批量抓。

---

## 1. 动效库

判断标准只有一条：**能不能"给定时间求值"**（`seek(t)` / `goToAndStop` / `position`），
因为本项目的每一帧都必须是 `t` 的纯函数。详细约束、踩坑与用法见
[prompts.md](prompts.md) §2，这里只汇总结论。

| 库 | 授权（✔ 已核实 npm/仓库） | 驱动方式（✔ 已在包内核实） | 适合 |
| --- | --- | --- | --- |
| **lottie-web** 5.13 | MIT | `anim.goToAndStop(t*fps, true)` | AE 导出的 MG 动效（JSON / dotLottie） |
| **Rive** @rive-app/canvas 2.42 | MIT | 状态机 + `advance*` | 角色、图标、交互动效 |
| **Theatre.js** 0.7 | Apache-2.0 | `sequence.position = t` | 时间轴编排、可视化调参 |
| **GSAP** 3.15 | 免费但**非 OSI 开源** | `timeline({paused:true}).seek(t)` | 复杂时间轴、SVG、逐字 |
| anime.js 4.5 | MIT | v4 是 `createTimeline()` 那套（seek 接口**待核**） | 轻量补间 |
| Motion 4.x | MIT | ⚠ 基于 WAAPI 的部分**无法** seek | DOM 微交互（渲染链里慎用） |
| **Three.js** 0.186 / **PixiJS** 8.21 | MIT | 自己调 `renderer.render()`，用 `t` 驱动 | 3D / 2D 精灵 |
| d3-scale / d3-shape | ISC | 纯函数 | 坐标、比例尺、路径 |
| SplitType 0.3 | ISC | 纯拆分，无时钟 | 逐字/逐行动画的前置 |

**离线取用**：`npm pack <pkg>@<version>` → 解包 → 只留 `dist/` 里的 min 文件 + `LICENSE` →
放进 `assets/lib/<name>/` → 模板里用相对路径 `<script src>`。**不要用 CDN，不要留 node_modules。**

**不要引入库的情形**：能用纯函数直接算的（位置、宽高、颜色、透明度）自己算。
实测参考：获奖动效网页里 **9/15 根本没有动画库**（手写或自带小引擎）。

---

## 2. 素材库（图片 / 视频 / 插画）

| 源 | 授权 | 取用方式 | 备注 |
| --- | --- | --- | --- |
| **Pexels** | Pexels License：免费商用、**无需署名**；不可原样转售、不可暗示背书 | REST API，**需要免费 key**（✔ 实测无 key 返回 `401`） | 照片/视频质量高，接口简单 |
| **Pixabay** | Pixabay Content License：免费商用、无需署名；不可原样转售 | REST API，**需要免费 key**（✔ 实测无 key 返回 `400`） | 图/视频/插画/矢量都有 |
| **Unsplash** | Unsplash License：免费商用；不可原样转售、不可用其图片训练竞品 | API 需 key；也可手动下载 | 照片风格偏"编辑感" |
| **Wikimedia Commons** | **逐文件**授权：多为 CC-BY / CC-BY-SA / 公有领域 | MediaWiki API（免 key）**§ 本机网络不可达，未核实** | 有历史/科研/地理类稀有素材；必须逐条看授权 |
| **Openverse** | 聚合 CC 授权素材，逐条不同 | API **§ 本机不可达，未核实** | 适合按授权筛选，不适合盲取 |
| **Internet Archive** | 逐条目授权（有大量公有领域） | API **§ 本机不可达，未核实** | 历史影像/录音 |
| **自己生成** | 用 `imagegen` 命令（任何 OpenAI 兼容接口），提示词与风格子句见 [prompts.md](prompts.md) | `vs.py imagegen` | **最省事、授权最干净**，且能保证一组图风格一致 |

**最干净的路线**：能用 `imagegen` 生成的，就别去图库找——没有授权问题、没有署名负担、
风格还能统一（`image_style` 子句会自动拼在每个提示词后面）。

**素材落到工程里的写法**：

```jsonc
"assets": {
  "subject": "assets/hero.jpg",                    // 本地文件，渲染时直接读
  "backdrop": { "prompt": "…", "size": "1536x1024" } // 或者交给 imagegen 生成
}
```

**千万注意**：不要用"搜索引擎图片"。那类素材没有可用的授权链，用户交付出去是要担责的。

---

## 3. 音效库与配乐

| 源 | 授权 | 取用方式 | 备注 |
| --- | --- | --- | --- |
| **Freesound** | **逐条授权**：CC0 / CC-BY / CC-BY-NC / Sampling+ 混在一起 | REST API，**需要账号与 token**（✔ 实测无 token 返回 `401`） | 音效最全；**必须按授权筛选**，CC-BY 要署名，NC 不能商用 |
| **Pixabay Music / SFX** | Pixabay Content License | REST API 需 key（✔ 无 key `400`） | 配乐与音效都有，轻量 |
| **Mixkit** | Mixkit License：免费商用、无需署名；不可原样转售 | 手动下载 | 免费音效/配乐，风格偏"干净" |
| **ZapSplat** | 免费档**要求署名**；付费档免署名 | 手动下载 | 音效库大，注意免费档条款 |
| **YouTube Audio Library** | 逐条：有的免署名，有的要署名 | 仅网页手动下载 | 有现成分类，但不可脚本化 |
| **Free Music Archive / ccMixter** | 逐条 CC | 手动 / 部分 API | 音乐为主，署名要求看清楚 |
| **BBC Sound Effects** | **RemArc 许可：仅个人/教育/研究**，商用需另购 | 手动下载 | ⚠ 别拿它做商用交付 |
| **自己合成** | 你的代码或 ffmpeg 生成的音频没有第三方授权问题 | `ffmpeg -f lavfi -i sine=…`、`anoisesrc` | 适合节拍器、UI 提示音、低频铺底 |

**授权筛选的硬规则**（写进交付检查）：

- 只允许 **CC0 / 公有领域 / 明确免署名的免费许可**用于自动批量取用。
- **CC-BY** 可以商用，但必须在成片或说明里署名（作者 + 标题 + 授权 + 链接）。
- **CC-BY-NC / Sampling+ / 仅个人教育**（含 BBC RemArc）**不能进入商用成片**。
- 拿不准就换源，或者自己合成。

**落进工程**：音乐/音效走 `audio.tracks`，人声轨标 `"role": "voice"` 以启用闪避：

```jsonc
"audio": {
  "tracks": [
    { "src": "assets/sfx-whoosh.wav", "at": 2.4, "gain_db": -8 },
    { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true, "duck": true }
  ]
}
```

音量目标（`verify` 会测）：配乐均值 **-45 ~ -10 dB**，人声 **-18 ~ -12 dB**，配乐比人声低 15–20 dB。
先用 `vs.py probe <文件>` 看原始电平，再决定 `gain_db` 减多少。

---

## 4. 素材与音效的取用流程（可复现）

1. **先定"必须外部获取"的清单**：哪几拍需要照片、哪几处需要音效。能用生成的就不出门找。
2. **按第 2、3 节的规则选源**，凡是要 key 的平台先申请一个免费 key，存到环境变量或
   `~/.video-studio/config.json`（**不要写进工程文件**）。
3. **取回到工程**：`assets/` 下按用途命名（`hero.jpg`、`sfx-whoosh.wav`），
   同时把来源写进 `assets/CREDITS.md`：素材名 / 来源页 / 作者 / 授权 / 是否需署名。
4. **验证**：`vs.py probe assets/*` 看尺寸、时长、音量；图太小或音量太低当场换，
   不要指望渲染时补救。
5. **交付前**：`verify` 全绿 + 检查 `CREDITS.md` 里每一条都标了授权，
   CC-BY 的署名已经在片尾或说明里出现。

---

## 5. 一句话总结

- **动效库**：只有能按 `t` 求值的才能进场景；能自己算的别引库。
- **素材库**：优先生成（`imagegen`），其次 CC0/免署名图库；**永远不用搜索引擎图片**。
- **音效库**：Freesound 最全但授权混杂，按授权筛；BBC 只限个人教育，不能商用。
- **一律落盘**：渲染不联网，所有外部资源必须在渲染前进入工程目录并记录授权。
