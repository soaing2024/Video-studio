#!/usr/bin/env python3
"""video-studio CLI: render, edit, and verify video from a project spec.

    python vs.py doctor [--install-ffmpeg]
    python vs.py probe <file>...
    python vs.py sprite <image> [--out dir] [--width 64 --height 96 --colors 12]
    python vs.py beats <audio> [--cuts <seconds>]
    python vs.py init <dir> [--name x] [--template short|longform]
    python vs.py render <project.json> [--jobs N] [--force]
    python vs.py assemble <project.json> [--out out.mp4]
    python vs.py verify <project.json> [--video out.mp4] [--samples 5]
    python vs.py preview <project.json> [--segment id] [--at 2.0] [--out frame.png]
    python vs.py run <project.json> [--jobs N] [--skip-verify]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:  # the console codepage on Windows would otherwise mangle CJK JSON output
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib import (  # noqa: E402
    assemble, beats, brief as brief_mod, choreography, imagegen, montage, motion,
    narrate, probe, render, runtime, sprite, spec as specmod, style, tts, verify,
)

SKILL = runtime.SKILL_DIR
EXAMPLES = SKILL / "assets" / "examples"


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _ffmpeg() -> str:
    return runtime.find_ffmpeg()


def load_spec(path, want_narration: bool = True, seed: int | None = None) -> dict:
    """Load a project and resolve the two things that must agree across every command:
    the visual direction (from the style seed) and the narration timing.

    `narrate --script` records the script next to the build output; if the project itself has no
    narration block, that record is reused here so `narrate` then `run` works without editing
    the project file (and without destroying its comments).
    """
    spec = specmod.load(path)
    if seed is not None:
        spec.setdefault("style", {})["seed"] = int(seed)
    cfg = spec.setdefault("narration", {})
    if not cfg.get("lines"):
        manifest = render.build_dir(spec) / "voice" / "narration.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            if data.get("lines"):
                cfg["lines"] = [{"segment": l["segment"], "text": l["text"]}
                                 for l in data["lines"] if l.get("text")]
                cfg.setdefault("voice", data.get("voice"))
    # narration settles the real durations, so it has to run before anything plans against them
    if want_narration and narrate.configured(spec):
        narrate.apply(spec, _ffmpeg(), log=lambda m: print(m, file=sys.stderr))
    style.inject(spec)
    # The beat sheet is compiled before the motion plan so the camera can be keyed to it: one
    # timeline for the actors and the frame, instead of two that drift apart.
    choreography.inject(spec)
    motion.inject(spec)
    return spec


def cmd_doctor(args) -> int:
    report = runtime.doctor(install=args.install_ffmpeg)
    try:
        import numpy, PIL  # noqa: F401
        report["python_deps"] = {"numpy": True, "pillow": True}
    except Exception as e:  # pragma: no cover
        report["ok"] = False
        report["python_deps"] = {"error": str(e), "fix": "pip install numpy pillow"}
    emit(report)
    return 0 if report["ok"] else 1


def cmd_probe(args) -> int:
    ffmpeg = _ffmpeg()
    emit({p: probe.any_file(ffmpeg, p) for p in args.files})
    return 0


def cmd_sprite(args) -> int:
    out = Path(args.out) / (Path(args.image).stem + "-pixel.png") if args.out else \
        Path(args.image).with_name(Path(args.image).stem + "-pixel.png")
    report = sprite.make_sprite(args.image, str(out), width=args.width, height=args.height,
                               colors=args.colors, alpha_cutoff=args.alpha_cutoff)
    emit(report)
    return 0


def cmd_beats(args) -> int:
    ffmpeg = _ffmpeg()
    info = beats.detect(ffmpeg, args.audio, sensitivity=args.sensitivity, min_gap=args.min_gap)
    if args.cuts:
        info["cuts"] = beats.cut_points(info["beats"], args.cuts, min_len=args.min_len)
    emit(info)
    return 0


def cmd_init(args) -> int:
    target = Path(args.dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    names = {"starter": "starter.json", "short": "short.json", "longform": "longform.json"}
    source = EXAMPLES / names[args.template]
    project = target / "project.json"
    if project.exists():
        print(f"refusing to overwrite {project}", file=sys.stderr)
        return 1
    name = args.name or target.name
    text = source.read_text(encoding="utf-8").replace('"name": "example"', f'"name": "{name}"')
    text = text.replace('"name": "starter"', f'"name": "{name}"')
    project.write_text(text, encoding="utf-8")
    (target / "assets").mkdir(exist_ok=True)

    missing = sorted({m for m in re.findall(r'"(assets/[^"]+)"', text)
                      if not (target / m).exists()})
    note = "edit project.json, then run: vs.py run project.json"
    if missing:
        note = (f"add these files under ./assets before rendering: {', '.join(missing)}; " + note)
    emit({"project": str(project), "template": args.template,
          "missing_assets": missing, "note": note})
    return 0


def spec_from(args) -> dict:
    return load_spec(args.project, seed=getattr(args, "seed", None))


def _write_swatch(sig: dict, path: str) -> str:
    from PIL import Image, ImageDraw
    cols = sig["colors"]
    order = [("bg", 90), ("surface", 90), ("border", 60), ("dim", 90), ("text", 90),
             ("accent", 120), ("accent2", 120), ("accent3", 120)]
    im = Image.new("RGB", (980, 260), tuple(int(cols["bg"].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)))
    d = ImageDraw.Draw(im)
    x = 24
    for key, w in order:
        rgb = tuple(int(cols[key].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        d.rectangle([x, 40, x + w - 12, 150], fill=rgb)
        d.text((x, 160), key, fill=tuple(int(cols["dim"].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)))
        x += w
    d.text((24, 14), f"seed {sig['seed']} | {sig['palette_name']} | {sig['pacing']} | {sig['texture']}",
           fill=tuple(int(cols["text"].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)))
    d.text((24, 196), "layouts(k): " + ", ".join(sig["layouts"]["kinetic"]),
           fill=tuple(int(cols["dim"].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)))
    d.text((24, 216), "motions: " + ", ".join(sig["motions"]),
           fill=tuple(int(cols["dim"].lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def cmd_brief(args) -> int:
    """Lay out the whole design before any rendering happens."""
    if args.script:
        raw = Path(args.script).read_text(encoding="utf-8").splitlines()
        lines = [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("#")]
        name = args.name or Path(args.script).stem
        brief = brief_mod.from_script(
            lines, name=name, duration=args.duration, platform=args.platform,
            tone=args.tone or "", audience=args.audience or "",
            want_images=not args.no_images, image_size=args.image_size,
            seed=args.seed, music=args.music, voice=args.voice)
    else:
        brief = brief_mod.skeleton(args.topic or "untitled", beats=args.beats,
                                   duration=args.duration or 60, platform=args.platform,
                                   want_images=not args.no_images, seed=args.seed)
    report = brief_mod.plan_report(brief)
    if args.out:
        report.update(brief_mod.save(brief, args.out))
    else:
        report["brief"] = brief
    report["beats_summary"] = [
        {"id": b["id"], "act": b["act"], "template": b["template"],
         "device": b["visual_device"], "seconds": b["seconds"]} for b in brief["structure"]]
    emit(report)
    return 0 if not [i for i in report["issues"] if i["level"] == "error"] else 1


def cmd_compile(args) -> int:
    """Validate a brief and turn it into a renderable project."""
    brief = brief_mod.load(args.brief)
    issues = brief_mod.validate(brief)
    errors = [i for i in issues if i["level"] == "error"]
    if errors and not args.force:
        emit({"ok": False, "issues": issues,
              "hint": "fix the errors, or pass --force to compile anyway"})
        return 1
    spec = brief_mod.compile_brief(brief, music=args.music,
                                   progress_bar=not args.no_progress)
    out = Path(args.out) if args.out else Path(args.brief).with_name("project.json")
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    emit({"ok": True, "project": str(out), "segments": len(spec["segments"]),
          "narration_lines": len(spec.get("narration", {}).get("lines", [])),
          "images": sum(1 for s in spec["segments"] for v in s["assets"].values()
                        if isinstance(v, dict)),
          "style_seed": spec["style"]["seed"],
          "warnings": [i for i in issues if i["level"] == "warning"]})
    return 0


def cmd_setup(args) -> int:
    """Configure image generation. With no flags it reports the current state."""
    if args.presets:
        emit({k: {kk: vv for kk, vv in v.items() if kk != "api_key"}
              for k, v in imagegen.PRESETS.items()})
        return 0
    if not args.provider or not args.key:
        emit(imagegen.describe())
        return 0
    cfg = imagegen.configure(args.provider, args.key, base_url=args.base_url,
                             model=args.model, size=args.size, path=args.path)
    report = imagegen.describe(cfg)
    if args.test:
        probe_path = Path(args.test)
        report["test"] = imagegen.generate("a simple grey circle on a dark background",
                                          str(probe_path), cfg=cfg)
    emit(report)
    return 0


def cmd_imagegen(args) -> int:
    """Generate one image, or every image a project/brief asks for."""
    if args.from_project:
        spec = spec_from(args)
        if args.dry_run:
            pending = [{"segment": s["id"], "asset": k, "prompt": v["prompt"]}
                       for s in spec.get("segments", [])
                       for k, v in (s.get("assets") or {}).items()
                       if isinstance(v, dict) and v.get("prompt")]
            emit({"dry_run": True, "configured": imagegen.describe(), "pending": pending})
            return 0
        made = imagegen.resolve_assets(spec, log=lambda m: print(m, file=sys.stderr))
        emit({"generated": made, "count": len(made)})
        return 0

    if not args.prompt or not args.out:
        print("error: give a prompt and --out, or use --from-project", file=sys.stderr)
        return 2
    emit(imagegen.generate(args.prompt, args.out, size=args.size, n=args.n,
                          negative=args.negative, dry_run=args.dry_run))
    return 0


def cmd_style(args) -> int:
    sig = style.make_signature(args.seed, topic=args.topic)
    out = {"signature": sig}
    if args.swatch:
        out["swatch"] = _write_swatch(sig, args.swatch)
    if args.like:
        out["similarity_to_like"] = style.similarity(sig, style.make_signature(args.like))
    if args.history:
        past = style.load_history()
        out["closest_past"] = sorted(
            ({"name": e.get("name"), "similarity": style.similarity(sig, e.get("signature") or {})}
             for e in past), key=lambda r: -r["similarity"])[:3]
    emit(out)
    return 0


def cmd_render(args) -> int:
    spec = spec_from(args)
    ffmpeg, node = _ffmpeg(), runtime.find_node()
    results = render.render_all(spec, ffmpeg, node, jobs=args.jobs, force=args.force)
    emit({"segments": results, "build_dir": str(render.build_dir(spec))})
    return 0


def cmd_assemble(args) -> int:
    spec = spec_from(args)
    emit(assemble.assemble(spec, _ffmpeg(), out_path=args.out))
    return 0


def cmd_verify(args) -> int:
    spec = spec_from(args)
    report = verify.verify(spec, _ffmpeg(), video=args.video, samples=args.samples)
    emit(report)
    return 0 if report["ok"] else 1


def cmd_preview(args) -> int:
    spec = spec_from(args)
    seg = specmod.segment_map(spec).get(args.segment) if args.segment else spec["segments"][0]
    if not seg:
        print(f"unknown segment {args.segment}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else render.build_dir(spec) / "preview" / f"{seg['id']}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = render.prepare_assets(spec, seg)
    data_file = out.with_suffix(".json")
    data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    w, h, _ = render.work_size(spec)
    cmd = [runtime.find_node(), str(HERE / "render_segment.mjs"),
           "--scene", str(render.template_path(seg["template"])), "--out", str(out.with_suffix(".mp4")),
           "--data", str(data_file), "--fps", str(spec["video"]["fps"]),
           "--duration", str(seg["duration"]), "--width", str(w), "--height", str(h),
           "--still", str(args.at), "--still-out", str(out)]
    import subprocess
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=render.runtime_env())
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr, file=sys.stderr)
        return 1
    emit({"still": str(out), "segment": seg["id"], "at": args.at, "size": [w, h]})
    return 0


def cmd_run(args) -> int:
    spec = spec_from(args)
    ffmpeg, node = _ffmpeg(), runtime.find_node()
    log = (lambda m: print(m, file=sys.stderr)) if args.quiet else (lambda m: print(m, file=sys.stderr))
    print(f"[1/3] render {len(render.pending(spec))} segment(s)", file=sys.stderr)
    render.render_all(spec, ffmpeg, node, jobs=args.jobs, force=args.force, log=log)
    print("[2/3] assemble", file=sys.stderr)
    result = assemble.assemble(spec, ffmpeg, log=log)
    summary = {"output": result["output"], "duration": result["duration"]}
    if not args.skip_verify:
        print("[3/3] verify", file=sys.stderr)
        report = verify.verify(spec, ffmpeg, video=result["output"], samples=args.samples)
        summary["verify"] = report
        summary["ok"] = report["ok"]
    else:
        summary["ok"] = True
    emit(summary)
    return 0 if summary["ok"] else 1


def cmd_voices(args) -> int:
    emit({"engine": "sapi" if tts.available() else "unavailable",
          "voices": tts.list_voices()})
    return 0


def cmd_narrate(args) -> int:
    spec = specmod.load(args.project)
    cfg = spec.setdefault("narration", {})
    if args.voice:
        cfg["voice"] = args.voice
    if args.rate is not None:
        cfg["rate"] = args.rate
    if args.script:
        raw = Path(args.script).read_text(encoding="utf-8").splitlines()
        lines = [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("#")]
        order = []
        for item in spec["timeline"]:
            sid = item.get("segment")
            if sid and sid not in order:
                order.append(sid)
        if len(lines) != len(order):
            print("error: script has " + str(len(lines)) + " lines but the timeline has "
                  + str(len(order)) + " segments (" + ", ".join(order) + ")", file=sys.stderr)
            return 2
        cfg["lines"] = [{"segment": s, "text": t} for s, t in zip(order, lines)]
    if not cfg.get("lines"):
        print("error: nothing to narrate; add narration.lines or pass --script", file=sys.stderr)
        return 2
    report = narrate.apply(spec, _ffmpeg(), force=args.force,
                           log=lambda m: print(m, file=sys.stderr))
    emit(report)
    return 0


def cmd_montage(args) -> int:
    report = montage.build(_ffmpeg(), args.folder, args.music, args.out,
                           duration=args.duration, style=args.style, title=args.title,
                           width=args.width, height=args.height, fps=args.fps)
    emit(report)
    return 0


def cmd_plan(args) -> int:
    spec = spec_from(args)
    issues = specmod.validate(spec)
    w, h, scale = render.work_size(spec)
    fps = spec["video"]["fps"]
    ms_per_frame = 63 + 0.000127 * (w * h)   # fitted from measurements in pipeline.md
    frames = animated = still = cached = 0
    rows = []
    for seg in render.pending(spec):
        f = int(round(float(seg["duration"]) * fps))
        is_still = bool((seg.get("data") or {}).get("still"))
        hit = False
        try:
            path = render.segment_path(spec, seg["id"])
            key = path.with_suffix(".key")
            hit = bool(path.is_file() and key.is_file()
                       and key.read_text().strip() == render.cache_key(spec, seg))
        except OSError:
            hit = False
        cached += int(hit)
        if is_still:
            still += 1
        else:
            animated += 1
            frames += f
        rows.append({"segment": seg["id"], "template": seg["template"],
                     "seconds": seg["duration"], "frames": 0 if is_still else f,
                     "still": is_still, "cached": hit})
    jobs = max(1, min(int(spec["render"].get("jobs", 2)), os.cpu_count() or 4))
    seconds = frames * ms_per_frame / 1000 / jobs * 1.15
    errors = [i for i in issues if i["level"] == "error"]
    emit({
        "name": spec["name"],
        "duration": specmod.planned_duration(spec),
        "work_size": [w, h], "upscale": scale,
        "segments": rows,
        "animated": animated, "still": still, "cached": cached,
        "frames_to_render": frames,
        "estimated_render": {"jobs": jobs, "seconds": round(seconds, 1),
                             "minutes": round(seconds / 60, 1)},
        "output": str(Path(spec["base_dir"]) / (spec["name"] + ".mp4")),
        "style": style.report(spec),
        "choreography": choreography.report(spec),
        "issues": issues,
        "ok": not errors,
    })
    return 0 if not errors else 1


SELFTEST_PROJECT = {
    "name": "selftest",
    "video": {"width": 640, "height": 360, "fps": 24, "crf": 24, "preset": "veryfast"},
    "render": {"jobs": 2, "crf": 16},
    "look": {"accent": "#e0455f", "pixelate": {"scale": 2, "colors": 16},
             "fade_in": 0.3, "fade_out": 0.3, "progress_bar": {"height": 2}},
    "segments": [
        {"id": "a", "template": "kinetic", "duration": 2.0,
         "data": {"eyebrow": "SELFTEST", "title": "render ok",
                  "rows": [{"label": "A", "value": "one", "weight": 1.0}]}},
        {"id": "b", "template": "caption", "duration": 2.0,
         "data": {"still": True, "title": "hold ok", "caption": "still segment"}}
    ],
    "timeline": [{"segment": "a"},
                 {"segment": "b", "transition": {"type": "fade", "duration": 0.4}}],
}


def cmd_selftest(args) -> int:
    """Run a tiny project end to end - the regression check for this skill."""
    tmp = Path(tempfile.mkdtemp(prefix="vs-selftest-"))
    note = lambda m: print(m, file=sys.stderr)
    try:
        ffmpeg, node = _ffmpeg(), runtime.find_node()
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=220:duration=8", "-af", "volume=0.25",
                        str(tmp / "bed.wav")], check=True)
        spec_dict = json.loads(json.dumps(SELFTEST_PROJECT))
        spec_dict["audio"] = {"tracks": [{"src": "bed.wav", "gain_db": -6, "loop": True,
                                        "fade_in": 0.3, "fade_out": 0.3}]}
        project = tmp / "project.json"
        project.write_text(json.dumps(spec_dict, indent=2), encoding="utf-8")
        spec = specmod.load(str(project))
        render.render_all(spec, ffmpeg, node, jobs=int(args.jobs or 2), force=True, log=note)
        result = assemble.assemble(spec, ffmpeg, log=note)
        report = verify.verify(spec, ffmpeg, video=result["output"], samples=3)
        emit({"ok": report["ok"], "video": result["output"],
              "duration": result["duration"], "verify": report})
        return 0 if report["ok"] else 1
    finally:
        if args.keep:
            print("kept " + str(tmp), file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vs.py", description="code-driven video studio")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="check node / playwright / chromium / ffmpeg / python deps")
    d.add_argument("--install-ffmpeg", action="store_true", help="vendor ffmpeg via pip if missing")
    d.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("probe", help="inspect images / audio / video")
    pr.add_argument("files", nargs="+")
    pr.set_defaults(func=cmd_probe)

    sp = sub.add_parser("sprite", help="convert an image into a pixel-art sprite")
    sp.add_argument("image")
    sp.add_argument("--out")
    sp.add_argument("--width", type=int, default=64)
    sp.add_argument("--height", type=int, default=96)
    sp.add_argument("--colors", type=int, default=12)
    sp.add_argument("--alpha-cutoff", type=int, default=115)
    sp.set_defaults(func=cmd_sprite)

    bt = sub.add_parser("beats", help="detect beats/onsets and optional cut points")
    bt.add_argument("audio")
    bt.add_argument("--sensitivity", type=float, default=1.5)
    bt.add_argument("--min-gap", type=float, default=0.3)
    bt.add_argument("--cuts", type=float, help="target length: emit cut points for it")
    bt.add_argument("--min-len", type=float, default=1.2)
    bt.set_defaults(func=cmd_beats)

    ini = sub.add_parser("init", help="scaffold a project directory")
    ini.add_argument("dir", nargs="?", default=".")
    ini.add_argument("--name")
    ini.add_argument("--template", choices=["starter", "short", "longform"], default="starter")
    ini.set_defaults(func=cmd_init)

    r = sub.add_parser("render", help="render segments to cached intermediate clips")
    r.add_argument("project")
    r.add_argument("--jobs", type=int)
    r.add_argument("--force", action="store_true")
    r.add_argument("--seed", type=int, help="override the style seed for this render")
    r.set_defaults(func=cmd_render)

    a = sub.add_parser("assemble", help="cut, transition, mix and encode into the final file")
    a.add_argument("project")
    a.add_argument("--out")
    a.set_defaults(func=cmd_assemble)

    v = sub.add_parser("verify", help="measure the result instead of eyeballing it")
    v.add_argument("project")
    v.add_argument("--video")
    v.add_argument("--samples", type=int, default=5)
    v.set_defaults(func=cmd_verify)

    pv = sub.add_parser("preview", help="render a single still frame for fast iteration")
    pv.add_argument("project")
    pv.add_argument("--segment")
    pv.add_argument("--at", type=float, default=2.0)
    pv.add_argument("--seed", type=int, help="override the style seed")
    pv.add_argument("--out")
    pv.set_defaults(func=cmd_preview)

    run = sub.add_parser("run", help="render + assemble + verify")
    run.add_argument("project")
    run.add_argument("--jobs", type=int)
    run.add_argument("--force", action="store_true")
    run.add_argument("--skip-verify", action="store_true")
    run.add_argument("--samples", type=int, default=5)
    run.add_argument("--quiet", action="store_true")
    run.add_argument("--seed", type=int, help="override the style seed")
    run.set_defaults(func=cmd_run)

    st = sub.add_parser("style", help="sample or inspect a visual direction")
    st.add_argument("--seed", type=int)
    st.add_argument("--topic", help="derive the seed from this text")
    st.add_argument("--swatch", help="write a palette swatch PNG here")
    st.add_argument("--like", type=int, help="similarity against another seed")
    st.add_argument("--history", action="store_true", help="compare against past projects")
    st.set_defaults(func=cmd_style)

    su = sub.add_parser("setup", help="configure image generation (any OpenAI-compatible API)")
    su.add_argument("--provider", help="preset name, or custom")
    su.add_argument("--key", help="API key (stored outside the repo)")
    su.add_argument("--base-url")
    su.add_argument("--model")
    su.add_argument("--size")
    su.add_argument("--path", help="endpoint path, default /images/generations")
    su.add_argument("--presets", action="store_true", help="list known provider presets")
    su.add_argument("--test", help="generate one image here to verify the key works")
    su.set_defaults(func=cmd_setup)

    bf = sub.add_parser("brief", help="plan the whole video before rendering anything")
    bf.add_argument("--script", help="narration script, one line per beat")
    bf.add_argument("--topic", help="plan a skeleton for this topic instead")
    bf.add_argument("--out", help="write brief.json (and a readable .md) here")
    bf.add_argument("--name")
    bf.add_argument("--beats", type=int, default=6, help="skeleton beat count")
    bf.add_argument("--duration", type=float, help="target seconds")
    bf.add_argument("--platform", default="youtube", choices=sorted(brief_mod.PLATFORMS))
    bf.add_argument("--tone")
    bf.add_argument("--audience")
    bf.add_argument("--seed", type=int, help="fix the visual direction")
    bf.add_argument("--music")
    bf.add_argument("--voice")
    bf.add_argument("--image-size", default="1536x1024")
    bf.add_argument("--no-images", action="store_true", help="plan without generated images")
    bf.set_defaults(func=cmd_brief)

    cp = sub.add_parser("compile", help="validate a brief and emit project.json")
    cp.add_argument("brief")
    cp.add_argument("--out")
    cp.add_argument("--music")
    cp.add_argument("--no-progress", action="store_true")
    cp.add_argument("--force", action="store_true", help="compile despite errors")
    cp.set_defaults(func=cmd_compile)

    ig = sub.add_parser("imagegen", help="generate images with the configured provider")
    ig.add_argument("prompt", nargs="?")
    ig.add_argument("--out")
    ig.add_argument("--size")
    ig.add_argument("--n", type=int, default=1)
    ig.add_argument("--negative", help="negative prompt, when the provider supports it")
    ig.add_argument("--from-project", help="generate every prompt-backed asset in a project")
    ig.add_argument("--seed", type=int)
    ig.add_argument("--dry-run", action="store_true", help="print the request without sending it")
    ig.set_defaults(func=cmd_imagegen)

    vo = sub.add_parser("voices", help="list installed speech voices (for narration)")
    vo.set_defaults(func=cmd_voices)

    na = sub.add_parser("narrate", help="synthesize narration and time the visuals to it")
    na.add_argument("project")
    na.add_argument("--script", help="text file, one narration line per segment")
    na.add_argument("--voice", help="voice name from `vs.py voices`")
    na.add_argument("--rate", type=int, help="speaking rate -10..10")
    na.add_argument("--force", action="store_true")
    na.set_defaults(func=cmd_narrate)

    mo = sub.add_parser("montage", help="build a beat-cut montage project from a media folder")
    mo.add_argument("folder")
    mo.add_argument("--music", required=True)
    mo.add_argument("--out", required=True, help="project.json to write")
    mo.add_argument("--duration", type=float, help="target length in seconds")
    mo.add_argument("--style", choices=["energy", "calm", "punch"], default="energy")
    mo.add_argument("--title", help="add rendered title cards at both ends")
    mo.add_argument("--width", type=int, default=1920)
    mo.add_argument("--height", type=int, default=1080)
    mo.add_argument("--fps", type=int, default=30)
    mo.set_defaults(func=cmd_montage)

    pl = sub.add_parser("plan", help="dry run: problems, cache hits, estimated render time")
    pl.add_argument("project")
    pl.add_argument("--seed", type=int, help="override the style seed")
    pl.set_defaults(func=cmd_plan)

    st = sub.add_parser("selftest", help="run a tiny project end to end")
    st.add_argument("--jobs", type=int)
    st.add_argument("--keep", action="store_true")
    st.set_defaults(func=cmd_selftest)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (runtime.ToolError, specmod.SpecError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # keep the CLI honest instead of dumping a traceback
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
