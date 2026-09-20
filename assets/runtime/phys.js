/* Physical motion, baked and then sampled by the second.
 *
 * The rule that shapes this file: every animated value must be a pure function of `t`. A
 * simulation can still obey it - run the integrator once at load with a fixed step, store the
 * samples, and answer `at(t)` by interpolating them. Nothing here starts a clock, reads
 * the wall clock or unseeded randomness, so two renders of the same project are identical.
 *
 * What it buys over `Anim.spring` (a single overshooting scalar):
 *
 *   Phys.chain     follow-through with real lag - the tail of a whip, a stack of cards, a
 *                  cursor that drags its own highlight
 *   Phys.spring    arrivals with mass, in any damping regime, as a settled value
 *   Phys.ballistic a thrown object, with bounces and a floor
 *   Phys.pendulum  a swinging body with damping (signs, tags, hanging type)
 *   Phys.drag      friction: exponential settle, no overshoot
 *   Phys.noise     band-limited, seeded drift - breathing, handheld, film weave
 *   Phys.bake      the general tool: any `state -> state` step you can write
 *
 * Usage:
 *   const lift = <ID>Phys.spring({ from: 0, to: -40, stiffness: 180, damping: 0.55 });<ID>
 *   const whip = <ID>Phys.chain({ n: 5, gap: 0.05, stiffness: 320, damping: 0.7 });<ID>
 *   window.seek = (t) => {<ID>
 *     card.style.transform = `translateY(${lift.at(t)}px)`;<ID>
 *     whip.values(t).forEach((v, i) => seg[i].style.transform = `translateX(${v}px)`);<ID>
 *   };<ID>
 *
 * Cost: baking happens once, on first use, at 1/600 s. A 6-body chain over 20 s is ~72k floats.
 */
(function (global) {
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const BAKED_DT = 1 / 600;
// 15 minutes. The old cap was 30 s and silently clamped anything longer, so a long take kept
// sampling the last baked value - the motion froze mid-shot with no error. Memory is not the
// constraint here: 15 minutes at 1/600 s is 900k doubles, about 7 MB per system.
const MAX_BAKE = 900;           // seconds

  /* deterministic 32-bit hash -> [0,1) */
  function hash(i, seed) {
    let h = (i | 0) ^ Math.imul(seed | 0, 0x9e3779b1);
    h = Math.imul(h ^ (h >>> 16), 0x85ebca6b);
    h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }

  function rng(seed) {
    let a = (seed >>> 0) || 0x2f6e2b1;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* value noise: smooth, band-limited, and a pure function of (x, seed) */
  function vnoise(x, seed) {
    const i = Math.floor(x), f = x - i;
    const u = f * f * (3 - 2 * f);
    const a = hash(i, seed), b = hash(i + 1, seed);
    return a + (b - a) * u;
  }

  function fbm(x, seed, octaves, gain, lac) {
    let amp = 1, sum = 0, norm = 0, freq = 1;
    for (let o = 0; o < octaves; o++) {
      sum += vnoise(x * freq, seed + o * 101) * amp;
      norm += amp;
      amp *= gain; freq *= lac;
    }
    return norm ? sum / norm : 0;
  }

  function interpolate(samples, dt, t) {
    if (!samples.length) return 0;
    if (t <= 0) return samples[0];
    const x = t / dt;
    const i = Math.floor(x);
    if (i >= samples.length - 1) return samples[samples.length - 1];
    const f = x - i;
    return samples[i] + (samples[i + 1] - samples[i]) * f;
  }

  /* Run a fixed-step integrator once and hand back a sampler. `state` is any array/object the
     author's `step` mutates (or returns). `read` picks the value out of the state. */
  function bake(opts) {
    const o = opts || {};
    const dt = o.dt || BAKED_DT;
    const wanted = Math.max(0.1, o.duration || 12);
    const duration = Math.min(MAX_BAKE, wanted);
    const n = Math.ceil(duration / dt) + 1;
    const init = () => JSON.parse(JSON.stringify(o.state === undefined ? 0 : o.state));
    const step = o.step || function (s) { return s; };
    const read = o.read || function (s) { return s; };
    const out = new Float64Array(n);
    let s = init();
    for (let i = 0; i < n; i++) {
      out[i] = Number(read(s, i * dt)) || 0;
      const next = step(s, dt);
      if (next !== undefined) s = next;
    }
    return {
      dt: dt,
      duration: duration,
      samples: out,
      at(t) { return interpolate(out, dt, Math.max(0, t)); },
      clamped: wanted > duration,
      settled: wanted <= duration
    };
  }

  /* Damped spring, numerically integrated so every damping regime behaves.
     stiffness = k/m in rad^2/s^2 (100..500 is the usable band), damping = zeta (0.2..1.2). */
  function spring(opts) {
    const o = opts || {};
    const from = Number(o.from || 0), to = Number(o.to === undefined ? 1 : o.to);
    const k = Math.max(0.01, Number(o.stiffness === undefined ? 180 : o.stiffness));
    const z = Math.max(0.02, Number(o.damping === undefined ? 0.7 : o.damping));
    const v0 = Number(o.v0 || 0);
    const w0 = Math.sqrt(k);
    const dt = Math.min(BAKED_DT, 0.12 / w0);
    const o2 = { from: from, to: to, k: k, z: z, v0: v0 };
    const sys = bake({
      dt: dt,
      duration: Math.min(MAX_BAKE, Math.max(1.2, 6 / (z * w0 || 1))),
      state: { x: from - to, v: v0 },
      step(s, h) {                        // semi-implicit Euler
        s.v += (-o2.k * s.x - 2 * o2.z * w0 * s.v) * h;
        s.x += s.v * h;
        return s;
      },
      read(s) { return to + s.x; }
    });
    sys.to = to; sys.from = from;
    // Honest settle test: the spring is done when its tail is at the target. This used to be
    // hardcoded `true`, so a system that was still moving claimed it had finished.
    const tail = sys.samples[sys.samples.length - 1];
    sys.settled = Math.abs(tail - to) <= Math.max(0.001, Math.abs(to - from) * 0.01);
    return sys;
  }

  /* Chain of N bodies with follow-through: the head springs to `to`, every body behind it
     plays the same motion `gap` seconds later, and the tail can travel further (`gain`).
     The delay is applied to the clock, not through a laggy spring chasing a moving target:
     the latter makes followers overtake their own leader, which reads as a wobble rather
     than a whip. `smooth` runs each body through a critically damped tracker so the delayed
     start has no velocity corner. */
  function chain(opts) {
    const o = opts || {};
    const n = Math.max(2, Math.min(24, int(o.n, 6)));
    const gap = Math.max(0, Number(o.gap === undefined ? 0.05 : o.gap));       // seconds of lag
    const to = Number(o.to === undefined ? 1 : o.to);
    const from = Number(o.from || 0);
    const k = Math.max(0.01, Number(o.stiffness === undefined ? 320 : o.stiffness));
    const z = Math.max(0.02, Number(o.damping === undefined ? 0.7 : o.damping));
    const gain = Math.max(0.1, Number(o.gain === undefined ? 1 : o.gain));     // tail travel
    const smooth = o.smooth !== false;
    const w0 = Math.sqrt(k);
    const dt = Math.min(BAKED_DT, 0.12 / w0);
    const duration = Math.min(MAX_BAKE, Math.max(1.5, 6 / (z * w0 || 1) + gap * n));
    const steps = Math.ceil(duration / dt) + 1;

    // the head's own trajectory; everything behind it is a delayed (and amplified) copy
    const head = new Float64Array(steps);
    let x = from - to, v = 0;
    for (let f = 0; f < steps; f++) {
      head[f] = to + x;
      v += (-k * x - 2 * z * w0 * v) * dt;
      x += v * dt;
    }

    const series = [];
    for (let i = 0; i < n; i++) {
      const lagFrames = Math.round((gap * i) / dt);
      const amp = 1 + (gain - 1) * (n > 1 ? i / (n - 1) : 0);
      const line = new Float64Array(steps);
      let cx = from, cv = 0;
      for (let f = 0; f < steps; f++) {
        const src = Math.max(0, f - lagFrames);
        const target = from + (head[src] - from) * amp;
        if (!smooth) { line[f] = target; continue; }
        const prev = Math.max(0, src - 1);
        const targetV = (head[src] - head[prev]) / dt;
        cv += (-k * (cx - target) - 2 * w0 * (cv - targetV)) * dt;
        cx += cv * dt;
        line[f] = cx;
      }
      series.push(line);
    }

    return {
      n: n, dt: dt, duration: duration, gap: gap,
      item(i) {
        const idx = Math.max(0, Math.min(n - 1, int(i, 0)));
        return { at: (t) => interpolate(series[idx], dt, Math.max(0, t)) };
      },
      at(t, i) { return this.item(i || 0).at(t); },
      values(t) { const out = []; for (let i = 0; i < n; i++) out.push(this.item(i).at(t)); return out; }
    };
  }

  /* Thrown body with gravity and bounces. Analytic, so it is exact at any t. */
  function ballistic(opts) {
    const o = opts || {};
    const y0 = Number(o.y0 || 0), v0 = Number(o.v0 || 0);
    const g = Number(o.g === undefined ? 980 : o.g);
    const bounce = Math.max(0, Math.min(0.95, Number(o.bounce === undefined ? 0.45 : o.bounce)));
    const floor = o.floor === undefined ? null : Number(o.floor);
    return {
      at(t) {
        let y = y0, v = v0, left = Math.max(0, t), hits = 0;
        while (floor !== null && hits < 32) {
          const disc = v * v + 2 * g * (y - floor);
          if (disc < 0) break;                 // never reaches the floor again
          const hit = (v + Math.sqrt(disc)) / g;
          if (!(hit > 0) || hit > left) break; // the impact is after t
          left -= hit;
          v = -Math.sqrt(disc) * bounce;       // impact speed, reversed and damped
          y = floor;
          hits += 1;
          if (Math.abs(v) < 1e-3) break;
        }
        let yy = y + v * left - 0.5 * g * left * left;
        let vy = v - g * left;
        if (floor !== null && yy < floor) { yy = floor; vy = 0; }
        return { y: yy, vy: vy, hits: hits };
      }
    };
  }

  /* Swinging body: theta'' = -(g/L) sin(theta) - c theta'. Numerically baked (no closed form). */
  function pendulum(opts) {
    const o = opts || {};
    const len = Math.max(0.05, Number(o.len === undefined ? 1 : o.len));
    const g = Number(o.g === undefined ? 9.81 : o.g);
    const c = Math.max(0, Number(o.damping === undefined ? 0.35 : o.damping));
    const a0 = Number(o.theta0 === undefined ? 0.4 : o.theta0);
    const v0 = Number(o.v0 || 0);
    return bake({
      state: { a: a0, v: v0 },
      duration: Math.min(MAX_BAKE, Math.max(2, 24 / Math.max(0.05, c))),
      step(s, h) {
        s.v += (-(g / len) * Math.sin(s.a) - c * s.v) * h;
        s.a += s.v * h;
        return s;
      },
      read(s) { return s.a; }
    });
  }

  /* Friction: approaches the target with no overshoot. x(t) = target + (x0-target) e^{-kt} */
  function drag(opts) {
    const o = opts || {};
    const x0 = Number(o.from || 0), target = Number(o.to === undefined ? 1 : o.to);
    const k = Math.max(0.001, Number(o.k === undefined ? 3 : o.k));
    return { at(t) { return target + (x0 - target) * Math.exp(-k * Math.max(0, t)); } };
  }

  /* Seeded, band-limited drift. The workhorse for breathing, handheld and film weave. */
  function noise(opts) {
    const o = opts || {};
    const seed = int(o.seed, 1);
    const freq = Number(o.freq === undefined ? 1 : o.freq);
    const amp = Number(o.amp === undefined ? 1 : o.amp);
    const octaves = Math.max(1, Math.min(6, int(o.octaves, 2)));
    const gain = Number(o.gain === undefined ? 0.5 : o.gain);
    const lac = Number(o.lacunarity === undefined ? 2.13 : o.lacunarity);
    const base = Number(o.offset || 0);
    return {
      at(t) { return (fbm(t * freq + base, seed, octaves, gain, lac) * 2 - 1) * amp; }
    };
  }

  /* Two-axis drift at incommensurate frequencies (so it never visibly loops) plus a slow roll. */
  function handheld(opts) {
    const o = opts || {};
    const seed = int(o.seed, 7);
    const amp = Number(o.amp === undefined ? 2 : o.amp);
    const rot = Number(o.rot === undefined ? 0.15 : o.rot);
    const freq = Number(o.freq === undefined ? 0.35 : o.freq);
    const nx = noise({ seed: seed, freq: freq, amp: amp, octaves: 3 });
    const ny = noise({ seed: seed + 977, freq: freq * 1.618, amp: amp * 0.7, octaves: 3 });
    const nr = noise({ seed: seed + 313, freq: freq * 0.61, amp: rot, octaves: 2 });
    return {
      at(t) { return { x: nx.at(t), y: ny.at(t), rot: nr.at(t) }; },
      css(t, extra) {
        const v = this.at(t);
        return `translate3d(${v.x.toFixed(2)}px, ${v.y.toFixed(2)}px, 0) rotate(${v.rot.toFixed(3)}deg)` +
               (extra ? " " + extra : "");
      }
    };
  }

  function int(v, dflt) {
    const n = Number(v);
    return Number.isFinite(n) ? Math.round(n) : dflt;
  }

  global.Phys = {
    rng: rng,
    bake: bake,
    spring: spring,
    chain: chain,
    ballistic: ballistic,
    pendulum: pendulum,
    drag: drag,
    noise: noise,
    handheld: handheld,
    clamp01: clamp01,
    BAKED_DT: BAKED_DT,
    list: () => ["rng", "bake", "spring", "chain", "ballistic", "pendulum", "drag", "noise", "handheld"]
  };
})(typeof window !== "undefined" ? window : globalThis);
