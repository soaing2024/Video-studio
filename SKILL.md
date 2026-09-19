---
name: video-studio
description: Produce finished videos from code and source assets - motion-graphics clips, explainers, 5-minute long-form, high-energy montages, pixel-art. Renders frame-exact scenes in headless Chromium, assembles them with ffmpeg, and verifies the result by measurement. Interview-first: it plans with the user, waits for explicit approval of the full plan, then writes once and renders once, previewing a still only when a specific doubt requires it. Use when the user wants a video created, restyled, or pipelined from a spec; not for hand-editing footage in a GUI editor.
---

# Video Studio

Turn a project spec into a rendered, edited, verified video file.

## Three rules before anything else

**1. Talk first - never create on the first turn.** A request is a starting point, not a brief.
Interview the user over as many rounds as it takes before any narration, scene, spec or asset is
written: who it is for, where it plays, how long, what the viewer must think or do afterwards, the
tone (and what it must not be), whether there is narration, music, existing footage or a brand
look, and which references the user likes or rejects. A few focused questions per round; after each
round, restate what is settled and what is still open. Then present the **complete plan for
approval** - the script, the full storyboard (per beat: act, intent, spoken line, on-screen text,
visual device, duration, handoffs), the visual direction, the audio plan, the asset list and the
acceptance checklist. Stop there and wait for an explicit yes. Do not scaffold, compile, generate
images or render before that approval, and re-confirm after any change the user asks for.

**2. One write, one render, one export.** Once the plan is approved, the spec is written once, the
piece is rendered once, and that render is the delivered file. Design is settled in the plan, on
paper. A full `run` is the delivery step, not an exploration step: no "render it and see", no
repeated full renders to compare options, no rendering a piece whose plan is still moving. If
something is wrong after delivery, agree on the fix, revise the spec, and deliver one new round -
rendering is not the iteration loop.

**3. Preview only when necessary.** `preview` is an exception, not the design loop. Do not sweep a
still per beat "to check how it looks". Reason the still frame out on paper from the plan. Only a
specific, stateable doubt that paper cannot settle - asset loading, font fallback, whether a
composition holds at the real aspect - justifies rendering that one frame, and you should be able
to say which doubt it answers. A preview is not a render, but previewing every beat is the old
iterate-by-looking loop under a cheaper name.

## First move

Check the environment before any render or asset work (this can run while you interview the user):

```bash
python <skill-dir>/scripts/vs.py doctor --install-ffmpeg
```

`--install-ffmpeg` vendors a full ffmpeg into the skill's `vendor/` folder. Playwright ships an
ffmpeg that can only encode VP8/PNG, so a build found on PATH may be silently useless - the check
verifies `libx264` on purpose. Report anything `doctor` flags instead of working around it.

## Pipeline

Nothing in this list starts before the interview and the approved plan above. The plan is the gate:
no spec, scene, generated image or render until the user has said yes to it.

For anything bigger than one idea, start a step earlier: write the narration, run `brief` to lay
out acts, per-beat intent, on-screen text, visual devices and image prompts, then `compile` it
into a project. `plan` then reports the render budget and a distinctiveness verdict before any
render time is spent.

1. `probe` the source assets: size, alpha coverage, dominant colours, duration, loudness.
2. Write a project spec (JSON; `//` comments allowed).
3. Write the seven-line motion spec and declare the handoffs in `data.beats`, then audit them:
   `python scripts/beat_audit.py project.json` fails on exit-then-enter gaps, over-long moves and
   weak overlaps - the three causes of a slide-deck feel
   ([references/rhythm-handoff.md](references/rhythm-handoff.md)).
4. `preview` only when a specific doubt cannot be settled on paper: one targeted frame that answers
   it, never a per-beat sweep. The default is to judge the still frame from the plan.
5. `run`: render each segment straight into a cached clip, assemble with ffmpeg, verify by
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
| `init <dir> [--duration N]` | scaffold one take: a spec plus the scene to write |
| `preview <project> [--segment id] [--at 2.0]` | one still frame, only for a doubt paper cannot settle |
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
  "duration": 24.0,
  "scene": "scenes/take.html",
  "hold": [[6.0, 11.0]],              // seconds where the picture genuinely does not change
  "data": { "title": "...", "caption": "..." },
  "audio": {
    "tracks": [
      { "src": "assets/voice.wav", "at": 1.0, "gain_db": -3 },
      { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true }
    ]
  },
  "subtitles": { "src": "assets/subs.srt", "style": "FontName=Microsoft YaHei,FontSize=22,MarginV=36" }
}
```

**One take, no cuts.** The project is one `scene` and one `duration`; the whole piece runs from t=0
to the end. Change of scene is a transformation inside the shot, never an edit. `hold` lists the
seconds where the picture genuinely does not change - the renderer reuses one frame there, which is
the only cost lever a single take has left.

The multi-shot shape (`segments` + `timeline`, with `source` clips and xfade transitions) still
exists for exactly one job: a montage of existing footage, which `vs.py montage` generates.

### Segment data

A scene reads whatever you put in `data`; the skill imposes no field vocabulary. `assets` entries
are resolved to file URLs and injected alongside it, plus `duration`, `id` and the resolved `visual`
block (palette, accent, texture, pacing, an advisory `layout`).

`kinetic`, `caption` and `pixel` all read the same keys and ignore what they do not need:
`eyebrow`, `title`, `titleSize`, `subtitle`, `cn`, `rows[{label,value,weight,color}]`,
`callout{c1,c2}`, `footer`, `caption`, `chapter{index,total,label}`, `colors{...}`, `sprite{...}`,
and `hold` windows (the take-level equivalent of a held shot).

Assets: `subject` (any image), `sprite` plus `spriteShadow` (a pre-made pair - make one with
`vs.py sprite`), `background`. Anything else you need, pass it as data and read it in the scene.

**There are no built-in templates.** The skeletons were deleted on purpose: every shot is a scene
you write for this video, pointed at by `scene`. The renderer injects `Scene` / `Anim` / `Kit`, so
a scene never resolves a path - it defines `window.seek(t)` and nothing else. `vs.py init --duration N`
scaffolds N blank ones (plumbing only, no design). How to compose a shot, the gates it has to
pass, and the list of skeletons that are already used up:
[references/choreography.md](references/choreography.md).

## Rules that keep output correct

- **Talk first, get the plan approved, then create.** No spec, scene, image or render before the
  user has approved the full plan (script + storyboard + visual direction + audio + checklist).
- **One write, one render, one export.** The approved spec is written once; the full render happens
  once and its output is the deliverable. Iterate on paper, never by re-rendering the piece.
- **Preview only when necessary.** No per-beat still sweep as a design loop. One targeted `preview`
  frame is allowed when a specific doubt cannot be resolved from the plan.
- **One take, no cuts.** A project is one scene and one duration; the whole piece runs from t=0 to
  the end without a single cut. Change of scene is a transformation inside the shot, not an edit.
  Declare genuinely static stretches as `hold` windows - the renderer reuses one frame for them, and
  that is the only cost lever a single take has left.
- **Compose the shot, do not fill a template.** Every shot is authored for this video: pick the
  structure first, invent the mechanic from the subject's own physics, then write the scene. The
  old skeletons are deleted, not merely discouraged: a video assembled from a fixed set of them
  is the same video for every brief, and the second one wearing a used skeleton reads as
  machine-made. Check the used-
  skeleton list before inventing, and add what you used: [references/choreography.md](references/choreography.md).
- **The still frame is the design.** With motion stopped, the frame has to stand on its own. If it
  is a centred headline over a subtitle, the act of designing never happened - fix the structure,
  not the easing.
- **Held shots are free.** `"still": true` renders a single frame and holds it, so a 60s slide costs
  the same as a 1s clip. Use it for talking-head and slide sections of long videos.
- **Every animated value must be a pure function of `t`.** No CSS transitions, no
  `requestAnimationFrame`, no wall-clock time inside a scene.
- **An external library is only usable if it can be driven from `t`, and only if its dist file
  lives in the repo.** No CDN, no network at render time, no library ticker. If it cannot be
  seeked (`seek` / `goToAndStop` / `position`), it belongs in asset preparation, not in a scene.
  Vendoring steps and a checked licence list: [references/prompts.md](references/prompts.md).
- **Pixel look:** render at `width/scale` and let the assembler upscale with nearest. Keep motion on
  whole pixels - sub-pixel movement destroys the style once magnified.
- **Audio levels:** a music bed should measure a mean of roughly -45 to -10 dB in `verify`; voice
  around -18 to -12 dB. `amix` normalises by track count, so each added track costs about 6 dB.
- **Overlap the handoffs.** A transition whose exit finishes before its entrance begins reads as a
  slide deck however good the easing is; letting the two windows share 40-60% of their duration
  removes it, and whole-frame moves stay under ~1.2s with most of their change up front.
- **Judge the frame, not only the pixels.** Composition and colour are gated in
  [references/taste.md](references/taste.md); rhythm and handoffs in
  [references/rhythm-handoff.md](references/rhythm-handoff.md).
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
- Planning, visual distinctiveness and generated imagery:
  [references/creative.md](references/creative.md).
- Craft, from the animation/design tutorial canon - the twelve animation principles, the four
  presentation-design principles, composition and type-scale numbers, each turned into a
  checkable rule with its source: [references/craft.md](references/craft.md). Written in Chinese.
- Libraries worth reaching for - motion, footage, sound - with the licence and access rules for
  each, and why anything external has to be vendored before a render:
  [references/libraries.md](references/libraries.md). Written in Chinese.
- Advanced technique prompts - colour scales (chroma.js and friends), external motion libraries
  and how to vendor them offline, plus design and storyboarding vocabulary with copy-ready
  prompts: [references/prompts.md](references/prompts.md). Written in Chinese, because it is
  aimed at the Chinese-language tutorial ecosystem.
- How to compose a shot for this video instead of selecting a template - the seven-step loop,
  the macrostructures, the six generative operators for inventing a mechanic, motion tokens,
  the twelve timeline laws, the slop gates and the used-skeleton graveyard:
  [references/choreography.md](references/choreography.md). Written in Chinese.
- Aesthetic gates - proportion, type-scale jump, colour budget, ink ratio, reference traditions
  and the AI-slop blacklist: [references/taste.md](references/taste.md). Written in Chinese.
- The slide-deck failure - two-ended easing, exit-then-enter gaps, whole-frame replacement, and
  the numbers that fix each: [references/rhythm-handoff.md](references/rhythm-handoff.md). Written in Chinese.
- Motion realism - the seven-line motion spec, twelve hooks, per-feeling parameter sets:
  [references/motion-realism.md](references/motion-realism.md). Written in Chinese.
- Fast lane and self-checks - `scripts/scaffold.py` builds a project from `assets/starter/`;
  `scripts/qc_video.py` measures region ink and prints ASCII frame maps; `scripts/taste_check.py`
  reports rhythm and composition; `scripts/beat_audit.py` audits the handoff timeline.
