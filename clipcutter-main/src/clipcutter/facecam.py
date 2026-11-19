"""Find the streamer's facecam overlay so the clip can use the split layout
(facecam on top, gameplay below) automatically."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import system


def _frames(video: Path, start: float, end: float, n: int = 10) -> list[np.ndarray]:
    import cv2

    out = []
    for t in np.linspace(start, max(start + 0.5, end), n):
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", *system.hwaccel_args(), "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
        ).stdout
        if raw:
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                out.append(img)
    return out


def detect(video: Path, start: float, end: float) -> list[float] | None:
    """Return the facecam box [x, y, w, h] as fractions of the frame, or None.

    A facecam is a small face that stays in the same spot in most sampled frames
    (a full-screen "just chatting" face is not a facecam).
    """
    import cv2

    frames = _frames(video, start, end)
    if not frames:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    H, W = frames[0].shape[:2]
    boxes = []
    for f in frames:
        faces = cascade.detectMultiScale(f, scaleFactor=1.1, minNeighbors=6, minSize=(int(W * 0.03),) * 2)
        if len(faces):
            x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
            boxes.append((x + w / 2, y + h / 2, w, h))
    if len(boxes) < max(3, len(frames) * 0.5):
        return None
    b = np.median(np.array(boxes), axis=0)
    spread = np.std(np.array(boxes)[:, :2], axis=0)
    cx, cy, fw, fh = b
    if fw > W * 0.14 or spread.max() > W * 0.04:
        return None  # face too big (full-cam content) or moving around (an in-game character)
    if abs(cx - W / 2) < W * 0.2 and abs(cy - H / 2) < H * 0.25:
        return None  # centered face = the video itself is a camera shot, not a webcam overlay
    # expand the face box to a webcam-shaped crop (~ 4:3), clamp to frame
    cw, ch = min(fw * 3.2, W * 0.5), min(fh * 2.6, H * 0.6)
    x0 = max(0.0, min(cx - cw / 2, W - cw))
    y0 = max(0.0, min(cy - ch / 2, H - ch))
    return [round(x0 / W, 4), round(y0 / H, 4), round(cw / W, 4), round(ch / H, 4)]
