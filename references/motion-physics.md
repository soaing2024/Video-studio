# Motion physics — baked simulation, sampled by t

`Anim.spring` is one overshooting scalar. That covers arrivals, and nothing else: no mass
chains, no thrown objects, no swinging, no drift with a spectrum. This file is the layer that
adds those without breaking the one rule the renderer depends on.

**The rule, restated for simulations.** Every animated value must be a pure function of `t`.
A simulation can obey it: run the integrator **once** with a fixed step at load, store the
samples, and answer `at(t)` by interpolating them. Nothing here starts a clock; `phys.js` reads
the wall clock nowhere and never uses unseeded randomness. Two renders of the same project are
the same pixels, and a slice rendered at `t=12s` matches the same frame in a full take.

Injected as `Phys` alongside `Scene` / `Anim` / `Kit`. Source: `assets/runtime/phys.js`.

## API

```js
const drop   = Phys.spring({ from: -180, to: 0, stiffness: 190, damping: 0.62 });
const whip   = Phys.chain({ n: 5, gap: 0.055, from: 0, to: 1, stiffness: 300, damping: 0.62,
                            gain: 1.25 });
const ball   = Phys.ballistic({ y0: 300, v0: 0, g: 980, floor: 0, bounce: 0.5 });
const clock  = Phys.pendulum({ len: 1, g: 9.81, theta0: 0.4, damping: 0.3 });
const settle = Phys.drag({ from: 0, to: 1, k: 3 });
const breath = Phys.noise({ seed: 5, freq: 0.4, amp: 1, octaves: 3 });
const hand   = Phys.handheld({ amp: 3, rot: 0.12, seed: 11, freq: 0.22 });
```

| call | what it is | returns |
| --- | --- | --- |
| `spring` | damped spring, any damping regime; `damping` is zeta (0.45 ≈ 15% overshoot) | `{at(t), from, to}` |
| `chain` | head motion + N followers, each `gap` seconds later; `gain` lets the tail travel further | `{at(t,i), item(i).at(t), values(t), n, gap}` |
| `ballistic` | gravity with optional floor and bounce; analytic, exact at any `t` | `{at(t) -> {y, vy, hits}}` |
| `pendulum` | damped swing (`θ'' = -(g/L)sinθ - cθ'`) | `{at(t)}` |
| `drag` | friction: exponential approach, no overshoot | `{at(t)}` |
| `noise` | seeded band-limited 1-D noise (fBm, 1–6 octaves) | `{at(t)}` |
| `handheld` | two-axis drift at incommensurate frequencies + slow roll | `{at(t) -> {x,y,rot}, css(t)}` |
| `bake` | the general tool: `{state, step(s, dt), read(s)} -> {at(t)}` | `{at(t), samples}` |
| `rng(seed)` | deterministic PRNG if you need your own randomness | `() => number` |

Sampling: fixed step, default 1/600 s, linear interpolation between samples. Cheaper than it
sounds — a 6-body chain over a 20 s take is ~72k floats. Systems are clamped to a 30 s horizon.

## Which principle each call serves

| principle | call |
| --- | --- |
| squash & stretch | `spring` (or your own curve) drives the impact; keep `sx * sy ≈ 1` |
| anticipation | `spring({ v0: -v })`, or `Anim.withAnticipation` on the scalar track |
| follow-through / overlap | `chain` — the delay is applied to the clock, so followers replay the head's shape instead of overtaking it |
| arcs | offset the value along a perpendicular with a `sin(pi*p)` envelope |
| timing | every system is queried by `t`; `hold` windows still freeze the frame |
| weight | `damping` and `stiffness`: heavy = low stiffness, high damping, long decay |
| secondary action | drive them from the same `t` with their own smaller `spring`/`noise` |
| appeal / solidity | `noise` for breathing, `handheld` for a camera that is not on rails |

## Traps this file exists to avoid

1. **A follower that overtakes its leader.** Springing body *i* toward the instantaneous
   position of body *i-1* produces overshoot past the leader; the chain reads as a wobble.
   `Phys.chain` delays the clock instead and tracks with a critically damped filter.
   Verified: `|body_i(t) - head(t - i*gap)| == 0.0000` on the shipped implementation.
2. **Sub-stepping that depends on the render fps.** Baking at 1/600 s and interpolating means
   the same `t` gives the same value at 24, 30 or 60 fps — and at 2× shutter oversampling.
3. **Randomness in the scene.** `noise` and `handheld` take a `seed`. If you need your own,
   use `Phys.rng(seed)`; never `Math.random()`, which is the one thing `check` cannot forgive.
4. **Simulating during the frame loop.** Bake once at load (lazy, on first `at()`), then query.
   A `step()` call inside `seek(t)` would make the frame depend on history, and slices would
   disagree with full takes.

## Verification

`open -a` a `vs.py scrub <project>` page and step frame by frame: the scrub host drives the
same `seek(t)` the renderer calls, so what you see is the baked values, not a live simulation.
For a rendered check, `vs.py rehearse <project> --at a:b` gives a draft you can watch, and
`vs.py verify <project>` still owns the measured gates.
