/* Motion - the runtime that makes a discontinuity unrepresentable.
 *
 * Why a runtime and not a gate: an audit can only tell you, after a 25-minute render, that a
 * value was impossible to carry. The guarantee has to live where the value is produced. Every
 * drawn parameter in a scene is evaluated through these primitives, and the primitives cannot
 * return a step:
 *
 *   channel()  retargets FROM WHERE IT IS, takes at least 4 frames to arrive, and no single
 *              frame may cover more than 30% of the distance still to travel. A parameter
 *              therefore cannot jump between two frames - the "闪现" case - and every frame's
 *              position is reachable from the previous one, which is what "有迹可循" means
 *              in numbers.
 *   osc() / shake()  oscillators are snapped to a WHOLE NUMBER of frames per cycle (>= 5). At
 *              3 frames per cycle consecutive frames land on opposite extremes and a shake is
 *              read as a jump; at 5 the sampled wave is exactly periodic and every frame
 *              follows from the last - the "突变漂移" case. A rate above the band is folded to
 *              the fastest representable one, never rejected.
 *   hit()      an impact whose attack is at least 4 frames whatever you ask for, with a
 *              monotonic time warp for 卡肉 and its jitter taken from shake().
 *   gate()     appearance and disappearance with a floor on both ramps, so nothing pops into
 *              frame unannounced ("突脸").
 *
 * Traceability is provable per element rather than argued: every channel records its own worst
 * per-frame step and the widest travel it ever made, so `Motion.report()` shows the ratio.
 *
 * The delivery frame rate arrives as SCENE.fps (injected by the renderer), so the band is
 * computed for the format actually being delivered - the same scene rendered at 60 fps simply
 * gets a wider band. Nothing here starts a clock: every value stays a pure function of t,
 * which is this skill's one hard rule.
 */
window.Motion = (function () {
  const SCENE = window.SCENE || {};
  const FPS = Math.max(1, Number(SCENE.fps) || 30);
  const FRAME = 1 / FPS;
  const MIN_FRAMES = 4;          // shortest ramp a change may take
  const MAX_STEP_FRAC = 0.30;    // largest share of the travel one frame may cover
  const MIN_CYCLE = 5;           // frames per oscillator cycle
  const BAND_HZ = FPS / MIN_CYCLE;
  const TAU = Math.PI * 2;

  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const ease = (x) => {
    x = clamp01(x);
    return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  };
  const isVec = Array.isArray;
  const mix = (a, b, p) => (isVec(a) ? a.map((v, i) => v + (b[i] - v) * p) : a + (b - a) * p);
  const dist = (a, b) => (isVec(a) ? a.reduce((m, v, i) => Math.max(m, Math.abs(v - b[i])), 0)
                                   : Math.abs(a - b));

  const channels = [];

  /** A parameter that cannot step. `set()` retargets from the value the channel is showing
   *  right now (never from the previous target), so calling it every frame is safe. */
  function channel(name, initial) {
    let cur = isVec(initial) ? initial.slice() : initial;
    let from = cur, to = cur, t0 = -1e9;
    let dur = MIN_FRAMES * FRAME;
    let prev = cur, lastT = -1e8, worstStep = 0, worstT = 0, moves = 0, travelSeen = 1e-9;
    const ch = {
      name: name || ("ch" + channels.length),
      /** Target a new value. `in` is a request, never a guarantee: the ramp is never shorter
       *  than MIN_FRAMES, which is what makes a step impossible. */
      set(t, target, opts) {
        const o = opts || {};
        if (moves > 0 && dist(target, to) < 1e-9) return ch;      // same intent, no restart
        from = cur;                                              // <- unconditional: from here
        to = isVec(target) ? target.slice() : target;
        t0 = t - Math.max(0, Number(o.delay) || 0);
        dur = Math.max(Number(o.in) || 0, MIN_FRAMES * FRAME);
        travelSeen = Math.max(travelSeen, dist(from, to));
        moves += 1;
        return ch;
      },
      /** Place the value with no ramp. Only for the state a scene starts in, before any frame
       *  is drawn: at t = 0 there is no previous frame to be continuous with. */
      place(value) {
        cur = from = to = isVec(value) ? value.slice() : value;
        prev = isVec(cur) ? cur.slice() : cur;
        return ch;
      },
      at(t) {
        const p = clamp01((t - t0) / dur);
        let v = mix(from, to, ease(p));
        // The slew limit is the whole guarantee: a 4-frame cubic ramp would otherwise put 44%
        // of the move into its middle frame. Capped at 30%, every frame is followable, and
        // `p >= 1` still lands exactly on the target with no residue.
        const travel = dist(to, from);
        if (travel > 1e-9) {
          const cap = MAX_STEP_FRAC * travel;
          if (isVec(v)) {
            v = v.map((val, i) => prev[i] + Math.max(-cap, Math.min(cap, val - prev[i])));
          } else {
            v = prev + Math.max(-cap, Math.min(cap, v - prev));
          }
        }
        // No exact-snap shortcut when the cap is binding: snapping would put the whole
        // remainder into one frame (measured 33.8% of travel against a 30% cap). The capped
        // step converges and lands exactly once what is left is within the cap.
        cur = v;
        if (t > lastT && lastT > -1e7) {
          const step = dist(cur, prev);
          if (step > worstStep) { worstStep = step; worstT = t; }
        }
        prev = isVec(cur) ? cur.slice() : cur;
        lastT = t;
        return cur;
      },
      get value() { return cur; },
      /** Where it is, what it is heading to, and the worst frame it ever had, as a share of
       *  the widest travel it ever made. <= MAX_STEP_FRAC means the motion is traceable. */
      trace() {
        return { name: ch.name, value: cur, target: to, moves,
                 worstStep: +worstStep.toFixed(5),
                 worstShare: +(worstStep / Math.max(travelSeen, 1e-9)).toFixed(3),
                 worstAt: +worstT.toFixed(3) };
      },
    };
    channels.push(ch);
    return ch;
  }

  /** The fastest rate this delivery can carry, and how many frames a cycle of `hz` gets. */
  function safe(hz) {
    const want = Math.abs(Number(hz) || 1);
    const cycles = Math.max(MIN_CYCLE, Math.round(FPS / Math.max(want, 1e-6)));
    return { hz: FPS / cycles, rad: TAU * FPS / cycles, frames: cycles };
  }

  /** A band-limited oscillator in [-1, 1], exactly periodic over a whole number of frames so
   *  its values can never land on two extremes in a row. */
  function osc(t, opts) {
    const o = opts || {};
    const s = safe(o.hz);
    return Math.sin(TAU * (t * FPS) / (o.cycles || s.frames) + (o.phase || 0));
  }

  /** Two-axis shake in amplitude units (multiply by your own pixel scale). The second axis uses
   *  a co-prime cycle count, so the path does not visibly repeat. */
  function shake(t, opts) {
    const o = opts || {};
    const amp = o.amp === undefined ? 1 : o.amp;
    const s = safe(o.hz === undefined ? BAND_HZ * 0.85 : o.hz);
    const f = t * FPS;
    return [amp * Math.sin(TAU * f / s.frames + (o.phase || 0)),
            amp * Math.sin(TAU * f / (s.frames * 2 + 1) + 1.7 + (o.phase || 0))];
  }

  /** An impact that cannot pop: the attack is at least MIN_FRAMES whatever you ask for, so the
   *  frame after the hit is one the eye can follow from the frame before it. */
  function hit(t, opts) {
    const o = opts || {};
    const at = Number(o.at) || 0;
    const dt = t - at;
    const attack = Math.max(Number(o.attack) || 0, MIN_FRAMES * FRAME);
    const release = Math.max(Number(o.release) || 0.44, MIN_FRAMES * FRAME);
    const flashRelease = Math.max(Number(o.flashRelease) || 0.15, MIN_FRAMES * FRAME);
    // A LINEAR attack, not an eased one. A 4-frame cubic ramp puts 44% of the hit into its
    // middle frame - measured, and visible. Linear over >= 4 frames caps every frame's share
    // at 1/MIN_FRAMES = 25%, which is the same bound the channels hold to.
    const env = dt <= 0 ? 0 : (dt < attack ? Math.min(1, dt / attack)
                                           : Math.exp(-(dt - attack) / release));
    const flashEnv = dt <= 0 ? 0 : (dt < attack ? Math.min(1, dt / attack)
                                                 : Math.exp(-(dt - attack) / flashRelease));
    const j = shake(t, { amp: 1, hz: o.jitterHz, phase: (Number(o.seed) || 0) * 0.7 });
    const s = Number(o.shake) || 0;
    return {
      dark: (Number(o.dark) || 0) * env,
      flash: (Number(o.flash) || 0) * flashEnv,
      shake: s * env,
      jitter: [j[0] * s * env, j[1] * s * env],   // scale it, do not add it raw
      active: dt >= 0 && env > 0.002,
    };
  }

  /** 卡肉: one monotonic warp shared by every hit in the take. Each step stays far below 1 s/s,
   *  so the warped clock can only slow down and never runs backwards. */
  function warp(t, hits) {
    let off = 0;
    const list = hits || [];
    for (let i = 0; i < list.length; i++) {
      const h = list[i];
      const dt = t - (Number(h.at) || 0);
      if (dt <= 0) continue;
      const ramp = Math.max(Number(h.ramp) || 0.30, MIN_FRAMES * FRAME);
      off += (Number(h.amount) || 0) * Math.min(1, dt / ramp);
    }
    return off;
  }

  /** Appearance / disappearance with a floor on both ramps: nothing enters or leaves in one
   *  frame, whatever the caller asks for. */
  function gate(t, opts) {
    const o = opts || {};
    const at = Number(o.at) || 0;
    const inD = Math.max(Number(o.in) || 0.25, MIN_FRAMES * FRAME);
    const outD = Math.max(Number(o.out) || 0.25, MIN_FRAMES * FRAME);
    if (t < at) return 0;
    if (o.until === undefined) return ease((t - at) / inD);
    if (t <= o.until) return 1;
    return 1 - ease((t - o.until) / outD);
  }

  /** Traceability evidence, per element: the worst frame each parameter ever had, as a share of
   *  its widest travel. Nothing here can exceed MAX_STEP_FRAC by construction. */
  function report() {
    const rows = channels.map((c) => c.trace());
    const worst = rows.reduce((m, r) => (r.worstShare > (m ? m.worstShare : -1) ? r : m), null);
    return {
      fps: FPS, frame: +FRAME.toFixed(6),
      band_hz: +BAND_HZ.toFixed(3), band_rad: +(TAU * BAND_HZ).toFixed(1),
      min_ramp_s: +(MIN_FRAMES * FRAME).toFixed(4), max_step_frac: MAX_STEP_FRAC,
      channels: rows,
      worst: worst && worst.name, worst_share: worst ? worst.worstShare : 0,
      traceable: rows.every((r) => r.worstShare <= MAX_STEP_FRAC + 1e-6),
    };
  }

  return {
    fps: FPS, frame: FRAME, bandHz: BAND_HZ, bandRad: TAU * BAND_HZ,
    minFrames: MIN_FRAMES, minRamp: MIN_FRAMES * FRAME, maxStepFrac: MAX_STEP_FRAC,
    channel, safe, osc, shake, hit, warp, gate, report, ease, clamp01,
  };
})();
