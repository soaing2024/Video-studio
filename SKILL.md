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

For anything bigger than one idea, start a step earlier: write the narration, run `brief` to lay
out acts, per-beat intent, on-screen text, visual devices and image prompts, then `compile` it
into a project. `plan` then reports the render budget and a distinctiveness verdict before any
render time is spent.

1. `probe` the source assets: size, alpha coverage, dominant colours, duration, loudness.
2. Write a project spec (JSON; `//` comments allowed).
3. `preview` a still frame per segment while iterating on design - seconds per look, not minutes.
4. `run`: render each segment straight into a cached clip, assemble with ffmpeg, verify by
   measurement. Frames are piped into ffmpeg's stdin; no PNG sequence ever hits disk.

## Commands

| command | use it for |
| --- | --- |
| `doctor [--install-ffmpeg]` | runtime check: node, playwright, chromium, ffmpeg codecs, python deps |
| `brief --script s.txt --out brief.json` | plan the whole video before rendering anything |
| `compile brief.json` | validate a brief and emit project.json |
| `style [--seed N] [--swatch f.png]` | sample or inspect a visual direction |
| `setup --provider X --key K` | configure image generation (any OpenAI-compatible API) |
| `imagegen "prompt" --out f.png` | generate one image, or every image a project needs |
| `probe <files...>` | decide how to use an asset |
| `sprite <image> [--width 64 --height 96 --colors 12]` | image to pixel-art sprite plus shadow |
| `beats <audio> [--cuts 60]` | beat times and montage cut points |
| `icons sets` | icon sets that can be vendored, with licences |
| `icons search <query>` | find icons by name or tag (build-time; downloads once) |
| `icons add <name>... [--preset core]` | vendor icons into a template-loadable catalog |
| `icons list` | what the catalog holds now (offline) |
| `init <dir> [--template starter\|short\|longform]` | scaffold a project |
| `plan <project>` | dry run: problems, cache hits, budget, distinctiveness |
| `montage <folder> --music f.mp3 --out p.json` | beat-cut montage project from a folder |
| `voices` / `narrate <project> --script s.txt` | list voices, or synthesize narration and time the visuals to it |
| `preview <project> [--segment id] [--at 2.0]` | one still frame, fast design loop |
| `render <project> [--jobs N] [--force]` | render segments only (cached) |
| `assemble <project> [--out f.mp4]` | cut, transition, mix, encode only |
| `verify <project>` | measured acceptance report |
| `run <project> [--jobs N]` | all three, prints a JSON summary |
| `selftest` | end-to-end regression check, one beat per template |

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

`kinetic` and `caption` also take optional icons (see [Icons](#icons)); nothing is drawn unless
you ask, so adding these fields is the only thing that changes a frame:

- `eyebrowIcon` - glyph before (or after, on right-aligned layouts) the eyebrow, kinetic
- `rows[].icon` - kinetic: glyph on the row's label line; caption: replaces the coloured bullet
- `chapter.icon` - glyph inside the caption chapter chip

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
- **Drive the scene, or the shot renders empty.** A template creates every animated element at
  `opacity: 0` and only turns it visible through `scene.seek(t, null)` inside `window.seek(t)`.
  Omitting that call still produces a plausible-looking frame - background, grain and all - and
  only `verify`'s `content_detail` catches it.
- **Pixel look:** render at `width/scale` and let the assembler upscale with nearest. Keep motion on
  whole pixels - sub-pixel movement destroys the style once magnified.
- **Audio levels:** a music bed should measure a mean of roughly -45 to -10 dB in `verify`; voice
  around -18 to -12 dB. `amix` normalises by track count, so each added track costs about 6 dB.
- **Always verify.** If a check fails, fix the spec, not the check.

## Icons

A template that needs a recognisable symbol - a file, a film frame, a check, a gauge - should not
hand-draw it. `assets/icons/<set>.js` is a vendored catalog and `assets/runtime/icons.js` renders
it, for both template styles:

```html
<script src="../icons/lucide.js"></script>
<script src="../runtime/icons.js"></script>
```

```js
// canvas templates
Icons.draw(ctx, "gauge", 480, 320, 96, { color: INK, width: 2, mode: "hand" });
// DOM templates
stage.appendChild(Icons.el("film", { size: 64, color: C.accent, width: 1.5 }));
el.innerHTML = Icons.svg("sparkles", { size: 32 });   // or markup, when that is simpler
Icons.search("video");                                // names + upstream tags
```

`mode` is `"stroke"` (clean line art, the icon's native look), `"fill"`, or `"hand"` - a
three-pass dry-pencil build-up, so line art sits inside a hand-drawn scene instead of on top
of it. The catalog is a plain script: a render never touches the network, never hits file://
CORS, and produces the same frame for the same `t`, like every other scene value.

Ships with a 116-icon Lucide core (ISC, no attribution needed in the output) at 31 KB. Extend it
with `icons search` + `icons add`, which keep the icons already in the file and record set,
version and licence in the header. `--set tabler` is the MIT alternative; `--catalog` writes a
project-local catalog instead (load that one with your own `<script src>`).



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
- Planning, visual distinctiveness and generated imagery:
  [references/creative.md](references/creative.md).
