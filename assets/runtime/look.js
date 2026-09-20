/* The difference between "programmer particles" and motion design.
 *
 * A flat filled circle has no material: it reads as a dot, not as light. The four things that
 * actually make a particle field look expensive are all cheap, and all live here:
 *
 *   1. a SPRITE, not a shape - a small core with a halo, drawn with drawImage, so the edge is
 *      soft and the brightness falls off. One 64px sprite, scaled per particle, costs nothing.
 *   2. DEPTH - far particles are smaller, dimmer, less saturated and less sharp. Without this
 *      every field looks like wallpaper no matter how good the motion is.
 *   3. VELOCITY - a fast particle is a streak aligned with its own motion, not a round dot.
 *      Fast/slow is then readable in a single still frame.
 *   4. HIERARCHY - a few particles carry the light (the accent budget), the rest are quiet.
 *      Drawn the other way round - everything bright - the eye has nowhere to land.
 *
 * Deterministic like everything else: sprites are cached by key, `field()` is seeded, and no
 * clock is read. Injected alongside Scene / Anim / Phys / Kit as `Look`.
 */
(function (global) {
  const cache = new Map();

  function rgb(hex) {
    const h = String(hex).replace("#", "");
    const s = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const n = parseInt(s || "ffffff", 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  /* One soft sprite: bright core, quadratic halo. Cached by (color, size, halo). */
  function sprite(color, size, halo) {
    const s = Math.max(2, Math.round(size));
    const h = halo === undefined ? 0.55 : halo;
    const key = color + "|" + s + "|" + h.toFixed(2);
    if (cache.has(key)) return cache.get(key);
    const c = document.createElement("canvas");
    c.width = c.height = s * 4;
    const x = c.getContext("2d");
    const mid = s * 2;
    const [r, g, b] = rgb(color);
    const core = x.createRadialGradient(mid, mid, 0, mid, mid, s);
    core.addColorStop(0, `rgba(255,255,255,1)`);
    core.addColorStop(0.28, `rgba(${r},${g},${b},1)`);
    core.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.fillStyle = core;
    x.beginPath(); x.arc(mid, mid, s, 0, 6.283); x.fill();
    const haloR = s * (1.6 + h * 1.6);
    const g2 = x.createRadialGradient(mid, mid, s * 0.5, mid, mid, haloR);
    g2.addColorStop(0, `rgba(${r},${g},${b},${(0.42 * h).toFixed(3)})`);
    g2.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.globalCompositeOperation = "lighter";
    x.fillStyle = g2;
    x.beginPath(); x.arc(mid, mid, haloR, 0, 6.283); x.fill();
    const out = { canvas: c, mid, base: s };
    cache.set(key, out);
    return out;
  }

  /* Depth: one function that decides how a z in [-1,1] changes size, light and sharpness.
     Near (z>0) = bigger, brighter, sharper. Far = small, dim, washed toward the background. */
  function depth(z, opts) {
    const o = opts || {};
    const t = Math.max(-1, Math.min(1, z));
    const near = (t + 1) / 2;                       // 0 far .. 1 near
    const sizeK = (o.sizeRange === undefined ? 0.45 : o.sizeRange);
    return {
      size: 1 - sizeK + sizeK * 2 * near,
      alpha: (o.minAlpha === undefined ? 0.18 : o.minAlpha) +
             (1 - (o.minAlpha === undefined ? 0.18 : o.minAlpha)) * Math.pow(near, 1.35),
      // how much the particle is washed toward the background colour (atmospheric perspective)
      wash: (o.maxWash === undefined ? 0.55 : o.maxWash) * (1 - near),
      sharp: 0.35 + 0.65 * near,
      near: near
    };
  }

  /* A seeded field. Every particle gets its own depth, phase, size and hierarchy rank. */
  function field(o) {
    const cfg = o || {};
    const rnd = global.Phys ? global.Phys.rng(cfg.seed === undefined ? 1 : cfg.seed)
                            : (() => { let a = 1; return () => (a = (a * 16807) % 2147483647) / 2147483647; })();
    const n = Math.max(1, cfg.count || 800);
    const out = [];
    for (let i = 0; i < n; i++) {
      out.push({
        u: rnd(), v: rnd(),          // where in its own domain (0..1)
        z0: rnd() * 2 - 1,           // base depth
        size: (cfg.size || 2.2) * (0.6 + rnd() * 0.9),
        phase: rnd() * 6.283,
        rank: rnd(),                 // hierarchy: only the low ranks carry the accent
        seedv: rnd()
      });
    }
    if (cfg.accentShare) {           // explicitly promote the brightest few
      const k = Math.max(1, Math.round(n * cfg.accentShare));
      out.slice().sort((a, b) => a.rank - b.rank).slice(0, k).forEach((q) => { q.rank = q.rank * 0.1; });
    }
    return out;
  }

  /* Draw one particle. `x`,`y` in px; `vx`,`vy` in px per second; returns the size drawn. */
  function draw(ctx, color, x, y, size, alpha, opts) {
    const o = opts || {};
    const sp = sprite(color, o.spriteSize === undefined ? 2.4 : o.spriteSize, o.halo);
    const z = o.z === undefined ? 0 : o.z;
    const d = depth(z, o.depth);
    // `spriteScale` used to hold the same value in both branches, so the option did nothing.
    const s = size * d.size * (o.spriteScale === undefined ? 2.0 : Number(o.spriteScale));
    const a = alpha * d.alpha;
    if (s < 0.35 || a < 0.006) return 0;
    const vx = o.vx || 0, vy = o.vy || 0;
    const speed = Math.hypot(vx, vy);
    ctx.globalAlpha = Math.min(0.98, a);
    const streakFrom = o.streakFrom === undefined ? 220 : o.streakFrom;
    if (speed > streakFrom) {
      // velocity-aligned streak: the still frame itself shows how fast it is going
      const len = Math.min(o.maxStreak === undefined ? 46 : o.maxStreak, speed * 0.035);
      const ang = Math.atan2(vy, vx);
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(ang);
      ctx.drawImage(sp.canvas, -s * 0.5 - len, -s * 0.5, s + len, s);
      ctx.restore();
    } else {
      ctx.drawImage(sp.canvas, x - s * 0.5, y - s * 0.5, s, s);
    }
    ctx.globalAlpha = 1;
    return s;
  }

  /* Film weave for the camera: sub-pixel translate + a breath of roll. Seeded, no clock. */
  function weave(t, seed, amount) {
    const a = amount === undefined ? 1 : amount;
    const n = global.Phys ? global.Phys.noise({ seed: seed === undefined ? 9 : seed, freq: 0.37,
                                                amp: 1, octaves: 3 }) : { at: () => 0 };
    const n2 = global.Phys ? global.Phys.noise({ seed: (seed === undefined ? 9 : seed) + 51,
                                                 freq: 0.29, amp: 1, octaves: 2 }) : { at: () => 0 };
    return { x: n.at(t) * 1.7 * a, y: n2.at(t) * 1.2 * a, rot: n.at(t * 0.7 + 3) * 0.22 * a };
  }

  /* Value hierarchy: give the caller a 0..1 "how loud is this particle" from rank + depth. */
  function hierarchy(rank, near, opts) {
    const o = opts || {};
    const lift = o.floor === undefined ? 0.12 : o.floor;
    const hot = rank < (o.accent === undefined ? 0.08 : o.accent);
    return Math.min(1, lift + (hot ? 0.6 : 0.1) * Math.pow(near, 1.2));
  }

  global.Look = { sprite, depth, field, draw, weave, hierarchy, rgb };
})(typeof window !== "undefined" ? window : globalThis);
