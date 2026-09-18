# 中文速查（给人看的）

这套工具把「写代码做视频」固化成了四步：**看素材 → 写配置 → 试一帧 → 出片并验收**。

## 一次性准备

```powershell
python <skill>\scripts\vs.py doctor --install-ffmpeg
```

`--install-ffmpeg` 会把一个完整的 ffmpeg 装进技能的 `vendor/` 目录（约 84MB，装一次即可）。
为什么必须装：Playwright 自带的 ffmpeg 只能编 VP8，编不了 H.264，`doctor` 会主动把它判为不合格。
装完 `vendor/pylibs` 是 pip 留下的副本，可以手动删掉省空间。

## 四个命令

```powershell
# 1. 看素材：尺寸、透明通道、主色、时长、音量
python vs.py probe 我的图.png 我的音乐.mp3

  # 2. 新建项目（生成配置 + 一个空白场景，写它才是创作本身）
  python vs.py init 我的项目 --duration 20

# 3. 试一帧：改完配置先看单帧，几秒钟就有结果
python vs.py preview 我的项目\project.json --segment title --at 2.5

# 4. 出片：渲染 + 剪辑 + 验收
python vs.py run 我的项目\project.json --jobs 3
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

渲染速度参考（1080p、30fps）：逐帧约 0.38 秒/帧，`jobs: 3` 时五分钟片约 20 分钟；
像素风（320×180 渲染再 4 倍放大）约 0.025 秒/帧；hold 区间几乎不花时间。
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

## 出片前检查

1. `verify` 全绿：时长、分辨率、内容、淡入淡出、色板、音量。
2. 每个章节抽一帧看一眼，不要只看第一帧。
3. 章节编号 1..N 连续，和最后一段里的 `total` 对得上。
4. 相邻两段背景太像的话，接缝会像失误，给个 0.4-0.6 秒交叉淡化。

## 常见坑

- 改完场景重跑即可；整片是一个缓存单元。
- 想强制重渲加 `--force`。
- 中间片段在 `build/<项目名>/segments/`，删掉可以省空间，代价是下次要重渲。
- 技能目录里的 `vendor/` 是 ffmpeg，别删；`build/` 才是可以清理的。
