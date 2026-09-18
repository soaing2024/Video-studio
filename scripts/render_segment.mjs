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
// The skill's runtimes are injected, not linked from the scene: a scene file gets copied into
// the project it belongs to, so any relative <script src> it carried would break. Authors write
// `seek(t)` and nothing else; `Scene`, `Anim` and `Kit` are already on the page.
for (const rt of String(a.runtimes || "").split(",").filter(Boolean)) {
  await page.addInitScript({ path: rt });
}
await page.goto("file:///" + path.resolve(a.scene).replace(/\\/g, "/"));
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

// `--hold 0-2,7-9`: stretches of this take where the picture genuinely does not change.
const holds = String(a.hold || "").split(",").filter(Boolean).map((s) => {
  const [x, y] = s.split("-").map(Number);
  return [x, y];
}).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y) && y > x);
let lastBuf = null;
let distinct = 0;

for (let i = 0; i < total; i++) {
  const t = i / fps;
  // Inside a hold we reuse the previous frame instead of screenshotting: the take stays uncut and
  // the cost follows the number of *distinct* frames - the only cost lever a single take has left,
  // now that there are no separate still segments to lean on.
  const held = holds.some(([x, y]) => t > x + 0.5 / fps && t < y);
  const buf = held && lastBuf ? lastBuf : await frameAt(t);
  if (!held) {
    lastBuf = buf;
    distinct += 1;
  }
  if (!ff.stdin.write(buf)) await once(ff.stdin, "drain");
}
ff.stdin.end();
const code = await new Promise((resolve) => ff.on("close", resolve));
await browser.close();

const ok = code === 0 && !ffmpegError && errors.length === 0;
console.log(JSON.stringify({ ok, frames: total, distinctFrames: distinct, holds, seconds: duration,
                           size: [width, height], errors, ffmpegError }));
process.exit(ok ? 0 : 1);
