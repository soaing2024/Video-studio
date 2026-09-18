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

# 2. 新建项目（starter 模板不需要任何素材，直接能跑）
python vs.py init 我的项目 --template starter

# 3. 试一帧：改完配置先看单帧，几秒钟就有结果
python vs.py preview 我的项目\project.json --segment title --at 2.5

# 4. 出片：渲染 + 剪辑 + 验收
python vs.py run 我的项目\project.json --jobs 3
```

`run` 会打印一份 JSON 验收报告。**任何一项 `ok: false` 就说明有问题**，`detail` 会告诉你该调哪个参数。
退出码非 0 表示验收没通过。

## 三种画面模板

| 模板 | 适合 | 关键字段 |
| --- | --- | --- |
| `kinetic` | 开场、章节页、片尾；6-10 秒最好 | `eyebrow` `title` `subtitle` `rows` `callout` |
| `caption` | 解说、口播、长视频正文 | `chapter` `title` `rows` `caption` |
| `pixel` | 像素风；自动把图片转成精灵 | `title` `cn` `sprite` `rows` |
| `stat` | 大数字计数，短视频钩子 | `value` `decimals` `suffix` `label` |
| `quote` | 金句 / 停顿卡 | `quote` `author` `source` |
| `terminal` | 技术解说、代码演示 | `lines[{text,kind}]` `cards[{label,value}]` |
| `chart` | 数据条形图 | `chart{unit,max}` `series[{label,value,color}]` |

七个模板都认同一套字段，缺什么就跳过什么。要加自己的样式，就复制一份模板 HTML，
保持 `window.seek(t)` 这个约定、并在里面调用 `scene.seek(t, null)` 驱动动画元素即可。

## 长视频的关键：静态段落

五分钟视频 = 20-40 个段落。绝大多数段落其实是"一张图 + 一句话"，那就别逐帧渲染：

```jsonc
{ "id": "ch03", "template": "caption", "duration": 24.0,
  "data": { "still": true, "title": "第三步：交付", "caption": "把结论写成一句话。" },
  "assets": { "subject": "assets/fig03.png" } }
```

`"still": true` 只渲染一帧再用 ffmpeg 保持住，**成本与时长无关**。
实测：1080p 的 60 秒静态段落跑完只要 14 秒；如果逐帧渲染要 23 分钟。

渲染速度参考（1080p、30fps）：

- 逐帧动画：约 0.38 秒/帧，单人跑五分钟视频约 58 分钟，`jobs: 3` 约 20 分钟
- 静态段落：几秒
- 像素风（320×180 渲染再 4 倍放大）：约 0.025 秒/帧，五分钟视频约 4 分钟

所以长视频的策略是：**只让该动的地方动**，正文用静态段落，动效留给开场、章节切换和真正的演示。

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

返回的 `cuts` 就是一串时间点。真实素材和渲染段落可以混着排：

```jsonc
"timeline": [
  { "source": "assets/clip01.mp4", "trim": [4.2, 6.9] },
  { "segment": "title-a", "transition": { "type": "fadeblack", "duration": 0.2 } }
]
```

## 出片前检查

1. `verify` 全绿：时长、分辨率、内容、内容细节（该有字的段落真的画出了字）、淡入淡出、色板、音量。
2. 每个章节抽一帧看一眼，不要只看第一帧。
3. 章节编号 1..N 连续，和最后一段里的 `total` 对得上。
4. 相邻两段背景太像的话，接缝会像失误，给个 0.4-0.6 秒交叉淡化。

## 常见坑

- 改完 `project.json` 直接重跑即可，**没改动的段落会命中缓存**，只有改过的重渲。
- 想强制重渲加 `--force`。
- 中间片段在 `build/<项目名>/segments/`，删掉可以省空间，代价是下次要重渲。
- 技能目录里的 `vendor/` 是 ffmpeg，别删；`build/` 才是可以清理的。
