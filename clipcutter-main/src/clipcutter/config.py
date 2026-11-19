"""Settings: defaults merged with an optional config.yaml."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "clips": 5,                 # how many clips to make per stream
    "min_len": 15,              # seconds (main part, hook not counted)
    "max_len": 55,
    "style": "genz",            # genz | hype | clean
    "layout": "auto",           # auto (facecam -> split, else blur) | blur | crop | split
    "facecam": None,            # for split layout: [x, y, w, h] as fractions of the frame
    "chat_delay": 5,            # chat reacts a few seconds after the moment
    "weights": {"chat": 0.40, "audio": 0.25, "speech": 0.20, "visual": 0.15},
    "whisper_model": "mlx-community/whisper-large-v3-turbo",
    "language": None,           # None = auto-detect
    "llm": {
        "provider": "auto",     # auto | claude | ollama | templates
        "model": "claude-opus-5-5",
        "ollama_model": "llama3.2",
    },
    "hook": {"enabled": True, "seconds": 2.5, "zoom": 1.2, "boom": True},
    "captions": {
        "enabled": True,
        "words_per_chunk": 3,
        "font": None,           # None = auto (Arial Black on mac/Windows, DejaVu Sans Bold on Linux)
        "size": 88,
        "color": "#FFFFFF",
        "highlight": "#FFE600",
        "y": 1450,
    },
    "header": True,             # keep hook text as a small header for the whole clip
    "video": {"width": 1080, "height": 1920, "fps": 30, "bitrate": "8M"},
    "output_dir": "output",
    "work_dir": ".work",
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | None = None) -> dict:
    candidates = [Path(path)] if path else [Path("config.yaml")]
    for p in candidates:
        if p.exists():
            return _merge(DEFAULTS, yaml.safe_load(p.read_text()) or {})
    return copy.deepcopy(DEFAULTS)
