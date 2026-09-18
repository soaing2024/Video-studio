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

`render.py` hashes template bytes + segment data + every asset's path/size/mtime + render size and
fps into a 16-char key, stored next to the clip as `.key`. A matching key means the clip is reused.

Measured effect: after the first run of the 3-segment demo, a full `run` took ~3 seconds because
only assembly and verification re-executed.

`--force` ignores the cache. Use it after changing anything the key cannot see (for example, a file
edited in place within the same second).

## 4. Assembly

One ffmpeg invocation per project. The filter graph is written to `build/<name>/filter.txt` and
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

Rendering is dominated by the screenshot round-trip, not by drawing.

| work size | per frame, 1 job | 5-minute video, 30 fps |
| --- | --- | --- |
| 1920×1080 | ~384 ms | ~58 min (≈20 min at `jobs: 3`) |
| 1280×720 | ~180 ms | ~27 min (≈10 min at `jobs: 3`) |
| 320×180 (pixel, scale 4) | ~25 ms at `jobs: 3` | ~4 min |
| held shot (`"still": true`) | one frame regardless of duration | seconds |

A 60-second 1080p held segment measured 14 s end-to-end including assembly and verification.

Ways to buy speed, in order of payoff: held shots for static sections → pixel look or lower
resolution → `fps: 24` for long-form → more `jobs` (diminishing returns past core count) → cached
segments for re-runs.

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

## 10. Extending it

- **New template:** copy one from `assets/templates/`, keep the `seek(t)` contract and the
  `window.SCENE` input, pass its path as `"template"` in a segment.
- **New look:** add a filter to the tail chain in `assemble.py`. Anything ffmpeg can express is
  available; keep it deterministic and duration-aware.
- **New quality gate:** add a measurement to `verify.py` and check the actual invariant, not the
  wording of a message.
