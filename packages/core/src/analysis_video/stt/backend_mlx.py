"""macOS Apple Silicon 1순위 백엔드 — MLX(Metal) 가속. 실측 37.6배 실시간(tiny)."""
import numpy as np

from .base import build_result

MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-turbo",
}


def transcribe(audio: np.ndarray, model_size: str, language: str | None = None) -> dict:
    import mlx_whisper

    repo = MODEL_REPOS[model_size]
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=repo, word_timestamps=True, language=language,
    )
    segments = [
        {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
        for s in result["segments"]
    ]
    words = [
        {"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
        for s in result["segments"] for w in s.get("words", [])
    ]
    return build_result(result["text"], segments, words,
                        backend="mlx", device="metal", model=repo)
