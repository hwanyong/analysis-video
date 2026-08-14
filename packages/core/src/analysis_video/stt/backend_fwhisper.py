"""NVIDIA CUDA(float16) / CPU(int8) 백엔드 — faster-whisper(CTranslate2).

CUDA 가용 시 GPU, 아니면 CPU int8 양자화로 각 플랫폼의 최적 경로를 탄다.
nvidia-cublas/cudnn pip 휠([cuda] extra)만으로 동작 — 시스템 CUDA 설치 불필요.
"""
import ctypes
import glob
import os
import sys

import numpy as np

from .base import build_result, build_source, model_download_guard


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


def cuda_available() -> bool:
    """CUDA 장치가 보이는가. 공개인 이유: doctor도 같은 답을 보고해야 하는데,
    그쪽이 ctranslate2를 직접 부르면 위 선로드를 건너뛰어 "doctor는 없다고 하는데
    전사는 GPU로 도는" 어긋남이 생긴다(stt.cuda_available 참조)."""
    try:
        _preload_cuda_libs()
        from ctranslate2 import get_cuda_device_count
        return get_cuda_device_count() > 0
    except Exception:
        return False


def model_repo(model_size: str) -> str | None:
    """가중치가 내려오는 HuggingFace 저장소 — doctor가 캐시 유무를 볼 때 쓴다.

    매핑의 출처는 상류(faster_whisper.utils._MODELS)다. 여기에 사본을 두면
    상류가 저장소를 옮길 때 조용히 갈리므로, 비공개 이름이라도 상류를 읽고
    없으면 None(모른다)을 돌려준다 — 아는 척하는 것보다 낫다."""
    try:
        from faster_whisper.utils import _MODELS
        return _MODELS.get(model_size)
    except Exception:
        return None


def transcribe(audio: np.ndarray, model_size: str, language: str | None = None,
               device: str = "auto", compute_type: str | None = None) -> dict:
    from faster_whisper import WhisperModel

    if device == "auto":
        device = "cuda" if cuda_available() else "cpu"
    elif device == "cuda":
        _preload_cuda_libs()
    if compute_type is None:
        compute_type = "float16" if device == "cuda" else "int8"

    # 가중치 취득은 생성자에서 일어난다 — 실패를 exit 4로 변환(base.py 참조)
    with model_download_guard(model_repo(model_size) or model_size):
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    # info는 언어 감지 결과다 — 세그먼트 생성기와 달리 지연 평가가 아니라
    # transcribe()가 돌려주는 시점에 이미 확정돼 있다(내부에서 먼저 감지한다).
    segments_iter, info = model.transcribe(audio, word_timestamps=True, language=language)

    segments, words, texts = [], [], []
    for seg in segments_iter:
        segments.append({"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()})
        texts.append(seg.text)
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})

    # 감지한 언어를 반드시 남긴다 — 근거는 backend_mlx의 같은 자리에 있다.
    # 확률(info.language_probability)까지 싣지 않는 이유: source의 다른 칸은 전부
    # 판정에 쓰이는 값인데 이것은 어디서도 읽히지 않아 죽은 칸이 되고, 백엔드마다
    # 있고 없고가 달라(mlx는 확률을 돌려주지 않는다) 스키마가 출처별로 갈린다.
    return build_result("".join(texts), segments, words,
                        backend="faster-whisper", device=device, model=model_size,
                        source=build_source("whisper", language=info.language))
