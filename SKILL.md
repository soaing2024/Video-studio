---
name: video-studio
description: Create finished videos from code and assets - motion graphics, explainers, long-form pieces, montages, and pixel art - rendered frame-exact in headless Chromium, assembled with ffmpeg, and verified by measurement. Interview first and write, generate, or render only after the user approves the full plan. Not for hand-editing footage in a GUI editor.
metadata:
  short-description: "Code-driven video: render, assemble, verify end to end"
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

**2. One write, one delivery render, one export.** Once the plan is approved, the spec is written
once, the piece is rendered once, and that render is the delivered file. A full `run` is the
delivery step, not an exploration step: no "render it and see", no repeated full renders to
compare options, no rendering a piece whose plan is still moving. What you *may* do freely is
the cheap rehearsal below. If something is wrong after delivery, agree on the fix, revise the
spec, and deliver one new round - rendering is not the iteration loop.

**3. Rehearse cheaply, preview deliberately.** Timing cannot be judged on paper, so watching it
is allowed and expected - through the two rehearsals that never touch the delivery render:
`vs.py scrub <project>` (an interactive page driving the real `seek(t)`: play, step frames,
check safe areas) and `vs.py rehearse <project>` (a draft at a fraction of the pixels and
frames, plus a contact sheet of the whole take). Both are for *timing, rhythm and handoffs*,
which paper cannot settle at all.

What is still gated is the still-frame question: do not sweep a still per beat "to check how it
looks". Reason the frame out on paper from the plan first; only a specific, stateable doubt
that paper cannot settle - asset loading, font fallback, whether a composition holds at the
real aspect - justifies `preview` for that one frame, and you should be able to say which doubt
it answers. Composition is judged at the rehearsal scale; a full-quality still is the exception.

## First move

Check the environment before any render or asset work (this can run while you interview the user):

```bash
python <skill-dir>/scripts/vs.py doctor --install-ffmpeg
python <skill-dir>/scripts/vs.py selftest        # end-to-end smoke test, a few seconds
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
4. `check` the whole timeline. `preview` only when a specific doubt cannot be settled on paper:
   one targeted frame that answers it, never a per-beat sweep. The default is to judge the still
   frame from the plan.
5. `plan` for the frame budget, then `run`: render straight into cached clips, assemble with
   ffmpeg, verify by measurement. Frames are piped into ffmpeg's stdin; no PNG sequence ever
   hits disk.

## Commands

Every command accepts `--json`, `--verbose` and `--quiet`; failures return
`{code, where, expected, got, fix_hint}`.

**Plan and prepare**

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
| `sfx "whoosh" [--get ID] [--out dir]` | search Freesound or fetch one effect; licence-gated, writes CREDITS.md |
| `voices` | list installed speech voices |
| `narrate <project> --script s.txt` | synthesize narration, time the take to it, write subtitles |
| `montage <media-dir> --music m.mp3 --out p.json` | beat-cut montage from existing footage |
| `libs [--install name...]` | list vendored browser libraries, or vendor one from npm (build-time only) |
| `init <dir> [--duration N]` | scaffold one take: a spec plus the scene to write |

**Render and deliver**

| command | use it for |
| --- | --- |
| `plan <project>` | dry run: problems, cache hits, frame budget, estimated render time |
| `preview <project> [--segment id] [--at 2.0]` | one still frame, only for a doubt paper cannot settle |
| `rehearse <project> [--at a:b] [--scale 0.35] [--fps 12]` | cheap draft you can watch, plus a contact sheet; never touches the delivery clips |
| `scrub <project> [--open]` | interactive page driving the real scene: play, step frames, safe areas - no render at all |
| `render <project> [--jobs N] [--slices N] [--force]` | render cached clips only |
| `assemble <project> [--out f.mp4]` | cut, transition, mix, encode only |
| `run <project> [--jobs N] [--slices N]` | all three, prints a JSON summary |
| `verify <project>` | measured acceptance report |
| `selftest [--keep]` | tiny project end to end, as a regression check |

**Inspect and repair**

| command | use it for |
| --- | --- |
| `check <project>` | pre-render timeline scan: ghost elements, out-of-frame text, NaN transforms, CJK/contrast |
| `patch <edits.json>` | hash-checked multi-edit patcher with syntax checks and full rollback |
| `audio [<project>] --cues cues.json` / `--check` | build or measure the audio bed against the mix target |
| `card <dir>` | standalone closing card project |
| `api [task]` | the CLI, library and injected-surface index, without reading source |
| `cat <file> [--lines a:b]` / `diff <file>` | cached reads and changed-line ranges |

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
    "finish": {                    // lens + emulsion, applied to the whole frame after the fold
      "preset": "film",            // clean | film | analog | print (or override any key below)
      "halation": { "amount": 0.14, "sigma": 16, "threshold": 0.70, "warmth": 0.35 },
      "grain": { "amount": 3, "chroma": 0.3, "seed": 20260920 },
      "chroma": { "px": 1 },     // lateral chromatic aberration
      "vignette": { "angle": 0.30 },
      "shutter": { "samples": 2 }, // motion blur: render 2x denser, average. Doubles render time.
      "lut": "assets/grade.cube"   // optional 3D LUT
    },
    "pixelate": { "scale": 4, "colors": 16, "dither": "none" },
    "fade_in": 0.5, "fade_out": 0.8,
    "progress_bar": { "height": 4, "color": "#e0455f" }
  },
  "duration": 24.0,
  "scene": "scenes/take.html",
  "libs": ["lucide", "lottie"],       // vendored browser libraries this shot may use
  "hold": [[6.0, 11.0]],              // seconds where the picture genuinely does not change
  "data": { "title": "...", "caption": "..." },
  "audio": {
    "tracks": [
      { "src": "assets/voice.wav", "at": 1.0, "gain_db": -3 },
      { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true }
    ],
    // SFX: the cue bed is synthesized locally (no sample licensing) and pre-mixed to one wav.
    "room": 0.35,
    "cues": [
      { "t": 0.62, "cue": "click", "pan": -0.2 },
      { "t": 2.70, "cue": "whoosh", "dur": 0.8, "f0": 260, "f1": 1500 },
      { "t": 24.55, "cue": "chime", "gain_db": -6 }
    ],
    // Master: two-pass linear loudnorm to a delivery target (+ limiter). Omit to skip.
    "master": { "lufs": -14, "tp": -1.0, "lra": 11 }
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
Its per-segment `"still": true` flag is legacy - a single-take project rejects it, because it
would freeze the whole take; use `hold` windows instead.

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

### Vendored libraries

`"libs": ["lucide"]` injects a browser library into the page through the same mechanism as
`Scene` / `Anim` / `Kit` - Playwright's init script, read from `assets/lib/` - so a scene never
carries a `<script src>` and never reaches the network. `vs.py libs` lists what is vendored and
what could be; `vs.py libs --install <name>` vendors one from npm at build time.

- `lucide` (ISC, 2108 icons) - `Scene.icon("arrow-right", {size, color, strokeWidth})` and
  `Scene.iconNames()`. Icons are DOM, so there is no font fallback and no network.
- `lottie` (MIT) - `Anim.lottie(host, data, {fps}).seek(t)`. Point a `.json` asset at the
  Bodymovin export and it arrives parsed in `SCENE.assets` (a `file://` XHR would be blocked).
- `anime` (MIT) - `Anim.timeline(seconds, build).seek(t)`, with the engine's autoplay and ticker
  left off.
- `chroma-js` (BSD-3-Clause AND Apache-2.0, v3.2) - perceptual colour scales, Brewer
  palettes, luminance and contrast checks. Pure functions, so it never needs a clock:
  `chroma.scale(["#0d1b2a", "#3cd3d4"]).mode("lch").colors(7)`.
- `three` (MIT, r186) - `Scene.three()` for a WebGL layer (plus `environment()` and `bloom()`),
  `Scene.css3d()` for real DOM placed in 3D, and `Scene.surface()` for a 2D canvas used as a
  texture. Combining 2D and 3D has its own document:
  [references/three-d.md](references/three-d.md).

Both motion wrappers exist to keep the one hard rule intact: the library is built once, then told
where to stand on every frame. Nothing starts a clock, so the same `t` still gives the same
frame. Reach for one only when the effect cannot be written directly as a function of `t`
([references/libraries.md](references/libraries.md)).

**There are no built-in templates.** The skeletons were deleted on purpose: every shot is a scene
you write for this video, pointed at by `scene`. The renderer injects `Scene` / `Anim` / `Kit`, so
a scene never resolves a path - it defines `window.seek(t)` and nothing else. `vs.py init --duration N`
scaffolds one blank take (plumbing only, no design). How to compose a shot, the gates it has to
pass, and the list of skeletons that are already used up:
[references/choreography.md](references/choreography.md).

## Rules that keep output correct

- **One take, no cuts.** A project is one scene and one duration; the whole piece runs from t=0 to
  the end without a single cut. Change of scene is a transformation inside the shot, not an edit.
  Declare genuinely static stretches as `hold` windows - the renderer reuses one frame for them, and
  that is the only cost lever a single take has left.
- **Compose the shot, do not fill a template.** Every shot is authored for this video: pick the
  structure first, invent the mechanic from the subject's own physics, then write the scene. The
  old skeletons are deleted, not merely discouraged: a video assembled from a fixed set of them
  is the same video for every brief, and the second one wearing a used skeleton reads as
  machine-made. Check the used-skeleton list before inventing, and add what you used:
  [references/choreography.md](references/choreography.md).
- **The still frame is the design.** With motion stopped, the frame has to stand on its own. If it
  is a centred headline over a subtitle, the act of designing never happened - fix the structure,
  not the easing.
- **Holds are free; `still` is not.** `hold` windows cost one frame each and are the lever for
  talking-head and slide-like stretches of long videos. `"still": true` is the legacy per-segment
  flag of the multi-shot/montage shape and is rejected by single-take projects.
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
- **Sound effects carry their licence.** `vs.py sfx` searches Freesound CC0-only by default,
  converts what it fetches to 48 kHz wav, and appends a `CREDITS.md` row; CC BY is opt-in with
  `--licence by`, and BY-SA / NC / Sampling+ need `--allow-risky` (never for a commercial cut).
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
- 5-minute and longer videos - frame budgeting, render time, narration, subtitles, chapters, and
  what to check before delivery: [references/longform.md](references/longform.md).
- Recipes for montage, short-form, long-form, explainer and pixel styles, including beat-synced
  cutting and vertical framing: [references/formats.md](references/formats.md).
- Chinese manual for the human operator: [README.md](README.md) (long form) and
  [references/guide-zh.md](references/guide-zh.md) (one-page cheat sheet).
- Planning, visual distinctiveness and generated imagery:
  [references/creative.md](references/creative.md).
- Craft, from the animation/design tutorial canon - the twelve animation principles, the four
- The twelve animation principles as a paste-ready prompt, each mapped to an executable
  parameter and a measurable check: [references/principles-prompt.md](references/principles-prompt.md).
  Written in Chinese, because that is how the request arrives.
- Physical motion that still obeys `seek(t)` - springs, follow-through chains, ballistic,
  pendulum, drag, seeded drift, and the traps: [references/motion-physics.md](references/motion-physics.md).
- Optical finish and the cheaper rehearsal loop (what `rehearse` / `scrub` do, what the
  audio bed and the two-pass master are): [references/pipeline.md](references/pipeline.md).
  presentation-design principles, composition and type-scale numbers, each turned into a
  checkable rule with its source: [references/craft.md](references/craft.md). Written in Chinese.
- Libraries worth reaching for - icons, motion, footage, sound - with the licence and access rules for
  each, and why anything external has to be vendored before a render:
  [references/libraries.md](references/libraries.md). Written in Chinese.
- 2D and 3D in one shot - the four ways to combine a WebGL layer, real DOM in 3D (CSS3D), canvas
  textures and DOM overlays; camera and lighting defaults; the measured cost of bloom; and the
  list of things that break frame exactness: [references/three-d.md](references/three-d.md).
  Written in Chinese.
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

## Tooling beyond the core

`vs.py api [task]` indexes the CLI, every library function and the injected `Scene`/`Anim`/`Kit`
surface, so an agent can call the tool without reading its source; [API.md](API.md) and
[api_index.json](api_index.json) are the same data, regenerated by `scripts/api_index.py`.

Recent additions and their measured effect - GPU/CDP rendering, time-sliced parallel renders,
numeric preview reports, hash-checked patching, the audio cue library - are recorded in
[UPGRADE.md](UPGRADE.md), with the audit that motivated them in [AUDIT.md](AUDIT.md) and
[PLAN.md](PLAN.md). Those three are historical documents: where they disagree with this file,
this file wins.
