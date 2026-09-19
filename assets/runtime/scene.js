/* scene.js - plumbing for a hand-written shot, and nothing else.
 *
 * This file deliberately contains no visual identity: no palette, no layout, no motion style.
 * It gives a scene the things every shot needs and nothing more:
 *
 *   Scene.mount(opts)   -> { stage, layer(name), canvas(name) }
 *   Scene.type(el, size, opts)  -> applies one entry from the type scale
 *   Scene.safe()        -> the box that survives platform UI and the progress bar
 *   Scene.ready()       -> set __sceneReady, so the renderer knows `seek` exists
 *   Scene.icon(name, opts)      -> an <svg> from a vendored icon set (`"libs": ["lucide"]`)
 *   Scene.iconNames()   -> the icon names that set actually provides
 *
 * A scene is: build your own elements, then expose `window.seek(t)` as a pure function of t.
 * Compose the shot from references/choreography.md - do not look for a skeleton to fill.
 */
(function (global) {
  const SAFE = { top: 0.06, right: 0.06, bottom: 0.12, left: 0.06 };

  function mount(opts) {
    const o = opts || {};
    const stage = o.stage || document.getElementById("stage") || document.body;
    // The stage is a full-viewport box, always. Setting `position: relative` here used to collapse
    // it to zero height - the children are absolutely positioned, so they contribute no height -
    // and every layer measured 320x0: a scene that renders as pure background with no error.
    Object.assign(stage.style, { position: "absolute", inset: "0", overflow: "hidden" });
    if (o.background) stage.style.background = o.background;
    global.SCENE = o.data || global.SCENE || {};

    const layers = new Map();
    function layer(name, css) {
      if (layers.has(name)) return layers.get(name);
      const el = document.createElement("div");
      el.className = "scene-layer";
      el.dataset.layer = name;
      Object.assign(el.style, { position: "absolute", inset: "0" }, css || {});
      stage.appendChild(el);
      layers.set(name, el);
      return el;
    }

    function canvas(name, css) {
      const host = layer(name, css);
      const cv = document.createElement("canvas");
      cv.width = global.innerWidth;
      cv.height = global.innerHeight;
      Object.assign(cv.style, { position: "absolute", inset: "0" });
      host.appendChild(cv);
      return { canvas: cv, ctx: cv.getContext("2d") };
    }

    return { stage, layer, canvas, layers, data: global.SCENE };
  }

  /* One entry of a type scale. Sizes are fractions of the short edge, so the same scene works at
   * 720p or 4K, which is the whole point of authoring instead of picking. */
  function type(el, size, opts) {
    const o = opts || {};
    const base = Math.min(global.innerWidth, global.innerHeight);
    Object.assign(el.style, {
      fontFamily: o.family || '"Microsoft YaHei", "Noto Sans SC", system-ui, sans-serif',
      fontSize: `${Math.round(base * size)}px`,
      fontWeight: o.weight || "500",
      lineHeight: o.lineHeight || "1.05",
      letterSpacing: o.tracking === undefined ? "-0.01em" : `${o.tracking}em`,
      color: o.color || "#f2f4f1",
      margin: "0"
    });
    return el;
  }

  /* Icons come from a vendored set and are built by hand into an <svg>.
   * Nothing here reads a clock: an icon is part of the still frame, and whatever moves it is the
   * scene's own t-derived transform. Opt in with `"libs": ["lucide"]` in project.json. */
  const SVG_NS = "http://www.w3.org/2000/svg";
  let ICON_INDEX = null;

  function iconKey(name) {
    return String(name || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  }

  function iconMap() {
    const lib = global.lucide;
    if (!lib || !lib.icons) {
      throw new Error('Scene.icon needs a vendored icon library: add "libs": ["lucide"] to project.json, then run: python vs.py libs --install lucide');
    }
    if (!ICON_INDEX) {
      ICON_INDEX = new Map();
      for (const [key, value] of Object.entries(lib.icons)) {
        if (Array.isArray(value)) ICON_INDEX.set(iconKey(key), { key, node: value });
      }
    }
    return ICON_INDEX;
  }

  function iconNames() {
    return [...iconMap().values()].map((v) => v.key).sort();
  }

  function icon(name, opts) {
    const o = opts || {};
    const hit = iconMap().get(iconKey(name));
    if (!hit) {
      throw new Error(`Scene.icon: no icon named "${name}". Both "arrow-right" and "ArrowRight" work; Scene.iconNames() lists all of them.`);
    }
    const size = o.size || 48;
    const svg = document.createElementNS(SVG_NS, "svg");
    const attrs = {
      viewBox: "0 0 24 24", width: size, height: size, fill: "none",
      stroke: o.color || "currentColor", "stroke-width": o.strokeWidth || 2,
      "stroke-linecap": "round", "stroke-linejoin": "round"
    };
    for (const key of Object.keys(attrs)) svg.setAttribute(key, attrs[key]);
    svg.style.display = "block";
    if (o.className) svg.setAttribute("class", o.className);
    for (const [tag, child] of hit.node) {
      const el = document.createElementNS(SVG_NS, tag);
      for (const key of Object.keys(child || {})) el.setAttribute(key, child[key]);
      svg.appendChild(el);
    }
    return svg;
  }

  function safe() {
    return {
      top: global.innerHeight * SAFE.top,
      left: global.innerWidth * SAFE.left,
      width: global.innerWidth * (1 - SAFE.left - SAFE.right),
      height: global.innerHeight * (1 - SAFE.top - SAFE.bottom)
    };
  }

  function ready() {
    global.__sceneReady = true;
  }

  global.Scene = { mount, type, safe, ready, SAFE, icon, iconNames };
})(window);
