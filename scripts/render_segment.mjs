// Frame-exact scene renderer. One scene + one time window -> H.264 mp4 (frames are piped
// into ffmpeg's stdin and never touch disk).
//
// Usage: node render_segment.mjs --scene <html> --out <mp4> --data <json> [options]
//
// Delivery-size defaults, measured on a 4K scene over 12-frame windows, single process:
//   playwright png, software GL (old default) ..... 730 ms/frame
//   + GPU rasterisation .......................... 671 ms/frame   (--gpu false to disable)
//   + CDP png optimizeForSpeed, still lossless ... 166 ms/frame   (--png-compression default)
//   + jpeg 97, lossy, preflight only ............. 102 ms/frame   (--jpeg 97)
// The GPU flags matter because headless Chromium otherwise falls back to SwiftShader, i.e.
// CPU rasterisation, even on a machine with a discrete GPU.
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    out[argv[i].replace(/^--/, "")] = argv[i + 1];
  }
  return out;
}

const a = parseArgs(process.argv.slice(2));

function fail(code, where, expected, got, fix_hint, detail) {
  console.log(JSON.stringify({ ok: false, error: {
    code, where, expected, got, fix_hint,
    ...(detail ? { detail: String(detail).slice(-600) } : {}) } }));
  process.exit(1);
}

if (!a.scene || !a.out) {
  fail("BAD_ARGS", "render_segment.mjs", "--scene <html> --out <mp4>",
       process.argv.slice(2).join(" "),
       "python scripts/api_index.py lists every flag; vs.py preview/render call this for you");
}

const fps = Number(a.fps || 30);
const duration = Number(a.duration || 8);
const width = Number(a.width || 1920);
const height = Number(a.height || 1080);
const crf = String(a.crf || 12);
// ultrafast keeps x264's lookahead buffers small: at 4K a single encoder holds ~12 MB per
// buffered frame, and N of those is what kills a parallel 4K render.
const preset = a.preset || "ultrafast";
const data = a.data ? JSON.parse(fs.readFileSync(a.data, "utf8")) : {};
const total = Math.round(duration * fps);
const rebootEvery = Number(a.reboot || 0);
const fastPng = String(a["png-compression"] || "fast") !== "default";
const jpeg = a.jpeg ? Number(a.jpeg) : 0;
const gpu = String(a.gpu === undefined ? "true" : a.gpu) !== "false";
// Draft mode: the CSS layout stays at `width x height` (so composition is honest) while the
// captured image is scaled down. Only CDP can do that; Playwright's own screenshot cannot.
const scale = Number(a.scale || 1);

const GPU_ARGS = ["--use-angle=d3d11", "--enable-gpu-rasterization", "--enable-zero-copy",
                  "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"];
const playwright = require(process.env.VS_PLAYWRIGHT || "playwright");
const errors = [];
const consoleErrors = [];

async function boot() {
  const browser = await playwright.chromium.launch({ args: gpu ? GPU_ARGS : [] });
  // Draft capture scales with deviceScaleFactor, not with a CDP clip: the CSS layout stays at
  // width x height (so composition is honest) while the rasterised image comes back smaller.
  // A clip scale silently produced invalid frames on this Chromium build, which killed the
  // encoder and then hung the render loop on a drain that never came.
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
  await page.addInitScript((scene) => { window.SCENE = scene; }, data);
  await page.addInitScript((on) => { window.__SIG_CANVAS = on; }, a["sig-canvas"] !== "0");
  for (const rt of String(a.runtimes || "").split(",").filter(Boolean)) {
    await page.addInitScript({ path: rt });
  }
  await page.goto("file:///" + path.resolve(a.scene).replace(/\\/g, "/"));
  try {
    await page.waitForFunction('typeof window.seek === "function" && window.__sceneReady !== false',
                               null, { timeout: Number(a.ready_timeout || 30000) });
  } catch (e) {
    fail("SCENE_NOT_READY", path.basename(a.scene),
         "window.seek(t) defined and window.__sceneReady !== false",
         `not ready after ${Number(a.ready_timeout || 30000) / 1000}s`,
         "call Scene.ready() (or set window.__sceneReady = true) at the end of the scene; "
         + "run `vs.py preview <project> --report` to see the page errors",
         [...errors, ...consoleErrors].join("\n"));
  }
  await page.evaluate(() => document.fonts.ready);
  return { browser, page };
}

// DOM truth for the preview channel: what is actually visible, where, and how legible.
const PROBE = () => {
  const out = [];
  for (const e of document.querySelectorAll("div,span,svg,canvas")) {
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
    const text = e.children.length === 0 ? (e.textContent || "").trim() : "";
    if (!text && !e.classList.contains("p") && e.tagName !== "CANVAS") continue;
    out.push({ tag: e.tagName.toLowerCase(), cls: String(e.className).slice(0, 32),
               text: text.slice(0, 48), x: +r.x.toFixed(1), y: +r.y.toFixed(1),
               w: +r.width.toFixed(1), h: +r.height.toFixed(1),
               fs: Math.round(parseFloat(cs.fontSize) || 0), color: cs.color, bg: cs.backgroundColor });
    if (out.length >= 400) break;
  }
  return { viewport: { w: innerWidth, h: innerHeight }, elements: out, page_errors: [] };
};

// Frame signatures: a hash of everything that determines the picture at t (every
// element's transform/opacity/visibility/text, plus a 1/16-scale canvas readback). Two
// frames with the same signature are the same frame, so an edit only needs to re-render
// the frames whose state actually changed - which is what makes `--incremental` honest.
const STATE = () => {
  let h = 2166136261;
  const mix = (s) => { for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } };
  // Visual elements only: <script>/<style> are leaves too, and their textContent IS the
  // scene source - hashing them would make every source edit invalidate every frame.
  const SKIP = /^(SCRIPT|STYLE|LINK|META|TITLE|HEAD|NOSCRIPT|TEMPLATE)$/;
  for (const e of document.querySelectorAll("*")) {
    if (SKIP.test(e.tagName)) continue;
    const st = e.style;
    if (!st) continue;
    mix(st.transform || ""); mix(st.opacity || ""); mix(st.visibility || "");
    if (e.children.length === 0) mix(e.textContent || "");
  }
  const cv = document.querySelector("canvas");
  // Canvas readback is opt-out: it is the one part of the frame whose bytes are not a
  // pure function of the DOM state, so a scene whose FX live on canvas can over-invalidate.
  if (cv && window.__SIG_CANVAS !== false) {
    const c = document.createElement("canvas");
    c.width = 64; c.height = 36;
    const x = c.getContext("2d");
    x.drawImage(cv, 0, 0, 64, 36);
    const d = x.getImageData(0, 0, 64, 36).data;
    for (let i = 0; i < d.length; i += 17) h = (Math.imul(h, 33) + d[i]) | 0;
  }
  return h >>> 0;
};

// One frame's worth of paint. requestAnimationFrame can stall when the compositor is not
// producing frames (software rasterisation, a hidden page, a slow first paint), and the
// renderer must never wait forever on it: the timer is the escape hatch.
const paint = (page) => page.evaluate(() => new Promise((r) => {
  let done = false;
  const finish = () => { if (!done) { done = true; r(); } };
  requestAnimationFrame(finish);
  setTimeout(finish, 40);
}));

async function grab(page, cdp) {
  if (jpeg) return page.screenshot({ type: "jpeg", quality: jpeg });
  if (fastPng && cdp) {
    try {
      const r = await cdp.send("Page.captureScreenshot",
                               { format: "png", optimizeForSpeed: true, fromSurface: true });
      return Buffer.from(r.data, "base64");
    } catch (e) { /* older chromium: fall back to the default encoder */ }
  }
  return page.screenshot({ type: "png" });
}

let session = await boot();
if (a.debug) process.stderr.write(`[dbg] booted scale=${scale}\n`);
let cdp = fastPng ? await session.page.context().newCDPSession(session.page).catch(() => null) : null;

if (a.sig) {
  const stride = Math.max(1, Math.round(Number(a["sig-stride"] || 1)));
  const sigs = [];
  for (let i = 0; i < total; i += stride) {
    await session.page.evaluate((tt) => window.seek(tt), i / fps);
    await paint(session.page);
    sigs.push(await session.page.evaluate(STATE));
  }
  await session.browser.close();
  fs.mkdirSync(path.dirname(path.resolve(a.sig)), { recursive: true });
  fs.writeFileSync(a.sig, JSON.stringify({ frames: total, stride, sigs, errors }));
  console.log(JSON.stringify({ ok: true, sig: a.sig, frames: total, stride,
                               distinct: new Set(sigs).size, gpu, errors: [] }));
  process.exit(0);
}

if (a.still) {
  const at = Number(a.still);
  await session.page.evaluate((t) => window.seek(t), at);
  await paint(session.page);
  const buf = await grab(session.page, cdp);
  const out = a["still-out"] || "still.png";
  fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  fs.writeFileSync(out, buf);
  if (a.probe) {
    const probe = await session.page.evaluate(PROBE);
    probe.page_errors = [...errors, ...consoleErrors];
    probe.t = at;
    fs.mkdirSync(path.dirname(path.resolve(a.probe)), { recursive: true });
    fs.writeFileSync(a.probe, JSON.stringify(probe));
  }
  await session.browser.close();
  console.log(JSON.stringify({ ok: true, still: out, probe: a.probe || null, t: at,
                               bytes: buf.length, gpu, fastPng, jpeg, errors: [] }));
  process.exit(0);
}

fs.mkdirSync(path.dirname(path.resolve(a.out)), { recursive: true });
const ff = spawn(a.ffmpeg || "ffmpeg", [
  "-y", "-hide_banner", "-loglevel", "error",
  "-f", "image2pipe", "-framerate", String(fps), "-i", "-",
  "-c:v", "libx264", "-preset", preset, "-crf", crf,
  "-pix_fmt", "yuv420p", "-movflags", "+faststart", a.out,
], { stdio: ["pipe", "inherit", "pipe"] });

let ffmpegError = null, ffStderr = "";
ff.on("error", (e) => { ffmpegError = String(e); });
ff.stderr.on("data", (d) => { ffStderr += String(d); });

const holds = String(a.hold || "").split(",").filter(Boolean).map((s) => {
  const [x, y] = s.split("-").map(Number);
  return [x, y];
}).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y) && y > x);

let lastBuf = null, distinct = 0, reboots = 0;
const t0 = Date.now();
for (let i = 0; i < total; i++) {
  const t = i / fps;
  if (rebootEvery && i > 0 && i % rebootEvery === 0) {
    await session.browser.close();
    session = await boot();
    cdp = fastPng ? await session.page.context().newCDPSession(session.page).catch(() => null) : null;
    reboots += 1;
  }
  const held = holds.some(([x, y]) => t > x + 0.5 / fps && t < y);
  let buf = held && lastBuf ? lastBuf : null;
  if (!buf) {
    try {
      await session.page.evaluate((tt) => window.seek(tt), t);
      await paint(session.page);
      if (a.debug) process.stderr.write(`[dbg] f${i} painted\n`);
      buf = await grab(session.page, cdp);
      if (a.debug) process.stderr.write(`[dbg] f${i} grabbed ${buf.length}\n`);
    } catch (e) {
      fail("FRAME_FAILED", `${path.basename(a.scene)} @ t=${t.toFixed(3)}s (frame ${i}/${total})`,
           "seek(t) returns without throwing",
           String(e).split("\n")[0],
           `vs.py preview <project> --report --at ${t.toFixed(2)} shows the failing state`,
           [...errors, ...consoleErrors].join("\n"));
    }
    lastBuf = buf;
    distinct += 1;
  }
  if (!ff.stdin.write(buf)) {
    // Wait for capacity, but never past the encoder's own death. A dead ffmpeg used to mean
    // an unbounded wait here instead of an error message, because 'close' had already
    // fired before anyone listened for it.
    const dead = (ff.exitCode !== null) || ff.killed;
    if (!dead) {
      await Promise.race([
        once(ff.stdin, "drain"),
        once(ff.stdin, "error").catch(() => null),
        new Promise((r) => setTimeout(r, 30000)),
      ]);
    }
    if (ff.exitCode !== null && ff.exitCode !== 0) {
      fail("FFMPEG_FAILED", `libx264 -> ${path.basename(a.out)} at frame ${i}/${total}`,
           "the encoder accepts piped frames", `exit ${ff.exitCode}`,
           "re-run with --progress 1 to see how far it got; note that a scaled screenshot " +
           "must stay PNG, because Chromium emits progressive JPEGs at deviceScaleFactor " +
           "below 1 and ffmpeg's pipe probe cannot detect them", ffStderr);
    }
  }
  if (a.progress && i % Number(a.progress) === 0) {
    process.stderr.write(`\r${i}/${total} ${((Date.now() - t0) / Math.max(1, i + 1)).toFixed(0)} ms/frame`);
  }
}
ff.stdin.end();
const code = await new Promise((resolve) => ff.on("close", resolve));
await session.browser.close();

if (code !== 0 || ffmpegError) {
  fail("FFMPEG_FAILED", `libx264 -> ${path.basename(a.out)}`, "encoder exit 0",
       ffmpegError || `exit ${code}`,
       "at 4K lower the concurrency (--jobs 2): each x264 encoder buffers ~12 MB per "
       + "lookahead frame. Keep --preset ultrafast, or set --reboot 90 to cap browser memory",
       ffStderr);
}
if (errors.length) {
  fail("PAGE_ERROR", a.scene, "no uncaught exceptions while rendering",
       `${errors.length} page error(s): ${errors[0]}`,
       "fix the first error, then re-run `vs.py check <project>`",
       errors.join("\n"));
}

console.log(JSON.stringify({
  ok: true, frames: total, distinct_frames: distinct, seconds: Number(duration.toFixed(3)),
  size: [width, height], ms_per_frame: Math.round((Date.now() - t0) / total),
  reboots, gpu, fast_png: fastPng, jpeg, preset, errors: [] }));
