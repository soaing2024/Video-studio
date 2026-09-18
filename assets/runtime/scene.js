/* scene.js - plumbing for a hand-written shot, and nothing else.
 *
 * This file deliberately contains no visual identity: no palette, no layout, no motion style.
 * It gives a scene the four things every shot needs and nothing more:
 *
 *   Scene.mount(opts)   -> { stage, layer(name), canvas(name) }
 *   Scene.type(el, size, opts)  -> applies one entry from the type scale
 *   Scene.safe()        -> the box that survives platform UI and the progress bar
 *   Scene.ready()       -> set __sceneReady, so the renderer knows `seek` exists
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

  global.Scene = { mount, type, safe, ready, SAFE };
})(window);
