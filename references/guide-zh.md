# 中文速查（给人看的）

这套工具把「写代码做视频」固化成了四步：**先对话问清 → 确认方案 → 写配置 → 一次出片并验收**；`preview` 只是非必要不动用的例外。

## 三条使用约定（AI 代理必须遵守）

**一、不要拿到需求就创作。** 代理要先和你来回沟通几轮，把受众、平台、时长、语气、旁白、配乐、现成素材、品牌规范和参考喜好问清楚；每轮复述“已定 / 未定”。

**二、交付完整方案并等你确认。** 确认前不建工程、不 compile、不生成图片、不渲染。确认后才开写，而且**一次编写、一次渲染、直接导出**。

**三、非必要不 preview。** 默认不试帧。设计取舍在方案里定（构图、字号跳跃、色彩预算、素材是否齐备）；只有纸面判断不了的具体疑问，才渲那一帧去回答它，不做逐拍试帧。

## 一次性准备

```powershell
python <skill>\scripts\vs.py doctor --install-ffmpeg
```

`--install-ffmpeg` 会把一个完整的 ffmpeg 装进技能的 `vendor/` 目录（约 84MB，装一次即可）。
为什么必须装：Playwright 自带的 ffmpeg 只能编 VP8，编不了 H.264，`doctor` 会主动把它判为不合格。
安装脚本会把二进制复制到 `vendor/` 后删掉 `vendor/pylibs`；若你看到残留的 `vendor/pylibs`，
可以放心手动删除（`doctor --install-ffmpeg` 会按需装回）。

## 出片流程（都发生在方案确认之后）

```powershell
# 1. 看素材：尺寸、透明通道、主色、时长、音量
python vs.py probe 我的图.png 我的音乐.mp3

# 2. 新建项目（生成配置 + 一个空白场景，写它才是创作本身）
python vs.py init 我的项目 --duration 20

# 3. 先自检与预算，不花渲染时间
python vs.py check 我的项目\project.json
python vs.py plan  我的项目\project.json --slices 6 --jobs 3

# 4.（可选，非必要不做）纸面判断不了的疑问才渲一帧
python vs.py preview 我的项目\project.json --at 2.5

# 5. 出片：渲染 + 剪辑 + 验收（一次成片）
python vs.py run 我的项目\project.json --slices 6 --jobs 3
```

`run` 会打印一份 JSON 验收报告。**任何一项 `ok: false` 就说明有问题**，`detail` 会告诉你该调哪个参数。
退出码非 0 表示验收没通过。

## 画面：没有模板，只有场景

技能不分段，也不提供画面模板。**一个项目 = 一个场景文件 + 一个总时长**，整片一镜到底：

```jsonc
"duration": 24.0,
"scene": "scenes/take.html",
"hold": [[6.0, 11.0]]      // 这几秒画面不变，复用一帧
```

写一个 HTML：`window.seek(t)` 是 t 的纯函数，数据从 `window.SCENE` 读。`Scene` / `Anim` / `Kit`
由渲染器注入（**不要写 `<script src>`**）。换场不靠切，只有四种：移出/移入、变换、横扫、明暗呼吸。
规则与闸门见 [choreography.md](choreography.md)。

## 长视频的关键：hold

五分钟是一个镜头，不是 20-40 个段落。唯一省钱的杠杆是声明静止：

```jsonc
"duration": 300,
"hold": [[12.5, 26.0], [58.0, 96.0]]
```

hold 里的帧渲染器直接复用，**成本与时长无关**。经验值：5 分钟片把"真在动"的秒数压到 90 秒以内，
其余全部 hold；用 `vs.py plan` 看 `frames_to_render`。

渲染速度别背数字：`vs.py plan` 会按你的机器、分辨率与 hold 拆分给出 `ms_per_frame` 与墙钟估计。
单镜头默认是单进程，加了 `--slices N --jobs M` 才会按时间切片并行（合并时校验总帧数）。
像素风（320×180 渲染再整数倍放大）与 hold 区间仍是两个最有效的省钱手段。

## 常用搭配

**换风格**：`look.accent` 改主色；像素风加 `"pixelate": {"scale": 4, "colors": 16}`；
调色用 `"grade": {"saturation": 1.1}`。

**配乐和旁白**：

```jsonc
"audio": { "tracks": [
  { "src": "assets/voice.wav", "at": 1.0, "gain_db": -3 },
  { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true }
] }
```

`gain_db` 是相对原文件电平的增减。先用 `probe` 看原文件多少 dB，再决定减多少：
人声目标 -18 ~ -12 dB，配乐 -38 ~ -28 dB（比人声低 15-20 dB）。
注意 `amix` 会按轨道数做归一化，每加一条轨道整体大约再降 6 dB，加完要复验。

**字幕**：写一份 SRT，挂到 `subtitles.src`，会用 `subtitles` 滤镜烧进画面，中文样式示例：

```jsonc
"subtitles": { "src": "assets/subs.srt",
  "style": "FontName=Microsoft YaHei,FontSize=30,OutlineColour=&H80000000,BorderStyle=1,Outline=2,MarginV=36" }
```

**混剪**：给音乐打点，再让剪辑点落在节拍上。

```powershell
python vs.py beats assets/track.mp3 --cuts 45 --min-len 0.8
```

返回的 `cuts` 就是一串时间点。**这是混剪专用的分段写法**（其余项目都是一镜到底）：

```jsonc
"timeline": [
  { "source": "assets/clip01.mp4", "trim": [4.2, 6.9] },
  { "segment": "title-a", "transition": { "type": "fadeblack", "duration": 0.2 } }
]
```

## 图标、动效与 3D（可选）
**图标与动效库**：工程里写 `"libs": ["lucide", "lottie", "anime"]`，渲染器会把库注入页面，场景里不用写 `<script src>`。

```js
const icon = Scene.icon("arrow-right", { size: 64, color: "#e0455f" });   // 图标是 DOM，无字体、无联网
const box  = Anim.lottie(host, SCENE.assets.motion, { fps: 30 });        // AE/Bodymovin 导出放 assets/*.json
const tl   = Anim.timeline(3, (t) => t.add(el, { x: [0, 200], duration: 2000 }));
window.seek = (t) => { box.seek(t % box.duration); tl.seek(t); icon.style.transform = `translateX(${t * 40}px)`; };
```

**3D**：`"libs": ["three"]` 装一次（`python vs.py libs --install three`），然后

```js
const view = Scene.three({ background: "#080a0b" });   // WebGL 图层
view.scene.add(mesh); view.environment(); view.bloom({ strength: .5 });
const css  = Scene.css3d();                            // 真 DOM 摆进 3D
const s    = Scene.surface(512, 320);                  // 2D 画布 → CanvasTexture
window.seek = (t) => { mesh.rotation.y = t; view.render(); css.render(); };
```

注意：WebGL 是软件渲染（实测 1280×720 + bloom 约 0.2 秒/帧），3D 也必须只按 `t` 求值。
四种 2D×3D 组合方式、镜头光照默认值与禁忌清单见 [three-d.md](three-d.md)。
已落盘：`lucide`（ISC，2108 图标）、`lottie`（MIT）、`anime`（MIT）；需要其他库先 `python vs.py libs --install <名字>`。
能自己用纯函数写出来的动效，仍然不要引库（规则与授权见 [libraries.md](libraries.md)）。

## 出片前检查

1. `verify` 全绿：时长、分辨率、内容、淡入淡出、色板、音量。
2. 交付前抽查每个内部章节的代表帧（这是交付检查，不是设计阶段的逐拍试帧）。
3. 章节编号 1..N 连续，和最后一段里的 `total` 对得上。
4. 单镜头内部的重构要重叠交接；混剪里相邻片段背景太像时，给 0.4-0.6 秒交叉淡化。

## 常见坑

- 改完场景重跑即可；缓存按分片与参数键控，未变化的部分会跳过。
- 想强制重渲加 `--force`。
- 中间片段在 `build/<项目名>/segments/`，删掉可以省空间，代价是下次要重渲。
- 技能目录里的 `vendor/` 是 ffmpeg，别删；`build/` 才是可以清理的。
