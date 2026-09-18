# Long-form: 5 minutes and beyond

Everything here is about filling runtime without wasting render time or losing the thread.

## 1. Budget the structure before anything else

A 5-minute video is 300 seconds. Do not think in one timeline; think in segments.

| section | typical share | segment length | count |
| --- | --- | --- | --- |
| cold open / hook | 10-20 s | 5-10 s | 2-3 |
| context | 30-45 s | 10-15 s | 3-4 |
| core argument | 2-2.5 min | 15-30 s | 6-10 |
| demonstration | 1-1.5 min | 20-45 s | 3-4 |
| recap + CTA | 20-30 s | 8-12 s | 2 |

Aim for 20-40 segments. Fewer means every segment has to carry too much and becomes a slideshow;
more means the render budget and the chapter numbering both get noisy.

## 2. Write the narration first, then the visuals

Draft the spoken script, split it at natural paragraph breaks, and make each paragraph one segment.
Duration follows the words: Chinese narration runs roughly 4-5 characters per second, English about
2.5 words per second. A 40-character Chinese paragraph is therefore about 9 seconds.

This ordering matters because the script decides the segment count, and the segment count decides
the render time. Never design 40 shots and then discover the script is 3 minutes short.

## 3. Use held shots for anything static

`"still": true` renders one frame and holds it for the segment duration. This is the single biggest
lever on a long video.

```jsonc
{ "id": "ch03a", "template": "caption", "duration": 24.0,
  "data": { "still": true, "title": "第三步：交付", "caption": "把上面的结论写成一句话。" },
  "assets": { "subject": "assets/fig03.png" } }
```

Measured: a 60-second 1080p held segment costs ~14 s end-to-end (one rendered frame plus encode),
versus ~23 minutes if rendered frame by frame. A 5-minute video built mostly from held shots plus a
few animated segments finishes in a couple of minutes.

Reserve full animation for the hook, section transitions, and the diagrams that actually move. If a
section only holds a slide and a caption, hold it.

## 4. Budget the render

At 1080p with `jobs: 3`, animated segments cost roughly 0.13 s per frame of wall time, i.e. about
4 seconds of render per second of finished video. A 5-minute video with 60 seconds of animated
segments and 240 seconds of held shots lands around 4-6 minutes of wall time. Check
`references/pipeline.md` for the raw per-resolution numbers.

Rules of thumb:

- Animated seconds are the budget. Keep a running total; 60-90 s of animation in a 5-minute video is
  plenty.
- `render.crf: 12` for intermediates is visually lossless and keeps `build/` small; the final
  `video.crf: 20` is fine for talk-heavy content.
- Intermediates live in `build/<name>/segments/`. Delete the folder to reclaim space at the cost of
  re-rendering.
- Parallel `jobs` should not exceed physical cores; screenshot capture is CPU-bound.

## 5. Audio: voice over music

```jsonc
"audio": { "tracks": [
  { "src": "assets/voice.wav", "at": 1.0, "gain_db": -3 },
  { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true }
] }
```

Targets, as measured by `verify`:

- voice around -18 to -12 dB mean
- music bed around -38 to -28 dB mean, i.e. roughly 15-20 dB under the voice
- `gain_db` is relative to the file as delivered. Probe it first: a track that already measures
  -31 dB needs only -6, not -26.

`amix` normalises by track count, so adding a third track quietly lowers the other two. Re-check
levels after every track you add.

If the mix still fights, lower the music with `gain_db` rather than raising the voice, and prefer a
music bed with no vocals under narration.

## 6. Subtitles

Write an SRT next to the audio and hand it to the assembler. It is burned in after the look, so it
survives grading and the pixel pass.

```jsonc
"subtitles": { "src": "assets/subs.srt",
  "style": "FontName=Microsoft YaHei,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=36" }
```

For 1080p bump `FontSize` to 30-34. `MarginV` keeps the text clear of the bottom edge and of any
progress bar. Keep each cue under about 20 Chinese characters or two lines; long cues get clipped
and read badly.

Verify that subtitles actually rendered: extract a frame inside a cue window and count bright pixels
in the bottom band, then compare with a frame in a gap between cues.

## 7. Chapters and the progress bar

Give every segment `chapter: { index, total, label }`; `caption` and `pixel` render it as a chip, so
the viewer always knows where they are. Add a global bar instead of a per-segment one:

```jsonc
"look": { "progress_bar": { "height": 4, "color": "#e0455f" } }
```

## 8. Delivery checklist

Before handing over a long video, confirm:

1. `verify` passes — duration within 2% of planned, no black sections, fades present, audio level in
   range.
2. Spot-check one frame per chapter with `preview` or a frame extraction, not just the first frame.
3. Chapter numbering runs 1..N with no gaps and matches the count in the last segment.
4. Watch the joins: a cut between two segments with a similar background reads as a mistake — give
   the boundary a 0.4-0.6 s crossfade or a hard contrast change.
5. File size and `+faststart` — the encoder already sets faststart, and a 5-minute 1080p file at
   crf 20 lands around 50-150 MB depending on motion.
6. Keep the build folder if you may need to re-cut; only `build/<name>/segments/*.mp4` is expensive
   to regenerate.

## 9. Re-editing

Because segments are cached independently, changing one chapter costs one segment plus assembly.
Re-cut the order by editing `timeline` only. If a segment's `data` changes, only that segment
re-renders — this is what makes iteration on a long video practical.
