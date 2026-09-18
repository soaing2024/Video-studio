/* Minimal animation runtime.
 *
 * The difference between this and a CSS entrance: an Actor owns a track of keyframe segments that
 * span the whole shot. It is always travelling between states, so a frame at t=1s and a frame at
 * t=4s differ because the subject is mid-action - not because a fade finished. Timing controls the
 * eye actually reads: anticipation, arcs, spring settle, overlap.
 *
 * Everything is a pure function of t, so the renderer stays frame-exact.
 */
(function (global) {
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

  const EASE = {
    linear: (x) => x,
    in: (x) => x * x * x,
    out: (x) => 1 - Math.pow(1 - x, 3),
    inout: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    expo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
    back: (x) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
    bounce: (x) => {
      const n1 = 7.5625, d1 = 2.75;
      if (x < 1 / d1) return n1 * x * x;
      if (x < 2 / d1) return n1 * (x -= 1.5 / d1) * x + 0.75;
      if (x < 2.5 / d1) return n1 * (x -= 2.25 / d1) * x + 0.9375;
      return n1 * (x -= 2.625 / d1) * x + 0.984375;
    }
  };

  // damped spring: overshoots then settles, which is what makes an arrival feel like weight
  function spring(p, stiffness, damping) {
    if (p >= 1) return 1;
    const w = Math.sqrt(Math.max(0.001, stiffness)) * 6.283;
    const z = Math.min(0.99, Math.max(0.05, damping));
    const wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-z * w * p) * Math.cos(wd * p);
  }

  // anticipation: dip the opposite way before the move, then go
  function withAnticipation(p, amount) {
    if (!amount) return p;
    const a = Math.min(0.35, amount);
    if (p < a) return -amount * Math.sin((p / a) * Math.PI) * 0.9;
    return (p - a) / (1 - a);
  }

  const isColor = (v) => typeof v === "string" && v.trim().startsWith("#");
  const lerp = (a, b, p) => a + (b - a) * p;
  const hex2 = (h) => {
    h = h.replace("#", "");
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  function mixColor(a, b, p) {
    const A = hex2(a), B = hex2(b);
    return `rgb(${Math.round(lerp(A[0], B[0], p))},${Math.round(lerp(A[1], B[1], p))},${Math.round(lerp(A[2], B[2], p))})`;
  }
  function blend(a, b, p) {
    if (isColor(a) && isColor(b)) return mixColor(a, b, p);
    if (typeof a === "number" && typeof b === "number") return lerp(a, b, p);
    return p < 1 ? a : b;
  }

  class Actor {
    /* props: x, y, scale, rot, opacity, blur, width, height, clip, color, radius, skew */
    constructor(node, initial, opts) {
      this.node = node;
      this.base = Object.assign({ x: 0, y: 0, scale: 1, rot: 0, opacity: 1, blur: 0,
                                  width: null, height: null, clip: 0, color: null, radius: null,
                                  skew: 0 }, initial || {});
      this.opts = Object.assign({ origin: "50% 50%", units: {} }, opts || {});
      this.segs = [];
      this.static = Object.assign({}, this.base);
    }

    /* Schedule a move. `at` is absolute shot time, `dur` seconds of travel. */
    to(target, o) {
      o = o || {};
      const at = o.at || 0;
      const dur = o.dur === undefined ? 0.6 : o.dur;
      const from = Object.assign({}, this.lastState(at));
      const seg = {
        t0: at,
        t1: at + Math.max(0.001, dur),
        from,
        to: Object.assign({}, from, target),
        ease: o.ease || "out",
        spring: o.spring || 0,
        damping: o.damping === undefined ? 0.55 : o.damping,
        anticipation: o.anticipation || 0,
        arc: o.arc || 0,
        arcAngle: o.arcAngle === undefined ? 90 : o.arcAngle,
        stagger: o.stagger || 0
      };
      this.segs.push(seg);
      this.segs.sort((a, b) => a.t0 - b.t0);
      return this;
    }

    /* Where this actor is at time t, ignoring anything scheduled after t. */
    lastState(t) {
      let state = Object.assign({}, this.base);
      for (const s of this.segs) {
        if (s.t0 > t) break;
        state = Object.assign(state, s.to);
      }
      return state;
    }

    /* Hold a value from `at` onwards without travel. */
    snap(target, at) {
      this.segs.push({ t0: at, t1: at, from: target, to: target, ease: "linear", spring: 0,
                       anticipation: 0, arc: 0, arcAngle: 90 });
      this.segs.sort((a, b) => a.t0 - b.t0);
      return this;
    }

    sample(t) {
      let state = Object.assign({}, this.base);
      let active = null;
      for (const s of this.segs) {
        if (s.t0 > t) break;
        if (t >= s.t1) { state = Object.assign(state, s.to); continue; }
        active = s;
        break;
      }
      if (!active) return state;

      const { from, to, t0, t1 } = active;
      let p = clamp01((t - t0) / (t1 - t0));
      const e = active.spring
        ? spring(p, active.spring, active.damping)
        : EASE[active.ease](withAnticipation(p, active.anticipation));
      const out = {};
      const keys = new Set([...Object.keys(from), ...Object.keys(to)]);
      for (const k of keys) {
        const a = from[k], b = to[k];
        if (a === undefined || b === undefined) { out[k] = b === undefined ? a : b; continue; }
        out[k] = blend(a, b, e);
      }
      if (active.arc) {
        const dx = (to.x || 0) - (from.x || 0);
        const dy = (to.y || 0) - (from.y || 0);
        const len = Math.hypot(dx, dy) || 1;
        const off = Math.sin(Math.PI * clamp01(p)) * active.arc;
        const rad = (active.arcAngle * Math.PI) / 180;
        out.x = (out.x || 0) + (-dy / len) * off * Math.cos(rad);
        out.y = (out.y || 0) + (dx / len) * off * Math.sin(rad);
      }
      return out;
    }

    /* Write the sampled state to the DOM in one pass. */
    render(t) {
      const s = this.sample(t);
      const parts = [];
      if (s.x || s.y) parts.push(`translate3d(${(s.x || 0).toFixed(2)}px, ${(s.y || 0).toFixed(2)}px, 0)`);
      if (s.rot) parts.push(`rotate(${s.rot.toFixed(3)}deg)`);
      if (s.skew) parts.push(`skewX(${s.skew.toFixed(3)}deg)`);
      if (s.scale !== 1) parts.push(`scale(${s.scale.toFixed(5)})`);
      const st = this.node.style;
      st.transformOrigin = this.opts.origin;
      st.transform = parts.length ? parts.join(" ") : "none";
      st.opacity = String(s.opacity);
      st.filter = s.blur ? `blur(${s.blur.toFixed(2)}px)` : "";
      if (s.width !== null && s.width !== undefined) st.width = `${s.width}px`;
      if (s.height !== null && s.height !== undefined) st.height = `${s.height}px`;
      if (s.clip) st.clipPath = `inset(0 ${((1 - s.clip) * 100).toFixed(2)}% 0 0)`;
      else st.clipPath = "";
      if (s.color) st.color = s.color;
      if (s.radius !== null && s.radius !== undefined) st.borderRadius = `${s.radius}px`;
      return s;
    }
  }

  class Scene {
    constructor() {
      this.actors = [];
      this.cam = null;
      this.layers = [];
    }
    actor(node, initial, opts) {
      const a = new Actor(node, initial, opts);
      this.actors.push(a);
      return a;
    }
    /* One camera for the whole shot: travel plus impact response. */
    camera(node, plan, layers, shake, hits) {
      this.cam = { node, plan, layers, shake, hits: hits || [] };
      return this.cam;
    }
    bump(t, decay) {
      let b = 0;
      for (const h of (this.cam ? this.cam.hits : [])) {
        if (t <= h) continue;
        const k = (t - h) / decay;
        if (k < 1) b += Math.exp(-3.2 * k);
      }
      return Math.min(2.4, b);
    }
    seek(t, hooks) {
      for (const a of this.actors) a.render(t);
      if (this.cam) {
        const { plan, layers, shake } = this.cam;
        const ramp = EASE[plan.ease] || EASE.inout;
        const p = ramp(clamp01(t / Math.max(0.3, plan.duration || 1)));
        const b = this.bump(t, shake.decay);
        const x = (plan.x_from || 0) + ((plan.x_to || 0) - (plan.x_from || 0)) * p;
        const y = (plan.y_from || 0) + ((plan.y_to || 0) - (plan.y_from || 0)) * p;
        const sc = ((plan.scale_from || 1) + ((plan.scale_to || 1) - (plan.scale_from || 1)) * p) * (1 + 0.022 * b);
        const rot = (plan.rot_from || 0) + ((plan.rot_to || 0) - (plan.rot_from || 0)) * p;
        const sx = (Math.sin(t * shake.freq) + 0.5 * Math.sin(t * shake.freq * 2.3 + 1.1)) * shake.amp * b;
        const sy = (Math.cos(t * shake.freq * 1.3) + 0.5 * Math.sin(t * shake.freq * 3.1)) * shake.amp * 0.7 * b;
        for (const layer of layers) {
          const depth = layer.depth;
          layer.node.style.transform =
            `translate3d(${(x * depth + sx).toFixed(2)}px, ${(y * depth + sy).toFixed(2)}px, 0) ` +
            `scale(${(1 + (sc - 1) * depth).toFixed(5)}) rotate(${(rot * depth).toFixed(3)}deg)`;
        }
      }
      if (hooks) hooks(t, this.bump(t, this.cam ? this.cam.shake.decay : 0.3));
    }
  }

  global.Anim = { Actor, Scene, EASE, spring, clamp01, mixColor };
})(window);
