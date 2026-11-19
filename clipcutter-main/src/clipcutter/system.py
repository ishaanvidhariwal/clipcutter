"""Everything that differs between macOS, Windows and Linux: fonts, video encoder, speech model."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
APPLE_SILICON = IS_MAC and platform.machine() == "arm64"
WINFONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def _first(cands):
    for c in cands:
        path = c[0] if isinstance(c, tuple) else c
        if path and Path(path).exists():
            return c
    return None


# Bold caption/hook font (Latin text)
BOLD_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    str(WINFONTS / "ariblk.ttf"), str(WINFONTS / "arialbd.ttf"),
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
]
# Hindi / Devanagari (path, index inside .ttc)
HINDI_FONTS = [
    ("/System/Library/Fonts/Kohinoor.ttc", 3),                 # Kohinoor Devanagari Bold
    ("/System/Library/Fonts/Supplemental/DevanagariMT.ttc", 1),
    (str(WINFONTS / "NirmalaB.ttf"), 0), (str(WINFONTS / "Nirmala.ttc"), 1), (str(WINFONTS / "mangalb.ttf"), 0),
    ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/noto/NotoSansDevanagari-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf", 0),
]
EMOJI_FONTS = [
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    str(WINFONTS / "seguiemj.ttf"),
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
]


def bold_font(configured: str | None = None) -> str:
    if configured and Path(configured).exists():
        return configured
    f = _first(BOLD_FONTS)
    if not f:
        raise SystemExit("No bold font found. Set captions.font in config.yaml to a .ttf file "
                         "(see docs/SETUP.md).")
    return f


def hindi_font() -> tuple[str, int] | None:
    return _first(HINDI_FONTS)


def emoji_font() -> str | None:
    return _first(EMOJI_FONTS)


# ---------- video ----------

@lru_cache(maxsize=None)
def _encoders() -> str:
    try:
        return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        raise SystemExit("ffmpeg is not installed. See docs/SETUP.md.")


def encoder_args(bitrate: str) -> list[str]:
    """Hardware H.264 encoder when there is one (much faster), else libx264."""
    enc = _encoders()
    if IS_MAC and "h264_videotoolbox" in enc:
        return ["-c:v", "h264_videotoolbox", "-b:v", bitrate, "-profile:v", "high"]
    if "h264_nvenc" in enc and shutil.which("nvidia-smi"):
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", bitrate]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def hwaccel_args() -> list[str]:
    """Decode on the GPU/media engine where it's reliable (macOS)."""
    return ["-hwaccel", "videotoolbox"] if IS_MAC else []


# ---------- speech-to-text ----------

def whisper_backend() -> str:
    return "mlx" if APPLE_SILICON else "faster-whisper"


def js_runtimes() -> dict:
    """yt-dlp needs a JavaScript runtime to download from YouTube (else HTTP 403)."""
    rt = {}
    for name in ("deno", "node"):
        if shutil.which(name):
            rt[name] = {}
    return rt


def text_shaping_ok() -> bool:
    """Hindi needs complex text shaping (Pillow + raqm + fribidi)."""
    try:
        from PIL import features
        return bool(features.check("raqm"))
    except Exception:
        return False
