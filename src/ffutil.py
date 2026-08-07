import subprocess
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image


def get_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def get_fps(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "0", "-of", "csv=p=0", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    num, den = out.split("/")
    return float(num) / float(den)


def decode_gray_frames(path: Path, w: int = 64, h: int = 36) -> list[np.ndarray]:
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
           "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    frame_size = w * h
    frames = []
    while True:
        buf = proc.stdout.read(frame_size)
        if len(buf) < frame_size:
            break
        frames.append(np.frombuffer(buf, dtype=np.uint8).reshape(h, w).astype(np.float32))
    proc.wait()
    return frames


def extract_gray_array(path: Path, time_s: float, w: int = 200, h: int = 112) -> np.ndarray | None:
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{time_s:.3f}", "-i", str(path),
           "-vf", f"scale={w}:{h},format=gray", "-frames:v", "1", "-f", "rawvideo", "pipe:1"]
    out = subprocess.run(cmd, capture_output=True).stdout
    if len(out) < w * h:
        return None
    return np.frombuffer(out, dtype=np.uint8).reshape(h, w)


def extract_frame(path: Path, time_s: float, out_path: Path) -> bool:
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-ss", f"{time_s:.3f}",
         "-i", str(path), "-frames:v", "1", str(out_path)],
        check=True,
    )
    return out_path.exists()


def yavg(img_path: Path) -> float:
    img = Image.open(img_path).convert("L")
    return float(np.mean(np.asarray(img)))


def phash(img_path: Path) -> imagehash.ImageHash:
    return imagehash.phash(Image.open(img_path))
