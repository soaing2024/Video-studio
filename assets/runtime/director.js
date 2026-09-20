/* director.js - the language layer: a scene in tens of lines instead of a thousand.
 *
 * Why this exists: the machinery a shot needs is always the same - a camera that never
 * stops, objects projected through depth, keyframed geometry, impact response, a canvas
 * FX layer - and hand-writing it costs an agent ~1000 lines per film. This module is that
 * machinery as a *vocabulary*, not as a template: you still author every element, every
 * beat and every handoff, you just spend characters on the ideas instead of the plumbing.
 *
 *   const S = D.scene({duration: 30, bg:'#f7f8fa', grid:96});
 *   S.cam([[0,960,540,80,.92], [2.7,900,500,-120,.8,'s6'], [6.6,960,540,1520,.95,'s2']]);
 *   const caret = S.el('caret', {box:[3,38], pos:[860,540], z:1600});
 *   S.typing(caret, 'video-studio', {t0:.62, dt:.095, size:46});
 *   const w = S.panel('modal', {box:[620,392], at:'3.0:0 3.3:1 s6 5.34:1 5.56:0 in',
 *                               pos:[960,540], z:2250, from:caret});
 *   S.rows(w, 3); S.chart(w, {x:300,y:214,w:292,h:86, bars:14});
 *   S.button(w, {label:'Run', box:[132,44], pos:[526,352], morph:'portal'});
 *   S.fx.wave(2.70, [960,540,1600], {r:1700}); S.fx.flash(6.02, [1220,700,2200]);
 *
 * Everything stays a pure function of t: S.seek(t) writes the frame, nothing owns a clock.
 *
 * Time values, in order of brevity:
 *   number            constant
 *   [t,v,ease]        one segment (ease optional, default 's2')
 *   [[t,v],...]       several segments
 *   "t:v ease t:v"    the same, as a string - about 40% fewer characters
 */
(function (global) {
  "use strict";

  const VW = () => global.innerWidth, VH = () => global.innerHeight;
  const DESIGN = 1920;                       // authoring units; 4K render = 2x
  const cl = (v, a, b) => (v < a ? a : v > b ? b : v);
  const c01 = (v) => cl(v, 0, 1);

  /* springs tuned so a segment actually travels and rebounds: stiffness is in units of
   * "cycles across the segment", not "per second" - see AUDIT.md on the old bug. */
  function spr(p, k, d) {
    if (p >= 1) return 1;
    const w = Math.sqrt(Math.max(0.001, k)) * 6.2831853, z = cl(d, 0.05, 0.985);
    return 1 - Math.exp(-z * w * p) * Math.cos(w * Math.sqrt(1 - z * z) * p);
  }
  const E = {
    lin: (p) => p,
    s1: (p) => spr(p, 1.45, 0.62), s2: (p) => spr(p, 2.30, 0.55), s3: (p) => spr(p, 4.20, 0.42),
    s4: (p) => spr(p, 0.72, 0.80), s5: (p) => spr(p, 3.30, 0.62), s6: (p) => spr(p, 1.70, 0.38),
    out: (p) => 1 - Math.pow(1 - p, 3), in: (p) => p * p * p,
    expo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
    io: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  };

  /* "0:960 s6 2.7:900 6.6:960" -> [[0,960],[2.7,900,'s6'],[6.6,960]] */
  function parse(spec) {
    if (typeof spec === "string") {
      const out = [];
      const toks = spec.trim().split(/\s+/);
      for (let i = 0; i < toks.length; i++) {
        const m = /^(-?[\d.]+):(-?[\d.]+)$/.exec(toks[i]);
        if (!m) continue;
        const ease = toks[i + 1] && !toks[i + 1].includes(":") ? toks[++i] : "s2";
        out.push([parseFloat(m[1]), parseFloat(m[2]), ease]);
      }
      return out;
    }
    if (Array.isArray(spec) && spec.length && Array.isArray(spec[0])) {
      return spec.map((k) => [k[0], k[1], k[2] || "s2"]);
    }
    return spec;
  }

  function track(t, keys) {
    keys = parse(keys);
    if (typeof keys === "number") return keys;
    if (!keys || !keys.length) return 0;
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const k1 = keys[i], k0 = keys[i - 1];
      if (t <= k1[0]) {
        const p = c01((t - k0[0]) / Math.max(1e-6, k1[0] - k0[0]));
        const f = E[k1[2]] || E.s2;
        return k0[1] + (k1[1] - k0[1]) * f(p);
      }
    }
    return keys[keys.length - 1][1];
  }

  /* ---------------------------------------------------------------- scene */

  function scene(opts) {
    const o = opts || {};
    const stage = document.getElementById(o.stage || "stage") || document.body;
    Object.assign(stage.style, { position: "absolute", inset: "0", overflow: "hidden",
      background: o.bg || "#f7f8fa",
      fontFamily: o.font || '"Microsoft YaHei","Noto Sans SC","Segoe UI",system-ui,sans-serif',
      color: o.ink || "#0b0f14" });
    const S = global.DESIGN || DESIGN;
    const world = document.createElement("div");
    Object.assign(world.style, { position: "absolute", left: "0", top: "0",
      width: DESIGN + "px", height: (DESIGN * 9 / 16) + "px", transformOrigin: "0 0",
      transform: "scale(" + (VW() / DESIGN) + ")" });
    stage.appendChild(world);
    global.SCENE = global.SCENE || {};

    const fx = document.createElement("canvas");
    Object.assign(fx.style, { position: "absolute", inset: "0", pointerEvents: "none", zIndex: "9" });
    fx.width = VW(); fx.height = VH();
    stage.appendChild(fx);
    const ctx = fx.getContext("2d");

    const OBJ = [], UPD = [], WAVES = [];
    let camPath = [], camHits = o.hits || [], shakeAmp = o.shake === undefined ? 1 : o.shake;

    const el = (name, cfg) => {
      const c = cfg || {}, d = document.createElement(c.tag || "div");
      if (c.cls) d.className = c.cls;
      if (c.html) d.innerHTML = c.html;
      if (c.text) d.textContent = c.text;
      const box = c.box || [10, 10];
      // Origin 0 0, not the CSS default: frame() places every object with a trailing
      // translate(-50%,-50%), and with the origin at the centre that offset is applied inside
      // the scale, displacing anything at depth by (S-1)*size/2 - 1057 px for a 520 px box at
      // 5x. Probe-measured against a three.js camera at the same world point: 1.4 px error
      // with origin 0 0, versus the object's own half-width with the default.
      Object.assign(d.style, { position: "absolute", left: "0", top: "0",
        width: box[0] + "px", height: box[1] + "px", transformOrigin: "0 0" }, c.style || {});
      (c.parent || world).appendChild(d);
      // x / y / rot / sx / sy are honoured here, not only through move(): passing them in the
      // config used to be silently ignored, so a track written inline never ran. pos stays as
      // the shorthand for "constant x and y".
      const obj = { el: d, name: name || d.className,
        x: c.x !== undefined ? c.x : (c.pos ? c.pos[0] : 0),
        y: c.y !== undefined ? c.y : (c.pos ? c.pos[1] : 0),
        z: c.z || 0, zc: c.depth,
        sx: c.sx !== undefined ? c.sx : 1, sy: c.sy !== undefined ? c.sy : 1,
        rot: c.rot !== undefined ? c.rot : 0, op: 1,
        blur: 0, keep: c.keep, mst: c.mst, parent: c.parent, off: c.off };
      d.__o = obj;                    // motion verbs take the node and find its track
      OBJ.push(obj);
      if (c.at) {                       // presence window: opacity springs in/out on its own
        const w = parse(c.at);
        const tin = w[0], a = (w[1] && w[1][1]) || 1, tout = w[2], b = (w[3] && w[3][1]) || 0;
        obj.op = [[tin[0], tin[1]], [tin[0] + (c.fadeIn || 0.22), a, c.easeIn || "s6"]];
        if (tout) obj.op.push([tout[0], b === 1 ? 1 : (c.hold === false ? 1 : 1)], [tout[0] + (c.fadeOut || 0.2), 0, "in"]);
      }
      return d;
    };

    /* panels and their dense interior - the look that otherwise costs 40 lines each */
    const panel = (name, cfg) => {
      const c = Object.assign({ cls: "d-p" },
        { box: cfg && cfg.box ? cfg.box : [560, 360] }, cfg || {});
      if (!c.style) c.style = {};
      if (!c.cls.includes("d-flat")) c.style.boxShadow = c.shadow === false ? "none"
        : "0 30px 66px -44px rgba(15,23,42,.42), inset 0 1px 0 rgba(255,255,255,.94)";
      c.style.borderRadius = (c.radius === undefined ? 18 : c.radius) + "px";
      c.style.border = "1px solid rgba(15,23,42,.075)";
      c.style.background = "linear-gradient(178deg,rgba(255,255,255,.97),rgba(248,250,253,.92))";
      const d = el(name || "panel", c);
      if (c.chrome !== false) {                       // title row: rule + glyph + title bar
        bar(d, [16, 13, 10, 10], { r: 3, c: "rgba(15,23,42,.2)" });
        bar(d, [38, 16, 86, 7], {});
        bar(d, [0, 38, c.box[0], 1], { c: "rgba(15,23,42,.07)", r: 0 });
      }
      return d;
    };

    function bar(parent, rect, cfg) {
      const c = cfg || {}, d = document.createElement("div");
      Object.assign(d.style, { position: "absolute", left: rect[0] + "px", top: rect[1] + "px",
        width: rect[2] + "px", height: rect[3] + "px",
        borderRadius: (c.r === undefined ? 2 : c.r) + "px",
        background: c.c || "rgba(15,23,42,.11)" });
      parent.appendChild(d);
      return d;
    }
    const rows = (parent, n, cfg) => {
      const c = cfg || {}, x = c.x || 24, y = c.y || 60, gap = c.gap || 22, out = [];
      for (let i = 0; i < n; i++) {
        const w = (c.w || 300) * (1 - (i % 3) * 0.12);
        out.push(bar(parent, [x, y + i * gap, w, c.h || 6], { c: c.c || "rgba(15,23,42,.075)" }));
        if (c.dot !== false) bar(parent, [x - 12, y + i * gap, 6, 6], { r: 3, c: "rgba(15,23,42,.16)" });
      }
      return out;
    };
    const chart = (parent, cfg) => {
      const c = cfg || {}, n = c.bars || 12;
      for (let i = 0; i < n; i++) {
        const h = (c.min || 12) + ((i * 37) % (c.max || 60));
        bar(parent, [c.x + i * (c.gap || 22), c.y + c.h - h, c.bw || 11, h],
            { c: i === (c.accent === undefined ? n - 2 : c.accent) ? "rgba(31,107,255,.6)" : "rgba(15,23,42,.10)" });
      }
      bar(parent, [c.x, c.y + c.h, c.w || 280, 1], { c: "rgba(15,23,42,.08)", r: 0 });
      return parent;
    };

    /* text: one call, and the type scale is a fraction of the short edge like Scene.type */
    const text = (name, str, cfg) => {
      const c = cfg || {};
      const d = el(name || "text", Object.assign({ tag: "div" }, c, { box: c.box || [10, c.size || 40] }));
      d.textContent = str;
      const base = Math.min(VW() * DESIGN / VW(), (DESIGN * 9 / 16));
      Object.assign(d.style, { fontSize: (c.size || 40) + "px", fontWeight: c.weight || "500",
        letterSpacing: (c.tracking === undefined ? "-0.02em" : c.tracking + "em"),
        color: c.color || "#0b0f14", whiteSpace: "nowrap", lineHeight: "1.05",
        fontFamily: c.mono ? '"Cascadia Mono",Consolas,monospace' : undefined });
      if (c.center) d.style.transform = "translate(-50%,-50%)";
      // size the box to the text so pos means "centre of the words", not "left edge"
      if (!c.box) { d.style.width = d.offsetWidth + "px"; d.style.height = d.offsetHeight + "px"; }
      return d;
    };

    /* per-letter typing with a caret that snaps - 12 lines of intent, not 60 of DOM */
    const typing = (host, str, cfg) => {
      const c = cfg || {}, size = c.size || 46, spans = [], caret = document.createElement("div");
      const row = document.createElement("div");
      Object.assign(row.style, { position: "absolute", left: (c.x || 0) + "px", top: (c.y || 0) + "px",
        whiteSpace: "nowrap", height: (c.h || size * 1.3) + "px" });
      host.appendChild(row);
      for (const ch of str) {
        const s = document.createElement("span");
        s.textContent = ch;
        Object.assign(s.style, { display: "inline-block", fontSize: size + "px",
          lineHeight: (c.h || size * 1.3) + "px", fontWeight: c.weight || "500",
          letterSpacing: "-0.005em", color: c.color || "#0b0f14", opacity: "0",
          fontFamily: '"Cascadia Mono",Consolas,monospace' });
        row.appendChild(s); spans.push(s);
      }
      Object.assign(caret.style, { position: "absolute", left: "0px", top: "4px",
        width: "3px", height: (size * 0.82) + "px", background: c.color || "#0b0f14",
        borderRadius: "1px" });
      row.appendChild(caret);
      UPD.push((t) => {
        const t0 = c.t0 === undefined ? 0 : c.t0, dt = c.dt || 0.095;
        const n = cl(Math.floor((t - t0) / dt) + 1, 0, spans.length);
        for (let i = 0; i < spans.length; i++) {
          const p = c01((t - (t0 + i * dt)) / 0.2);
          if (p <= 0) { spans[i].style.opacity = "0"; continue; }
          const e = E.s6(p);
          spans[i].style.transform = `translateY(${((1 - E.expo(p)) * 9).toFixed(1)}px) scale(${(0.62 + 0.38 * e).toFixed(3)})`;
          spans[i].style.opacity = String(Math.min(1, p * 4));
        }
        const last = Math.max(0, n - 1);
        const x = last < 0 ? 0 : (spans[last].offsetLeft + size * 0.58);
        const hold = (t - (t0 + last * dt)) < 0.17;
        const blink = t > t0 + spans.length * dt + 0.4 ? 0.45 : (hold ? 1 : 0.5 + 0.5 * Math.cos(6.2832 * t * 0.86 + 1.2));
        caret.style.transform = `translateX(${x.toFixed(1)}px) scaleY(${(0.4 + 0.6 * blink).toFixed(3)})`;
        caret.style.opacity = String(c.keepCaret ? 1 : 0.3 + 0.7 * blink);
        row.style.transform = c.center === false ? "" :
          `translateX(${(-(spans[Math.min(spans.length - 1, Math.max(0, n - 1))].offsetLeft + size * 0.6) / 2).toFixed(1)}px)`;
      });
      return { row, caret, spans };
    };

    /* ---------------------------------------------------------------- camera */

    /* stations: [t, x, y, z, zoom, rot, ease] - the camera arrives at each one and never
     * stops; handheld drift and impact shake are added on top. */
    function cam(stations, cfg) {
      // Normalise every station to seven slots. A row that stops at five (the shipped 30 s
      // example does) leaves `rot` undefined, and undefined plus a drift term is NaN - which
      // propagates into every transform in the frame. Silently. Fill the gaps instead.
      camPath = (stations || []).map((s) => [s[0], s[1], s[2], s[3],
        s[4] === undefined ? 1 : s[4], s[5] === undefined ? 0 : s[5], s[6] || "s2"]);
      const c = cfg || {};
      camHits = c.hits || camHits;
      if (c.shake !== undefined) shakeAmp = c.shake;
      return stations;
    }
    function bump(t) {
      let b = 0;
      for (const h of camHits) {
        const time = Array.isArray(h) ? h[0] : h, amp = Array.isArray(h) ? h[1] : 1;
        if (t <= time) continue;
        const k = (t - time) / 0.4;
        if (k < 1) b += amp * Math.exp(-3.6 * k);
      }
      return Math.min(3.2, b);
    }
    function camAt(t) {
      const keys = ["x", "y", "z", "zoom", "rot"], out = {};
      if (!camPath.length) { out.x = DESIGN / 2; out.y = DESIGN * 9 / 32; out.z = 0; out.zoom = 1; out.rot = 0; }
      else if (t <= camPath[0][0]) { keys.forEach((k, i) => (out[k] = camPath[0][i + 1])); }
      else if (t >= camPath[camPath.length - 1][0]) {
        const s = camPath[camPath.length - 1]; keys.forEach((k, i) => (out[k] = s[i + 1]));
      } else {
        for (let j = 1; j < camPath.length; j++) {
          if (t <= camPath[j][0]) {
            const k0 = camPath[j - 1], k1 = camPath[j];
            const p = (E[k1[6]] || E.s2)(c01((t - k0[0]) / Math.max(1e-6, k1[0] - k0[0])));
            keys.forEach((k, i) => (out[k] = k0[i + 1] + (k1[i + 1] - k0[i + 1]) * p));
            break;
          }
        }
      }
      const b = bump(t);
      const hx = Math.sin(t * 1.71 + 0.62) * 4.6 + Math.sin(t * 3.13 + 2.24) * 2.1;
      const hy = Math.cos(t * 1.43 + 0.21) * 3.7 + Math.sin(t * 2.36 + 1.42) * 1.9;
      out.cx = DESIGN / 2 + hx + Math.sin(t * 47.3) * 7.5 * b * shakeAmp;
      out.cy = DESIGN * 9 / 32 + hy + Math.cos(t * 41.1 + 0.7) * 6.2 * b * shakeAmp;
      out.rot += Math.sin(t * 0.83 + 1.13) * 0.22 + Math.sin(t * 37.7 + 1.9) * 0.34 * b * shakeAmp;
      out.zoom *= 1 + 0.028 * b * shakeAmp;
      out.shake = b;
      return out;
    }

    function proj(t, camv, obj) {
      let x = obj.x, y = obj.y, z = obj.z;
      if (obj.parent && obj.parent.__obj) { const p = obj.parent.__obj; x += p.x; y += p.y; z += p.z; }
      x = track(t, x); y = track(t, y);
      z = obj.zc !== undefined ? camv.z + track(t, obj.zc) : track(t, z);
      const dz = z - camv.z, k = 1600 / Math.max(260, dz);
      return { px: camv.cx + (x - camv.x) * k * camv.zoom, py: camv.cy + (y - camv.y) * k * camv.zoom,
        k, sc: k * camv.zoom, dz, opacity: c01((dz - 230) / 340) * c01(1 - (dz - 3300) / 2200) };
    }

    /* ---------------------------------------------------------------- motion verbs */

    const api = {
      world, stage, ctx, canvas: fx, OBJ, el, panel, bar, rows, chart, text, typing, cam,
      track: (t, k) => track(t, k), E,
      hit: (t, amp) => { camHits.push([t, amp === undefined ? 1 : amp]); return api; },
      /* where an object lands at time t: the coordinate space other verbs target */
      at: (obj, t) => { const c = camAt(t), s = proj(t, c, obj.__o || obj); return [s.px, s.py]; },
      move: (obj, cfg) => { Object.assign(obj.__o || obj, cfg); return api; },
      /* fly: presence + a spring arrival from an offset direction */
      fly: (obj, cfg) => {
        const c = cfg || {}, dx = (c.from === "left" ? -1 : c.from === "right" ? 1 : 0);
        Object.assign(obj.__o || obj, {
          x: [[c.t, (c.pos ? c.pos[0] : 0) + dx * (c.dist || 900)], [c.t + (c.dur || 0.55), c.pos[0], c.ease || "s6"]],
          y: c.y ? [[c.t, c.y[0]], [c.t + (c.dur || 0.55), c.y[1], c.ease || "s6"]] : undefined });
        return api;
      },
      /* morph: A becomes B - same element, geometry interpolated. Buttons become windows. */
      morph: (obj, cfg) => {
        const c = cfg || {};
        Object.assign(obj.__o || obj, {
          sx: [[c.t, c.from[0] / c.box[0]], [c.t + (c.dur || 0.6), 1, c.ease || "s3"]],
          sy: [[c.t, c.from[1] / c.box[1]], [c.t + (c.dur || 0.6), 1, c.ease || "s3"]] });
        return api;
      },
      /* collect: gather every non-kept object into a point - how a film closes */
      collect: (cfg) => {
        const c = cfg || {};
        api.__collect = { t: c.t, dur: c.dur || 1.5, to: c.to || [DESIGN / 2, DESIGN * 9 / 32, 5200], keep: c.keep || [] };
        return api;
      },
    };

    /* ---------------------------------------------------------------- fx layer */
    const fxapi = {
      wave: (t, at, cfg) => { WAVES.push(Object.assign({ t, at, r: 1400, a: 1, kind: 0 }, cfg || {})); return fxapi; },
      /* particles: burst(at, {n, t}) - stars and sparks, deterministic */
      parts: [],
      burst: (t, at, cfg) => {
        const c = cfg || {}, n = c.n || 160, arr = [];
        let seed = 987654321;
        const rnd = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
        for (let i = 0; i < n; i++) {
          arr.push({ a: rnd() * 6.2832, sp: 90 + Math.pow(rnd(), 1.7) * (c.spread || 1500),
            s: 1.4 + rnd() * 5.4, life: 0.75 + rnd() * 1.5, kind: i % 4 === 0 ? 0 : 1,
            rot: rnd() * 6.2832, rs: (rnd() * 2 - 1) * 7, t0: t + rnd() * 0.1, at,
            col: c.color || "31,107,255" });
        }
        fxapi.parts = fxapi.parts.concat(arr);
        WAVES.push({ t, at, r: c.r || 1500, a: 1.35, kind: 0 });
        WAVES.push({ t: t + 0.13, at, r: 900, a: 1, kind: 1 });
        return fxapi;
      },
      hud: (box, cfg) => { fxapi.__hud = Object.assign({ box }, cfg || {}); return fxapi; },
    };

    /* the frame: update every object, then draw the canvas layer */
    let last = 0;
    function frame(t) {
      const camv = camAt(t);
      for (const upd of UPD) upd(t);
      const col = api.__collect ? (E.s4)(c01((t - api.__collect.t) / api.__collect.dur)) : 0;
      const anchorZ = api.__collect ? api.__collect.to[2] : 0;
      for (const obj of OBJ) {
        const s = proj(t, camv, obj);
        let sx = s.sc * track(t, obj.sx), sy = s.sc * track(t, obj.sy);
        let op = s.opacity * track(t, obj.op === undefined ? 1 : obj.op);
        let rot = track(t, obj.rot) + camv.rot;
        // motion stretch, so a fast element blurs along its own path instead of merely moving
        if (obj.mst) {
          const c2 = camAt(Math.max(0, t - 0.0166)), s2 = proj(t - 0.0166, c2, obj);
          const dv = Math.hypot(s.px - s2.px, s.py - s2.py) / 0.0166;
          const st = Math.min(0.2, dv / 9000);
          if (Math.abs(s.px - s2.px) > Math.abs(s.py - s2.py)) sx *= 1 + st; else sy *= 1 + st;
          const bl = Math.min(2, dv / 5200);
          if (obj.el.style.filter !== (bl > 0.18 ? `blur(${bl.toFixed(2)}px)` : "")) {
            obj.el.style.filter = bl > 0.18 ? `blur(${bl.toFixed(2)}px)` : "";
          }
        }
        let px = s.px, py = s.py;
        if (col > 0 && !obj.keep) {
          const to = api.__collect.to, k = 1600 / Math.max(260, anchorZ - camv.z);
          const ax = camv.cx + (to[0] - camv.x) * k * camv.zoom, ay = camv.cy + (to[1] - camv.y) * k * camv.zoom;
          px += (ax - px) * col; py += (ay - py) * col;
          sx *= 1 - col * 0.94; sy *= 1 - col * 0.94;
          op *= 1 - Math.pow(col, 0.72); rot *= 1 - col;
        }
        const st = obj.el.style;
        st.transform = `translate3d(${px.toFixed(2)}px,${py.toFixed(2)}px,0)` +
          (rot ? ` rotate(${rot.toFixed(3)}deg)` : "") +
          (sx !== 1 || sy !== 1 ? ` scale(${sx.toFixed(5)},${sy.toFixed(5)})` : "") +
          " translate(-50%,-50%)";
        st.opacity = op < 0 ? "0" : op > 1 ? "1" : op.toFixed(3);
        st.visibility = op <= 0.005 ? "hidden" : "visible";
      }
      draw(t, camv);
      last = t;
    }

    function draw(t, camv) {
      const s = VW() / DESIGN;
      ctx.setTransform(s, 0, 0, s, 0, 0);
      ctx.clearRect(0, 0, DESIGN, DESIGN * 9 / 16);
      const place = (at) => {
        const dz = at[2] - camv.z, k = 1600 / Math.max(260, dz);
        return [camv.cx + (at[0] - camv.x) * k * camv.zoom, camv.cy + (at[1] - camv.y) * k * camv.zoom, k * camv.zoom];
      };
      for (const w of WAVES) {
        const age = t - w.t;
        if (age < 0 || age > 1.15) continue;
        const [px, py, k] = place(w.at);
        if (!isFinite(px) || !isFinite(py) || !isFinite(k)) continue;
        const rad = w.r * 0.5 * (0.1 + 0.9 * E.s5(c01(age / 0.85))) * k;
        const al = (1 - c01(age / 0.85)) * w.a;
        if (age < 0.3) {
          const fl = (1 - c01(age / 0.3)) * w.a * 0.55;
          const g = ctx.createRadialGradient(px, py, 0, px, py, 400 + k * 260);
          g.addColorStop(0, `rgba(255,255,255,${(fl * 0.95).toFixed(3)})`);
          g.addColorStop(0.42, `rgba(208,224,255,${(fl * 0.55).toFixed(3)})`);
          g.addColorStop(1, "rgba(255,255,255,0)");
          ctx.fillStyle = g; ctx.fillRect(px - 700, py - 700, 1400, 1400);
        }
        if (w.kind === 1) {
          ctx.strokeStyle = `rgba(31,107,255,${(al * 0.42).toFixed(3)})`; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.arc(px, py, rad * 0.72, 0, 6.2832); ctx.stroke();
        } else {
          ctx.strokeStyle = `rgba(255,255,255,${(al * 0.75).toFixed(3)})`; ctx.lineWidth = 1.6;
          ctx.beginPath(); ctx.arc(px, py, rad * 0.985, 0, 6.2832); ctx.stroke();
          ctx.strokeStyle = `rgba(31,107,255,${(al * 0.55).toFixed(3)})`; ctx.lineWidth = 3.2;
          ctx.beginPath(); ctx.arc(px, py, rad * 0.94, 0, 6.2832); ctx.stroke();
        }
      }
      for (const p of fxapi.parts) {
        const age = t - p.t0;
        if (age < 0 || age > p.life) continue;
        const [ox, oy] = place(p.at);
        if (!isFinite(ox) || !isFinite(oy)) continue;
        const dp = age * (1 - 0.52 * age / p.life);
        const x = ox + Math.cos(p.a) * p.sp * dp, y = oy + Math.sin(p.a) * p.sp * dp * 0.72 + 210 * age * age;
        const al = (1 - c01(age / p.life)) * cl(age / 0.06, 0, 1);
        if (p.kind === 0) {
          ctx.save(); ctx.translate(x, y); ctx.rotate(p.rot + p.rs * age);
          ctx.fillStyle = `rgba(${p.col},${al.toFixed(3)})`; ctx.beginPath();
          for (let j = 0; j < 10; j++) {
            const ang = -Math.PI / 2 + j * Math.PI / 5, rr = (j % 2 ? p.s * 0.85 : p.s * 2.1);
            const qx = Math.cos(ang) * rr, qy = Math.sin(ang) * rr;
            j ? ctx.lineTo(qx, qy) : ctx.moveTo(qx, qy);
          }
          ctx.closePath(); ctx.fill(); ctx.restore();
        } else {
          ctx.fillStyle = `rgba(${p.col},${(al * 0.5).toFixed(3)})`;
          ctx.beginPath(); ctx.arc(x, y, p.s * 0.66, 0, 6.2832); ctx.fill();
        }
      }
      const hud = fxapi.__hud;
      if (hud && t > (hud.from || 0)) {
        const alpha = c01((t - (hud.from || 0)) / 0.5) * (1 - c01((t - (hud.until || 1e9)) / 0.5)) * (hud.a || 0.55);
        if (alpha > 0.01) {
          // per-component: a box may be static numbers or a keyframed track
          const bx = track(t, hud.box[0]), by = track(t, hud.box[1]),
                bw = track(t, hud.box[2]), bh = track(t, hud.box[3]);
          const c2 = camAt(t);
          const dz = (hud.z || 0) - c2.z, k = 1600 / Math.max(260, dz);
          const cx = c2.cx + (bx - c2.x) * k * c2.zoom, cy = c2.cy + (by - c2.y) * k * c2.zoom;
          const hw = bw * 0.5 * k * c2.zoom, hh = bh * 0.5 * k * c2.zoom;
          const x0 = cx - hw, y0 = cy - hh, x1 = cx + hw, y1 = cy + hh, bl = 48 + 10 * Math.sin(t * 3.1);
          ctx.strokeStyle = `rgba(31,107,255,${alpha.toFixed(3)})`; ctx.lineWidth = 1.4;
          for (const [X, Y, sx2, sy2] of [[x0, y0, 1, 1], [x1, y0, -1, 1], [x0, y1, 1, -1], [x1, y1, -1, -1]]) {
            ctx.beginPath(); ctx.moveTo(X + sx2 * bl, Y); ctx.lineTo(X, Y); ctx.lineTo(X, Y + sy2 * bl); ctx.stroke();
          }
          const sy3 = y0 + ((t * 0.42) % 1) * (y1 - y0);
          const g = ctx.createLinearGradient(x0, sy3 - 24, x0, sy3 + 24);
          g.addColorStop(0, "rgba(31,107,255,0)"); g.addColorStop(0.5, `rgba(31,107,255,${(alpha * 0.55).toFixed(3)})`);
          g.addColorStop(1, "rgba(31,107,255,0)");
          ctx.fillStyle = g; ctx.fillRect(x0, sy3 - 24, x1 - x0, 48);
        }
      }
    }

    /* expose */
    Object.assign(api, { fx: fxapi, frame, requestAnimationFrame: undefined });
    /* window.seek receives ABSOLUTE take time - the channel (assets/runtime/scene.js) already
     * shifted it by this worker's slice offset, so adding anything here would double-count it on
     * a parallel render. Clamp against the TAKE's own length when the payload carries one. */
    const TLEN = (global.SCENE && global.SCENE.duration) || o.duration || 30;
    global.seek = function (t) { frame(Math.max(0, Math.min(TLEN, Number(t)))); };
    global.__sceneReady = true;
    return api;
  }

  global.D = { scene, parse, track, E, spr };
})(window);
