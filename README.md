# Video Studio

**用代码做视频的完整流水线**：写一份配置 → 逐帧渲染 → 剪辑合成 → 自动验收。

支持短视频、解说视频、5 分钟以上长视频、高燃混剪、像素风；带离线中文旁白、自动字幕、
人声避让配乐、节拍混剪和一套"用测量代替肉眼"的验收机制。

- **渲染器**：无头 Chromium（Playwright）。把画面写成时间的纯函数 `seek(t)`，逐帧精确截图
- **剪辑器**：ffmpeg 滤镜图，负责剪切、转场、调色、限色、字幕、混音、响度归一化
- **验收器**：解码成片后用像素统计与音量测量判断成败，不靠肉眼
- **旁白**：离线 TTS 合成，**时长由念完这句话需要多久自动决定**，字幕同步生成

它同时是一个 **Codex 技能**：既可以用命令行直接跑，也可以让 AI 代理按 `SKILL.md` 的规范调用。

---

## 安装

```bash
# 1. 克隆到技能目录（Codex 会自动发现）
git clone https://github.com/soaing2024/Video-studio.git ~/.codex/skills/video-studio

# Windows 上你的技能目录可能是 %USERPROFILE%\.agents\skills\
# 2. 检查依赖并自动安装 ffmpeg
python ~/.codex/skills/video-studio/scripts/vs.py doctor --install-ffmpeg

# 3. 自检：跑一个极小工程验证整条链路
python ~/.codex/skills/video-studio/scripts/vs.py selftest
```

`doctor` 会检查 Node、Playwright + Chromium、ffmpeg（需含 libx264）以及 Python 的 numpy / Pillow，
缺什么就告诉你怎么补。首次运行 `--install-ffmpeg` 会把 ffmpeg 装进 `vendor/`（约 84MB，已被 .gitignore 忽略）。

装好后在 Codex 里直接说"用 $video-studio 把这段脚本做成视频"即可。

---

## 五分钟上手

```powershell
# 1. 建项目（starter 模板不需要任何素材，直接能跑）
python vs.py init 我的项目 --template starter

# 2. 试一帧（改完配置先看单帧，几秒出结果）
python vs.py preview 我的项目\project.json --segment title --at 2.5

# 3. 出片：渲染 + 剪辑 + 验收
python vs.py run 我的项目\project.json --jobs 3
```

`run` 会打印一份 JSON 验收报告。任何一项 `ok: false` 都说明有问题，`detail` 会指出该调哪个参数；
退出码非 0 表示验收未通过。

---

## 命令一览

| 命令 | 用途 |
| --- | --- |
| `doctor [--install-ffmpeg]` | 环境检查 / 自动装 ffmpeg |
| `brief --script 台词.txt --out brief.json` | **生成前完整规划**：分幕、分镜、视觉手段、图片提示词 |
| `compile brief.json` | 校验规划并编译成可渲染的 project.json |
| `style [--seed N] [--swatch f.png]` | 采样/查看一套视觉方向（配色、构图、动态） |
| `setup --provider X --key K` | 配置图片生成（任意 OpenAI 兼容平台） |
| `imagegen "提示词" --out f.png` | 生成单张图片，或生成工程里声明的全部图片 |
| `probe <文件...>` | 看素材：尺寸、透明通道、主色、时长、音量 |
| `sprite <图片> [--width 64 --height 96 --colors 12]` | 图片转像素精灵（含 1px 描边与阴影） |
| `beats <音频> [--cuts 60]` | 节拍检测，给出剪辑点 |
| `voices` | 列出本机可用语音（旁白用） |
| `narrate <项目> --script 台词.txt` | 合成旁白、按语音长度定时、生成字幕 |
| `montage <素材目录> --music 音乐.mp3 --out 项目.json` | 从素材文件夹自动生成混剪工程 |
| `init <目录> [--template starter\|short\|longform]` | 新建工程 |
| `plan <项目>` | 空跑：问题清单、缓存命中、预计渲染时长 |
| `preview <项目> [--segment id] [--at 2.0]` | 渲染单帧，设计迭代用 |
| `render <项目> [--jobs N] [--force]` | 只渲染（命中缓存则跳过） |
| `assemble <项目> [--out 成片.mp4]` | 只剪辑合成 |
| `verify <项目>` | 只验收 |
| `run <项目> [--jobs N]` | 渲染 + 剪辑 + 验收 |
| `selftest` | 极小工程端到端回归自检 |

---

## 一、先规划，再渲染

`brief` 会产出一份完整且可编辑的设计文档；没写完就不让它开始渲染。

```powershell
python vs.py brief --script 台词.txt --out brief.json --platform douyin --tone "冷静专业" --seed 2024
python vs.py compile brief.json --out project.json   # 校验 + 编译
python vs.py plan project.json                        # 预算 + 多样性体检
python vs.py run project.json
```

`brief.json`（机器读）与 `brief.md`（人读）里包含：目标平台与画幅、前提与承诺、**分镜表**（每一拍的幕、意图、口播、屏上文字、模板、视觉手段、时长）、**视觉方向**、每拍需要生成的图片提示词、音频方案、验收清单。

“完整”是被强制执行的：`validate` 会对缺失意图、缺屏上文字、残留 TODO、相邻两拍模板与手段完全相同、前提/承诺未写直接报错；对首拍不是钩子、构图种类太少、估算时长偏离目标超过 25%、字幕行过长给出警告。

## 二、避免同质化：每支片子有自己的视觉方向

每个工程带一个**风格签名**（由种子决定）：调色板（经对比度校验）、字号与字距、构图池、入场动态池、转场池、纹理、节奏档位、圆角、描边风格、图片风格子句。同一种子完全可复现，换种子就是换一套审美。

每拍轮换使用构图与动态，**相邻两拍不会撞构图**，强调色在调色板的和声里循环；节奏档位会整体加快/放慢入场速度并插入“呼吸”拍。

```powershell
python vs.py style --seed 2024 --swatch style.png   # 先看配色和方案
python vs.py run project.json --seed 777            # 不改文件，直接换一套
```

`plan` 会给出多样性体检：用了多少种构图/动态/转场、相邻重复数（必须为 0）、以及与历史项目的最高相似度（签名记在 `~/.video-studio/history.json`）。

单拍想指定构图，写在数据里即可：

```jsonc
"data": { "visual": { "layout": "fullbleed", "entrance": "wipe", "density": "minimal" } }
```

## 三、用 API 生成图片

支持任何 OpenAI 兼容的图片接口（OpenAI、硅基流动、阿里云百炼、火山方舟、各类聚合平台）。密钥存在 `~/.video-studio/config.json`，不写进工程文件，所有命令输出里都会脱敏。

```powershell
python vs.py setup --presets                                 # 看内置平台预设
python vs.py setup --provider siliconflow --key sk-xxxx --model Kwai-Kolors/Kolors
python vs.py setup --provider custom --base-url https://你的聚合平台/v1 --path /images/generations --key sk-xxxx --model 模型名
python vs.py setup --test 测试图.png                          # 立刻验证密钥可用
```

工程里把素材写成提示词，渲染前会自动生成（按提示词哈希缓存，不会重复花钱）：

```jsonc
"assets": { "subject": { "prompt": "黄昏屋顶上的一个人影", "size": "1536x1024" } }
```

整片共用一句 `image_style`（由风格签名给出）会拼在每个提示词后面，保证一组图看起来是一套。`imagegen --dry-run` 可以只看请求不发出去。

## 项目配置

一份 `project.json` 描述整支片子（支持 `//` 注释）：

```jsonc
{
  "name": "我的片子",
  "video": { "width": 1920, "height": 1080, "fps": 30, "crf": 20, "preset": "medium" },
  "render": { "jobs": 3, "crf": 12 },
  "look": {
    "accent": "#e0455f",
    "grade": { "saturation": 1.06, "contrast": 1.04 },
    "pixelate": { "scale": 4, "colors": 16, "dither": "none" },
    "fade_in": 0.5, "fade_out": 0.8,
    "progress_bar": { "height": 4, "color": "#e0455f" },
    "overlay": { "src": "assets/logo.png", "x": "W-w-32", "y": "32", "opacity": 0.85 }
  },
  "segments": [
    { "id": "intro", "template": "kinetic", "duration": 6.0,
      "data": { "eyebrow": "开场", "title": "一句话结论" },
      "assets": { "subject": "assets/hero.png" } }
  ],
  "timeline": [
    { "segment": "intro" },
    { "segment": "body", "transition": { "type": "fade", "duration": 0.5 } },
    { "source": "existing-clip.mp4", "trim": [12.0, 15.5] },
    { "source": "photo.png", "trim": [0, 4.0], "zoom": { "from": 1.02, "to": 1.12, "pan": "left" } }
  ],
  "audio": {
    "tracks": [
      { "src": "assets/voice.wav", "role": "voice", "gain_db": -3 },
      { "src": "assets/music.mp3", "gain_db": -20, "fade_in": 2, "fade_out": 3, "loop": true, "duck": true }
    ],
    "duck": { "threshold": 0.03, "ratio": 8, "attack": 150, "release": 600 },
    "loudnorm": { "i": -14, "tp": -1.5, "lra": 11 }
  },
  "subtitles": { "src": "assets/subs.srt", "style": "FontName=Microsoft YaHei,FontSize=30,MarginV=40" }
}
```

要点：

- `segments` 是**要渲染的内容**，`timeline` 是**组装顺序**。没进 timeline 的段落不会渲染，不花时间。
- timeline 里既能放渲染段落（`segment`），也能放**已有素材**（`source`），两者可随意混排——这是混剪的基础。
- 图片素材会自动循环成视频流；`zoom` 给它加推拉摇移（Ken Burns）。
- `speed: 1.25` 让素材加速播放，时长与转场位置自动重算。
- `duration` 可写数字（下限），也可写 `"auto"`（完全由旁白长度决定）。

---

## 模板

| 模板 | 适合 | 主要字段 |
| --- | --- | --- |
| `kinetic` | 开场、章节页、片尾（6-10 秒最佳） | `eyebrow` `title` `subtitle` `rows` `callout` |
| `caption` | 解说、口播、长视频正文 | `chapter` `title` `subtitle` `rows` `caption` |
| `pixel` | 像素风（自动把图片转精灵） | `title` `cn` `sprite` `rows` |
| `stat` | 大数字计数，短视频钩子 | `value` `decimals` `suffix` `label` |
| `quote` | 金句 / 停顿卡 | `quote` `author` `source` |
| `terminal` | 技术解说、代码演示 | `lines[{text,kind}]` `charsPerSecond` `cards[{label,value}]` `logLines` `statLabel` |
| `chart` | 数据条形图 | `chart{unit,max}` `series[{label,value,color}]` |

七个模板读同一套字段，缺什么跳过什么。要自己的样式：复制任意模板 HTML，
保持 `window.seek(t)` 约定，再用 `"template": "路径/我的.html"` 指过去。

---

## 旁白：让时长跟着语音走

写一份纯文本台词（一行一句，对应时间线上第 1、2、3… 个段落）：

```
把视频做出来，其实只需要写一个配置文件。
所有时长都会根据我念完这句话需要多久，自动计算出来。
字幕也会同步生成，不用手工对齐。
```

```powershell
python vs.py voices                       # 先看有哪些语音
python vs.py narrate 项目\project.json --script 台词.txt --voice "Microsoft Huihui Desktop"
python vs.py run 项目\project.json
```

它会做四件事：

1. 逐句合成语音（离线，不联网，不需要 API key）；
2. **把每个段落时长设为"念完这句的时间 + 前后留白"**；
3. 把各句拼成一条连续音轨（按时间点插入静音）；
4. 生成同步 SRT 并烧进画面。

于是"画面比台词长""台词没说完画面就切了"这类问题从根上消失。台词改动后重跑 `narrate` 即可，
语音按内容哈希缓存，不会重复合成。

> 目前语音合成走 Windows 的 SAPI，其他系统可自行录音或接外部 TTS，把音频挂到 `audio.tracks`。

---

## 长视频（5 分钟以上）

五分钟视频 = 20-40 个段落，不要想成一条时间线。

**关键杠杆：静态段落。**

```jsonc
{ "id": "ch03", "template": "caption", "duration": 24.0,
  "data": { "still": true, "title": "第三步：交付", "caption": "把结论写成一句话。" },
  "assets": { "subject": "assets/fig03.png" } }
```

`"still": true` 只渲染一帧，再由 ffmpeg 保持住，**成本与时长无关**。
实测：1080p 的 60 秒静态段落端到端 14 秒；逐帧渲染要 23 分钟。

渲染速度实测（30fps）：

| 分辨率 | 每帧耗时 | 5 分钟视频（逐帧） | 5 分钟视频（jobs=3） |
| --- | --- | --- | --- |
| 1920×1080 | ~384 ms | ~58 分钟 | ~20 分钟 |
| 1280×720 | ~180 ms | ~27 分钟 | ~10 分钟 |
| 320×180（像素风 scale=4） | ~25 ms | ~4 分钟 | — |
| 静态段落 | 只渲一帧 | 几秒 | — |

所以长视频策略是：**只让该动的地方动**。动效留给开场、章节切换和真正的演示，
正文用静态段落，配 `chapter` 章节标签与 `progress_bar` 进度条。

流程：写旁白 → 一个自然段一个段落 → `narrate` 定时 → `plan` 看预算 → `run`。

---

## 混剪

```powershell
python vs.py montage 素材文件夹 --music 音乐.mp3 --out 混剪.json --duration 60 --style energy --title "标题"
python vs.py plan 混剪.json
python vs.py run 混剪.json
```

它会：扫描文件夹里的图片和视频并逐个探测时长 → 检测音乐节拍与 BPM →
按节拍切镜头（风格 `energy` / `punch` / `calm` 决定镜头长度区间）→ 图片自动加推拉摇移、
视频自动取中段并偶尔 1.25 倍速 → 每隔几刀插间黑转场换气 → 响度归一化到平台标准。

生成的是**普通工程文件**，可以继续手改，也可以只当草稿。

---

## 像素风

```jsonc
"look": { "pixelate": { "scale": 4, "colors": 16, "dither": "none" } }
```

- 渲染分辨率自动变为 `宽/scale`，再由 ffmpeg 用最近邻整数倍放大；
- `pixel` 模板会把 `assets.subject` 自动转成精灵（BOX 降采样 → Alpha 二值化 → 限色 → 1px 描边）；
- 动作必须落在整数像素上，否则放大后会抖动；
- 预设配色见 `assets/palettes.json`：`pixel16`、`gameboy`（配 `colors: 4`）、`mono`（配 `colors: 2` + `dither: "bayer"`）。

---

## 自动验收（这工具最值钱的部分）

`verify` 会解码成片并测量：

| 检查项 | 能抓出的问题 |
| --- | --- |
| `duration` | 转场偏移算错、段落丢了或重复 |
| `resolution` | 渲染尺寸不对、被静默缩放 |
| `content` | 全黑、素材没加载进来 |
| `content_detail` | 该有字的段落一个字都没画（模板没驱动它的动画元素） |
| `fade_in` / `fade_out` | 淡入淡出根本没生效（时长算错时很常见） |
| `pixel_blocks` | 用双线性放大冒充最近邻（像素风破功） |
| `palette` | 限色没生效（把帧重新量化到目标色数，量误差） |
| `audio_present` / `audio_level` | 混音静音、配乐比人声低太多或高太多 |

开发这套工具的过程中，验收抓出过这些真问题：交叉淡化长度公式写错（成片短了 3.5 秒）、
双音轨输入序号错位、`zoompan` 与 `concat` 时间基准不一致、稀疏节拍下切点算法退化成两个镜头、
"间黑转场被内容检查误判成黑屏"。**任何一项不过，改配置，别改验收标准。**

---

## 常见问题

**改了配置要重渲全部吗？**
不用。每个段落独立缓存，缓存键包含模板内容、数据、素材修改时间和输出规格；没改的段落直接复用。
强制重渲加 `--force`。

**中间文件在哪？能删吗？**
`build/<项目名>/` 下：`segments/` 是中间片段，`voice/` 是旁白和字幕。删掉可省空间，代价是下次要重渲。
仓库里 `vendor/`（ffmpeg）别删、也别提交。

**配乐听不见 / 太吵？**
先 `probe` 看原文件电平再调 `gain_db`。人声目标约 -18 ~ -12 dB，配乐比人声低 15-20 dB。
`amix` 默认会对所有轨道做归一化，本项目默认关闭（`normalize: 0`），所以 `gain_db` 是多少就是多少。

**想让人声一出来配乐自动变小？**
给配乐轨加 `"duck": true`，给人声轨标 `"role": "voice"`，再配 `audio.duck` 参数。

**Windows 之外能用吗？**
渲染、剪辑、验收、混剪都跨平台；只有 `voices` / `narrate` 依赖 Windows 语音引擎（SAPI）。

---

## 目录结构

```
video-studio/
├─ SKILL.md                 技能入口（给 AI 代理看的规范）
├─ README.md                本文档
├─ LICENSE                  MIT（含第三方组件说明）
├─ agents/openai.yaml       界面元数据
├─ assets/
│  ├─ templates/            7 个画面模板（HTML + JS）
│  ├─ examples/             三个可运行示例工程
│  └─ palettes.json         配色预设
├─ references/
│  ├─ pipeline.md           原理、失败模式、性能数据
│  ├─ longform.md           长视频工作流
│  ├─ formats.md            各种形态的做法
│  └─ guide-zh.md           中文速查
├─ scripts/
│  ├─ vs.py                 命令行入口
│  ├─ render_segment.mjs    逐帧渲染器
│  └─ lib/                  运行时探测、渲染编排、剪辑装配、验收、TTS、混剪等
└─ vendor/                  首次运行自动下载的 ffmpeg（.gitignore 已忽略）
```

---

## 授权

代码采用 MIT（见 `LICENSE`）。仓库只包含源码，不打包 ffmpeg 与 Chromium。

- ffmpeg 由 `vs.py doctor --install-ffmpeg` 按需安装，该构建启用了 libx264，属 **GPL**。
  若你要把它随商业产品一起分发，请先评估 GPL 义务，或改用 LGPL 构建。
- Chromium / Playwright（BSD）、Node.js（MIT）、Python（PSF）均由用户环境提供。
- 模板只按名称引用系统字体。微软雅黑等系统字体不可随包分发，
  如需内嵌请换用思源黑体 / Noto Sans SC（SIL OFL）。
