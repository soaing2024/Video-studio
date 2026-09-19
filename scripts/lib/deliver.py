"""Delivery extras: a standalone closing card, and the note that ships with a render.

P2-J. When the film itself carries no extra text (a common requirement), the promotion
belongs in a separate asset rather than bolted onto the take - and every delivery deserves
a one-page note that states what was rendered, what was measured, and what is licensed.
"""
from __future__ import annotations

import json
from pathlib import Path

CARD_HTML = """<!doctype html><meta charset="utf-8">
<style>
 html,body{margin:0;height:100%%;overflow:hidden;background:#f7f8fa;
   font-family:"Microsoft YaHei","Noto Sans SC","Segoe UI",system-ui,sans-serif}
 #stage{position:absolute;inset:0;background:radial-gradient(130%% 95%% at 50%% 44%%,#fff 0%%,#f9fafc 44%%,#eceef2 100%%)}
 #g{position:absolute;left:-40%%;top:-40%%;width:180%%;height:180%%;
   background-image:linear-gradient(to right,rgba(17,24,39,.045) 1px,transparent 1px),
                    linear-gradient(to bottom,rgba(17,24,39,.045) 1px,transparent 1px);
   background-size:96px 96px;transform:scale(1.02)}
 #w{position:absolute;left:50%%;top:50%%;transform:translate(-50%%,-50%%);text-align:left}
 #mark{width:62px;height:62px;border-radius:19px;background:%(accent)s;display:flex;
   align-items:center;justify-content:center;box-shadow:0 26px 50px -24px %(accent)s;opacity:0}
 #mark svg{width:32px;height:32px}
 #t{font-size:176px;font-weight:600;letter-spacing:-.045em;color:#0b0f14;margin-top:56px;opacity:0;white-space:nowrap}
 #r{width:620px;height:1px;background:rgba(15,23,42,.16);transform-origin:0 50%%;transform:scaleX(0);margin-top:26px}
 #cn{font-size:36px;font-weight:500;color:#6d7887;margin-top:22px;opacity:0;white-space:nowrap}
</style>
<div id="stage"><div id="g"></div>
 <div id="w">
  <div id="mark"><svg viewBox="0 0 24 24" fill="#fff"><path d="M12 2.6l2.9 5.9 6.5.95-4.7 4.6 1.1 6.5L12 17.5l-5.8 3.05 1.1-6.5-4.7-4.6 6.5-.95z"/></svg></div>
  <div id="t">%(title)s</div><div id="r"></div><div id="cn">%(cn)s</div>
 </div>
</div>
<script>
window.seek = function(t){
  var e = function(p){ return t <= 0 ? 0 : (1 - Math.exp(-2.3 * 1.0 * Math.min(1, p)) * Math.cos(2.4 * Math.min(1, p))); };
  document.getElementById('mark').style.opacity = String(Math.min(1, t / .35));
  document.getElementById('mark').style.transform = 'scale(' + (0.6 + 0.4 * e(t / .6)) + ')';
  document.getElementById('t').style.opacity = String(Math.min(1, Math.max(0, (t - .2) / .4)));
  document.getElementById('t').style.transform = 'translateY(' + ((1 - e((t - .2) / .6)) * 26) + 'px)';
  document.getElementById('r').style.transform = 'scaleX(' + e((t - .55) / .9) + ')';
  document.getElementById('cn').style.opacity = String(Math.min(1, Math.max(0, (t - .8) / .5)));
  document.getElementById('cn').style.transform = 'translateY(' + ((1 - e((t - .8) / .7)) * 22) + 'px)';
  document.getElementById('g').style.transform = 'scale(' + (1.02 + t * 0.004) + ') translateX(' + (-t * 1.5) + 'px)';
};
(function(){ var d = document.createElement('div'); window.__sceneReady = true; })();
</script>"""


def closing_card(out_dir: str | Path, title: str = "Star it.", cn: str = "去点亮 Star",
                 accent: str = "#1f6bff", duration: float = 5.0,
                 width: int = 3840, height: int = 2160, fps: int = 60) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scene = out / "card.html"
    scene.write_text(CARD_HTML % {"title": title, "cn": cn, "accent": accent}, encoding="utf-8")
    spec = {"name": out.name or "card", "video": {"width": width, "height": height, "fps": fps,
                                                 "crf": 16, "preset": "fast"},
            "render": {"jobs": 1, "crf": 12, "slices": 4},
            "look": {"accent": accent}, "duration": duration, "scene": "card.html",
            "data": {"title": title}, "audio": {"tracks": []}}
    (out / "project.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "which": "card", "project": str(out / "project.json"),
            "scene": str(scene), "duration": duration,
            "how": f"python scripts/vs.py run {out / 'project.json'} --slices 4 --jobs 4"}


def note(spec: dict, verify_report: dict | None = None, out: str | Path | None = None) -> str:
    """The one-page delivery note: specs, measured acceptance, and what to call it."""
    v = spec.get("video", {})
    seg = (spec.get("segments") or [{}])[0]
    lines = [f"# {spec.get('name', 'video')} — delivery note", "",
             f"- **画面**: {v.get('width')}x{v.get('height')} @ {v.get('fps')} fps, "
             f"{float(seg.get('duration') or spec.get('duration') or 0):g}s，一镜到底（无剪辑）",
             f"- **编码**: H.264 High, CRF {v.get('crf')}, preset {v.get('preset')}",
             f"- **场景**: `{Path(str(seg.get('scene', spec.get('scene', '')))).name}`"
             f"（`window.seek(t)` 纯函数，可任意时间点重渲）",
             f"- **音频**: {len((spec.get('audio') or {}).get('tracks') or [])} 条轨道，"
             f"仅动效/UI 音效" if spec.get("audio") else "- **音频**: 无", ""]
    if verify_report:
        lines += ["## 验收（测量，非目测）", ""]
        for c in verify_report.get("checks", []):
            lines.append(f"- {'PASS' if c['ok'] else 'FAIL'} `{c['check']}`: {c['detail']}")
        lines.append("")
    lines += ["## 版权", "",
              "- 浏览器库：见 `assets/lib/*/manifest.json`（lucide ISC / three MIT / lottie MIT / anime MIT）",
              "- 音效：本片由 `scripts/lib/audio.py` 合成，无第三方素材",
              "- 字体：系统字体（Microsoft YaHei / Segoe UI），未嵌入", ""]
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    return text
