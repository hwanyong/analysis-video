"""NVIDIA CUDA(float16) / CPU(int8) 백엔드 — faster-whisper(CTranslate2).

CUDA 가용 시 GPU, 아니면 CPU int8 양자화로 각 플랫폼의 최적 경로를 탄다.
nvidia-cublas/cudnn pip 휠([cuda] extra)만으로 동작 — 시스템 CUDA 설치 불필요.
"""
import ctypes
import glob
import os
import sys

import numpy as np

from .base import build_result


def _preload_cuda_libs() -> None:
    """[cuda] extra의 pip nvidia 휠(cublas/cudnn)은 시스템 로더 검색 경로에 없다 —
    ctranslate2가 dlopen하기 전에 명시 선로드해야 GPU 경로가 실제로 동작한다.
    (faster-whisper 문서의 LD_LIBRARY_PATH 방식은 프로세스 시작 후엔 무효라
    ctypes RTLD_GLOBAL 선로드로 대체. 미설치·비GPU 환경에서는 조용히 통과.)"""
    if sys.platform == "darwin":
        return
    try:
        import nvidia.cublas.lib as cublas_lib
        import nvidia.cudnn.lib as cudnn_lib
    except ImportError:
        return
    for mod in (cublas_lib, cudnn_lib):
        d = os.path.dirname(mod.__file__)
        if sys.platform == "win32":
            os.add_dll_directory(d)
        else:
            for so in sorted(glob.glob(os.path.join(d, "*.so*"))):
                try:
                    ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def _cuda_available() -> bool:
    try:
        _preload_cuda_libs()
        from ctranslate2 import get_cuda_device_count
        return get_cuda_device_count() > 0
    except Exception:
        return False


def transcribe(audio: np.ndarray, model_size: str, language: str | None = None,
               device: str = "auto", compute_type: str | None = None) -> dict:
    from faster_whisper import WhisperModel

    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    elif device == "cuda":
        _preload_cuda_libs()
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
