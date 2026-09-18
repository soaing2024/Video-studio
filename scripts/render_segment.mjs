// Frame-exact segment renderer: HTML/CSS/JS scene -> H.264 mp4 (frames are piped to ffmpeg).
// Usage: node render_segment.mjs --scene <html> --out <mp4> --data <json> [options]
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    out[key] = argv[i + 1];
  }
  return out;
}

const a = parseArgs(process.argv.slice(2));
if (!a.scene || !a.out) {
  console.error("usage: render_segment.mjs --scene <html> --out <mp4> --data <json> [--fps 30 --duration 8 --width 1280 --height 720 --ffmpeg <path> --crf 12 --preset veryfast --still <t> --still-out <png>]");
  process.exit(2);
}

const fps = Number(a.fps || 30);
const duration = Number(a.duration || 8);
const width = Number(a.width || 1280);
const height = Number(a.height || 720);
const crf = String(a.crf || 12);
const preset = a.preset || "veryfast";
const data = a.data ? JSON.parse(fs.readFileSync(a.data, "utf8")) : {};
const total = Math.round(duration * fps);

const playwright = require(process.env.VS_PLAYWRIGHT || "playwright");
const browser = await playwright.chromium.launch();
const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });

const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.addInitScript((scene) => { window.SCENE = scene; }, data);
await page.goto("file:///" + path.resolve(a.scene).replace(/\\/g, "/"));

// Base type for every scene, including user-written templates: without it the page default is a
// serif face, so Latin and digits render Times New Roman while CJK falls back elsewhere and the
// mixed-script typography breaks on the first line.
await page.addStyleTag({ content: `
  html, body, #stage, .stage {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC",
                 "PingFang SC", "Segoe UI", system-ui, -apple-system, sans-serif;
  }` });
await page.waitForFunction('typeof window.seek === "function" && window.__sceneReady !== false', null, { timeout: 30000 });
await page.evaluate(() => document.fonts.ready);

async function frameAt(t) {
  await page.evaluate((time) => window.seek(time), t);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
  return page.screenshot({ type: "png" });
}

if (a.still) {
  const buf = await frameAt(Number(a.still));
  fs.mkdirSync(path.dirname(path.resolve(a["still-out"] || "still.png")), { recursive: true });
  fs.writeFileSync(a["still-out"] || "still.png", buf);
  await browser.close();
  console.log(JSON.stringify({ ok: true, still: a["still-out"] || "still.png", errors }));
  process.exit(0);
}

fs.mkdirSync(path.dirname(path.resolve(a.out)), { recursive: true });
const ff = spawn(a.ffmpeg || "ffmpeg", [
  "-y", "-hide_banner", "-loglevel", "error",
  "-f", "image2pipe", "-framerate", String(fps), "-i", "-",
  "-c:v", "libx264", "-preset", preset, "-crf", crf,
  "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out,
], { stdio: ["pipe", "inherit", "inherit"] });

let ffmpegError = null;
ff.on("error", (e) => { ffmpegError = String(e); });

for (let i = 0; i < total; i++) {
  const buf = await frameAt(i / fps);
  if (!ff.stdin.write(buf)) await once(ff.stdin, "drain");
}
ff.stdin.end();
const code = await new Promise((resolve) => ff.on("close", resolve));

// Layout audit: the failures that pixels alone do not reveal - a template that never renders its
// actors, text that sits off-frame after the camera drifts, blocks that overlap, and a page that
// never declared a font and therefore renders Times New Roman.
// Sample near the end: every beat has fired by then, so "still invisible" really means never
// visible rather than "not yet arrived".
const auditAt = Math.min(Math.max(2.6, duration * 0.85), Math.max(2.6, duration - 0.35));
let audit = null;
try {
  await page.evaluate((tt) => window.seek(tt), auditAt);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
  const runAudit = (tt) => page.evaluate((tt) => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const effOpacity = (n) => {
      let o = 1;
      for (let el = n; el && el !== document.documentElement; el = el.parentElement) {
        const v = parseFloat(getComputedStyle(el).opacity);
        o *= Number.isFinite(v) ? v : 1;
      }
      return o;
    };
    const label = (el) => (el.id ? "#" + el.id : el.tagName.toLowerCase()) +
      "(" + (el.textContent || "").trim().slice(0, 14) + ")";
    const texts = [];
    document.querySelectorAll("*").forEach((el) => {
      if (el.tagName === "SCRIPT" || el.tagName === "STYLE" || el.tagName === "CANVAS") return;
      if (el.children.length) return;
      const txt = (el.textContent || "").trim();
      if (!txt) return;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      // layout box (ignores transforms) for overlap tests, and the visual box for visibility:
      // a camera rotation inflates a wide element's bounding rect by tens of pixels and would
      // otherwise be reported as overlapping its neighbours.
      let lx = 0, ly = 0;
      for (let n = el; n; n = n.offsetParent) { lx += n.offsetLeft; ly += n.offsetTop; }
      texts.push({ name: label(el), opacity: +effOpacity(el).toFixed(3),
                    x: Math.round(lx), y: Math.round(ly),
                    w: el.offsetWidth, h: el.offsetHeight,
                    cx: Math.round(r.left + r.width / 2), cy: Math.round(r.top + r.height / 2),
                    size: parseFloat(cs.fontSize) });
    });
    const visible = texts.filter((t) => t.opacity > 0.05 && t.w > 0 && t.h > 0);
    const invisible = texts.filter((t) => t.opacity <= 0.05);
    // overlays and decorative bleeds are deliberate, so off-frame and overlap checks only judge
    // elements that read as primary content - i.e. actually opaque.
    const primary = visible.filter((t) => t.opacity > 0.6);
    // a transformed element is off-frame when its visible centre leaves the viewport
    const offscreen = primary.filter((t) => t.cx < 0 || t.cy < 0 || t.cx > vw || t.cy > vh);
    const overlaps = [];
    for (let i = 0; i < primary.length; i++) {
      for (let j = i + 1; j < primary.length; j++) {
        const a = primary[i], b = primary[j];
        const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
        const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        if (ox <= 2 || oy <= 2) continue;
        const smaller = Math.min(a.w * a.h, b.w * b.h) || 1;
        if ((ox * oy) / smaller > 0.3) overlaps.push(a.name + " x " + b.name);
      }
    }
    const bodyFont = getComputedStyle(document.body).fontFamily || "";
    return { at: tt, viewport: [vw, vh], font: bodyFont,
             serifRisk: /times|serif/i.test(bodyFont) && !/sans-serif/i.test(bodyFont),
             textNodes: texts.length, visible: visible.length, invisible: invisible.length,
             invisibleSamples: invisible.slice(0, 6).map((t) => t.name),
             invisibleNames: invisible.map((t) => t.name),
             offscreen: offscreen.length, offscreenSamples: offscreen.slice(0, 6).map((t) => t.name),
             overlaps: overlaps.length, overlapSamples: overlaps.slice(0, 4) };
  }, tt);

  // Two instants, intersected: something still invisible late in the shot is broken; something
  // that has simply not arrived yet at the first sample is not.
  const first = await runAudit(auditAt);
  const late = await runAudit(Math.max(2.8, duration - 0.6));
  const common = (first.invisibleNames || []).filter((n) => (late.invisibleNames || []).includes(n));
  audit = Object.assign({}, late, { invisible: common.length,
                                  invisibleSamples: common.slice(0, 6),
                                  sampledAt: [auditAt, Math.max(2.8, duration - 0.6)] });
} catch (e) {
  audit = { error: String(e).split("\n")[0] };
}

await browser.close();

const ok = code === 0 && !ffmpegError && errors.length === 0;
console.log(JSON.stringify({ ok, frames: total, seconds: duration, size: [width, height], errors, ffmpegError, audit }));
process.exit(ok ? 0 : 1);
