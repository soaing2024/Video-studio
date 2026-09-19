# Long-form: 5 minutes and beyond, in one take

Everything here is about filling runtime without wasting render time or losing the thread. The old
version of this file budgeted 20-40 *segments*; there are no segments any more. There is one shot,
and it runs from t=0 to the end.

## 1. The budget is frames, and holds are the only lever

Cost = frames to render = `duration × fps` minus the frames inside `hold` windows, divided by
`slices × jobs` (a single take renders in one process unless you pass `--slices`). A 5-minute
take at 1920×1080/30fps is 9000 frames before holds; `vs.py plan` turns that into wall clock for
your machine. There is no "make this bit a still segment" escape any more, so the take declares
it instead:

```jsonc
"duration": 300,
"scene": "scenes/take.html",
"hold": [[12.5, 26.0], [58.0, 96.0], [140.0, 205.0]]
```

Inside a hold the renderer reuses the previous frame: those seconds still exist in the finished
file, but they cost one frame each instead of 30 per second. Rule of thumb for a 5-minute take:

- keep **animated seconds under 90** and hold the rest
- check the split with `vs.py plan` - it prints `frames_to_render`, per-beat `hold`, and an estimate
- if the take is still too expensive: 1280×720 (about half), 24fps (a fifth less), or the pixel look
  (320×180, roughly 15×)

## 2. Write the narration first

Draft the script, then decide where the picture has to change. Chinese narration runs roughly 4-5
characters per second, English about 2.5 words per second, so a 40-character paragraph is about 9
seconds. The script decides the length of the take; the take decides the render.

`vs.py narrate <project> --script script.txt` synthesizes the voice and sets the duration from what
was actually spoken. For a single take, narrate it as one continuous line -
`{"segment": "take", "text": "..."}` - and let the scene place its internal cues against those
timings.

## 3. Structure the inside of the take

A five-minute single take still needs structure; it just does not get it from cuts. Aim for **8-12
internal chapters**, each one a real recomposition of the frame (the four devices are in
[formats.md](formats.md)), with the chapter label and the global progress bar
(`look.progress_bar`) telling the viewer where they are.

| section | typical share | chapters | how the frame changes |
| --- | --- | --- | --- |
| cold open | 10-20 s | 1-2 | full-frame statement, then the first transformation |
| context | 30-45 s | 2-3 | move the camera; replace one object with another |
| core argument | 2-2.5 min | 4-6 | the meat: one recomposition per idea, holds between |
| demonstration | 1-1.5 min | 2-3 | let something actually happen on screen |
| recap + CTA | 20-30 s | 1-2 | return to the opening frame, changed |

Rules that survive the change from segments to one take:

- **Animated seconds are the budget.** Budget them like money.
- **A recomposition is not an entrance.** The old failure was "everything fades up and holds";
  a chapter has to *change the arrangement* of the frame, not just bring in more type.
- **Escape the entry** at some point: the viewer needs at least one moment where the camera moves
  into the subject rather than the subject arriving.
- `render.crf: 12` for intermediates is visually lossless; the final `video.crf: 20` is fine.
- Intermediates live in `build/<name>/segments/`. Delete that folder to reclaim space at the cost of
  re-rendering.

## 4. Audio

```jsonc
"audio": {
  "tracks": [
    { "src": "assets/voice.wav", "at": 1.0, "gain_db": -3, "role": "voice" },
    { "src": "assets/music.mp3", "gain_db": -26, "fade_in": 2, "fade_out": 3, "loop": true, "duck": true }
  ]
}
```

Targets, as measured by `verify`: voice around -18 to -12 dB mean; music bed around -38 to -28 dB,
roughly 15-20 dB under the voice. `gain_db` is relative to the file as delivered - probe it first.
`amix` normalises by track count, so re-check levels after every track you add.

## 5. Subtitles

Burn them in; they survive grading and the pixel pass. Keep each cue under about 20 Chinese
characters or two lines, and keep `MarginV` clear of the progress bar:

```jsonc
"subtitles": { "src": "assets/subs.srt",
  "style": "FontName=Microsoft YaHei,FontSize=30,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=40" }
```

Verify subtitles actually rendered: extract a frame inside a cue window, count bright pixels in the
bottom band, and compare with a frame between cues.

## 6. Delivery checklist

1. `verify` passes - duration, content, fades, motion, audio level.
2. **No dead stretch**: the `motion` check reports frozen intervals against a budget; a long take
   with no holds declared and nothing moving is the failure this catches.
3. Spot-check a frame per internal chapter, not just the first frame.
4. Chapter numbering runs 1..N with no gaps.
5. Watch the joins *inside* the take: a recomposition that lands while the previous content is still
   fading reads as a mistake. One window, one event.
6. Keep `build/<name>/segments/` if you may re-cut; that clip is expensive to regenerate.

## 7. Re-editing

The take is cached in slices under `--slices`: a signature pass finds which slices actually
changed, so an edit re-renders only those, and a crash only re-renders what is missing (change
the **hold windows** and only the cost changes). During development, render at 1280×720 with
`fps: 12` to get the timing right, then set the delivery format and render once.
