import subprocess
from pathlib import Path


def split_media(video_path: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "audio.wav"
    video_only_path = out_dir / "video.mkv"

    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-i", str(video_path),
         "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio_path)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-i", str(video_path),
         "-an", "-c:v", "copy", str(video_only_path)],
        check=True,
    )
    return audio_path, video_only_path
