# Pipeline mechanics

How the pieces work, what was measured, and every failure this tool has already hit.

## 1. Frame exactness

A scene exposes `window.seek(t)` and nothing else. Given a time in seconds it computes the entire
frame: no CSS transitions, no `requestAnimationFrame`, no `Date.now()`. That single constraint buys
three things:

- **Exact framing.** 30 fps means 30 distinct values of `t`; there is no such thing as a late frame.
- **Reproducibility.** The same `t` always yields the same pixels, so a re-render is byte-comparable.
- **Incrementality.** An edit to second 12 cannot disturb second 11.

Screen recording cannot do any of this: it is a real-time system, so a busy machine drops or
duplicates frames, and nothing can be re-rendered selectively.

## 2. Render path

```
scene.html + data.json
  → Chromium (playwright), viewport = work size
  → page.evaluate(seek(t)) ; screenshot() → PNG Buffer
  → ffmpeg stdin (-f image2pipe) → libx264 crf 12 → build/<name>/segments/<id>.mp4
```

Frames never touch the filesystem. That matters at scale: a 5-minute 1080p video is 9000 frames,
which as PNGs would be several gigabytes and thousands of filesystem calls.

`render_segment.mjs` is deliberately small: launch, inject `window.SCENE`, wait for
`__sceneReady`, loop `seek`/`screenshot`, stream to ffmpeg, report page errors as JSON on stdout.

## 3. Caching

`render.py` hashes scene bytes + segment data + every asset's path/size/mtime + render size, fps,
shutter, hold windows, the segment crf/preset/jpeg flags, the accent and the vendored-library
fingerprints into a 16-char key, stored next to the clip as `.key`. A matching key means reuse.

Measured effect: after the first run of the 3-segment demo, a full `run` took ~3 seconds because
only assembly and verification re-executed.

Slicing is opt-in: `--slices N` (or `render.slices`) cuts a take into N time ranges, each with
its own cache key, and the ranges are allocated by cumulative frame index so the per-slice frame
counts always add up to the take's own frame count. A crash re-renders only the missing slices,
and the join verifies the total before the take is accepted.

With `--incremental` a downscaled signature pass additionally records which frames changed, but a
slice is only re-used when the signature is unchanged **and** every non-scene input (assets,
encode args, libraries, size, holds) still matches - otherwise an edited asset would keep the old
pictures and stamp them as fresh.

`--force` ignores the cache. Use it after changing anything the key cannot see (for example, a file
edited in place within the same second).

## 4. Assembly

One ffmpeg invocation per project. A single-take project feeds the fold a single clip, so
concat/xfade do nothing and the filter graph is just the look chain; the fold exists for the
montage path (many `source` clips) and for multi-shot projects.

The filter graph is written to `build/<name>/filter.txt` and
passed via `-/filter_complex` (falling back to `-filter_complex_script` on older builds).

**Per input:** `trim=start=a:end=b, setpts=PTS-STARTPTS, fps=F, setsar=1`, plus
`scale=w:h:force_original_aspect_ratio=decrease, pad=w:h:(ow-iw)/2:(oh-ih)/2` for timeline entries
that reference external footage.

**Fold:** the first clip is the accumulator; each following clip extends it.

- cut → `[acc][cN]concat=n=2:v=1:a=0`
- transition → `[acc][cN]xfade=transition=T:duration=D:offset=O`

with `O = accumulated_length - D`.

**Look:** optional `eq` grade → optional `split/palettegen/paletteuse/scale` pixel pass → fades →
progress bar → subtitles → `[vout]`.

**Audio:** each track gets `atrim, asetpts, volume=<dB>dB, afade…, adelay`, then all tracks meet in
`amix`, then `atrim` to the video length. Looping tracks are opened with `-stream_loop -1`.

## 5. Alpha compositing

Two blend modes matter, and the difference is one factor of `αd`:

- `source-over` — `C = Cs·αs + Cd·αd·(1 − αs)`: normal layering.
- `source-atop` — `C = Cs·αs·αd + Cd·αd·(1 − αs)`: paint only where the destination is already
  opaque.

`source-atop` is how an effect is confined to a cut-out subject without writing a mask by hand. Draw
the subject into an offscreen canvas, switch to `source-atop`, fill the gradient, switch back, then
`drawImage` the offscreen canvas onto the visible one.

## 6. Pixel-art maths

- **Downsample** with area averaging (`Image.BOX`, or a canvas draw at reduced size). Nearest
  sampling from a 16× larger source keeps one arbitrary pixel per block and shreds the silhouette.
- **Upscale** only by an integer factor with nearest neighbour (`scale=…:flags=neighbor`). A
  non-integer factor yields blocks that are alternately 3 and 4 pixels wide, which reads as a
  mistake rather than a style.
- **Palette** via `palettegen`/`paletteuse`. Dithering trades spatial detail for apparent depth
  (Floyd–Steinberg for organic, Bayer for ordered); `dither=none` keeps hard edges.
- **Outline** = `dilate(mask) − mask`, painted in a dark colour. Baked into the sprite once, not
  recomputed per frame.
- **Motion** must land on whole pixels. Round every transform output.

## 7. Verification

`verify.py` decodes the finished file and measures it:

| check | catches |
| --- | --- |
| `duration` vs planned | transition offset maths, dropped or duplicated clips |
| `resolution` | wrong render size, silent rescale |
| `content` luma of sampled frames | black video, missing media |
| `fade_in` / `fade_out` | fades that start past the end because the duration was wrong |
| `pixel_blocks` | bilinear instead of nearest upscaling |
| `palette` | re-quantisation error vs the requested palette size |
| `audio_present` / `audio_level` | silent mix, or a bed that is 20 dB too quiet |

Colour counts are useless on a lossy encode — that is why the palette check re-quantises to the
requested size and measures the error instead.

## 8. Measured throughput

Rendering is dominated by the screenshot round-trip, not by drawing. The numbers below are the
measured 3840×2160 baseline from the audit that produced the current renderer (see AUDIT.md §6);
lower resolutions scale roughly with pixel count, and `vs.py plan` prints the figure for the
machine you are actually on.

| configuration | ms/frame | lossless | 1800 frames, one job |
| --- | --- | --- | --- |
| Playwright PNG, software raster (old default) | 730 | yes | ~22 min |
| + GPU rasterisation | 671 | yes | ~20 min |
| + CDP `optimizeForSpeed` PNG (current default) | 166 | yes | ~5 min |
| + JPEG q97 (preview only) | 102 | no | ~3 min |
| `hold` window | 1 frame per window, whatever its length | yes | seconds |

Ways to buy speed, in order of payoff: `hold` windows for static sections → pixel look or lower
resolution → `fps: 24` for long-form → cached slices for re-runs. `--slices N` (opt-in only, for
parallel rendering of a single take; diminishing returns past core count) is a deliberate
exception the user has to ask for - the default is always one process.

## 9. Failure modes already hit

1. **Playwright's ffmpeg cannot encode H.264.** It only offers libvpx/VP8 and PNG. `doctor` verifies
   `libx264` and `--install-ffmpeg` vendors a full build via `imageio-ffmpeg`.
2. **CSS `mask-image` is refused on `file://`.** The mask resource is fetched with CORS semantics and
   a file page is an opaque origin, so the mask evaluates to fully transparent and the subject
   vanishes. Use canvas `source-atop` instead.
3. **`easeOutBack` with the wrong constants returns 0.2 at `t = 0`** (`1 - c3 + c1`). Elements pop
   in before their entrance. Use `c1 = 1.70158`, `c3 = c1 + 1`, and check the endpoints of every
   easing function.
4. **`xfade` output length is `offset + len(B)`, not `offset + duration + len(B)`.** Getting this
   wrong makes the accumulated length drift, which shortens the final file and pushes later
   transitions past the end of their input.
5. **`trim` drops the frame-rate metadata**, so a following `xfade` fails with
   `current rate of 1/0 is invalid`. Re-declare it: `trim=…,setpts=PTS-STARTPTS,fps=30`.
6. **`amix` divides by the number of inputs.** Two tracks at -3 dB each leave the mix about 6 dB
   quieter than expected; a "quiet" bed can end up inaudible. Measure with `verify`.
7. **Naive comment stripping breaks `"//"` keys.** Count quotes or scan character by character
   instead of splitting on `//`.
8. **`-shortest` is required when audio and video are mapped together**, otherwise a looping music
   track can extend the file past the last video frame.

9. **A helper that silently drops its text argument** produced a frame where the numbers, the
   axis labels and the closing line never rendered, while the render summary stayed clean and the
   still looked like an empty page. Measure ink in the regions that must carry content
   (`scripts/qc_video.py`) instead of trusting the render.
10. **An exit factor that saturates.** `opacity = exit * enter` behaves during the transition and
    then pins the element at 0 forever once `exit` reaches 1. Give exits their own window.
11. **`position: absolute` inside a flex parent is not centred** - flex alignment only applies to
    in-flow children, so a "centred" digit lands in a corner.
12. **A fade to or from black on a white video** both looks wrong and trips the `fade_in` gate.
    Fade inside the scene (animate content opacity on a white stage) and leave `look.fade_in: 0`.
13. **Colour counts are meaningless on an encoded frame too** - anti-aliasing and the codec invent
    thousands of one-pixel shades, so a raw unique count flags every frame. Quantise and threshold
    by area before judging a palette, and ignore the assembler's own overlays (progress bar).

## 10. Extending it

- **New scene:** write one (`vs.py init --duration N` scaffolds one), keep the `seek(t)` contract and the
  `window.SCENE` input, and point the project's `"scene"` at it.
- **New look:** add a filter to the tail chain in `assemble.py`. Anything ffmpeg can express is
  available; keep it deterministic and duration-aware.
- **New quality gate:** add a measurement to `verify.py` and check the actual invariant, not the
  wording of a message.

## 11. Optical finish (`look.finish`)
it is the delivered file that `verify` measures. Measured here: a -1.0 dBTP limiter left the
encoded file at -0.35 dBTP and failed its own gate.

`verify` now gates two things it used to ignore: `mastering` (integrated LUFS within ±1.5 of the
declared target, true peak within +0.4 dB of it) and a cue-only mix, which is allowed to sit
louder than a background bed because the cues *are* the programme. Cue-only projects used to
fail `audio_present` with "no audio configured" - a bug the smoke test caught.

## 13. Rehearsal: the cheap half of the loop

```bash
python scripts/vs.py scrub <project> [--open]           # interactive, no render at all
python scripts/vs.py rehearse <project> --at 3:9 --scale 0.35 --fps 12
```

`scrub` copies the scene, injects the same runtimes the renderer injects, sets `window.SCENE`,
and appends a transport bar (play, scrub, ±1 frame, 0.25–2×, safe-area overlay). Arrows step a
frame, shift+arrows jump a second. It writes `build/<name>/scrub.html` and renders nothing.

`rehearse` renders a draft with `deviceScaleFactor = scale` at a reduced fps, and with
`--scale` ≠ 1 it forces PNG (see the failure mode below). It writes to
`build/<name>/rehearsal/`, never to `build/<name>/segments/`, so no cache key and no delivery
clip is touched. `--at a:b` rehearses one window.

**The take offset is a channel fact, not a scene fact.** Every entry point - a parallel slice, a
still, a rehearsal window, the scrub page - hands the scene *absolute* take time on the same
clock as `duration`. The renderer does that by passing `--offset` to `render_segment.mjs`, which
sets `window.__TAKE_OFFSET` before the runtimes load; `assets/runtime/scene.js` wraps
`window.seek` by it, and `render_segment.mjs` re-asserts the wrap after boot in case a scene
redefined the property. `window.SCENE` never carries the offset, so a scene written without any
knowledge of slicing is correct by construction and needs no offset handling at all.

A scene written before this rule, one that reached into the payload for the legacy offset field
and added it itself, keeps working unchanged: that field is no longer published, so the scene's
own `+ 0` is a no-op on top of the channel's shift.

The test that keeps it honest is `vs.py selftest`, which renders with `--slices 2` and requires
the two halves to differ. Before this rule, every slice rendered window one and the joined take
was that window repeated N times - `verify` could not see it, because its samples all landed
inside the repeated content and differed from each other anyway.

Measured on the selftest scene: a 30 s 1080p take is ~14 s of wall clock as a draft and ~4
minutes as a delivery render. That ratio is the whole point.

## 14. Failure modes added by this layer

14. **Progressive JPEG cannot be piped.** Chromium emits *progressive* JPEG at
    `deviceScaleFactor` below 1. ffmpeg's `image2pipe` demuxer **parses** to find frame
    boundaries (it does not decode), cannot parse progressive, and dies with "Could not find
    codec parameters" - after which the renderer waited forever on a broken pipe. A scaled
    draft must stay PNG; full-size `--jpeg` preflights are baseline and still fine.
15. **A dead encoder must not mean an infinite wait.** `ff.stdin.write()` returning false and
    then awaiting only `drain` hangs forever when ffmpeg already exited: checking
    `ff.exitCode` *before* racing the events, plus a timeout, is what makes the failure
    legible. `once(ff, "close")` cannot be relied on: the event may have fired already.
16. **`requestAnimationFrame` can stall.** With software rasterisation or a hidden page, rAF
    may never fire, and every frame becomes an infinite wait. The renderer now races rAF
    against a 40 ms timer before grabbing.
17. **`colorlevels` cannot amplify.** `rimax` is capped at 1.0, so a highlight glow has to be
    re-expanded with a `curves` point, not a gain.

Everything before this stage is vector-accurate: flat fields, hard edges, no light behaviour.
The finish chain is the one place where the whole frame gets lens/emulsion treatment, and it
sits **after the fold** so a montage does not change look at every cut. Order:

```
lut3d -> tone (lift/roll/gamma/saturation) -> halation (threshold + gblur + warm mix,
screen-blended) -> chroma (rgbashift) -> vignette -> grain (noise, seeded) -> unsharp
```

Presets: `clean`, `film`, `analog`, `print`; every key can be overridden. Numbers that were
measured on a flat grey field rather than guessed: `vignette=angle` 0.30 leaves corners at 83%
of centre luma, 0.55 at 52%, 0.75 at 25% - so the presets stop at 0.42. Grain at `alls=3`
measures ~2.1/255 of frame-to-frame change; `alls=8` is the analog preset and is already
loud. `colorlevels` tops out at `rimax=1`, which is why the glow is re-expanded with a
`curves` point instead of a gain.

Grain is skipped automatically on a `pixelate` project unless it is asked for by name: grain on
a block grid reads as a broken palette.

### Shutter (motion blur)

`look.finish.shutter: {samples: N}` renders at `fps * N` and folds with
`tmix=frames=N`, then `trim=start_frame=N-1` and back to the delivery fps. Cost is linear in
N, so it is a delivery decision: turn it on for hero moves, expect 2× render time at N=2.
`--slices` is forced to 1 in this mode (each slice would average across its own boundary and
the seam would show).

## 12. Sound: cue bed, duck, master

`audio.cues` is rendered by `lib/audio.py` into one cached stereo wav (`build/<name>/audio/cues-*.wav`)
and mixed as a single track, because `amix` divides by track count: eight separate cue files
would each cost ~6 dB of headroom for nothing. Each cue is seeded from its own parameters, so
reordering the list cannot change how a cue sounds. `audio.room` adds three early reflections
(11/23/41 ms, decorrelated) - not a reverb, just enough that a cue stops reading as a dry
sample dropped on the timeline.

`audio.master` turns on a **two-pass linear** loudness master: `assemble` renders the mix to
`premix.wav`, measures it with `loudnorm ... print_format=json`, then applies
`loudnorm=linear=true:measured_*=...`. Linear mode corrects with one static gain, so nothing
pumps - that is the difference between "normalized" and "mastered". An `alimiter` follows it,
set 0.4 dB below the ceiling: AAC adds inter-sample overshoot after the filter runs, and
