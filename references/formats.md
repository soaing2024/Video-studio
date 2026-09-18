# Format recipes

Pick the row that matches the job, then adjust. Every recipe is a spec fragment, not a new tool.

## High-energy montage (高燃混剪)

Goal: cuts land on the music, energy never drops, the file stays short (15-60 s).

```bash
python vs.py beats assets/track.mp3 --cuts 45 --min-len 0.8
```

The result is a list of timestamps. Build the timeline from them, either by cutting real footage with
`source` entries or by cutting between rendered segments:

```jsonc
"timeline": [
  { "source": "assets/clip01.mp4", "trim": [4.2, 6.9], "transition": { "type": "cut" } },
  { "source": "assets/clip02.mp4", "trim": [11.0, 13.4] },
  { "segment": "title-a", "transition": { "type": "fadeblack", "duration": 0.2 } }
]
```

- Shot length 0.8-1.5 s when the beat is fast, 2-3 s in the chorus.
- `transition: "cut"` on the beat is stronger than any dissolve; save `fade`/`fadeblack` for the
  section changes only.
- Keep every segment's own animation short: a montage segment is a background plus one moving
  element, not a full graphics build.
- Grade for punch: `"grade": { "saturation": 1.15, "contrast": 1.08 }`.
- Land the final cut exactly on a beat and let the music resolve.

## Short-form vertical (短视频)

```jsonc
"video": { "width": 1080, "height": 1920, "fps": 30 }
```

- The subject goes in the middle 60% of the height; the top 12% and bottom 20% are covered by app UI
  and captions on most platforms.
- Hook inside 3 seconds: the first segment should be the payoff, not a logo.
- One line of on-screen text at a time. Text at 60-80 px for 1080-wide output.
- 6-12 segments, 3-6 s each, total 20-45 s.
- Captions burned in (`subtitles`) outperform platform-generated ones for retention.

## Long-form explainer (5 分钟以上)

See [longform.md](longform.md). The short version: narration script first → one paragraph per
segment → `"still": true` for slides → animated segments only for the hook, section breaks and real
diagrams → chapter chips → global progress bar.

## Explainer with talking-head or voice-over (解说视频)

Use the `caption` template for every beat. It renders a chapter chip, headline, bullet list, media
panel and a lower-third narration band, so the viewer can read or listen.

```jsonc
{ "id": "ch02", "template": "caption", "duration": 12.0,
  "assets": { "subject": "assets/fig02.png" },
  "data": {
    "chapter": { "index": 2, "total": 6, "label": "背景" },
    "title": "问题从哪里来",
    "rows": [ { "value": "2023：需求增长 3.2 倍", "color": "#e0455f" } ],
    "caption": "用年份和数字代替形容词。",
    "footer": "chapter 02" } }
```

- Three bullets maximum per segment; more means the segment should be split.
- Put the number, not the adjective, in the bullet.
- If the voice-over runs long, extend the segment duration rather than trimming the audio — the
  visuals are held, so lengthening costs nothing.

## Product / data motion graphics (kinetic)

`kinetic` carries an eyebrow, headline, subtitle, up to four label/value/bar rows, a subject image
with an entrance and a silhouette-masked scan, a selection frame and a footer.

- Best at 6-10 s. It has enough moving parts that longer segments feel slow.
- The `weight` field on each row drives the bar fill; keep values as data, not decoration.
- Use it for the hook, section dividers and the CTA of any format.

## Pixel style

```jsonc
"look": { "pixelate": { "scale": 4, "colors": 16, "dither": "none" } }
```

- Renders at `width/scale`; 1280×720 with `scale: 4` renders at 320×180, which is also ~15× faster.
- `pixel` template converts `assets.subject` into a sprite automatically (`sprite.width/height/colors`).
- Prefer `"sprite": { "width": 64, "height": 96, "colors": 12 }` for a full-body cut-out, smaller for
  props.
- Presets live in `assets/palettes.json`: `pixel16`, `gameboy` (with `colors: 4`), `mono` (with
  `colors: 2, dither: "bayer"`).
- Never combine a pixelated look with smooth sub-pixel motion; round every transform.

## Custom template

Copy `assets/templates/kinetic.html`, keep `window.seek(t)` pure, read `window.SCENE`, and set
`"template": "path/to/my.html"` in the segment. The renderer injects the data before page scripts run
and waits for `window.__sceneReady !== false`.
