"""Signals: loudness, scene cuts, chat activity, and speech (transcript with word timings)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 16000

HYPE_CHAT = re.compile(
    r"(lul|lmao|lmfao|kekw|omegalul|pog|poggers|w+\b|clip|clip it|no way|wtf|bro|"
    r"💀|😭|😂|🤣|🔥|😳|!!|\?\?|monka|pepelaugh|icant|cinema|aura|cooked|ratio)",
    re.I,
)


# ---------- basics ----------

def probe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    s = (data.get("streams") or [{}])[0]
    return {"width": int(s.get("width") or 0), "height": int(s.get("height") or 0),
            "duration": float(data["format"]["duration"])}


def load_audio(video: Path, work: Path) -> np.ndarray:
    """Mono 16 kHz float32 audio, cached on disk as raw PCM."""
    raw = work / "audio16k.pcm"
    if not raw.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1",
             "-ar", str(SR), "-f", "s16le", str(raw)],
            check=True,
        )
    pcm = np.memmap(raw, dtype=np.int16, mode="r")
    return pcm


def loudness(pcm: np.ndarray, seconds: int) -> np.ndarray:
    """RMS loudness in dB for every second."""
    out = np.full(seconds, -90.0, dtype=np.float32)
    for t in range(seconds):
        chunk = np.asarray(pcm[t * SR:(t + 1) * SR], dtype=np.float32)
        if chunk.size:
            rms = np.sqrt(np.mean(chunk ** 2)) / 32768.0
            out[t] = 20 * np.log10(rms + 1e-9)
    return out


def scene_cuts(video: Path, seconds: int, work: Path) -> np.ndarray:
    """Scene-change count per second, from keyframes only (fast even on long VODs)."""
    cache = work / "scenes.json"
    if cache.exists():
        times = json.loads(cache.read_text())
    else:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-skip_frame", "nokey", "-i", str(video),
             "-vf", "scale=320:-2,scdet=threshold=12", "-an", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        times = [float(m) for m in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", proc.stderr)]
        cache.write_text(json.dumps(times))
    out = np.zeros(seconds, dtype=np.float32)
    for t in times:
        if 0 <= int(t) < seconds:
            out[int(t)] += 1
    return out


# ---------- chat ----------

def _chat_items(path: Path):
    """Yield (seconds, text) from the chat formats we know about."""
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return
    records: list = []
    if text[0] == "[":
        records = json.loads(text)
    elif text[0] == "{" and "\n" not in text:
        obj = json.loads(text)
        records = obj.get("comments") or obj.get("messages") or [obj]
    else:
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    for r in records:
        # YouTube live chat replay (yt-dlp .live_chat.json)
        replay = r.get("replayChatItemAction")
        if replay:
            t = int(replay.get("videoOffsetTimeMsec", 0)) / 1000
            for act in replay.get("actions", []):
                item = act.get("addChatItemAction", {}).get("item", {})
                rend = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
                if rend:
                    runs = rend.get("message", {}).get("runs", [])
                    msg = "".join(x.get("text") or x.get("emoji", {}).get("shortcuts", [""])[0] for x in runs)
                    yield t, msg
            continue
        # TwitchDownloader / Twitch API comments
        if "content_offset_seconds" in r:
            body = r.get("message", {})
            yield float(r["content_offset_seconds"]), body.get("body", "") if isinstance(body, dict) else str(body)
            continue
        # chat-downloader and simple formats
        for tk in ("time_in_seconds", "offset", "time", "t"):
            if tk in r:
                yield float(r[tk]), str(r.get("message") or r.get("text") or "")
                break


def chat_activity(path: Path | None, seconds: int, delay: int) -> tuple[np.ndarray | None, dict]:
    """Weighted messages per second, shifted back by `delay` to line up with the moment."""
    if not path or not path.exists():
        return None, {}
    out = np.zeros(seconds, dtype=np.float32)
    samples: dict[int, list[str]] = {}
    n = 0
    for t, msg in _chat_items(path):
        sec = int(t) - delay
        if 0 <= sec < seconds:
            out[sec] += 2.0 if HYPE_CHAT.search(msg) else 1.0
            samples.setdefault(sec, []).append(msg)
            n += 1
    if n == 0:
        return None, {}
    return out, samples


# ---------- speech ----------

def transcribe_window(pcm: np.ndarray, start: float, end: float, model: str, language: str | None) -> list[dict]:
    """Words with absolute timestamps for [start, end].
    Apple Silicon: mlx-whisper (GPU). Windows/Linux/Intel mac: faster-whisper (CPU, or CUDA if available)."""
    from .system import whisper_backend

    a = max(0, int(start * SR))
    b = int(end * SR)
    audio = np.asarray(pcm[a:b], dtype=np.float32) / 32768.0
    if audio.size < SR:
        return []
    # anti-loop: few temperature retries + drop hallucinated text in silent/music parts
    # (without this, music in Hindi videos made one window take 5+ minutes)
    common = dict(word_timestamps=True, language=language, condition_on_previous_text=False,
                  temperature=(0.0, 0.4), hallucination_silence_threshold=2.0)
    words = []
    if whisper_backend() == "mlx":
        import mlx_whisper

        res = mlx_whisper.transcribe(audio, path_or_hf_repo=model, verbose=None, **common)
        for seg in res.get("segments", []):
            for w in seg.get("words", []):
                if w["word"].strip():
                    words.append({"w": w["word"].strip(), "s": round(start + w["start"], 2),
                                  "e": round(start + w["end"], 2)})
    else:
        segments, _ = _faster_model(model).transcribe(audio, **common)
        for seg in segments:
            for w in seg.words or []:
                if w.word.strip():
                    words.append({"w": w.word.strip(), "s": round(start + w.start, 2), "e": round(start + w.end, 2)})
    return words


_FW = {}


def _faster_model(model: str):
    """faster-whisper model name from our config name, e.g. mlx-community/whisper-large-v3-turbo -> large-v3-turbo."""
    from faster_whisper import WhisperModel

    name = model.split("/")[-1].removeprefix("whisper-").removesuffix("-mlx")
    if name not in _FW:
        try:
            import ctranslate2
            cuda = ctranslate2.get_cuda_device_count() > 0
        except Exception:
            cuda = False
        _FW[name] = WhisperModel(name, device="cuda" if cuda else "cpu",
                                 compute_type="float16" if cuda else "int8")
    return _FW[name]
