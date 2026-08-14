"""플랫폼별 최적 STT 백엔드 자동 선택.

우선순위: ① macOS Apple Silicon → mlx-whisper(Metal)
          ② NVIDIA CUDA 가용     → faster-whisper GPU(float16)
          ③ 그 외               → faster-whisper CPU(int8)
오버라이드: --stt-backend 플래그 또는 환경변수 ANALYSIS_VIDEO_STT (mlx | faster-whisper).
모든 백엔드는 base.py의 동일 출력 스키마를 반환해야 한다.

**백엔드는 선택 설치다**: `analysis-video[stt]` extra로만 들어온다.
그래서 "백엔드가 없다"는 이 모듈에서 오류가 아니라 **상태**이고, 그 상태를 묻는
자리(installed_backends·preferred_backend)는 아무것도 던지지 않는다. 결손이
오류가 되는 자리는 백엔드가 실제로 필요해진 순간 하나뿐이다(resolve_backend) —
자막이 있는 영상은 그 자리에 닿지도 않는다(cli.run_transcribe의 사다리).

그 전에는 환경 진단(doctor)이 "백엔드 없음 = 환경 고장"이라 단정했다. 그래서
자막만으로 끝까지 분석되는 기계가 종료코드 4를 받았고, 스킬 문서에는 "doctor가
안 된다고 해도 자막이 있는 영상은 분석된다"는 해명을 사람이 손으로 덧붙여야 했다.
진단은 능력 목록을 보고하고, 실패는 그 능력이 필요해진 순간에 낸다.
"""
import os
import platform
import sys
from importlib.util import find_spec
from pathlib import Path

from ..errors import EXIT_DEPS, EXIT_INPUT, CliError
from .base import DEFAULT_MODEL

# 백엔드 이름 → 그것이 설치돼 있는지 볼 임포트 이름. 두 값을 따로 적으면
# (전에는 BACKENDS 튜플과 resolve_backend 안의 dict였다) 한쪽만 늘어난다.
MODULES = {"mlx": "mlx_whisper", "faster-whisper": "faster_whisper"}
BACKENDS = tuple(MODULES)

# extra 이름을 문자열로 여기저기 적지 않는다 — CLI 힌트와 에이전트 가이드가
# 같은 설치 명령을 안내해야 하고, extra 이름이 바뀌면 한 군데만 고치면 된다.
STT_EXTRA = "analysis-video[stt]"
INSTALL_COMMAND = f"pip install '{STT_EXTRA}'"
# 사용자가 실제로 칠 수 있는 세 가지 형태. uvx는 첫 호출 때 받은 버전을 캐시해
# 이후에도 그것을 계속 쓰므로 @latest를 붙인다(상류 문서 확인).
INSTALL_HINT = (f"uvx '{STT_EXTRA}@latest' · uv tool install '{STT_EXTRA}' · "
                f"{INSTALL_COMMAND} 중 하나로 설치하세요")


def preference() -> tuple[str, ...]:
    """이 플랫폼에서 백엔드를 고르는 순서 — 설치 여부는 보지 않는다.

    Apple Silicon만 mlx가 앞이다(Metal 가속, 실측 37.6배 실시간). 그 밖에서는
    faster-whisper가 앞이고, mlx는 "설치돼 있다면 안 쓸 이유는 없다"는 자리로
    남는다 — 그 조합은 사용자가 일부러 만든 것이기 때문이다."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return ("mlx", "faster-whisper")
    return ("faster-whisper", "mlx")


def installed_backends() -> tuple[str, ...]:
    """설치돼 있는 백엔드를 선호 순서로. **빈 튜플은 오류가 아니라 상태다.**"""
    return tuple(name for name in preference() if find_spec(MODULES[name]))


def preferred_backend() -> str | None:
    """`auto`가 고를 백엔드. 하나도 없으면 None — 물음이 "지금 되는가"이지
    "고장인가"가 아니므로 여기서는 예외를 던지지 않는다(doctor가 이걸 쓴다)."""
    backends = installed_backends()
    return backends[0] if backends else None


def resolve_backend(override: str | None = None,
                    notes: list[str] | None = None) -> str:
    """실제로 전사할 백엔드를 정한다 — **백엔드 결손이 오류가 되는 유일한 자리.**

    notes는 호출자가 여기까지 내려온 사유다(자막 후보를 왜 하나도 못 썼는가).
    오류의 details에 그대로 실어 보낸다: "STT 백엔드가 없다"만 남으면 받는 쪽은
    자막을 옆에 두는 것으로 해결된다는 사실을 알 수 없고, 사다리가 남긴 사유는
    transcript.json에 실리기 전에 이 실패로 사라진다."""
    choice = override or os.environ.get("ANALYSIS_VIDEO_STT") or "auto"
    if choice not in ("auto", *BACKENDS):
        raise CliError(EXIT_INPUT, "stt-backend-unknown",
                       f"알 수 없는 STT 백엔드: {choice}",
                       hint=f"가능한 값: auto, {', '.join(BACKENDS)}")

    if choice == "auto":
        resolved = preferred_backend()
        if resolved is not None:
            return resolved
        raise CliError(EXIT_DEPS, "stt-backend-missing",
                       "음성 인식(STT) 백엔드가 설치되어 있지 않습니다 — "
                       "이 영상에는 쓸 수 있는 자막이 없어 음성을 받아써야 합니다",
                       hint=f"{INSTALL_HINT}. 자막 파일(.srt/.vtt/.smi)을 영상 옆에 "
                            f"두거나 --transcript로 지정하면 백엔드 없이도 분석됩니다",
                       details={"notes": list(notes)} if notes else None)

    if not find_spec(MODULES[choice]):
        raise CliError(EXIT_DEPS, "stt-backend-missing",
                       f"요청한 STT 백엔드 '{choice}'({MODULES[choice]})가 설치되어 "
                       f"있지 않습니다",
                       hint=f"{INSTALL_HINT}. Apple Silicon에서 faster-whisper를 "
                            f"쓰려면 'analysis-video[stt-fwhisper]' extra가 필요하고, "
                            f"mlx는 Apple Silicon 전용입니다",
                       details={"notes": list(notes)} if notes else None)
    return choice


def model_status(backend: str, model_size: str) -> dict:
    """모델 가중치의 저장소·캐시 상태. 네트워크를 쓰지 않는다.

    doctor가 "이 환경에서 지금 전사가 되는가"를 답할 수 있게 하려는 것 —
    모듈 설치 여부만 보던 이전 판정은 캐시가 비고 오프라인인 환경에도
    초록불을 켰다. cached=None은 "판정 불가"이고 False와 다르다."""
    repo = None
    if backend == "mlx":
        from . import backend_mlx
        repo = backend_mlx.model_repo(model_size)
    elif backend == "faster-whisper":
        from . import backend_fwhisper
        repo = backend_fwhisper.model_repo(model_size)

    cached: bool | None = None
    cache_dir: str | None = None
    try:
        from huggingface_hub import try_to_load_from_cache
        from huggingface_hub.constants import HF_HUB_CACHE
        cache_dir = str(HF_HUB_CACHE)
        if repo is not None:
            cached = isinstance(try_to_load_from_cache(repo, "config.json"), str)
    except Exception:
        pass
    return {"model": model_size, "repo": repo, "cached": cached, "cache_dir": cache_dir}


def cuda_available() -> bool:
    """CUDA 장치가 보이는가 — 판정은 faster-whisper 백엔드가 단독으로 한다.

    doctor가 ctranslate2를 직접 부르던 것을 여기로 모은다: 그쪽은 pip nvidia 휠
    선로드(backend_fwhisper._preload_cuda_libs)를 하지 않아, 같은 기계에서
    doctor는 "CUDA 없음"이라 하고 전사는 GPU로 도는 어긋남이 가능했다.
    백엔드가 없으면 임포트가 실패하고 False가 된다 — 그것이 사실이다."""
    from . import backend_fwhisper
    return backend_fwhisper.cuda_available()


def transcribe_audio(media_path: Path, model_size: str = DEFAULT_MODEL,
                     backend: str | None = None, language: str | None = None) -> dict:
    """media_path는 **오디오 스트림을 가진 아무 컨테이너**다 — 원본 영상이어도 된다.
    인자 이름이 audio_path였을 때 그것은 wav를 함의했지만, load_audio_mono16k는
    컨테이너를 가리지 않고 같은 배열을 만든다(실측 비트 동일). 지금 CLI가 넘기는
    것은 원본 영상이고, 중간 wav는 만들지 않는다(split.py 머리말).

    기본 모델을 여기 문자열로 다시 적지 않고 base.DEFAULT_MODEL을 쓴다.
    cli는 늘 model을 넘기므로 지금 산출물이 틀어지지는 않지만, 기본값을 두 곳에
    적어 두면 한쪽만 바뀌는 날 라이브러리로 부른 쪽과 CLI가 다른 모델을 쓴다
    (실제로 tiny→small 변경 때 이 자리가 tiny로 남아 갈렸다)."""
    from .. import media
    name = resolve_backend(backend)
    audio = media.load_audio_mono16k(media_path)
    if name == "mlx":
        from . import backend_mlx
        return backend_mlx.transcribe(audio, model_size, language=language)
    from . import backend_fwhisper
    return backend_fwhisper.transcribe(audio, model_size, language=language)
