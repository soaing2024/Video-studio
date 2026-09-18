# The essence of animation

"Make it move more" is not the same instruction as "make it an animation". A shot can be full of
moves and still read as a slide deck, and that is measurable: count the frames that are identical to
the frame before them. The old engine measured 56-80% frozen on text-heavy templates. It is now
0-17%, and `verify` fails a project that regresses.

Four things do the work. They are structural, not decorative - no amount of extra glow, particle
spam or shake substitutes for any of them.

## 1. Causality: one thing acts on another

A slide has elements. An animation has events. The difference is whether what happens to B is caused
by A. When a bar grows and the number beside it changes because the bar grew, the frame is a system;
when they fade in side by side, it is a list. In this engine the cause is the beat sheet: a beat is a
state change that everything on screen reacts to, at slightly different times, with the reactions
sized to the beat's intensity.

## 2. Continuity: never two identical frames

`Anim.driftAt` gives every actor a perpetual wander on top of its keyframes - three incommensurate
frequencies, phased per element, so nothing moves together and nothing repeats inside a shot. Without
it, a shot with six moves still spends most of its runtime frozen, because moves are short and the
gaps between them are long. This is the single cheapest fix for the "it looks like PowerPoint"
feeling, and it is why the engine can now pass a frame-to-frame stillness check.

## 3. Composition: the page has to change

The other half of "the same page is on screen too long" is that the arrangement never changes. The
beat sheet therefore schedules two *composition* beats on their own clock, independent of the
nudges:

- `relayout` - the text block and the subject swap sides. Same material, recomposed.
- `restage` - the camera cuts. A hard reframe: a new framing, a new page, in the same shot.

`choreography.PAGE_DWELL` caps how long the arrangement may hold (1.8-3.0s by pacing), and the
camera gets a hard cut at every `restage` through `Anim.Path`. Measured: a 25-second shot now carries
6-14 composition changes instead of one.

## 4. Travel you can see, and text that survives it

The old camera nudged the frame 14-20px over two seconds - about 10px/s, which the eye reads as a
still image however smoothly it is interpolated. The camera now follows a bounded sweep of ~100px
amplitude at a visible speed, with a per-page offset that makes each reframe land on a different
framing.

That travel is split across layers by depth, and the split is deliberate: the background and subject
carry it, and the text plate takes almost none of it. These layouts run edge to edge - a headline
that starts 88 units from the frame cannot move with the camera without clipping its own edge. Its
life comes from the drift and the beat sheet instead. The renderer's layout audit samples five
instants and fails on type that leaves the frame.

## What this looks like per template

| Template | per frame (0-255) | per second | frozen |
|---|---|---|---|
| pixel | 6.98 | 12.12 | 1% |
| kinetic | 7.24 | 14.34 | 0% |
| caption | 4.43 | 9.59 | 1% |
| stat / quote / terminal / chart | 5.72 | 11.15 | 0% |
| short-form mix (hook / explain / cta) | 3.22 | 7.67 | 11% |
| old engine, kinetic (control) | 0.31 | 1.17 | 86% |

Gates: `verify` requires change per second >= 2.2 and frozen intervals <= 15% plus whatever static
runtime the project declares. `plan` reports the beat sheet's worst gap and worst composition dwell
so a shot that would fail is visible before anything renders.

## Applying it to a new template

1. Call `scene.driftDefaults(M.drift, S.id)` before creating any actor.
2. Use `Kit.makeCamera` (or `new Anim.Path(M.camera_keys)`) - never a list of separately eased
   waypoints.
3. Schedule content on `establish`, not on a beat that may not exist in a given shot. A row that
   only appears on a `build` beat is invisible for the whole shot when the beat sheet has none.
4. Give every beat something to move that is *already on screen*.
5. Handle `relayout` and `restage`; they are what stop a long shot from being one page.
6. Let the layout audit run and read its warnings - off-frame, never-visible and overlapping blocks
   are reported per segment with the offending text.
