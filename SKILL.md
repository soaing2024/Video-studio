---
name: video-studio
description: Produce finished videos from code and source assets - motion-graphics clips, explainers, 5-minute long-form, high-energy montages, pixel-art. Renders frame-exact scenes in headless Chromium, assembles them with ffmpeg, and verifies the result by measurement. Use when the user wants a video created, restyled, or pipelined from a spec; not for hand-editing footage in a GUI editor.
---

# Video Studio

Turn a project spec into a rendered, edited, verified video file.

## First move

Check the environment before anything else:

```bash
python <skill-dir>/scripts/vs.py doctor --install-ffmpeg
```

`--install-ffmpeg` vendors a full ffmpeg into the skill's `vendor/` folder. Playwright ships an
ffmpeg that can only encode VP8/PNG, so a build found on PATH may be silently useless - the check
verifies `libx264` on purpose. Report anything `doctor` flags instead of working around it.

## Pipeline

1. `probe` the source assets: size, alpha coverage, dominant colours, duration, loudness.
2. Write a project spec (JSON; `//` comments allowed).
3. `preview` a still frame per segment while iterating on design - seconds per look, not minutes.
4. `run`: render each segment straight into a cached clip, assemble with ffmpeg, verify by
   measurement. Frames are piped into ffmpeg's stdin; no PNG sequence ever hits disk.

## Commands

| command | use it for |
| --- | --- |
| `doctor [--install-ffmpeg]` | runtime check: node, playwright, chromium, ffmpeg codecs, python deps |
| `probe <files...>` | decide how to use an asset |
| `sprite <image> [--width 64 --height 96 --colors 12]` | image to pixel-art sprite plus shadow |
| `beats <audio> [--cuts 60]` | beat times and montage cut points |
| `init <dir> [--template starter\|short\|longform]` | scaffold a project |
| `preview <project> [--segment id] [--at 2.0]` | one still frame, fast design loop |
| `render <project> [--jobs N] [--force]` | render segments only (cached) |
| `assemble <project> [--out f.mp4]` | cut, transition, mix, encode only |
| `verify <project>` | measured acceptance report |
| `run <project> [--jobs N]` | all three, prints a JSON summary |

`run` and `verify` exit non-zero when a check fails. Read the failing `detail` - it names the knob to
turn.

## Project spec

```jsonc
{
  "name": "my-video",
  "video": { "width": 1280, "height": 720, "fps": 30, "crf": 18, "preset": "slow" },
  "render": { "jobs": 3, "crf": 12 },          // intermediates; 12 is visually lossless
  "look": {
    "accent": "#e0455f",
    "grade": { "saturation": 1.06, "contrast": 1.04 },
    "pixelate": { "scale": 4, "colors": 16, "dither": "none" },
    "fade_in": 0.5, "fade_out": 0.8,
    "progress_bar": { "height": 4, "color": "#e0455f" }
  },
  "segments": [
    { "id": "intro", "template": "kinetic", "duration": 6.0,
      "data": { "eyebrow": "SHOT 01", "title": "Headline", "subtitle": "Supporting line" },
      "assets": { "subject": "assets/hero.png" } }
  ],
  "timeline": [
    { "segment": "intro" },
    { "segment": "body", "transition": { "type": "fade", "duration": 0.5 } },
    { "source": "existing-clip.mp4", "trim": [12.0, 15.5] }   // cut real footage into the timeline
  ],
  "audio": {
    "tracks": [
      { "src": "assets/voice.wav", "at": 1.0, "gain_db": -3 },
      { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true }
    ]
  },
  "subtitles": { "src": "assets/subs.srt", "style": "FontName=Microsoft YaHei,FontSize=22,MarginV=36" }
}
```

`segments` are rendered; `timeline` is what gets assembled, in that order. An unused segment costs
nothing. A timeline entry may point at a `source` file instead of a segment, which is how existing
footage enters a montage.

### Segment data the templates read

`kinetic`, `caption` and `pixel` all read the same keys and ignore what they do not need:
`eyebrow`, `title`, `titleSize`, `subtitle`, `cn`, `rows[{label,value,weight,color}]`,
`callout{c1,c2}`, `footer`, `caption`, `chapter{index,total,label}`, `colors{...}`, `sprite{...}`,
and `still: true`.

Assets: `subject` (any image; `pixel` auto-converts it to a sprite), `sprite` plus `spriteShadow`
(pre-made), `background`.

Templates are plain HTML exposing `window.seek(t)`. Write a custom one in the project and pass its
path as `template` when none of the three fit.

## Rules that keep output correct

- **One idea per segment.** 4-12s for a short, 8-20s for an explainer; a 5-minute video is 20-40
  segments, not one long animation.
- **Held shots are free.** `"still": true` renders a single frame and holds it, so a 60s slide costs
  the same as a 1s clip. Use it for talking-head and slide sections of long videos.
- **Every animated value must be a pure function of `t`.** No CSS transitions, no
  `requestAnimationFrame`, no wall-clock time inside a scene.
- **Pixel look:** render at `width/scale` and let the assembler upscale with nearest. Keep motion on
  whole pixels - sub-pixel movement destroys the style once magnified.
- **Audio levels:** a music bed should measure a mean of roughly -45 to -10 dB in `verify`; voice
  around -18 to -12 dB. `amix` normalises by track count, so each added track costs about 6 dB.
- **Always verify.** If a check fails, fix the spec, not the check.

## Routing

- Mechanics and failure modes - frame exactness, caching, the filter graph, alpha compositing,
  pixel-art maths, measured throughput, and every bug this tool has hit so far:
  [references/pipeline.md](references/pipeline.md).
- 5-minute and longer videos - segment budgeting, render time, narration, subtitles, chapters, and
  what to check before delivery: [references/longform.md](references/longform.md).
- Recipes for montage, short-form, long-form, explainer and pixel styles, including beat-synced
  cutting and vertical framing: [references/formats.md](references/formats.md).
- Chinese manual for the human operator: [README.md](README.md) (long form) and
  [references/guide-zh.md](references/guide-zh.md) (one-page cheat sheet).
