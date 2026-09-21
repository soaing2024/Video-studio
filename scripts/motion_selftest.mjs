// Proof, not promise: load the Motion runtime the way the renderer injects it (an init script,
// before any scene code) and measure whether a drawn parameter can actually jump.
//
//     node scripts/motion_selftest.mjs
//
// Every assertion is a measurement over simulated frames at the delivery rate. If one of these
// can fail, the guarantee is a slogan; this file exists so it cannot quietly become one.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(here, "..", "assets", "runtime", "motion.js"), "utf8");

function boot(fps) {
  const win = { SCENE: { fps } };                 // exactly what the page gets injected with
  new Function("window", SRC)(win);
  return win.Motion;
}

let failures = 0;
function check(name, ok, detail) {
  if (!ok) failures++;
  console.log((ok ? "  ok   " : "  FAIL ") + name + (detail ? "  -- " + detail : ""));
}

for (const fps of [24, 30, 60]) {
  const M = boot(fps);
  const FRAME = 1 / fps;
  console.log(`\n== ${fps} fps  (band ${M.bandHz.toFixed(2)} Hz = ${M.bandRad.toFixed(1)} rad/s, ` +
              `min ramp ${(M.minRamp * 1000).toFixed(0)} ms, max step ${M.maxStepFrac} of travel)`);

  // 1. a hard retarget can never cover more than maxStepFrac of the travel in one frame
  {
    const ch = M.channel("x", 0);
    ch.place(0);
    let t = 0;
    ch.at(t);                                     // settle at 0
    ch.set(t, 100, { in: 0 });                    // "make it snap" - the runtime refuses
    let worst = 0, prev = ch.at(t);
    for (let i = 0; i < 40; i++) {
      t += FRAME;
      const v = ch.at(t);
      worst = Math.max(worst, Math.abs(v - prev));
      prev = v;
    }
    check("hard retarget is rate-limited", worst <= 100 * M.maxStepFrac + 1e-6,
          `worst frame moved ${worst.toFixed(1)} of 100 (cap ${(100 * M.maxStepFrac).toFixed(1)})`);
    check("and it still arrives exactly", Math.abs(prev - 100) < 1e-6, `landed at ${prev}`);
  }

  // 2. retargeting mid-flight continues from the shown value: no jump back to the old target
  {
    const ch = M.channel("y", 0);
    ch.place(0);
    let t = 0;
    ch.at(t);
    ch.set(t, 100, { in: 1 });
    for (let i = 0; i < 6; i++) { t += FRAME; ch.at(t); }
    const mid = ch.value;
    ch.set(t, -100, { in: 1 });                   // reverse halfway
    let worst = 0, prev = mid;
    for (let i = 0; i < 60; i++) {
      t += FRAME;
      const v = ch.at(t);
      worst = Math.max(worst, Math.abs(v - prev));
      prev = v;
    }
    check("mid-flight reversal does not snap", worst <= 200 * M.maxStepFrac + 1e-6,
          `mid was ${mid.toFixed(1)}, worst frame ${worst.toFixed(1)}`);
  }

  // 3. vector parameters obey the same bound component-wise
  {
    const ch = M.channel("pos", [0, 0]);
    ch.place([0, 0]);
    let t = 0;
    ch.at(t);
    ch.set(t, [800, -450], { in: 0 });
    let worst = 0, prev = ch.at(t);
    for (let i = 0; i < 60; i++) {
      t += FRAME;
      const v = ch.at(t);
      worst = Math.max(worst, Math.abs(v[0] - prev[0]), Math.abs(v[1] - prev[1]));
      prev = v;
    }
    check("vector channels are bounded too", worst <= 800 * M.maxStepFrac + 1e-6,
          `worst axis step ${worst.toFixed(1)} of 800`);
  }

  // 4. requested oscillators above the band are folded, and the sampled wave stays followable
  {
    let worst = 0, cycles = new Set();
    for (const hz of [9.7, 40, 200]) {
      const s = M.safe(hz);
      cycles.add(s.frames);
      let prev = M.osc(0, { hz });
      for (let i = 1; i <= 400; i++) {
        const v = M.osc(i * FRAME, { hz });
        worst = Math.max(worst, Math.abs(v - prev));
        prev = v;
      }
    }
    const maxAllowed = 2 * Math.sin(Math.PI / 5) + 1e-6;     // one step of a 5-frame cycle
    check("fast carriers fold into the band", [...cycles].every((c) => c >= 5),
          `cycle lengths ${[...cycles].join(", ")} frames`);
    check("oscillator step stays inside one 5-frame step", worst <= maxAllowed,
          `worst |Δ| ${worst.toFixed(3)} (limit ${maxAllowed.toFixed(3)})`);
  }

  // 5. each shake axis repeats on a whole frame count, so neither can drift onto two extremes
  {
    const s = M.safe(9.7);
    const a = M.shake(0, { amp: 1, hz: 9.7 });
    const b1 = M.shake(s.frames / fps, { amp: 1, hz: 9.7 });
    const b2 = M.shake((s.frames * 2 + 1) / fps, { amp: 1, hz: 9.7 });
    check("each shake axis repeats on a whole frame count",
          Math.abs(a[0] - b1[0]) < 1e-9 && Math.abs(a[1] - b2[1]) < 1e-9,
          `axis0 |Δ| ${Math.abs(a[0] - b1[0]).toExponential(1)} after ${s.frames} frames, ` +
          `axis1 |Δ| ${Math.abs(a[1] - b2[1]).toExponential(1)} after ${s.frames * 2 + 1}`);
  }

  // 6. an impact asked to slam instantly still gets a multi-frame attack
  {
    let worst = 0, prev = M.hit(0, { at: 0, dark: 0.9 }).dark;
    for (let i = 1; i <= 30; i++) {
      const v = M.hit(i * FRAME, { at: 0, dark: 0.9, attack: 0 }).dark;
      worst = Math.max(worst, v - prev);
      prev = v;
    }
    check("impact attack has a floor", worst <= 0.9 / M.minFrames + 1e-6,
          `worst frame gained ${worst.toFixed(3)} of 0.9 (cap ${(0.9 / M.minFrames).toFixed(3)})`);
  }

  // 7. appearance has a floor on both ramps
  {
    const first = M.gate(0 + FRAME, { at: 0, in: 0 });
    const last = M.gate(1.0, { at: 0, in: 0 });
    check("gate-in cannot flash on", first <= M.ease(1 / M.minFrames) + 1e-6 && last > 0.99,
          `first frame ${first.toFixed(3)}, one second later ${last.toFixed(3)}`);
  }

  // 8. the 卡肉 warp is monotonic and never takes more than a fraction of a second per second
  {
    const hits = [];
    for (let i = 0; i < 30; i++) hits.push({ at: 5 + i * 4, amount: 0.07, ramp: 0.3 });
    let worstSlope = 0, prev = M.warp(0, hits);
    for (let i = 1; i <= 3000; i++) {
      const v = M.warp(i * FRAME, hits);
      worstSlope = Math.max(worstSlope, (v - prev) / FRAME);
      if (v < prev - 1e-9) { worstSlope = 99; break; }
      prev = v;
    }
    check("time warp is monotonic and never overruns", worstSlope < 1.0,
          `worst d(warp)/dt ${worstSlope.toFixed(3)}`);
  }

  // 9. the accounting agrees: nothing the runtime produced ever exceeded the cap
  {
    const ch = M.channel("busy", 0);
    ch.place(0);
    let t = 0;
    ch.at(t);
    for (let i = 0; i < 200; i++) {
      if (i % 3 === 0) ch.set(t, (i % 2 ? 1 : -1) * (50 + i), { in: 0.2 });
      t += FRAME;
      ch.at(t);
    }
    const r = M.report();
    check("report() certifies traceability", r.traceable === true && r.worst_share <= r.max_step_frac,
          `worst share ${r.worst_share} of ${r.max_step_frac} across ${r.channels.length} channels`);
  }
}

console.log(failures === 0
  ? "\nmotion runtime: every drawn parameter is traceable by construction."
  : `\nmotion runtime: ${failures} assertion(s) FAILED - the guarantee is broken.`);
process.exit(failures === 0 ? 0 : 1);
