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

## 使用约定：先对话，确认后一次出片，非必要不试帧

以下四条是对所有使用者的约定，AI 代理调用本技能时必须遵守，人工直接跑命令时也建议按同一节奏来。

**一、先对话，再创作。** 一句话需求不等于一份 brief。代理不会拿到需求就开写，而是先和你来回沟通几轮，把片子问清楚：给谁看、在哪个平台播、多长、要让人记住什么或做什么、语气是什么（以及不要是什么）、有没有旁白/配乐/现成素材/品牌规范、有没有喜欢或明确不要的参考。每轮只问几个关键问题，并复述“已经定了什么、还差什么”。

**二、确认完整方案后才开始生成。** 信息问全后，代理会先把一份完整方案交给你确认：**剧本/口播稿** ＋ **完整分镜表**（每一拍的幕、意图、口播、屏上文字、视觉手段、时长、交接方式）＋ **视觉方向** ＋ **音频方案** ＋ **素材清单** ＋ **验收清单**。你明确同意之前，不建工程、不 compile、不生成图片、不渲染；方案改动后，改完再确认一次。

**三、一次编写，一次渲染，直接导出。** 方案确认后，配置只写一遍、成片只渲一遍，渲完直接导出交付文件。整片 `run` 是交付动作而不是试错动作：不做“先渲一版看看”，不为比较方案反复全片渲染。交付后发现问题，就改配置、重新确认、再交付一轮，而不是把渲染当成迭代器。

**四、非必要不 preview。** 不看单帧是默认状态。设计上的取舍在方案阶段就想清楚（构图、字号跳跃、色彩预算、素材是否齐备），不要靠逐拍试帧来找感觉。只有出现一个具体的、纸面上说不清的疑问时（素材到底有没有加载进来、字体回退成什么样、这个构图在实际画幅里立不立得住），才渲那一帧去回答它，并说明这一帧是为了回答什么。preview 不是全片渲染，但把每一拍都试一遍，只是换了个便宜名字的“边看边改”。

---

## 五分钟上手

> 下面三步都发生在**方案确认之后**：先对话把片子问清楚，拿到你的确认，再进这里。

```powershell
# 1. 建项目（生成一份配置 + 一个空白场景文件）
python vs.py init 我的项目 --duration 20

# 2.（可选，非必要不做）只有纸面上判断不了的疑问，才渲一帧回答它
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
| `init <目录> [--duration N]` | 新建工程（含一个待写的场景） |
| `libs [--install 名称...]` | 看已落盘的浏览器库，或从 npm 装一个（只在构建时联网） |
| `plan <项目>` | 空跑：问题清单、缓存命中、预计渲染时长 |
| `preview <项目> [--segment id] [--at 2.0]` | 渲单帧，仅当纸面判断不了具体疑问时用 |
| `render <项目> [--jobs N] [--slices N] [--force]` | 只渲染（命中缓存或未变切片则跳过） |
| `assemble <项目> [--out 成片.mp4]` | 只剪辑合成 |
| `verify <项目>` | 只验收 |
| `run <项目> [--jobs N] [--slices N]` | 渲染 + 剪辑 + 验收（一次成片） |
| `selftest` | 极小工程端到端回归自检 |
| `check <项目>` | 渲染前全时间轴自检（幽灵元素 / 出框文字 / NaN / CJK 与对比度） |
| `patch <edits.json>` | 哈希校验的多处修改，失败整批回滚 |
| `audio [<项目>] --cues cues.json` / `--check` | 生成或测量音效床（均值/峰值目标） |
| `card <目录>` | 独立结尾卡工程 |
| `api [任务]` | 查 CLI / 库函数 / 注入 API，不必读源码 |
| `cat <文件> [--lines a:b]` / `diff <文件>` | 缓存读取 / 只看变更行 |

---

## 一、先对话、先规划，再渲染

`brief` 会产出一份完整且可编辑的设计文档；没写完就不让它开始渲染。

这份文档同时也是**交给使用者确认的方案**：代理必须先把它讲清楚（剧本、完整分镜、视觉方向、音频与验收清单），拿到明确确认之后才 `compile` 和渲染。`brief` 只是把方案写成文件，确认是使用者给的，不是工具自己过的。

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

`plan` 会给出多样性体检：用了多少种构图与动态、相邻重复数（必须为 0）、以及与历史项目的最高相似度（签名记在 `~/.video-studio/history.json`）。

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

## 四、图标、动效与 3D 库：离线注入，不改场景路径

外部库在这条流水线里只有一种合法形态：**dist 随仓库走、渲染时不联网、能按 `t` 求值**。

```powershell
python vs.py libs                      # 已经落盘了哪些、还能装哪些
python vs.py libs --install anime       # 需要时才从 npm 取一次（构建期，渲染期不联网）
```

工程里写 `"libs": ["lucide", "lottie"]`，渲染器把库文件注入页面（和 `Scene` / `Anim` / `Kit` 同一条路径），
**场景里不用写 `<script src>`**——场景会被复制进工程，相对路径会断。

| 库 | 授权 | 在场景里怎么用 |
| --- | --- | --- |
| `lucide` 1.47（2108 个图标） | ISC | `Scene.icon("arrow-right", { size: 64, color: "#e0455f" })` |
| `lottie` 5.13 | MIT | `Anim.lottie(host, SCENE.assets.motion, { fps: 30 }).seek(t)` |
| `anime` 4.5 | MIT | `Anim.timeline(3, (tl) => tl.add(el, { x: [0, 200], duration: 2000 })).seek(t)` |
| `d3-scale` 4.0（需要时再装） | ISC | 纯函数，直接算坐标与刻度 |
| `three` 0.186 | MIT | `Scene.three()` / `Scene.css3d()` / `Scene.surface()`，在 `seek(t)` 里调 `render()` |

**3D：一个 WebGL 图层，外加两种和 2D 合成的方式。**

```js
const view = Scene.three({ background: "#080a0b" });   // WebGL：scene / camera / renderer 直接给你
view.scene.add(mesh); view.environment(); view.bloom({ strength: .5 });

const css = Scene.css3d();            // 真 DOM 摆进 3D（透视、倾斜、纵深）
const s   = Scene.surface(512, 320);  // 2D 画布 → THREE.CanvasTexture

window.seek = (t) => { mesh.rotation.y = t * .55; view.render(); css.render(); };
```

three 是唯一需要打包的库：官方从 r150 起只发 ESM，`vs.py libs --install three` 会调一次 esbuild 把它打成单文件 IIFE。
WebGL 在本机是软件渲染，1280×720 + bloom 实测约 0.2 秒/帧；**3D 同样只能按 `t` 求值**。
四种组合方式（3D 垫底 + DOM 文字 / CSS3D / Canvas 贴图 / bloom 只作用于 3D）、镜头光照默认值与禁忌清单，
见 [references/three-d.md](references/three-d.md)。

两个动效包装只做一件事：库只创建一次、关掉自动播放，然后每帧告诉它“站在 `t`”。所以
**同一个 `t` 必然同一帧**（实测同一帧两次渲染 sha256 一致）。能自己用纯函数写出来的效果，仍然不要引库。

`.json` 素材会被解析后注入 `SCENE.assets`（而不是文件 URL）：lottie 的 Bodymovin 导出直接放
`assets/*.json` 即可——`file://` 下的 XHR 本来也会被浏览器拦掉。

图标只在承担信息时用（方向、状态、来源），不要当装饰。完整的授权清单、以及 Tabler / Phosphor /
Simple Icons 各自能不能进这条流水线，见 [references/libraries.md](references/libraries.md) §2。

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
  "duration": 24.0,
  "scene": "scenes/take.html",
  "libs": ["lucide", "anime"],       // 可选：vendored 进 assets/lib 的浏览器库
  "hold": [[6.0, 11.0]],              // 这几秒画面真的不变，渲染器复用一帧
  "data": { "title": "…", "caption": "…" },
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

- **整片是一个镜头**：`duration` 是总时长，`scene` 是唯一那个场景文件；没有 `segments`，没有
  `timeline`，没有转场——换场是镜头内的变换（见 [references/choreography.md](references/choreography.md)）。
- **静止要声明**：`hold` 列出的区间渲染器只渲一帧、其余复用。没声明的静止会被验收算成死拍。
- **数据随便放**：`data` 里写什么，场景里就通过 `window.SCENE` 读什么；技能不规定字段。
- **素材**：`assets` 里的相对路径按工程目录解析；图片也可写成 `{ "prompt": "…" }` 交给
  `imagegen` 生成。
- **多镜头是例外**：只有混剪（`vs.py montage`）用 `timeline` 拼 `source` 片段，因为那本来就是
  多镜头。

---

## 场景：整片就是一个文件

**技能不分段。** 一个项目 = 一个场景文件 + 一个总时长，整片从 t=0 连续到结束：

```jsonc
{ "name": "我的片子",
  "video": { "width": 1920, "height": 1080, "fps": 30, "crf": 20 },
  "duration": 24.0,
  "scene": "scenes/take.html",
  "hold": [[6.0, 11.0]],                    // 这几秒画面真的不变，渲染器复用一帧
  "data": { "title": "…", "caption": "…" } }
```

三条硬约束（不满足就没法逐帧渲染）：**离线**、**`seek(t)` 是 t 的纯函数**（不能有
`requestAnimationFrame`、`Date.now()`、CSS transition）、**同一个 t 必然同一帧**。

作者只需要写 `seek(t)`。`Scene` / `Anim` / `Kit` 三个运行时由渲染器注入，场景文件里不用
`<script src>`——因为场景会被复制进工程，任何相对路径都会断。可用的接线：

```js
const S = Scene.mount({ background: "#0b0d0c" });  // 或什么都不传
const layer = S.layer("type");
Scene.type(el, 0.16, { weight: "600", color: "#f2f4f1" });  // 字号按短边比例，720p 到 4K 都成立
const box = Scene.safe();       // 竖向安全区：顶部 6% / 底部 12%
Scene.ready();                  // 置 __sceneReady
window.seek = (t) => { /* 全部画面都是 t 的函数 */ };
```

**换场不靠剪辑**，只有四种手法：移出/移入、把一件东西变成下一件、用画面里的元素横扫替换、
一次明暗呼吸。怎么编排、有哪些闸门，见 [references/choreography.md](references/choreography.md)。

`vs.py init 我的项目 --duration 20` 会生成一份配置 + 一个空白场景（只有管线，没有任何设计）。

## 编排规则：每支片子现写画面，不要套模板

[references/choreography.md](references/choreography.md) 是这个项目的编排规范。它只解决一件事：
**技能不再提供模板：原来的七个骨架已经删除。** 现在的流程是每一拍现写一个场景文件，
`seek(t)` 与 `Scene`/`Anim`/`Kit` 的接线由渲染器负责。同一套骨架出现在第二支片子里，它就是 AI 味。

立论是可测量的：模板复用的失败形态是**静帧没设计** —— 关掉动效看那一帧，如果它只是
"居中大标题 + 一行副标题"，那这支片子的画面从来就没被设计过。所以规范里最重要的一条闸门是
**静帧闸门**：先让这一帧在不动的时候能站住，再让它动起来。

文档里有什么：

- **七步编排流程**：定沟通任务 → 选宏观结构 → 抽取主题的物理 → 发明签名机制 →
  定视觉系统 → 逐拍编排 → 两遍批判
- **五种宏观结构**（单一场景 / 幕 / 编辑式 + 定点节目 / 索引 / 单屏仪器）与它们各自适合什么
- **六个生成算子**（直译物理 / 输入反转 / 维度替换 / 介质想象 / 杂交 / 破坏规则），
  用来给每一支片子发明一个"只属于这个题目"的机制
- **视觉硬数字**：色彩三档 60/30/10、字号跳跃 ≈ 8×（获奖作品实测中位数）、
  版式双峰不要居中列、一个构成而不是一堆面板
- **动效 token**：时长档位、缓动字典（带 cubic-bezier 数值）、弹簧档位、错开档位、变换预算
- **十二条时间轴铁律**：死拍是几层平台期撞在一起、一个窗口只放一件事（淡入会吃掉同窗口
  的一切）、零速度关键帧后面必然有死拍、装置不能比内容活得久、每一拍都要有一张 money
  frame、灵动 vs 飘是静止比例问题
- **查重表**：现在已经用滥的骨架（大数字 + 小标签、三栏卡片、终端打字、满屏淡入淡出……），
  换片子前先查一遍，用完把新机制写回去
- **闸门**：静帧闸门、AI 味清单（A1–A8 / B1–B8）、多样性与死拍闸门（跑 `plan` 看
  `adjacent_layout_repeats` 和 `choreography.worst_gap`）

规则不是凭空写的：它们是从动效网页设计的「不用模板编排自定义设计」「AI 味闸门」
「多轨时间轴编排」「动效 token」，前端设计的「每页一个签名、两遍批判」，以及演示文稿设计
的「一页一个主张、一个构成而不是一堆面板」里挑出来、改写成视频语言的，§10 里逐条标了出处。

---

## 旁白：让时长跟着语音走

写一份纯文本台词。单镜头里，整镜时长由念完这段台词的时间决定：

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
2. **把整镜时长设为"念完这段台词的时间 + 前后留白"**；
3. 把各句拼成一条连续音轨（按时间点插入静音）；
4. 生成同步 SRT 并烧进画面。

于是"画面比台词长""台词没说完画面就切了"这类问题从根上消失。台词改动后重跑 `narrate` 即可，
语音按内容哈希缓存，不会重复合成。

> 目前语音合成走 Windows 的 SAPI，其他系统可自行录音或接外部 TTS，把音频挂到 `audio.tracks`。

---

## 长视频（5 分钟以上）

**成本 = 要渲染的帧数 = 时长 × 帧率 − hold 内的帧，再除以 `slices × jobs`。** 单镜头默认单进程，
要并行得显式加 `--slices N`；5 分钟 1080p/30fps 是 9000 帧（未扣 hold），具体墙钟用
`vs.py plan` 按你的机器估。以前可以靠"静态段落"省钱，现在没有段落了，改成在**镜头内部**声明静止：

```jsonc
"duration": 300,
"hold": [[12.5, 26.0], [58.0, 96.0], [140.0, 205.0]]
```

hold 里的帧是复用的，所以那几秒在成片里照样存在，但只花一帧的成本。5 分钟片的经验值：
**真正在动的秒数压到 90 秒以内**，其余全部 hold；用 `vs.py plan` 看 `frames_to_render` 与每段
`hold` 的拆分。还是太贵就降规格：1280×720 约减半，`fps: 24` 再省五分之一，像素风（320×180）
约快 15 倍。

结构上，5 分钟的单镜头依然要有节奏，只是不靠切：目标 **8-12 个内部章节**，每章一次真正的
画面重构（不是"淡入更多字"），配上章节标签与全局进度条。细节见
[references/longform.md](references/longform.md)。

## 混剪（唯一允许分段的形态）

混剪按定义就是多镜头，所以它是这套"一镜到底"规则**唯一**的例外：素材是现成片段，镜头长度由
音乐决定。其余所有项目都走单镜头。

## 像素风

```jsonc
"look": { "pixelate": { "scale": 4, "colors": 16, "dither": "none" } }
```

- 渲染分辨率自动变为 `宽/scale`，再由 ffmpeg 用最近邻整数倍放大；
- 想要像素精灵：先用 `vs.py sprite assets/subject.png` 转出来，再把结果当普通素材传给场景；
- 动作必须落在整数像素上，否则放大后会抖动；
- 预设配色见 `assets/palettes.json`：`pixel16`、`gameboy`（配 `colors: 4`）、`mono`（配 `colors: 2` + `dither: "bayer"`）。

---

## 手艺层：动画 / 演示 / 版式三套规则

[references/craft.md](references/craft.md) 是编排规则的**手艺层**——编排讲一支片子怎么走，
这份讲每一帧和每一次运动怎么做对，来源是动画与设计领域的经典教程，并且逐条转成了可检查的形式：

- **动画十二原则**（挤压拉伸、预备动作、跟随与重叠、弧线、慢入慢出、二次动作、时间、夸张…）
  翻译成本管线里的检查项，并补上"同时有 3 个以上东西在动"这类反例
- **演示设计四原则**（对比 / 重复 / 对齐 / 亲密性）加上断言式标题、一屏一个主张、
  数据墨水比、故事线 SCQA、图表的四条硬规则
- **版式与前端设计**：三分 / 九宫格 / 三角形 / Z 形 / 留白、8pt 网格、模块化字号阶梯、
  4-8× 字号跳跃、对比度阈值、安全区、格式塔分组，以及"居中一切"这类反例清单
- **三条可直接投喂的提示词**：用十二原则审运动、用四原则审一屏、用构图法审版式

凡引用之处都在文件末尾标了出处（书与作者），文件本身是重新组织的检查表，不是原文摘录。

## 快手线与自检工具

`scripts/` 下与 `vs.py` 并列的四个工具：

| 工具 | 用途 |
| --- | --- |
| `scaffold.py` | 从 `assets/starter/` 生成可渲染工程：管线直接复用，只写这一支的构成；style seed 按工程名派生，可复现 |
| `qc_video.py` | 批量抽帧 + 分区墨量 + ASCII 出图：在没有图像输入的环境里也能“看”画面，并抓出“渲染成功但内容是空的” |
| `taste_check.py` | `--rhythm` 给节奏指标与柱状图（冻结帧比例、最长死拍、每秒变化、p90/均值）；`--stills` 给构图指标（留白、重心偏离、对称度、墨团、安全区） |
| `beat_audit.py` | 审 `data.beats` 的交接：GAP / 弱交接 / 动作过长 / 内部空档，并打出时间轴图 |

```bash
python scripts/scaffold.py ./my-video --name my-video --duration 10
python scripts/beat_audit.py my-video/project.json      # 渲染前：交接不过就别渲
python scripts/qc_video.py --project my-video --times 2,4,6
python scripts/taste_check.py my-video/my-video.mp4     # 渲染后：节奏 + 构图
```

三份配套文档：`references/taste.md`（审美闸门与 AI 味黑名单）、`references/rhythm-handoff.md`（“PPT 感”的三个根因与解法）、`references/motion-realism.md`（7 行运动设定、12 条真实感钩子、情绪→参数）。

## 高级技法提示词库

[references/prompts.md](references/prompts.md) 是一份可以直接投喂给 AI 的提示词库（中文），
覆盖三类“高级”内容：

- **色彩与色阶**：chroma-js / colorjs.io / culori / d3-scale 的选型与授权，sequential /
  diverging / qualitative 三种色阶，LCh 感知均匀插值，对比度与色盲校验。另外把容易混淆的
  **视频侧色阶**（有限/全范围、`zscale`、HDR→SDR）分清楚——那些是 ffmpeg 滤镜链的活。
- **外接动效动画库**：Lottie / Rive / Theatre.js / GSAP / anime.js / Three.js / PixiJS
  的授权（已逐条核对）与“能不能按时间求值”的筛选标准，离线 vendor 流程，以及这个项目
  踩过的坑：`file://` 下 `mask-image` 被当跨域、rAF 破坏帧精确、wasm 路径、字体回退、
  体积与署名。
- **设计与分镜**：分镜表字段与 `brief` 字段的对应关系、镜头语言与构图清单、色彩脚本与
  视觉母题、节奏安排，以及“审一遍分镜哪里会让人看不懂”这类质检提示词。

整份文件只有一句硬判断：**能被 `seek(t)` 驱动的库才能进场景，而且它的 dist 必须随仓库
走——渲染过程不联网。**


## 自动验收（这工具最值钱的部分）

`verify` 会解码成片并测量：

| 检查项 | 能抓出的问题 |
| --- | --- |
| `duration` | 转场偏移算错、段落丢了或重复 |
| `resolution` | 渲染尺寸不对、被静默缩放 |
| `content` | 全黑、素材没加载进来 |
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
不用。缓存键包含场景文件内容、数据、素材修改时间和输出规格；加了 `--slices N` 后每个时间片
各有缓存键，渲染器还会用降采样的签名探针找出真正变化的切片，只重渲那些切片。
强制重渲加 `--force`。

**中间文件在哪？能删吗？**
`build/<项目名>/` 下：`segments/` 是中间片段（`--slices` 时是各时间片），`voice/` 是旁白和字幕。
删掉可省空间，代价是下次要重渲。
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
├─ API.md                   CLI / 库 / 注入 API 索引（自动生成）
├─ AUDIT.md / PLAN.md       改造审计与计划（历史文档）
├─ UPGRADE.md               改造增量与实测（历史文档）
├─ agents/openai.yaml       界面元数据
├─ assets/
│  ├─ starter/               可复用工程骨架（场景管线 + 工程模板）
│  ├─ scenes/_blank.html    空白场景骨架（只有管线，没有任何设计）
│  ├─ palettes.json         配色预设
│  ├─ lib/                  vendored 浏览器库（lucide / lottie / anime / three + 各自 LICENSE）
│  ├─ examples/             参考示例（director 语法演示）
│  └─ runtime/              注入运行时：scene / anim / kit / three-kit / director
├─ references/
│  ├─ pipeline.md           原理、失败模式、性能数据
│  ├─ longform.md           长视频工作流
│  ├─ formats.md            各种形态的做法
│  ├─ prompts.md            高级技法提示词库（色彩色阶 / 外接动效库 / 设计分镜）
│  ├─ creative.md           规划、视觉差异化与图片生成
│  ├─ craft.md              动画 / 演示 / 版式三套手艺规则（中文）
│  ├─ libraries.md          值得用的库与授权 / 离线约束（中文）
│  ├─ choreography.md       编排规则：每拍现写画面，不套模板（含闸门与查重表）
│  ├─ taste.md              审美闸门：比例/字号/色彩预算/参照体系/AI 味黑名单
│  ├─ rhythm-handoff.md     “PPT 感”的三个根因与解法（重叠交接 / 共享元素 / 缩短整帧动作）
│  ├─ motion-realism.md     7 行运动设定、12 条真实感钩子、情绪→参数
│  ├─ three-d.md            2D × 3D：WebGL 图层 / CSS3D / Canvas 贴图的组合方式
│  └─ guide-zh.md           中文速查
├─ scripts/
│  ├─ vs.py                 命令行入口
│  ├─ render_segment.mjs    逐帧渲染器
│  ├─ scaffold.py           从骨架生成工程
│  ├─ scan_scene.mjs        场景 DOM/几何探针（check 与 preview --report 用）
│  ├─ scene_check.py        全时间轴自检的分析层
│  ├─ api_index.py          生成 API.md / api_index.json
│  ├─ apply_patch.py        哈希校验的多处修改器（失败整批回滚）
│  ├─ qc_video.py           抽帧 / 分区墨量 / ASCII 出图
│  ├─ taste_check.py        节奏（--rhythm）与构图（--stills）测量
│  ├─ beat_audit.py         交接审计 + 时间轴图
│  └─ lib/                  运行时探测、渲染编排、库注入（libs.py）、剪辑装配、验收、TTS、混剪等
└─ vendor/                  ffmpeg（`doctor --install-ffmpeg` 按需落盘，GPL 构建；.gitignore 已忽略）
```

---

## 授权

代码采用 MIT（见 `LICENSE`）。源码仓库不包含 ffmpeg 与 Chromium（`vendor/` 被 `.gitignore` 排除），
本机安装时按需落盘。

`assets/lib/` 下随仓库分发四个可选的浏览器库：Lucide（ISC）、lottie-web（MIT）、anime.js（MIT）、
three（MIT）；d3-scale（ISC）用 `vs.py libs --install d3-scale` 按需落盘。每个库目录都带自己的
`LICENSE` 与记录包名/版本/来源/sha256 的
`manifest.json`；它们都是宽松许可，可随本项目一起分发。GSAP 这类“免费但非 OSI 开源”的库不默认落盘。

- ffmpeg 由 `vs.py doctor --install-ffmpeg` 按需安装，该构建启用了 libx264，属 **GPL**。
  若你要把它随商业产品一起分发，请先评估 GPL 义务，或改用 LGPL 构建。
- Chromium / Playwright（BSD）、Node.js（MIT）、Python（PSF）均由用户环境提供。
- 场景只按名称引用系统字体。微软雅黑等系统字体不可随包分发，
  如需内嵌请换用思源黑体 / Noto Sans SC（SIL OFL）。
