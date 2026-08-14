"""macOS Apple Silicon 1순위 백엔드 — MLX(Metal) 가속. 실측 37.6배 실시간(tiny)."""
import numpy as np

from .base import build_result, build_source, model_download_guard

MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "turbo": "mlx-community/whisper-turbo",
}


def model_repo(model_size: str) -> str:
    """가중치가 내려오는 HuggingFace 저장소 — doctor가 캐시 유무를 볼 때도 쓴다."""
    return MODEL_REPOS[model_size]


def transcribe(audio: np.ndarray, model_size: str, language: str | None = None) -> dict:
    import mlx_whisper

    repo = model_repo(model_size)
    with model_download_guard(repo):
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
    # 감지한 언어를 반드시 남긴다. language 인자를 준 실행에서는 그 값이 그대로
    # 돌아오고, 안 준 실행에서는 모델이 오디오를 듣고 고른 값이 온다 — 후자가
    # 없으면 "영어 영상인데 왜 한국어 대사가 없나"를 산출물만 보고 답할 수 없다.
    # 선언이 아니라 감지라는 사실은 source.kind가 이미 말한다(base.build_source).
    return build_result(result["text"], segments, words,
                        backend="mlx", device="metal", model=repo,
                        source=build_source("whisper", language=result["language"]))
