# Format recipes

Every recipe here is a fragment for a **single take**: one scene, one duration, no cuts. What used
to be a cut is now a transformation inside the shot (see [choreography.md](choreography.md) §0).

## 一镜到底的四个通用手法

换场不靠剪辑，只有四种手段：

1. **移出 / 移入**：镜头移到让当前主体离开画面边缘，新主体从另一侧进来。
2. **变换**：画面里的一件东西变成下一件（数字滚成另一个数字、形状展开成结构）。
3. **横扫**：用画面内部的一个元素（色带、光带、手写字）横穿而过来替换内容。
4. **明暗呼吸**：一次快速压暗再亮起，等于一个软切；用多了廉价，用一次很有效。

其它三条纪律：

- **要有面积在动。** 运动指标是全帧平均，细线在 1080p 上几乎不可见（实测同一条 2px 的线：
  320×180 是 2.3/255，1920×1080 只有 0.72/255）。
- **一个窗口只放一件事。** 淡入会吃掉同窗口里的一切。
- **静止要声明**：`"hold": [[6.0, 11.0]]`，渲染器复用一帧；没声明的静止会被算成死拍。

## Short-form vertical（短视频）

```jsonc
"video": { "width": 1080, "height": 1920, "fps": 30 },
"duration": 30,
"scene": "scenes/take.html"
```

- 主体放在中间 60% 的高度里；顶部 12% 与底部 20% 会被平台界面和字幕压住。
- **钩子在开场 3 秒内**——不是"第一段要是钩子"，而是第 3 秒时必须已经给出结论。
- 一次只出现一行字，1080 宽输出用 60-80px。
- 20-45 秒一个镜头，从 t=0 到结束不停，中间靠上面四种手法换场。
- 字幕烧进画面（`subtitles`）比平台自动字幕更能留住人。

## Long-form explainer（5 分钟以上）

见 [longform.md](longform.md)。一句话版本：**一个镜头，内部切 8-12 个章节**，每章一次明确的
画面重构；大部分时间用 `hold` 声明静止，只让真正要动的地方动。

## Explainer with voice-over（解说视频）

同一个镜头，画面随口播推进：

- 一屏最多三条信息；超过三条说明这一屏该"换"了——用变换或横扫，不要切。
- 信息块用**替换**而不是堆叠：新的进来时旧的离开同一个位置。
- 旁白念长了要延长画面时，注意**成本线性增长**（帧数 = 时长 × 帧率）。如果那几秒画面本来就不
  变，把它写进 `hold`，成本才是零。
- 章节标签、进度条这类"脚手架"必须跟着内容一起退场，不要留在空画面上。

## Product / data motion graphics（数据与产品镜头）

- 别用"条形图依次生长"这个默认答案；让数字自己成为画面（大数字、刻度、对比）。
- 数字旁边要有刻度或参照物，否则观众读不出量级。
- 先交代单位与口径，再让数字动。

## Pixel style（像素风）

```jsonc
"look": { "pixelate": { "scale": 4, "colors": 16, "dither": "none" } }
```

- 渲染分辨率降到 `宽/scale`：1280×720 配 `scale: 4` 就是 320×180，**同时快约 15 倍**。
- 精灵先用命令行做出来，再当普通素材传给场景：`vs.py sprite assets/subject.png`。
- 预设配色见 `assets/palettes.json`：`pixel16`、`gameboy`（配 `colors: 4`）、
  `mono`（配 `colors: 2, dither: "bayer"`）。
- 动作必须落在整数像素上，否则放大后会抖动。
- 量化时钟（每秒 11-15 个新状态）比调缓动更能做出手绘 / 定格的手感。

## 混剪（唯一允许分段的形态）

混剪按定义就是多镜头，所以它是**例外**：素材是现成片段，镜头长度由音乐决定。

```bash
python vs.py montage 素材文件夹 --music 音乐.mp3 --out 混剪.json --duration 60 --style energy
```

生成的是普通工程（`timeline` 里是 `source` 条目 + 一张片头卡 / 片尾卡场景），可以接着手改。
切点落在节拍上：`vs.py beats 音乐.mp3 --cuts 45 --min-len 0.8`。

- 快节奏段镜头 0.8-1.5 秒，副歌 2-3 秒。
- 节拍上用硬切比任何溶解都强；`fade` / `fadeblack` 只留给段落转折。
- 每个渲染出来的卡片镜头本身也要简短：背景 + 一个在动的元素，不要在建画面。
- 冲击感靠调色：`"grade": { "saturation": 1.15, "contrast": 1.08 }`。
- 最后一刀落在拍子上，让音乐收完。

## 写场景（不是"选模板"）

没有模板可选。写一个 HTML：`window.seek(t)` 是 t 的纯函数，数据从 `window.SCENE` 读。
`Scene` / `Anim` / `Kit` 由渲染器注入，**不要写 `<script src>`**。工程里写
`"scene": "scenes/take.html"`（路径按工程目录解析）。渲染器会等 `window.__sceneReady !== false`。
怎么编排见 [choreography.md](choreography.md)。
