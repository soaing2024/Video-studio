# API.md — 不读源码就能用

由 `python scripts/api_index.py` 生成，请勿手改。完整签名见 `api_index.json`。

## 契约

- **场景**：an .html file exposing window.seek(t) as a pure function of t, then window.__sceneReady = true
- **项目**：project.json: {name, video{width,height,fps,crf,preset}, duration, scene, libs[], data{}, audio{tracks[]}}
- **一次生成**：the deliverable is rendered once; slicing `--slices N` splits ONE export across processes, it is not a second render

## 输出契约

- 任何命令加 `--json` → 恰好一个紧凑 JSON 对象。
- 失败形状：`{"ok":false,"error":{"code","where","expected","got","fix_hint"}}`。
- 长输出默认头尾各 20 行，`--verbose` 全量；`--quiet` 只留错误。

## 常见任务（复制即用）

### doctor — 

```bash
vs.py doctor --install-ffmpeg
```

### preview — 

```bash
vs.py preview work/mine/project.json --at 2.75,7.9 --report
vs.py preview work/mine/project.json --at 12.9 --report --ascii 90
```

### check — 

```bash
vs.py check work/mine/project.json --json
```

### plan — 

```bash
vs.py plan work/mine/project.json --json
```

### render — 

```bash
vs.py render work/mine/project.json --slices 8 --jobs 4
vs.py render work/mine/project.json --incremental --json
```

### assemble — 

```bash
vs.py assemble work/mine/project.json --out outputs/film.mp4
```

### verify — 

```bash
vs.py verify work/mine/project.json --video outputs/film.mp4 --json
```

### run — 

```bash
vs.py run work/mine/project.json --slices 8 --jobs 4 --json
```

### init — 

```bash
vs.py init work/mine --duration 30
```

### patch — 

```bash
vs.py patch edits.json
python scripts/apply_patch.py edits.json --json
```

### audio — 

```bash
vs.py audio work/mine --cues cues.json
vs.py audio work/mine --check
```

### card — 

```bash
vs.py card work/mine --title 'Star it.' --cn '去点亮 Star'
```

### api — 

```bash
python scripts/api_index.py
vs.py api preview
```

### sfx — 

```bash
vs.py sfx "whoosh transition" --top 8
vs.py sfx --get 12345 --out assets/sfx --name whoosh-01
```

## 场景里可用的注入 API

- `Scene`: ``
- `Anim`: ``
- `Kit`: ``
- `flags`: `crf`, `data`, `debug`, `duration`, `ffmpeg`, `fps`, `gpu`, `height`, `hold`, `jpeg`, `out`, `preset`, `probe`, `progress`, `ready_timeout`, `reboot`, `runtimes`, `scale`, `scene`, `sig`, `still`, `url`, `width`

## 命令一览

| 命令 | 用途 | 主要参数 |
| --- | --- | --- |
| `doctor` |  | `--install-ffmpeg`, `--verbose`, `--quiet`, `--limit` |
| `probe` |  | `--verbose`, `--quiet`, `--limit` |
| `libs` |  | `--install`, `--verbose`, `--quiet`, `--limit` |
| `sprite` |  | `--out`, `--width`, `--height`, `--colors`, `--alpha-cutoff`, `--verbose`, `--quiet`, `--limit` |
| `beats` |  | `--sensitivity`, `--min-gap`, `--cuts`, `--min-len`, `--verbose`, `--quiet`, `--limit` |
| `sfx` |  | `--get`, `--token`, `--access-token`, `--test`, `--licence`, `--top`, `--sort`, `--min-dur`, `--max-dur`, `--out`, `--name`, `--quality`, `--kind`, `- |
| `init` |  | `--name`, `--duration`, `--verbose`, `--quiet`, `--limit` |
| `render` |  | `--jobs`, `--force`, `--seed`, `--verbose`, `--quiet`, `--limit`, `--slices`, `--preset`, `--jpeg`, `--reboot`, `--incremental`, `--no-gpu` |
| `assemble` |  | `--out`, `--verbose`, `--quiet`, `--limit` |
| `verify` |  | `--video`, `--samples`, `--verbose`, `--quiet`, `--limit` |
| `preview` |  | `--segment`, `--at`, `--seed`, `--out`, `--verbose`, `--quiet`, `--limit`, `--report`, `--ascii`, `--ascii-map` |
| `run` |  | `--jobs`, `--force`, `--skip-verify`, `--samples`, `--quiet`, `--seed`, `--verbose`, `--limit`, `--slices`, `--preset`, `--jpeg`, `--reboot`, `--incre |
| `style` |  | `--seed`, `--topic`, `--swatch`, `--like`, `--history`, `--verbose`, `--quiet`, `--limit` |
| `setup` |  | `--provider`, `--key`, `--base-url`, `--model`, `--size`, `--path`, `--presets`, `--test`, `--verbose`, `--quiet`, `--limit` |
| `brief` |  | `--script`, `--topic`, `--out`, `--name`, `--beats`, `--duration`, `--platform`, `--tone`, `--audience`, `--seed`, `--music`, `--voice`, `--image-size |
| `compile` |  | `--out`, `--music`, `--no-progress`, `--force`, `--verbose`, `--quiet`, `--limit` |
| `imagegen` |  | `--out`, `--size`, `--n`, `--negative`, `--from-project`, `--seed`, `--dry-run`, `--verbose`, `--quiet`, `--limit` |
| `voices` |  | `--verbose`, `--quiet`, `--limit` |
| `narrate` |  | `--script`, `--voice`, `--rate`, `--force`, `--verbose`, `--quiet`, `--limit` |
| `montage` |  | `--music`, `--out`, `--duration`, `--style`, `--title`, `--width`, `--height`, `--fps`, `--verbose`, `--quiet`, `--limit` |
| `plan` |  | `--seed`, `--verbose`, `--quiet`, `--limit`, `--slices`, `--jobs`, `--preset`, `--jpeg`, `--reboot`, `--incremental`, `--no-gpu` |
| `selftest` |  | `--jobs`, `--keep`, `--verbose`, `--quiet`, `--limit` |
| `rehearse` |  | `--verbose`, `--quiet`, `--limit`, `--at`, `--scale`, `--fps`, `--jpeg`, `--no-sheet` |
| `scrub` |  | `--verbose`, `--quiet`, `--limit`, `--out`, `--open` |
| `check` |  | `--verbose`, `--quiet`, `--limit`, `--stride` |
| `patch` |  | `--verbose`, `--quiet`, `--limit` |
| `audio` |  | `--verbose`, `--quiet`, `--limit`, `--cues`, `--out`, `--duration`, `--check` |
| `card` |  | `--verbose`, `--quiet`, `--limit`, `--title`, `--cn`, `--accent` |
| `api` |  | `--verbose`, `--quiet`, `--limit` |
| `cat` |  | `--verbose`, `--quiet`, `--limit`, `--lines`, `--cache-dir` |
| `diff` |  | `--verbose`, `--quiet`, `--limit` |
