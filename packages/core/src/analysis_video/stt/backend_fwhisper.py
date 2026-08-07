"""NVIDIA CUDA(float16) / CPU(int8) 백엔드 — faster-whisper(CTranslate2).

CUDA 가용 시 GPU, 아니면 CPU int8 양자화로 각 플랫폼의 최적 경로를 탄다.
nvidia-cublas/cudnn pip 휠([cuda] extra)만으로 동작 — 시스템 CUDA 설치 불필요.
"""
import numpy as np

from .base import build_result


def _cuda_available() -> bool:
    try:
        from ctranslate2 import get_cuda_device_count
        return get_cuda_device_count() > 0
    except Exception:
        return False


def transcribe(audio: np.ndarray, model_size: str, language: str | None = None,
               device: str = "auto", compute_type: str | None = None) -> dict:
    from faster_whisper import WhisperModel

    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    if compute_type is None:
        compute_type = "float16" if device == "cuda" else "int8"

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments_iter, _info = model.transcribe(audio, word_timestamps=True, language=language)

    segments, words, texts = [], [], []
    for seg in segments_iter:
        segments.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
        texts.append(seg.text)
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})

    return build_result("".join(texts), segments, words,
                        backend="faster-whisper", device=device, model=model_size)
