#!/usr/bin/env python3
"""video-studio CLI: render, edit, and verify video from a project spec.

    python vs.py doctor [--install-ffmpeg]
    python vs.py probe <file>...
    python vs.py libs [--install <name>...]
    python vs.py sprite <image> [--out dir] [--width 64 --height 96 --colors 12]
    python vs.py beats <audio> [--cuts <seconds>]
    python vs.py sfx "<query>" [--get ID] [--out assets/sfx]
    python vs.py init <dir> [--name x] [--duration 20]
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
    analyze,
    fmt,
    assemble, beats, brief as brief_mod, choreography, imagegen, libs, montage, motion,
    finish, narrate, probe, rehearse, render, runtime, sfx as sfxmod, sprite, spec as specmod,
    style, tts, verify,
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
    motion.inject(spec)
    choreography.inject(spec)
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


def cmd_libs(args) -> int:
    """What a scene may use: vendored browser libraries, and how to add one."""
    if args.install:
        try:
            libs.install(args.install, log=lambda m: print(m, file=sys.stderr))
        except libs.LibError as e:
            emit({"ok": False, "error": str(e)})
            return 1
    emit(libs.describe())
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


CREDITS_STUB = """# 素材与授权

每个外部素材一行：文件名 / 来源页 / 作者 / 授权 / 是否需署名。
取用规则见技能的 references/libraries.md。
"""


def cmd_sfx(args) -> int:
    """Search Freesound or fetch one effect; the licence gate decides what may be automated."""
    rep = sfxmod.run(query=args.query, get=args.get, token=args.token,
                     access_token=args.access_token, test=args.test, mode=args.licence,
                     top=args.top, sort=args.sort, min_dur=args.min_dur, max_dur=args.max_dur,
                     out=args.out, name=args.name, quality=args.quality, kind=args.kind,
                     credits=args.credits, allow_risky=args.allow_risky, dry_run=args.dry_run)
    fmt.emit(rep, human=sfxmod.human(rep))
    return 0 if rep.get("ok") else 1


def cmd_init(args) -> int:
    """Scaffold a single-take project: one spec, one scene to write.

    One take, no cuts: there is nothing to assemble, so the whole job is composing the shot
    (references/choreography.md). The scene shipped as the starting file is plumbing - a `seek(t)`
    body with nothing designed in it.
    """
    target = Path(args.dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    project = target / "project.json"
    if project.exists():
        print(f"refusing to overwrite {project}", file=sys.stderr)
        return 1

    name = args.name or target.name
    scene = target / "scenes" / "take.html"
    scene.parent.mkdir(parents=True, exist_ok=True)
    scene.write_text(render.BLANK_SCENE.read_text(encoding="utf-8"), encoding="utf-8")

    spec = {
        "name": name,
        "video": {"width": 1920, "height": 1080, "fps": 30, "crf": 20, "preset": "medium"},
        "render": {"jobs": 3, "crf": 12},
        "duration": float(args.duration),
        "scene": "scenes/take.html",
        "hold": [],
        "look": {"fade_in": 0.5, "fade_out": 0.8, "progress_bar": {"height": 4}},
        "data": {"title": "第一镜", "caption": ""},
    }
    project.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / "assets").mkdir(exist_ok=True)
    credits = target / "assets" / "CREDITS.md"
    if not credits.exists():
        credits.write_text(CREDITS_STUB, encoding="utf-8")
    emit({"project": str(project), "scene": "scenes/take.html",
          "note": "one take, no cuts - write the shot, then preview / plan / run"})
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
    d.text((24, 196), "compositions: " + ", ".join(sig["compositions"]),
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
    report["timeline_summary"] = [
        {"index": c.get("index"), "at": c.get("at"), "seconds": c.get("seconds"),
         "device": c.get("device"), "on_screen": c.get("on_screen")}
        for c in (brief.get("take") or {}).get("timeline", [])]
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
    emit({"ok": True, "project": str(out), "duration": spec["duration"],
          "scene_to_write": spec["scene"], "hold": spec.get("hold") or [],
          "narration_lines": len(spec.get("narration", {}).get("lines", [])),
          "chapters": len(spec.get("data", {}).get("timeline", [])),
          "hold_seconds": round(sum(b - a for a, b in (spec.get("hold") or [])), 2),
          "note": "write the scene, then: vs.py preview / plan / run",
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
    results = render.render_all(spec, ffmpeg, node, jobs=args.jobs, force=args.force,
                                slices=getattr(args, "slices", None),
                                incremental=getattr(args, "incremental", None), log=fmt.note)
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
           "--scene", str(render.scene_path(seg)), "--out", str(out.with_suffix(".mp4")),
           "--data", str(data_file), "--fps", str(spec["video"]["fps"]),
           "--duration", str(seg["duration"]), "--width", str(w), "--height", str(h),
           "--still", str(args.at), "--still-out", str(out)] + render.runtime_args(spec, seg)
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
    render.render_all(spec, ffmpeg, node, jobs=args.jobs, force=args.force, log=log,
                       slices=getattr(args, "slices", None),
                       incremental=getattr(args, "incremental", None))
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
        # A take can declare still stretches; those frames are reused, so they are not render cost.
        held = sum(max(0.0, float(b) - float(a)) for a, b in (seg.get("hold") or []))
        held_frames = int(round(held * fps))
        if is_still:
            still += 1
        else:
            animated += 1
            frames += max(0, f - held_frames)
        rows.append({"segment": seg["id"], "scene": Path(seg["scene"]).name,
                     "seconds": seg["duration"], "frames": 0 if is_still else f - held_frames,
                     "hold": round(held, 2), "still": is_still, "cached": hit})
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
             "fade_in": 0.3, "fade_out": 0.6, "progress_bar": {"height": 2}},
    # One take: a single scene for the whole runtime, with a held stretch in the middle. That hold
    # exercises the only cost lever a single take still has - the renderer reuses one frame instead
    # of screenshotting 1.4s of identical picture.
    "duration": 3.6,
    "scene": "scenes/take.html",
    "hold": [[2.0, 3.2]],
    "data": {"title": "render ok", "caption": "one take, no cuts"},
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
        # The selftest uses the shipped blank scene: it is the only one the skill ships, and it
        # is exactly the file an author starts from.
        (tmp / "scenes").mkdir(exist_ok=True)
        (tmp / "scenes" / "take.html").write_text(
            render.BLANK_SCENE.read_text(encoding="utf-8"), encoding="utf-8")
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

    lb = sub.add_parser("libs", help="list or vendor the browser libraries a scene may use")
    lb.add_argument("--install", nargs="+", metavar="NAME",
                    help="vendor these libraries from npm (build-time only; renders stay offline)")
    lb.set_defaults(func=cmd_libs)

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

    sf = sub.add_parser("sfx", help="search or fetch a Freesound effect (licence-gated)")
    sf.add_argument("query", nargs="?", help="search text, e.g. 'whoosh transition'")
    sf.add_argument("--get", metavar="ID|URL", help="fetch this sound instead of searching")
    sf.add_argument("--token", help="store a Freesound API key outside the repo")
    sf.add_argument("--access-token", dest="access_token",
                    help="store an OAuth2 token for original-quality downloads")
    sf.add_argument("--test", action="store_true", help="one-result search to verify the key")
    sf.add_argument("--licence", "--license", dest="licence", choices=("cc0", "by", "all"),
                    default="cc0",
                    help="cc0 (default) | by (adds an attribution row) | all (flagged)")
    sf.add_argument("--top", type=int, default=12, help="results to show")
    sf.add_argument("--sort", default="score", choices=sfxmod.SORTS)
    sf.add_argument("--min-dur", type=float)
    sf.add_argument("--max-dur", type=float)
    sf.add_argument("--out", default="assets/sfx", help="where the fetched file lands")
    sf.add_argument("--name", help="file slug for the fetched sound")
    sf.add_argument("--quality", choices=("preview", "original"), default="preview",
                    help="preview = HQ mp3, no OAuth2; original needs an access token")
    sf.add_argument("--kind", choices=("wav", "source"), default="wav",
                    help="convert to 48 kHz wav, or keep the source file")
    sf.add_argument("--credits", help="CREDITS.md to append to (default: <out>/../CREDITS.md)")
    sf.add_argument("--allow-risky", action="store_true",
                    help="accept BY-SA / NC / Sampling+ (not a commercial deliverable)")
    sf.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    sf.set_defaults(func=cmd_sfx)

    ini = sub.add_parser("init", help="scaffold a project directory")
    ini.add_argument("dir", nargs="?", default=".")
    ini.add_argument("--name")
    ini.add_argument("--duration", type=float, default=20.0, help="take length in seconds")
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


def _cmd_preview_dispatch(args) -> int:
    """--report turns a still into a judgement: numbers, not an image to look at."""
    if not getattr(args, "report", False):
        return _cmd_preview_orig(args)
    spec = spec_from(args)
    ffmpeg, node = runtime.find_ffmpeg(), runtime.find_node()
    seg = specmod.segment_map(spec).get(args.segment) if args.segment else spec["segments"][0]
    times = [float(x) for x in str(args.at or "0").split(",") if x.strip()]
    out_dir = render.build_dir(spec) / "preview"
    rows = render.probe_frames(spec, seg, ffmpeg, node, times, out_dir,
                               w=int(getattr(args, "width", 0) or 0) or None,
                               h=int(getattr(args, "height", 0) or 0) or None)
    rep = analyze.merge(rows, ascii_cols=int(getattr(args, "ascii", 96) or 96))
    rep["which"] = "preview"
    (out_dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    fmt.emit(rep, human=analyze.human(rep, ascii_for=times[0] if getattr(args, "ascii_map", False) else None)
             + f"\nreport: {out_dir / 'report.json'}")
    return 0 if rep["ok"] else 1


def _cmd_plan_v2(args) -> int:
    """Budget before render: estimated wall clock, memory-safe concurrency, fallbacks."""
    spec = spec_from(args)
    issues = specmod.validate(spec)
    w, h, _ = render.work_size(spec)
    frames = int(round(float(spec["duration"]) * spec["video"]["fps"]))
    shutter = render.shutter_samples(spec)
    frames = int(round(float(spec["duration"]) * spec["video"]["fps"])) * shutter
    slices = int(getattr(args, "slices", 1) or 1)
    jobs = render.safe_jobs(w, h, int(getattr(args, "jobs", 0) or spec["render"].get("jobs", 2)),
                            log=fmt.note)
    per = render.frame_cost_ms(spec, w, h)
    gb = render.free_gb()
    cached = 0
    for seg in render.pending(spec):
        key = seg and Path(str(render.segment_path(spec, seg["id"]))).with_suffix(".key")
        if key.is_file():
            cached += 1
    wall = frames * per / 1000 / max(1, min(jobs, slices))
    advice = []
    if per > 60 and render.png_kind(spec) == "png":
        advice.append("use the default fast PNG (drop --png-compression default): -75% per frame")
    if slices <= 1 and shutter == 1 and specmod.planned_duration(spec) > 3:
        advice.append(f"add --slices {min(8, max(2, jobs * 2))} --jobs {jobs}: "
                      f"a single take renders in one process otherwise")
    if shutter > 1:
        advice.append(f"shutter x{shutter}: {frames} frames to render, slices forced to 1")
    if gb is not None and gb < 4 and jobs > 2:
        advice.append(f"shutter x{shutter}: {frames} frames to render, slices forced to 1")
        advice.append(f"only {gb:.1f} GB free: keep --jobs <= 2, x264 buffers ~12 MB/frame at 4K")
    out = {"ok": not [i for i in issues if i["level"] == "error"], "which": "plan",
           "frames": frames, "size": [w, h], "png_kind": render.png_kind(spec),
           "shutter_samples": shutter,
           "finish": finish.describe(finish.resolve(spec.get("look") or {},
                                      pixelate=bool((spec.get("look") or {}).get("pixelate")))),
           "audio_tracks": len((spec.get("audio") or {}).get("tracks") or []),
           "audio_cues": len((spec.get("audio") or {}).get("cues") or []),
           "master": (spec.get("audio") or {}).get("master"),
           "ms_per_frame": round(per), "slices": slices, "jobs": jobs, "free_gb": gb,
           "est_wall_min": round(wall / 60, 1), "cached_segments": cached,
           "issues": issues, "advice": advice}
    fmt.emit(out, human=f"plan: {frames} frames @ {w}x{h} ({render.png_kind(spec)}, "
                        f"{round(per)} ms/frame) -> ~{out['est_wall_min']} min "
                        f"with {jobs} job(s) x {slices} slice(s)"
                        + (f"; {len(advice)} suggestion(s)" if advice else ""))
    if advice and not fmt.is_json():
        for a in advice:
            print("  -> " + a)
    return 0 if out["ok"] else 2


def _inject_common(parser):
    """--json/--verbose everywhere, plus the new subcommands, without touching build_parser."""
    import argparse as _ap
    subs = [a for a in parser._actions if isinstance(a, _ap._SubParsersAction)]
    if not subs:
        return
    choices = subs[0].choices
    for name, sp in choices.items():
        for flag, kw in (("--json", dict(action="store_true", help="one compact JSON object")),
                         ("--verbose", dict(action="store_true", help="full logs")),
                         ("--quiet", dict(action="store_true", help="errors only")),
                         ("--limit", dict(type=int, default=20, help="truncation lines (head/tail)"))):
            if not any(flag in a.option_strings for a in sp._actions):
                sp.add_argument(flag, **kw)
    for name in ("render", "run", "plan"):
        if name not in choices:
            continue
        sp = choices[name]
        for flag, fkw in (("--slices", dict(type=int, default=1,
                                            help="split ONE take into N parallel time slices (same single export)")),
                          ("--jobs", dict(type=int, default=0, help="parallel workers")),
                          ("--preset", dict(default=None,
                                            help="x264 preset for intermediates (default ultrafast)")),
                          ("--jpeg", dict(type=int, default=None,
                                          help="lossy intermediate frames, preflight only")),
                          ("--reboot", dict(type=int, default=0,
                                            help="restart the browser every N frames")),
                          ("--incremental", dict(action="store_true",
                                                  help="re-render only the frames whose state changed")),
                          ("--no-gpu", dict(dest="no_gpu", action="store_true",
                                            help="do not ask Chromium for GPU rasterisation"))):
            if not any(flag in a.option_strings for a in sp._actions):
                sp.add_argument(flag, **fkw)
    if "plan" in choices:
        choices["plan"].set_defaults(func=_cmd_plan_v2)
    if "preview" in choices:
        pv = choices["preview"]
        pv.add_argument("--report", action="store_true", help="numbers instead of an image")
        for act in pv._actions:            # the existing --at is a float: accept a list instead
            if "--at" in act.option_strings:
                act.type = str
                act.help = "comma-separated seconds, e.g. 2.75,7.9,24.7"
        pv.add_argument("--ascii", type=int, default=96, help="ASCII map columns (0 disables)")
        pv.add_argument("--ascii-map", action="store_true", help="print the map in human output")
        globals()["_cmd_preview_orig"] = pv.get_default("func")
        pv.set_defaults(func=_cmd_preview_dispatch)

    def _add(name, help_, func, **kw):
        if name in choices:
            return
        sp = subs[0].add_parser(name, help=help_)
        for flag, fkw in (("--json", dict(action="store_true")), ("--verbose", dict(action="store_true")),
                          ("--quiet", dict(action="store_true")), ("--limit", dict(type=int, default=20))):
            sp.add_argument(flag, **fkw)
        for a, fkw in kw.items():
            sp.add_argument(a, **fkw)
        sp.set_defaults(func=func)

    def cmd_check(args):
        import subprocess as _sp
        cmd = [sys.executable, str(HERE / "scene_check.py"), args.project, "--json" if fmt.is_json() else ""]
        cmd += ["--stride", str(args.stride)]
        r = _sp.run([c for c in cmd if c], capture_output=True, text=True, encoding="utf-8",
                    errors="replace")
        sys.stdout.write(r.stdout)
        if r.returncode not in (0, 1):
            return fmt.report_error(fmt.fail("CHECK_FAILED", args.project, "scene_check runs",
                                            r.stderr.strip()[-200:],
                                            "python scripts/scene_check.py " + args.project))
        return r.returncode

    def cmd_patch(args):
        import subprocess as _sp
        cmd = [sys.executable, str(HERE / "apply_patch.py"), args.edits]
        if args.json:
            cmd.append("--json")
        r = _sp.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode

    def cmd_audio(args):
        from lib import audio as _audio
        if args.check:
            return _audio.main(["--check", args.check] + (["--json"] if fmt.is_json() else []))
        src = args.cues or args.project
        cues = (str(Path(src) / "cues.json") if src and Path(src).is_dir() else src)
        return _audio.main([cues or "-", "--out", args.out or "audio/mix.wav",
                            "--duration", str(args.duration)] + (["--json"] if fmt.is_json() else []))

    def cmd_card(args):
        from lib import deliver as _deliver
        res = _deliver.closing_card(Path(args.out), title=args.title, cn=args.cn,
                                    accent=args.accent or "#1f6bff")
        fmt.emit(res, human=f"card project -> {res['project']}")
        return 0

    def cmd_api(args):
        idx = json.loads((HERE.parent / "api_index.json").read_text(encoding="utf-8"))             if (HERE.parent / "api_index.json").is_file() else None
        if idx is None:
            return fmt.report_error(fmt.fail("NO_INDEX", "api_index.json", "generated index",
                                             "missing",
                                             "run: python scripts/api_index.py"))
        task = args.task
        if task:
            hit = next((c for c in idx["commands"] if c["name"] == task), None)
            fmt.emit({"ok": bool(hit), "which": "api", "command": hit},
                     human=json.dumps(hit, ensure_ascii=False, indent=1)[:1500] if hit else f"no such command: {task}")
            return 0 if hit else 2
        fmt.emit({"ok": True, "which": "api", "commands": [c["name"] for c in idx["commands"]],
                  "index": str(HERE.parent / "api_index.json")},
                 human=" ".join(c["name"] for c in idx["commands"]))
        return 0

    def cmd_cat(args):
        text = fmt.read_cached(args.file, Path(args.cache_dir) if args.cache_dir else None)
        rng = args.lines
        if rng:
            a, b = (rng.split(":") + [""])[:2]
            lo = int(a or 1)
            hi = int(b) if b else lo + 60
            text = "\n".join(f"{i + 1:>5}| {l}" for i, l in enumerate(text.splitlines()[lo - 1:hi], lo - 1))
        fmt.emit({"ok": True, "which": "cat", "file": args.file,
                  "bytes": len(text.encode()), "lines": text.count("\n") + 1},
                 human=text if not fmt.is_json() else text)
        return 0

    def cmd_diff(args):
        fmt.emit({"ok": True, "which": "diff", **fmt.diff_lines(args.file)},
                 human=json.dumps(fmt.diff_lines(args.file), ensure_ascii=False)[:1200])
        return 0

    # (registered below, after the rehearsal commands)
    def cmd_rehearse(args):
        """A draft you can watch: 35% of the pixels, 12 fps, JPEG, no delivery clip touched."""
        spec = spec_from(args)
        ffmpeg, node = runtime.find_ffmpeg(), runtime.find_node()
        rep = rehearse.draft(spec, ffmpeg, node, at=args.at, scale=args.scale,
                             fps=args.fps, jpeg=args.jpeg,
                             sheet=not getattr(args, "no_sheet", False), log=fmt.note)
        fmt.emit(rep, human=rehearse.summary_line(rep) +
                 "\n  (draft only: no delivery clip, cache key or output file was touched)")
        return 0

    _add("rehearse", "cheap draft render: watch timing before the delivery render", cmd_rehearse,
         **{"project": {},
            "--at": dict(default=None, help="a:b seconds to rehearse; default the whole shot"),
            "--scale": dict(type=float, default=0.35, help="capture scale (0.35 = 35%% pixels)"),
            "--fps": dict(type=int, default=12, help="draft frame rate"),
            "--jpeg": dict(type=int, default=85, help="draft JPEG quality"),
            "--no-sheet": dict(action="store_true", help="skip the contact sheet")})

    def cmd_scrub(args):
        """An interactive page that drives the real scene: the cheapest rehearsal there is."""
        spec = spec_from(args)
        rep = rehearse.scrub_html(spec, out=args.out, log=fmt.note)
        if getattr(args, "open", False):
            import webbrowser
            webbrowser.open(rep["html"])
        fmt.emit(rep, human=f"scrub page -> {rep['html']}\n  {rep['hint']}")
        return 0

    _add("scrub", "interactive scrub page: no render, real scene, real timing", cmd_scrub,
         **{"project": {},
            "--out": dict(default=None, help="where to write the page (default build/<name>/scrub.html)"),
            "--open": dict(action="store_true", help="open it in the default browser")})
    _add("check", "pre-render self-check: timeline scan + typography calibration", cmd_check,
         **{"project": {}, "--stride": dict(type=float, default=0.25)})
    _add("patch", "hash-checked multi-edit patcher", cmd_patch, **{"edits": {}})
    _add("audio", "build or check the audio bed", cmd_audio,
         **{"project": dict(nargs="?", default=None), "--cues": dict(default=None),
            "--out": dict(default=None), "--duration": dict(type=float, default=30.0),
            "--check": dict(default=None)})
    _add("card", "generate a standalone closing card project", cmd_card,
         **{"out": {}, "--title": dict(default="Star it."), "--cn": dict(default="去点亮 Star"),
            "--accent": dict(default=None)})
    _add("api", "introspect the skill without reading its source", cmd_api,
         **{"task": dict(nargs="?", default=None)})
    _add("cat", "read a file through the session cache (optionally a line range)", cmd_cat,
         **{"file": {}, "--lines": dict(default=None), "--cache-dir": dict(default=None)})
    _add("diff", "which line ranges changed since the last read", cmd_diff, **{"file": {}})


def main(argv=None) -> int:
    parser = build_parser()
    try:
        _inject_common(parser)
    except Exception as e:      # never let the convenience layer break the CLI
        fmt.warn(f"command surface injection skipped: {e}")
    args = parser.parse_args(argv)
    fmt.configure(json=getattr(args, "json", False), verbose=getattr(args, "verbose", False),
                  quiet=getattr(args, "quiet", False), limit=getattr(args, "limit", 20))
    try:
        return args.func(args)
    except fmt.VsError as e:
        return fmt.report_error(e)
    except (runtime.ToolError, specmod.SpecError) as e:
        return fmt.report_error(fmt.fail(type(e).__name__, "project", "a valid project / environment",
                                         str(e)[:300],
                                         "vs.py doctor --install-ffmpeg checks the runtime; "
                                         "vs.py plan <project> lists spec problems"))
    except Exception as e:  # keep the CLI honest instead of dumping a traceback
        return fmt.report_error(fmt.fail(type(e).__name__, "vs.py",
                                         "a handled failure", f"{e}"[:300],
                                         "re-run with --verbose for the traceback",
                                         __import__("traceback").format_exc() if getattr(args, "verbose", False) else ""))


if __name__ == "__main__":
    raise SystemExit(main())
