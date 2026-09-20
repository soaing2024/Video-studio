# 变更日志

## 2026-09-21 — 全方位修复轮（分支 `codex/full-repair-2026-09-21`）

本轮来自一次逐行审阅（全量阅读约 9.5k 行代码 + 2.9k 行文档，并对三处怀疑做了复现实验）。
下面按"用户要求 → 正确性 → 诊断通道 → 接口面 → 内容管线 → 运行时 → 文档"分组。

### 用户新增的三条要求

1. **取消三候选比较机制，由代理自己选择结构。**
   `shots` 命令、`choreography.candidates()/candidates_human()` 及其 CLI 入口已删除；
   SKILL.md / README / `references/choreography.md` §1.5 / `references/motion-design.md` §2
   全部改写为"自己选一个宏观结构 + 一个生成算子，对四条闸门负责"，不再要求出对照稿。
   `API.md` / `api_index.json` 已重新生成（31 个命令，`shots` 不再出现）。
2. **默认永不切片。**
   `--slices` 默认值改为 `None`；`render.resolve_slices()` 规定：只有 `--slices N` 或
   `render.slices` 显式给出时才切片，否则无论多长都是单进程。`plan` 会明说
   "one process, one take (slicing is opt-in)"，不再主动建议切片；`deliver.card` 不再默认
   `slices: 4`；文档与示例同步。
3. **全程中文汇报进度**（过程要求，不体现在代码里）。

### 正确性（会产生静默错误结果或硬失败的部分）

- **增量复用不再造假。** `render_sliced` 过去只按帧签名决定复用，然后**用当前键覆盖旧切片的键**，
  于是"改了图片资产/编码参数/库，只要场景没改"就会复用旧画面并把错误写进缓存。现在必须
  **同时满足**：帧签名未变 **且** 非场景输入（资产、编码参数、库、尺寸、hold）未变，才复用并重新盖章；
  签名探针失败时降级为全量渲染而不是中断。
- **缓存键统一。** 段级键与切片键现在共用 `_inputs_fingerprint()`，并把 `render.crf` 与
  `encode_args()`（preset/jpeg/png-compression/gpu/reboot）纳入——过去改 crf 会命中旧片段。
- **切片帧数按累计帧索引分配。** `slice_ranges()` 改为 `bounds = round(i*total/n)`，
  每片帧数之和恒等于 `round(duration*fps)`。实测：4.0s@24fps÷5（96 帧，不能被 5 整除）通过；
  252.06s@30fps÷4 = 7562 帧分毫不差。旧实现在不整除时直接报
  "joined take has 95 frames, expected 96"。
- **`--incremental` 的签名探针**改为喂完整 payload（含 assets），不再只喂 `data`。
- **`apply_patch` 的语法检查移进事务**：语法失败现在会真正回滚（旧代码在 `apply_edits` 提交之后
  才检查，回滚只存在于事务内部，于是提示写着"已回滚"而文件是坏的）。
- **`install_ffmpeg`** 的 pip 目标目录改为循环结束后清理一次：旧代码在第一次候选不合格时就删掉
  整个 wheel，后续候选根本没机会被尝试。
- **`spec.py`：`duration:"auto"` + `hold` 不再必然报错**（auto 时只校验形状，范围留到 narrate 之后）；
  validate 新增 hold 区间与最终时长的核对；`still: true` 的建议改为对单镜项目推荐 `hold`。
- **`compile --force` 真正生效**（内部二次校验会把它吃掉）。

### 诊断通道（"用数字代替眼睛"的那条路）

- **DOM 探针取"第一个不透明祖先背景"**（`effectiveBg`，必须定义在 `PROBE` 内部——`page.evaluate`
  只序列化函数自身）。实测：深底浅字的小字幕（真实对比度约 7:1）过去被判 `low_contrast`，现在通过。
- **analyze 增加极性判定**：`frame_stats` 读画面自身的中位亮度决定"墨"的方向，深底片不再 100% ink，
  `frame_nearly_empty` 对深底片恢复有效；ASCII 图的明暗也随之翻转。
- **`scene_check` 的 CJK 回退检测修好**：校准页的两行同文案文字过去被以 text 为键的 dict 折叠成一条，
  `len(widths) >= 2` 永假，这道门从未触发；现在按元素 id 取。同时实现了一直是 `None` 的
  `bilingual_scale`（并新增 `type_scale_collapsed` 问题类型）。
- **`scene_check.calibrate` 不再泄漏临时目录**（`try/finally`；此前 `%TEMP%` 里累积了 77 个
  `vs-calib-*`，实测修复后不再增长）。
- **`scan_scene.mjs` 的 rAF 加了 40 ms 超时兜底**（与 `render_segment.mjs` 一致），避免
  `vs.py check` 在合成器卡死时永久挂起。
- **`check` 改为喂完整 payload**，与真实渲染一致（读 `SCENE.assets.*` 的场景不再在 check 里拿到 undefined）。
- **`beat_audit` 的"弱交接"从脚注升级为失败**（`problems`），与文档声明的"必须重叠"一致。

### 接口面（宣称与实现不一致的部分）

- **死参数接通**：`--preset / --jpeg / --reboot / --no-gpu / --incremental` 现在通过
  `_render_overrides()` → `render.apply_render_overrides()` 真正生效，`plan` 的估算与 `render` 用同一份配置。
- **`--quiet` 修复**：`run` 的两个日志分支过去逐字相同，`--quiet` 完全无效；现在静默并把
  `[1/3][2/3][3/3]` 进度行一并关闭。
- **`plan` 恢复 style/choreography 判决**（v2 曾丢失），新增 `advisories`；同时修掉低磁盘分支的
  复制粘贴文案、恢复从帧数里扣除 hold 帧。
- **`style.remember()` 接通**（`assemble` / `run` 成功后记录视觉方向），`closest_past_project`
  不再恒为 null；顺带修掉单镜项目"distinct layouts ≥ 2"的假判决。
- **ffmpeg 解析统一**：`taste_check.py` / `qc_video.py` 不再硬编码 `ffmpeg-win-x86_64-v7.1.exe`，
  改走 `runtime.find_ffmpeg()`（带 PATH 兜底）；`find_ffmpeg` / `find_playwright` 进程内缓存
  （后者过去每个切片子进程都要遍历一次插件目录）。
- **注释剥离器统一**为 `scripts/lib/jsonc.py`（spec.py / scaffold.py / design_audit.py 共用），
  并保留空行，使 JSON 报错行号与作者文件一致。
- **api_index 修复**：`js_surface` 过去只收 `key: value` 形式，ES6 简写全被丢掉，生成的
  Scene/Anim/Kit 表面**一直是空的**；现在能抓简写与 `global.X.y =` 形式的成员，并覆盖
  Phys / Look / D；`render_flags` 不再把 `import.meta.url` 当成 `--url`。

### 内容管线

- **逐章旁白**：`compile` 现在为每一章生成一条带绝对时间锚点（`at` + `chapter`）的台词；
  `narrate` 逐条合成、按锚点摆放、自动补静音；朗读超出该章时隙时记录并顺延（不写重叠样本）；
  最后**用真实语音位置回写章节表**（`chapters_updated`），让画面、语音、字幕共用同一时钟。
  实测 3 句脚本：SRT 3 条独立字幕、声道 12.91s、章节表 0.0/4.25/8.25、take 12.9s。
  旧实现把整篇口播拼成一句，产出一条覆盖全片的巨型字幕。

### 运行时（注入给场景的 JS）

- `kit.bandSwapper` 去掉 `setTimeout`（改为同步写 DOM）——运行时里唯一一处墙钟副作用。
- `phys` 的 `MAX_BAKE` 30s → 900s，并返回 `clamped`；`spring` 的 `settled` 改为真实的尾部收敛判定
  （过去恒为 `true`，长镜头会在第 30 秒静默冻结）。
- `look.draw` 的 `spriteScale` 过去两个分支同值、选项无效，现在真正生效。

### 文档

- SKILL.md / README.md / `references/{choreography,motion-design,guide-zh,pipeline,longform}.md`
  与 `scripts/scaffold.py` 的失效指引（`references/motion-prompts.md` → `references/motion-realism.md`）
  全部同步；README 的缓存 FAQ 不再暗示"自动只重渲变化切片"。
- `API.md` / `api_index.json` 重新生成。

### 本轮已知未做

- `_inject_common` 仍在运行期给子命令补参数（"参数表分散在两处"的结构性隐患）。本轮已让两处
  一致并接通全部参数，但彻底改写为 `parents=` 参数族属于高风险重构，留给下一轮。
- `Anim` 段里的 `stagger` 字段仍未使用（文档教的错开方式是按元素偏移 `at`，不影响行为）。
- `motion-physics.md` 等文档中的 `Phys.bake` 上限说明未逐处更新（代码已改）。
