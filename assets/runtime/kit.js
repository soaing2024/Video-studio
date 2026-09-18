/* Scene kit: the parts every choreographed template needs.
 *
 * Stage layers, camera track, parallax, particles, light sweep, impact flash and the text splitter
 * live here so a template only has to describe what its own content does on each beat.
 */
(function (global) {
  const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

  function rgba(hex, a) {
    const h = String(hex || "#000").replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  function el(parent, tag, css, text) {
    const n = document.createElement(tag);
    Object.assign(n.style, css);
    if (text !== undefined) n.textContent = text;
    parent.appendChild(n);
    return n;
  }

  function splitWords(text) {
    const parts = String(text || "").split(/(\s+)/).filter(Boolean);
    if (parts.length >= 2 && String(text).indexOf(" ") !== -1) return parts;
    const chars = Array.from(String(text || ""));
    const out = [];
    for (let i = 0; i < chars.length; i += 2) out.push(chars.slice(i, i + 2).join(""));
    return out;
  }

  /* Deterministic scatter, seeded from the segment id so every render matches. */
  function rng(seedText) {
    let h = String(seedText || "seed").split("").reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 100000, 7);
    return () => { h = (h * 1103515245 + 12345) % 2147483648; return h / 2147483648; };
  }

  function textureCss(kind, color, amount) {
    const line = rgba(color, 0.45);
    if (kind === "dots") return { backgroundImage: `radial-gradient(${line} 1px, transparent 1px)`, backgroundSize: "40px 40px" };
    if (kind === "grid") return {
      backgroundImage: `linear-gradient(${line} 1px, transparent 1px), linear-gradient(90deg, ${line} 1px, transparent 1px)`,
      backgroundSize: "64px 64px"
    };
    if (kind === "scanlines") return { backgroundImage: "repeating-linear-gradient(0deg, rgba(0,0,0,0.42) 0 1px, transparent 1px 4px)" };
    if (kind === "grain") return {
      backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'>" +
        "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2'/></filter>" +
        "<rect width='140' height='140' filter='url(%23n)' opacity='0.6'/></svg>\")",
      backgroundRepeat: "repeat"
    };
    return {};
  }

  /* Layers + particles canvas + flash, in the stacking order templates expect. */
  const FONT = "'Microsoft YaHei UI','Microsoft YaHei','Noto Sans SC','Source Han Sans SC'," +
               "'PingFang SC','Segoe UI',system-ui,-apple-system,sans-serif";

  function buildStage(stage, o) {
    // never inherit the page default: it is a serif face, which breaks mixed CJK + Latin type
    stage.style.fontFamily = FONT;
    // CJK fonts have very tall default line boxes (an 88px glyph can take a 150px line), so pin a
    // predictable ratio; otherwise fixed pixel offsets overlap the moment text is laid out.
    stage.style.lineHeight = "1.25";
    document.body.style.fontFamily = FONT;
    const mk = (id) => {
      const n = document.createElement("div");
      n.className = "layer";
      n.id = id;
      stage.appendChild(n);
      return n;
    };
    const particles = document.createElement("canvas");
    particles.id = "particles";
    stage.insertBefore(particles, stage.firstChild);
    const layerBg = mk("layerBg");
    const layerGhost = mk("layerGhost");
    layerGhost.dataset.decor = "1";   // decorative: bleeds across the frame on purpose
    const layerMid = mk("layerMid");
    const layerFg = mk("layerFg");
    const flash = mk("flash");
    // The wipe a reframe travels on: one high-contrast bar crossing the frame in a third of a
    // second. Without it, a jump cut between two states of the same artwork reads as a glitch;
    // with it, it reads as a new page.
    const wipe = mk("wipe");
    Object.assign(wipe.style, { position: "absolute", top: "-20%", height: "140%", width: "34%",
      left: "-40%", opacity: "0", pointerEvents: "none", mixBlendMode: "screen",
      background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,0.55), rgba(255,255,255,0))", 
      filter: "blur(14px)" });
    const cv = particles;
    cv.width = window.innerWidth;
    cv.height = window.innerHeight;
    return { layerBg, layerGhost, layerMid, layerFg, flash, wipe, canvas: cv, ctx: cv.getContext("2d") };
  }

  function seedParticles(cfg, seedText, w, h) {
    const s = h / 720;
    const rnd = rng(seedText);
    return Array.from({ length: cfg.count || 20 }, () => ({
      x: rnd() * w, y: rnd() * h, r: (0.5 + rnd()) * (cfg.size || 2) * s,
      dx: (0.5 + rnd()) * (cfg.speed || 20) * s * (cfg.mode === "streak" ? 3.2 : 1),
      dy: (rnd() - 0.5) * (cfg.vertical || 8) * s,
      a: (0.4 + rnd() * 0.8) * (cfg.opacity === undefined ? 0.25 : cfg.opacity),
      ph: rnd() * 6.28
    }));
  }

  function drawParticles(ctx, list, t, color, w, h) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (const q of list) {
      const x = (q.x + q.dx * t) % (w + 40) - 20;
      const y = (q.y + q.dy * t + 8 * Math.sin(t * 0.65 + q.ph)) % (h + 40) - 20;
      ctx.fillStyle = rgba(color, q.a * (0.6 + 0.4 * Math.sin(t * 1.6 + q.ph)));
      ctx.beginPath();
      ctx.arc(x, y, q.r, 0, 6.283);
      ctx.fill();
    }
  }

  /* Camera: one waypoint per beat, plus impact punch and shake. Parallax per layer. */
  function makeCamera(motion, layers, opts) {
    const o = opts || {};
    const quant = o.quantize || 1;          // 1 for normal, >1 for pixel-art (whole pixels)
    // Every template lays out in 1280x720 units scaled by the viewport, so the camera has to be
    // scaled the same way. Applying raw pixels made the same shot move twice as far when it was
    // rendered at half size, which is how a layout that fits at 720p clipped at 360p.
    const view = (window.innerHeight || 720) / 720;
    const actor = new global.Anim.Actor(document.createElement("div"),
                                        { x: 0, y: 0, scale: 1, rot: 0, opacity: 1 });
    const track = (motion.camera_track && motion.camera_track.length) ? motion.camera_track : null;
    const boost = o.boost || 1;
    if (track) {
      for (const wp of track) {
        actor.to({ x: (wp.x || 0) * boost, y: (wp.y || 0) * boost,
                   scale: 1 + ((wp.scale || 1) - 1) * Math.min(2.2, boost), rot: (wp.rot || 0) * boost },
                 { at: wp.t, dur: wp.dur, ease: wp.ease, arc: wp.arc, spring: 0.3, damping: 0.8 });
      }
    } else {
      const cam = motion.camera || {};
      actor.to({ scale: cam.scale_to || 1.04, x: cam.x_to || 0, y: cam.y_to || 0 },
               { at: 0, dur: o.duration || 6, ease: "inout" });
    }
    // camera_keys is a spline through the poses the old waypoint list described, so the camera no
    // longer restarts from a standstill at every beat - and a `cut: true` key reframes hard.
    const keys = (motion.camera_keys && motion.camera_keys.length) ? motion.camera_keys : null;
    const path = keys ? new global.Anim.Path(keys) : null;
    const q = (v) => (quant > 1 ? Math.round(v / quant) * quant : v);
    return {
      actor, layers,
      bump(t, shake) {
        let b = 0;
        for (const h of (o.hits || [])) {
          if (t <= h) continue;
          const k = (t - h) / shake.decay;
          if (k < 1) b += Math.exp(-3.2 * k);
        }
        return Math.min(2.4, b);
      },
      apply(t) {
        const shake = o.shake || { amp: 1.5, decay: 0.3, freq: 13 };
        const cam = path ? path.sample(t) : actor.sample(t);
        const b = this.bump(t, shake);
        const sx = shake.amp * b * Math.sin(t * shake.freq);
        const sy = shake.amp * 0.65 * b * Math.cos(t * shake.freq * 1.3);
        const sc = (cam.scale || 1) * (1 + 0.02 * b);
        for (const lay of layers) {
          const d = lay.depth;
          lay.node.style.transform =
            `translate3d(${q((cam.x * d) * view + sx).toFixed(2)}px, ${q((cam.y * d) * view + sy).toFixed(2)}px, 0) ` +
            `scale(${(1 + (sc - 1) * d).toFixed(5)}) rotate(${(cam.rot * d).toFixed(3)}deg)`;
        }
        return b;
      }
    };
  }

  /* Sweep + halo + vignette + texture opacity, the ambient layer every shot shares. */
  function ambient(L, t, o) {
    const fade = o.fade === undefined ? 1 : o.fade;
    if (L.tex) L.tex.style.opacity = (Math.min(0.85, (o.textureAmount || 0.1) * 3.2) *
                                     global.Anim.EASE.out(clamp01(t / 0.9))).toFixed(4);
    if (L.vign) L.vign.style.opacity = (global.Anim.EASE.out(clamp01(t / 1.2)) * fade).toFixed(4);
    if (L.halo) L.halo.style.opacity = (0.5 * (1 + (o.pulseAmount || 0.012) * Math.sin(t * (o.pulseFreq || 1))) *
                                        global.Anim.EASE.out(clamp01(t / 1.2)) * fade).toFixed(4);
    if (L.sweep) {
      const sw = ((t * (o.sweepSpeed || 360)) % (window.innerWidth * 2.2)) - window.innerWidth * 1.1;
      L.sweep.style.left = `${sw.toFixed(1)}px`;
      L.sweep.style.opacity = ((o.sweepOpacity || 0.1) * 4 * fade).toFixed(4);
    }
    // Reframes get a wipe. The cut list comes from the shot's beat sheet, so every template that
    // calls ambient() renders the same gesture - which is what makes a new page legible as one.
    const wipe = L.wipe || (L.kit && L.kit.wipe);
    if (wipe && o.cuts && o.cuts.length) {
      let op = 0, at = -1;
      for (const c of o.cuts) {
        const k = (t - c) / 0.34;
        if (k >= 0 && k < 1) { op = Math.max(op, Math.sin(Math.PI * k)); at = k; }
      }
      wipe.style.opacity = (op * 0.55 * fade).toFixed(4);
      if (at >= 0) wipe.style.left = `${(-40 + 180 * at).toFixed(1)}%`;
    }
    if (L.ghost && o.ghost) {
      const span = window.innerWidth * 2.4;
      const dir = o.ghost.dir > 0 ? 1 : -1;
      const travelled = (t * o.ghost.speed) % span;
      L.ghost.style.left = `${(dir > 0 ? travelled - span * 0.7 : span * 0.7 - travelled).toFixed(1)}px`;
    }
  }

  /* The narration band / lower third: swap text instead of holding one line. */
  function bandSwapper(node, texts) {
    let idx = 0;
    return {
      node,
      next(at, animActor) {
        if (!texts || texts.length < 2) return;
        idx = Math.min(texts.length - 1, idx + 1);
        if (animActor) {
          animActor.to({ opacity: 0, y: -16, blur: 6 }, { at, dur: 0.24, ease: "in" });
          animActor.to({ opacity: 1, y: 0, blur: 0 }, { at: at + 0.26, dur: 0.42, ease: "out" });
        }
        setTimeout(() => { node.textContent = texts[idx]; }, 0);
        return texts[idx];
      }
    };
  }

  /* Large soft shapes that traverse the frame for the whole shot.
   *
   * A flat gradient moved by the camera changes no pixels, so a text-only shot reads as a still
   * image however much its camera or numbers move. These shapes give the frame structure to
   * travel through - which is what the eye, and the motion check, actually register.
   */
  function backdrop(layer, o) {
    o = o || {};
    const s = o.scale || 1;
    const rnd = rng(o.seed || "backdrop");
    const VW = o.width || 1280, VH = o.height || 720;
    const out = [];
    const count = o.count === undefined ? 3 : o.count;
    for (let i = 0; i < count; i++) {
      const w = (0.42 + rnd() * 0.34) * VW * s;
      const h = w * (0.62 + rnd() * 0.5);
      const alpha = o.alpha === undefined ? 0.22 : o.alpha;
      const col = o.color || "#ffffff";
      const node = el(layer, "div", {
        position: "absolute", left: "0px", top: "0px", width: w + "px", height: h + "px",
        borderRadius: "50%", opacity: "0", pointerEvents: "none",
        background: "radial-gradient(closest-side, " + rgba(col, alpha) + ", " + rgba(col, 0) + " 72%)",
        filter: "blur(" + Math.round((o.blur === undefined ? 12 : o.blur) * s) + "px)"
      });
      const fromX = -w * (0.4 + rnd() * 0.5);
      const toX = VW * s * (0.75 + rnd() * 0.5);
      const fromY = VH * s * (0.05 + rnd() * 0.45);
      const toY = VH * s * (0.15 + rnd() * 0.55);
      const actor = new global.Anim.Actor(node, { x: fromX, y: fromY, scale: 0.85 + rnd() * 0.4,
                                                   rot: rnd() * 40 - 20, opacity: 0 });
      actor.to({ opacity: 1, x: toX, y: toY, scale: 0.9 + rnd() * 0.45, rot: rnd() * 70 - 35 },
               { at: 0, dur: o.duration || 10, ease: "linear", arc: 16 });
      out.push(actor);
    }
    return out;
  }

  global.Kit = { FONT, clamp01, rgba, el, splitWords, rng, textureCss, buildStage, seedParticles,
                 drawParticles, makeCamera, ambient, bandSwapper, backdrop };
})(window);
