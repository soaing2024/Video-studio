"""Image generation through any OpenAI-compatible images endpoint.

Most aggregators and platforms (OpenAI, SiliconFlow, DashScope, Volcengine Ark, 302.AI, ...)
expose the same shape: POST {base_url}/images/generations with a bearer token, returning
`data[0].b64_json` or `data[0].url`. That single contract is what this module speaks, so the
user can point it at whichever service they already pay for.

The key is stored outside the repository, in ~/.video-studio/config.json, and is masked in
every command's output. It is never written into a project file.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".video-studio" / "config.json"

PRESETS = {
    "openai": {"base_url": "https://api.openai.com/v1", "path": "/images/generations",
               "model": "gpt-image-1", "size": "1536x1024"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "path": "/images/generations",
                    "model": "Kwai-Kolors/Kolors", "size": "1024x1024"},
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                  "path": "/images/generations", "model": "wanx2.1-t2i-turbo", "size": "1024x1024"},
    "volcengine": {"base_url": "https://ark.cn-beijing.volces.com/api/v3",
                   "path": "/images/generations", "model": "doubao-seedream-3-0-t2i-250415",
                   "size": "1024x1024"},
    "replicate": {"base_url": "https://api.replicate.com/v1", "path": "/predictions",
                  "model": "black-forest-labs/flux-schnell", "size": "1024x1024"},
    "custom": {"base_url": "", "path": "/images/generations", "model": "", "size": "1024x1024"},
}


class ImageGenError(RuntimeError):
    """Raised when image generation is unavailable or the provider refuses the request."""


# ------------------------------------------------------------------ configuration

def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_PATH.is_file():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    # environment wins, so CI or a one-off run never needs the file
    for env, key in (("VS_IMAGE_API_KEY", "api_key"), ("VS_IMAGE_BASE_URL", "base_url"),
                     ("VS_IMAGE_MODEL", "model"), ("VS_IMAGE_PATH", "path"),
                     ("VS_IMAGE_SIZE", "size")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def save_config(**fields) -> dict:
    cfg = load_config()
    cfg.update({k: v for k, v in fields.items() if v not in (None, "")})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # best effort: keep the key readable only by this user
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    return cfg


def configure(provider: str, api_key: str, base_url: str | None = None,
              model: str | None = None, size: str | None = None,
              path: str | None = None) -> dict:
    if provider not in PRESETS:
        raise ImageGenError(f"unknown provider '{provider}'; choose one of {', '.join(PRESETS)}")
    preset = PRESETS[provider]
    cfg = {
        "provider": provider,
        "api_key": api_key,
        "base_url": (base_url or preset["base_url"]).rstrip("/"),
        "path": path or preset["path"],
        "model": model or preset["model"],
        "size": size or preset["size"],
    }
    return save_config(**cfg)


def mask(key: str | None) -> str:
    if not key:
        return "(unset)"
    return key[:6] + "..." + key[-4:] if len(key) > 12 else "***"


def describe(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return {
        "configured": bool(cfg.get("api_key") and cfg.get("base_url")),
        "provider": cfg.get("provider", "(custom)"),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "size": cfg.get("size", ""),
        "api_key": mask(cfg.get("api_key")),
        "config_path": str(CONFIG_PATH),
    }


def require() -> dict:
    cfg = load_config()
    if not cfg.get("api_key"):
        raise ImageGenError(
            "image generation is not configured. Run `vs.py setup --provider <name> --key <key>` "
            f"(or set VS_IMAGE_API_KEY). Config lives at {CONFIG_PATH}."
        )
    if not cfg.get("base_url"):
        raise ImageGenError("image generation needs a base_url; set it in the provider preset")
    return cfg


# ------------------------------------------------------------------ requests

def build_request(prompt: str, cfg: dict, size: str | None = None, n: int = 1,
                  negative: str | None = None) -> tuple[str, dict, dict]:
    url = cfg["base_url"].rstrip("/") + cfg.get("path", "/images/generations")
    body = {"model": cfg.get("model", ""), "prompt": prompt, "n": max(1, int(n)),
            "size": size or cfg.get("size") or "1024x1024"}
    if negative:
        body["negative_prompt"] = negative
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {cfg['api_key']}"}
    return url, headers, body


def generate(prompt: str, out: str, cfg: dict | None = None, size: str | None = None,
             n: int = 1, timeout: int = 240, negative: str | None = None,
             dry_run: bool = False) -> dict:
    cfg = cfg or require()
    url, headers, body = build_request(prompt, cfg, size=size, n=n, negative=negative)
    if dry_run:
        return {"dry_run": True, "url": url, "model": body["model"], "size": body["size"],
                "authorization": "Bearer " + mask(cfg["api_key"]), "prompt": prompt}

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:800]
        raise ImageGenError(f"provider returned HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ImageGenError(f"could not reach {url}: {e.reason}") from e

    items = payload.get("data") or payload.get("images") or payload.get("output") or []
    if isinstance(items, dict):
        items = [items]
    if not items:
        raise ImageGenError(f"provider response had no image payload: {str(payload)[:400]}")

    written = []
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(items[:n]):
        target = out_path if i == 0 else out_path.with_name(f"{out_path.stem}-{i + 1}{out_path.suffix}")
        if isinstance(item, str) and item.startswith("http"):
            _download(item, target, timeout)
        elif isinstance(item, str):
            target.write_bytes(base64.b64decode(item))
        elif item.get("b64_json"):
            target.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            _download(item["url"], target, timeout)
        else:
            raise ImageGenError(f"unsupported image item: {str(item)[:200]}")
        written.append(str(target))
    return {"ok": True, "provider": cfg.get("provider"), "model": body["model"],
            "size": body["size"], "files": written, "prompt": prompt}


def _download(url: str, target: Path, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "video-studio/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        target.write_bytes(resp.read())


# ------------------------------------------------------------------ pipeline hook

def style_clause(spec: dict) -> str:
    return ((spec.get("style") or {}).get("signature") or {}).get("image_style", "")


def resolve_prompt(spec: dict, seg_id: str, name: str, value: dict, log=print) -> str:
    """Generate (or reuse) one prompt-backed asset and return its file path."""
    import hashlib
    prompt = value["prompt"]
    clause = style_clause(spec)
    if clause and value.get("style", True):
        prompt = f"{prompt}. {clause}"
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    target = Path(spec["base_dir"]) / "build" / spec["name"] / "gen" / f"{seg_id}-{name}-{digest}.png"
    if target.is_file() and not value.get("force"):
        return str(target)
    log(f"  imagegen {seg_id}.{name} -> {target.name}")
    return generate(prompt, str(target), size=value.get("size"), cfg=require())["files"][0]


def resolve_assets(spec, log=print) -> list[dict]:
    """Generate every prompt-backed asset in the project. Returns a manifest."""
    made = []
    for seg in spec.get("segments", []):
        for name, value in (seg.get("assets") or {}).items():
            if isinstance(value, dict) and value.get("prompt"):
                path = resolve_prompt(spec, seg["id"], name, value, log=log)
                seg["assets"][name] = path
                made.append({"asset": f"{seg['id']}.{name}", "path": path})
    return made
