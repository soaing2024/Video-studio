"""Assemble the timeline: trims, transitions, the global look, audio, subtitles."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import render, spec as specmod


def _escape_filter_path(p: str) -> str:
    s = str(Path(p).resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def build_graph(spec: dict) -> tuple[list[str], list[dict], str | None, float]:
    fps = spec["video"]["fps"]
    W, H = spec["video"]["width"], spec["video"]["height"]
    ww, wh, upscale = render.work_size(spec)
    items = spec["timeline"]

    inputs: list[dict] = []
    for item in items:
        if item.get("source"):
            src = Path(item["source"])
            still = src.suffix.lower() in specmod.IMAGE_SUFFIXES
            inputs.append({"path": str(src), "still": still,
                           "seconds": specmod.item_length(spec, item)})
        else:
            inputs.append({"path": str(render.segment_path(spec, item["segment"])), "still": False})

    overlay = (spec.get("look") or {}).get("overlay")
    ov_idx = None
    if overlay and overlay.get("src"):
        ov_idx = len(inputs)
        inputs.append({"path": overlay["src"], "still": True, "seconds": 1.0})

    graph: list[str] = []
    lengths: list[float] = []
    for i, item in enumerate(items):
        lo, hi = specmod.trim_range(spec, item)
        speed = max(0.05, float(item.get("speed", 1.0) or 1.0))
        length = specmod.item_length(spec, item)
        lengths.append(length)
        chain = (f"[{i}:v]trim=start={lo:.3f}:end={hi:.3f},setpts=PTS-STARTPTS,"
                 f"fps={fps},setsar=1")
        if item.get("source"):
            chain += (f",scale={ww}:{wh}:force_original_aspect_ratio=decrease"
                      f",pad={ww}:{wh}:(ow-iw)/2:(oh-ih)/2")
        zoom = item.get("zoom")
        if zoom:
            z0 = float(zoom.get("from", 1.0))
            z1 = float(zoom.get("to", 1.08))
            span = max(1.0, length * fps)
            pan = str(zoom.get("pan", "center"))
            zexpr = f"{z0}+({z1 - z0})*on/{span:.1f}"
            if pan == "left":        # travel right, revealing the right side
                xexpr, yexpr = f"(iw-iw/zoom)*on/{span:.1f}", "(ih-ih/zoom)/2"
            elif pan == "right":
                xexpr, yexpr = f"(iw-iw/zoom)*(1-on/{span:.1f})", "(ih-ih/zoom)/2"
            elif pan == "up":
                xexpr, yexpr = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*on/{span:.1f}"
            elif pan == "down":
                xexpr, yexpr = "(iw-iw/zoom)/2", f"(ih-ih/zoom)*(1-on/{span:.1f})"
            else:
                xexpr, yexpr = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
            chain += (f",zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1"
                      f":s={ww}x{wh}:fps={fps}")
        if abs(speed - 1.0) > 1e-6:
            chain += f",setpts=PTS/{speed:.4f},fps={fps}"
        # zoompan and concat disagree on timebase (1/30 vs AVTB); unify before folding them
        chain += f",settb=AVTB[c{i}]"
        graph.append(chain)

    acc = "c0"
    acc_len = lengths[0]
    for i in range(1, len(items)):
        tr = items[i].get("transition") or {}
        label = f"t{i}"
        if tr.get("type", "cut") == "cut":
            graph.append(f"[{acc}][c{i}]concat=n=2:v=1:a=0[{label}]")
            acc_len += lengths[i]
        else:
            dur = float(tr.get("duration", 0.5))
            if dur >= acc_len:
                raise ValueError(f"transition before '{items[i]['segment']}' is longer than the video so far")
            offset = acc_len - dur
            etype = tr.get("type", "fade")
            graph.append(f"[{acc}][c{i}]xfade=transition={etype}:duration={dur:.3f}:"
                         f"offset={offset:.3f}[{label}]")
            # xfade output length = offset + length(B): B's first frame lands at `offset`.
            acc_len = offset + lengths[i]
        acc = label
    total = acc_len

    look = spec.get("look") or {}
    grade = look.get("grade")
    stage = acc
    if grade:
        params = ":".join(f"{k}={v}" for k, v in grade.items())
        graph.append(f"[{stage}]eq={params}[look0]")
        stage = "look0"

    if ov_idx is not None:
        alpha = float(overlay.get("opacity", 1.0))
        oscale = float(overlay.get("scale", 1.0))
        prep = f"[{ov_idx}:v]format=rgba,colorchannelmixer=aa={alpha}"
        if abs(oscale - 1.0) > 1e-6:
            prep += f",scale=iw*{oscale}:ih*{oscale}"
        graph.append(prep + "[ovl]")
        graph.append(f"[{stage}][ovl]overlay=x={overlay.get('x', 'W-w-32')}:"
                     f"y={overlay.get('y', '32')}:format=auto[ov]")
        stage = "ov"

    px = look.get("pixelate")
    if px:
        colors = int(px.get("colors", 16))
        dither = px.get("dither", "none")
        graph.append(f"[{stage}]split[pal_in][pal_ref]")
        graph.append(f"[pal_in]palettegen=max_colors={colors}:reserve_transparent=0[pal]")
        graph.append(f"[pal_ref][pal]paletteuse=dither={dither},"
                     f"scale={W}:{H}:flags=neighbor[pix]")
        stage = "pix"
    elif (ww, wh) != (W, H):
        graph.append(f"[{stage}]scale={W}:{H}:flags=neighbor[up]")
        stage = "up"

    tail = []
    fade_in = float(look.get("fade_in", 0) or 0)
    fade_out = float(look.get("fade_out", 0) or 0)
    if fade_in:
        tail.append(f"fade=t=in:st=0:d={fade_in:.3f}")
    if fade_out:
        tail.append(f"fade=t=out:st={max(0.0, total - fade_out):.3f}:d={fade_out:.3f}")

    prog = look.get("progress_bar")
    if prog:
        ph = int(prog.get("height", 4))
        pcol = prog.get("color", "#e0455f")
        tail.append(f"drawbox=x=0:y=ih-{ph}:w=iw*t/{total:.3f}:h={ph}:"
                    f"color={pcol}@{prog.get('opacity', 0.9)}:t=fill")

    subs = (spec.get("subtitles") or {}).get("src")
    if subs:
        filt = f"subtitles='{_escape_filter_path(subs)}'"
        style = (spec.get("subtitles") or {}).get("style")
        if style:
            filt += f":force_style='{style}'"
        tail.append(filt)

    if tail:
        graph.append(f"[{stage}]" + ",".join(tail) + "[vout]")
    else:
        graph.append(f"[{stage}]null[vout]")

    tracks = (spec.get("audio") or {}).get("tracks", [])
    audio_out = None
    # capture the first free input index once: appending inside the loop must not shift it
    audio_base = len(inputs)
    for k, track in enumerate(tracks):
        idx = audio_base + k
        inputs.append({"path": track["src"], "loop": bool(track.get("loop")),
                       "stream_loop": bool(track.get("loop"))})
        parts = [f"atrim=0:{total:.3f}", "asetpts=PTS-STARTPTS",
                 f"volume={float(track.get('gain_db', -18))}dB"]
        if track.get("fade_in"):
            parts.append(f"afade=t=in:st=0:d={float(track['fade_in']):.3f}")
        if track.get("fade_out"):
            fo = float(track["fade_out"])
            parts.append(f"afade=t=out:st={max(0.0, total - fo):.3f}:d={fo:.3f}")
        delay = int(float(track.get("at", 0)) * 1000)
        if delay > 0:
            parts.append(f"adelay={delay}:all=1")
        graph.append(f"[{idx}:a]" + ",".join(parts) + f"[a{k}]")

    if tracks:
        audio_cfg = spec.get("audio") or {}
        duck = audio_cfg.get("duck") or {}
        voice_k = next((k for k, t in enumerate(tracks)
                       if t.get("role") == "voice" or t.get("_role") == "voice"), None)
        ducked = {k for k, t in enumerate(tracks) if t.get("duck")}
        mix_labels = []

        if ducked and voice_k is not None:
            thr = float(duck.get("threshold", 0.02))
            ratio = float(duck.get("ratio", 8))
            attack = float(duck.get("attack", 150))
            release = float(duck.get("release", 600))
            # the voice feeds both the mix and the sidechain, so it has to be split
            graph.append(f"[a{voice_k}]asplit=2[voice_mix][voice_sc]")
            for k in range(len(tracks)):
                if k in ducked:
                    graph.append(
                        f"[a{k}][voice_sc]sidechaincompress=threshold={thr}:"
                        f"ratio={ratio}:attack={attack}:release={release}[d{k}]")
                    mix_labels.append(f"[d{k}]")
                elif k == voice_k:
                    mix_labels.append("[voice_mix]")
                else:
                    mix_labels.append(f"[a{k}]")
        else:
            mix_labels = [f"[a{k}]" for k in range(len(tracks))]

        if ducked and voice_k is None:
            raise ValueError("audio.duck needs one track marked role: voice to act as the sidechain")

        # normalize=0 keeps the declared gains literal; the narration and probe commands exist
        # so those gains can be chosen from measurements instead of guesswork.
        normalize = 1 if audio_cfg.get("normalize", False) else 0
        graph.append(f"{''.join(mix_labels)}amix=inputs={len(tracks)}:duration=longest:"
                     f"dropout_transition=0:normalize={normalize}[mixraw]")
        chain = f"atrim=0:{total:.3f},asetpts=N/SR/TB"
        gain = float(audio_cfg.get("mix_gain_db", 0))
        if abs(gain) > 1e-6:
            chain += f",volume={gain}dB"
        loud = audio_cfg.get("loudnorm")
        if loud:
            chain += (f",loudnorm=I={loud.get('i', -16)}:TP={loud.get('tp', -1.5)}:"
                      f"LRA={loud.get('lra', 11)}")
        graph.append(f"[mixraw]{chain}[aout]")
        audio_out = "aout"

    return graph, inputs, audio_out, total


def assemble(spec: dict, ffmpeg: str, out_path: str | None = None, log=print) -> dict:
    build = render.build_dir(spec)
    out = Path(out_path) if out_path else Path(spec["base_dir"]) / f"{spec['name']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    graph, inputs, audio_out, total = build_graph(spec)
    script = build / "filter.txt"
    script.write_text(";\n".join(graph) + "\n", encoding="utf-8")

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats"]
    for item in inputs:
        if item.get("stream_loop"):
            cmd += ["-stream_loop", "-1"]
        if item.get("still"):
            # an image or logo has to be looped into a stream before it can be trimmed
            cmd += ["-loop", "1", "-framerate", str(spec["video"]["fps"]),
                    "-t", f"{float(item.get('seconds', 1.0)):.3f}"]
        cmd += ["-i", item["path"]]
    cmd += ["-/filter_complex", str(script), "-map", "[vout]"]
    if audio_out:
        cmd += ["-map", f"[{audio_out}]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", spec["video"]["preset"],
            "-crf", str(spec["video"]["crf"])]
    if (spec.get("look") or {}).get("pixelate"):
        cmd += ["-tune", "animation"]  # flat colour fields and hard edges
    cmd += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio_out:
        cmd += ["-shortest"]
    cmd += [str(out)]

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 and "Unrecognized" in proc.stderr and "filter_complex" in proc.stderr:
        cmd[cmd.index("-/filter_complex")] = "-filter_complex_script"
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"assembly failed:\n{proc.stderr[-4000:]}\n\nfilters:\n{script.read_text(encoding='utf-8')}")

    log(f"  assembled {out.name} ({total:.2f}s)")
    return {"output": str(out), "duration": round(total, 3), "filters": str(script),
            "cmd": " ".join(cmd)}
