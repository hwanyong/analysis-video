"""플랫폼별 최적 STT 백엔드 자동 선택 — 결정 A6(architecture-decisions §6).

우선순위: ① macOS Apple Silicon → mlx-whisper(Metal)
          ② NVIDIA CUDA 가용     → faster-whisper GPU(float16)
          ③ 그 외               → faster-whisper CPU(int8)
오버라이드: --stt-backend 플래그 또는 환경변수 ANALYSIS_VIDEO_STT (mlx | faster-whisper).
모든 백엔드는 base.py의 동일 출력 스키마를 반환해야 한다.
"""
import os
import platform
import sys
from importlib.util import find_spec
from pathlib import Path

from ..errors import EXIT_DEPS, EXIT_INPUT, CliError

BACKENDS = ("mlx", "faster-whisper")


def resolve_backend(override: str | None = None) -> str:
    choice = override or os.environ.get("ANALYSIS_VIDEO_STT") or "auto"
    if choice not in ("auto", *BACKENDS):
        raise CliError(EXIT_INPUT, "stt-backend-unknown",
                       f"알 수 없는 STT 백엔드: {choice}",
                       hint=f"가능한 값: auto, {', '.join(BACKENDS)}")

    if choice == "auto":
        if sys.platform == "darwin" and platform.machine() == "arm64" and find_spec("mlx_whisper"):
            return "mlx"
        if find_spec("faster_whisper"):
            return "faster-whisper"
        if find_spec("mlx_whisper"):
            return "mlx"
        raise CliError(EXIT_DEPS, "stt-backend-missing",
                       "사용 가능한 STT 백엔드가 없습니다 (mlx-whisper / faster-whisper 미설치)",
                       hint="pip install analysis-video 를 다시 실행하거나 "
                            "'analysis-video doctor'로 환경을 점검하세요")

    module = {"mlx": "mlx_whisper", "faster-whisper": "faster_whisper"}[choice]
    if not find_spec(module):
        raise CliError(EXIT_DEPS, "stt-backend-missing",
                       f"요청한 STT 백엔드 '{choice}'({module})가 설치되어 있지 않습니다",
                       hint="Apple Silicon 외 플랫폼의 faster-whisper는 기본 설치, "
                            "Apple Silicon에서는 'analysis-video[stt-fwhisper]' extra로 설치")
    return choice


def transcribe_audio(audio_path: Path, model_size: str = "tiny",
                     backend: str | None = None, language: str | None = None) -> dict:
    from .. import media
    name = resolve_backend(backend)
    audio = media.load_audio_mono16k(audio_path)
    if name == "mlx":
        from . import backend_mlx
        return backend_mlx.transcribe(audio, model_size, language=language)
    from . import backend_fwhisper
    return backend_fwhisper.transcribe(audio, model_size, language=language)
