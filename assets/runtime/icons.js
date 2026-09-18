/* Icon runtime for video-studio templates.
 *
 * One catalog, two consumers: DOM templates build SVG elements from the node list, canvas
 * templates build Path2D from the same nodes. Everything is synchronous and offline - the
 * catalog is vendored next to the template and loaded with <script src>, so a render never
 * touches the network and never hits file:// CORS.
 *
 *   window.ICONS = { set, version, license, viewBox, icons: {name: [[tag, attrs], ...]}, tags }
 *
 * Usage in a template:
 *   Icons.draw(ctx, "gauge", 480, 320, 96, { stroke: "#2f2b28", width: 2, mode: "hand" });
 *   stage.appendChild(Icons.el("film", { size: 64, color: "#e0455f", width: 1.5 }));
 *   el.innerHTML = Icons.svg("sparkles", { size: 32 });
 */
(function (root) {
  "use strict";

  const cache = new Map();

  function cat() { return root.ICONS || {}; }
  function viewBox() { return cat().viewBox || 24; }
  function nodes(name) { const c = cat(); return (c.icons && c.icons[name]) || null; }

  function has(name) { return !!nodes(name); }
  function list() { return Object.keys(cat().icons || {}).sort(); }

  function tags(name) {
    const t = cat().tags || {};
    return t[name] || [];
  }

  /** Substring search over names and the upstream tag list, so "video" finds clapperboard. */
  function search(query) {
    const q = String(query || "").toLowerCase().trim();
    if (!q) return list();
    return list().filter((name) => name.includes(q) ||
      tags(name).some((tag) => String(tag).toLowerCase().includes(q)));
  }

  function attrString(attrs) {
    return Object.keys(attrs).map((k) => k + '="' + String(attrs[k]).replace(/"/g, "&quot;") + '"').join(" ");
  }

  /** Inline SVG markup - the safest thing to hand to innerHTML inside a rendered frame. */
  function svg(name, opts) {
    const n = nodes(name);
    if (!n) return "";
    opts = opts || {};
    const size = opts.size || 24;
    const stroke = opts.stroke || opts.color || "currentColor";
    const fill = opts.fill || "none";
    const width = opts.width === undefined ? 2 : opts.width;
    const body = n.map(([tag, attrs]) => "<" + tag + " " + attrString(attrs) + "/>").join("");
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + viewBox() + " " + viewBox() +
      '" width="' + size + '" height="' + size + '" fill="' + fill + '" stroke="' + stroke +
      '" stroke-width="' + width + '" stroke-linecap="round" stroke-linejoin="round" ' +
      (opts.style ? 'style="' + opts.style + '" ' : "") + ">" + body + "</svg>";
  }

  /** A real SVGElement, for templates that animate DOM nodes with the kit/anim runtime. */
  function el(name, opts) {
    const n = nodes(name);
    if (!n) return null;
    opts = opts || {};
    const NS = "http://www.w3.org/2000/svg";
    const box = viewBox();
    const node = document.createElementNS(NS, "svg");
    node.setAttribute("viewBox", "0 0 " + box + " " + box);
    const size = opts.size || 24;
    node.setAttribute("width", size);
    node.setAttribute("height", size);
    node.setAttribute("fill", opts.fill || "none");
    node.setAttribute("stroke", opts.stroke || opts.color || "currentColor");
    node.setAttribute("stroke-width", opts.width === undefined ? 2 : opts.width);
    node.setAttribute("stroke-linecap", "round");
    node.setAttribute("stroke-linejoin", "round");
    if (opts.className) node.setAttribute("class", opts.className);
    if (opts.style) node.setAttribute("style", opts.style);
    n.forEach(([tag, attrs]) => {
      const child = document.createElementNS(NS, tag);
      Object.keys(attrs).forEach((k) => child.setAttribute(k, attrs[k]));
      node.appendChild(child);
    });
    return node;
  }

  /**
   * Path2D list for canvas templates, built once per icon and cached.
   * Path2D takes SVG path data directly; the primitive tags have to be assembled by hand.
   */
  function paths(name) {
    if (cache.has(name)) return cache.get(name);
    const n = nodes(name);
    if (!n) return [];
    const out = [];
    for (const [tag, a] of n) {
      const p = new Path2D();
      const num = (v) => (v === undefined ? 0 : parseFloat(v));
      switch (tag) {
        case "path":
          out.push(new Path2D(a.d));
          continue;
        case "line":
          p.moveTo(num(a.x1), num(a.y1));
          p.lineTo(num(a.x2), num(a.y2));
          break;
        case "rect": {
          const x = num(a.x), y = num(a.y), w = num(a.width), h = num(a.height);
          const r = num(a.rx) || num(a.ry) || 0;
          if (r > 0 && p.roundRect) p.roundRect(x, y, w, h, r);
          else p.rect(x, y, w, h);
          break;
        }
        case "circle":
          p.arc(num(a.cx), num(a.cy), num(a.r), 0, Math.PI * 2);
          break;
        case "ellipse":
          p.ellipse(num(a.cx), num(a.cy), num(a.rx), num(a.ry), 0, 0, Math.PI * 2);
          break;
        case "polyline":
        case "polygon": {
          const pts = String(a.points || "").trim().split(/[\s,]+/).map(Number);
          for (let i = 0; i + 1 < pts.length; i += 2) {
            if (i === 0) p.moveTo(pts[i], pts[i + 1]);
            else p.lineTo(pts[i], pts[i + 1]);
          }
          if (tag === "polygon") p.closePath();
          break;
        }
        default:
          continue;
      }
      out.push(p);
    }
    cache.set(name, out);
    return out;
  }

  /**
   * Draw an icon centred on (x, y).
   *   mode "stroke" (default) - clean line art, the icon's native look
   *   mode "fill"            - solid silhouette (stroke art filled reads as a blob; use sparingly)
   *   mode "hand"            - a few jittered passes, so line art sits inside a hand-drawn scene
   */
  function draw(ctx, name, x, y, size, opts) {
    const ps = paths(name);
    if (!ps.length) return false;
    opts = opts || {};
    const box = viewBox();
    const k = size / box;
    const mode = opts.mode || "stroke";
    const width = opts.width === undefined ? 2 : opts.width;
    const alpha = opts.alpha === undefined ? 1 : opts.alpha;
    const color = opts.color || opts.stroke || "#000";

    ctx.save();
    ctx.translate(x - size / 2, y - size / 2);
    ctx.scale(k, k);
    if (opts.rotate) {                       // rotate about the icon centre, in viewBox units
      ctx.translate(box / 2, box / 2);
      ctx.rotate(opts.rotate);
      ctx.translate(-box / 2, -box / 2);
    }
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;

    if (mode === "fill") {
      ctx.globalAlpha = alpha;
      ps.forEach((p) => ctx.fill(p));
    } else if (mode === "hand") {
      // Dry-pencil build-up: soft underlay, the line itself, then a light grain pass.
      // Offsets are given in output pixels, hence the /k back into viewBox units.
      const pass = (dx, dy, w, a) => {
        ctx.save();
        ctx.globalAlpha = alpha * a;
        ctx.lineWidth = w;
        ctx.translate(dx / k, dy / k);
        ps.forEach((p) => ctx.stroke(p));
        ctx.restore();
      };
      pass(0.5, -0.4, width * 2.4, 0.16);
      pass(0, 0, width, 0.92);
      pass(1.0, 0.7, width * 0.6, 0.42);
    } else {
      ctx.globalAlpha = alpha;
      ctx.lineWidth = width;
      ps.forEach((p) => ctx.stroke(p));
    }
    ctx.restore();
    return true;
  }

  root.Icons = {
    has: has, list: list, search: search, tags: tags,
    svg: svg, el: el, paths: paths, draw: draw,
    set: () => cat().set || "unknown",
    version: () => cat().version || "unknown",
    license: () => cat().license || "unknown",
  };
})(typeof window !== "undefined" ? window : globalThis);
