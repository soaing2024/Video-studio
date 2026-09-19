// Scan a scene across its whole timeline in ONE browser session and report, per element,
// when it is visible and whether anything is broken.
//
// This is the cheap instrument that catches the bugs `verify` cannot see: an element that
// flies out of frame, a window that is faintly visible from t=0 because a keyframe track
// ramps instead of holding, a transform that has gone to NaN.
//
// Usage: node scan_scene.mjs --scene <html> --data <json> --duration 30 --width 1920
//                            --height 1080 [--stride 0.25] [--runtimes a,b,c]
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, "")] = argv[i + 1];
  return out;
}
const a = parseArgs(process.argv.slice(2));
const duration = Number(a.duration || 30);
const stride = Number(a.stride || 0.25);
const width = Number(a.width || 1920), height = Number(a.height || 1080);
const data = a.data ? JSON.parse(fs.readFileSync(a.data, "utf8")) : {};
const playwright = require(process.env.VS_PLAYWRIGHT || "playwright");

const browser = await playwright.chromium.launch();
const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.addInitScript((s) => { window.SCENE = s; }, data);
for (const rt of String(a.runtimes || "").split(",").filter(Boolean)) {
  await page.addInitScript({ path: rt });
}
await page.goto("file:///" + path.resolve(a.scene).replace(/\\/g, "/"));

let ready = true;
try {
  await page.waitForFunction('typeof window.seek === "function" && window.__sceneReady !== false',
                             null, { timeout: 15000 });
} catch (e) {
  ready = false;
}

const out = { ok: ready, ready, stride, screen: [width, height], samples: 0,
              broken: [], visibility: {}, nan: [], errors: [], first_error_t: null };

if (ready) {
  // Per-frame probe: every element that carries text or looks like a panel, plus NaN scan.
  const sample = (t) => {
    const seen = [];
    let nan = 0;
    for (const e of document.querySelectorAll("div,span,svg,canvas")) {
      const tf = e.style && e.style.transform;
      if (tf && tf.includes("NaN")) nan += 1;
      const cs = getComputedStyle(e);
      if (cs.visibility !== "visible" || parseFloat(cs.opacity) < 0.05) continue;
      let p = e.parentElement, hidden = false;
      while (p) {
        const pc = getComputedStyle(p);
        if (pc.visibility !== "visible" || parseFloat(pc.opacity) < 0.05) { hidden = true; break; }
        p = p.parentElement;
      }
      if (hidden) continue;
      const r = e.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const text = e.children.length === 0 ? (e.textContent || "").trim().slice(0, 40) : "";
      seen.push({ id: e.id || (text ? "text:" + text : "") || e.className.toString().slice(0, 24),
                  tag: e.tagName.toLowerCase(), text,
                  x: Math.round(r.x), y: Math.round(r.y),
                  w: Math.round(r.width), h: Math.round(r.height) });
    }
    return { t, seen, nan };
  };

  const steps = Math.max(1, Math.floor(duration / stride));
  for (let i = 0; i <= steps; i++) {
    const t = Math.min(duration, i * stride);
    let res;
    try {
      await page.evaluate((tt) => window.seek(tt), t);
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
      res = await page.evaluate(sample, t);
    } catch (e) {
      out.broken.push({ t: +t.toFixed(3), kind: "seek_threw", detail: String(e).split("\n")[0].slice(0, 160) });
      if (out.first_error_t === null) out.first_error_t = +t.toFixed(3);
      continue;
    }
    out.samples += 1;
    if (res.nan && !out.nan.length) out.nan.push({ t: +t.toFixed(3), count: res.nan });
    for (const el of res.seen) {
      const key = el.id;
      if (!out.visibility[key]) out.visibility[key] = { tag: el.tag, text: el.text, size: [el.w, el.h], spans: [] };
      const rec = out.visibility[key];
      const last = rec.spans[rec.spans.length - 1];
      if (last && Math.abs(last[1] - t) < stride * 1.5) last[1] = +t.toFixed(3);
      else rec.spans.push([+t.toFixed(3), +t.toFixed(3)]);
      const outside = el.x + el.w < 0 || el.y + el.h < 0 || el.x > width || el.y > height;
      if (outside && el.text) {
        const b = out.broken[out.broken.length - 1];
        const item = { t: +t.toFixed(3), kind: "text_out_of_frame", text: el.text,
                       box: [el.x, el.y, el.w, el.h] };
        if (!b || b.kind !== "text_out_of_frame" || b.text !== el.text) out.broken.push(item);
      }
    }
  }
  out.errors = errors.slice(0, 5);
}
await browser.close();
console.log(JSON.stringify(out));
