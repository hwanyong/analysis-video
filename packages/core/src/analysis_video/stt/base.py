"""전사 결과의 공통 계약.

전사가 어디서 왔든(자막 파일·컨테이너 내장 트랙·whisper·오디오 없음) 아래 스키마의
dict 하나로 나온다 — 소비자(frames·align·metadata·GUI)는 출처를 몰라도 된다:

{
  "text":     str,                                             # 전체 전사
  "segments": [{"start": float, "end": float, "text": str}],   # 문장 단위
  "words":    [{"word": str, "start": float, "end": float}],   # 단어 타임스탬프
  "backend":  "subtitle" | "mlx" | "faster-whisper" | "none",
  "device":   "none" | "metal" | "cuda" | "cpu",
  "model":    str,        # 자막이면 포맷명("srt"/"vtt"/"smi"), whisper면 모델 크기
  "source":   {...},      # 이 전사가 어디서 왔는가 — build_source() 참조
}

열거에 "none"이 있는 이유: 오디오 스트림이 없는 영상은 예전부터
backend="none"/device="none"을 산출하고 있었는데 이 표에는 빠져 있었다 —
**선언과 산출이 갈려 있었다**. 스키마 문서가 실제 산출의 부분집합이면 소비자는
문서를 믿을 수 없으므로 이번에 맞춘다. "subtitle"은 자막 출처가 추가되며 새로
생긴 값이다.

words가 백엔드마다 다른 것도 계약의 일부다: 자막 출처는 큐 단위 시각만 있고
단어 시각이 없으므로 **항상 빈 배열**이다. 자막에서 단어 시각을 추정해 채우지
않는다 — 없는 정밀도를 만들어 내면 소비자가 그것을 whisper의 단어 시각과 같은
근거로 취급한다.
"""

import contextlib

from ..errors import EXIT_DEPS, CliError
from . import lang

MODEL_SIZES = ("tiny", "base", "small", "medium", "large", "turbo")
# CLI 기본값이자 에이전트 가이드가 안내하는 값 — 두 군데 적으면 갈린다.
#
# tiny → small (자막 우선 채택과 함께 바뀐 값). 자막 파일·내장 트랙을 먼저 찾게 된
# 뒤로 whisper가 도는 경우는 "자막이 아예 없는 영상"만 남는다. 대사를 얻을 다른
# 수단이 없어 전사 품질이 곧 산출물 전체의 품질이 되는, 가장 잘 받아써야 하는
# 상황만 남는 셈이다. tiny는 정반대 가정(자막 유무와 무관하게 whisper가 늘 돌던
# 시절, 속도로 파이프라인 전체를 지키던 값)에서 고른 값이라 그대로 두면 가장
# 아쉬운 자리에 가장 약한 모델이 남는다.
#
# 정직한 한계: 이 값은 실측으로 확정한 것이 아니다. 이 저장소의 STT 실측은
# README.md:148의 "Apple Silicon·mlx·tiny에서 37.6배 실시간" 하나뿐이고 small의
# 속도·정확도는 재지 않았다. 가중치도 약 74MB → 약 460MB로 늘어난다.
DEFAULT_MODEL = "small"

# source.kind가 가질 수 있는 값. 사다리의 단계 이름과 1:1이다:
#   explicit  --transcript로 사용자가 직접 지정한 자막 파일
#   sidecar   원본 옆에서 찾아낸 자막 파일
#   embedded  컨테이너 안에 들어 있던 자막 트랙 (split이 뽑아 둔 것)
#   whisper   자막을 못 찾아 음성을 받아쓴 경우
#   none      전사 자체가 없음 (오디오도 자막도 없는 영상)
SOURCE_KINDS = ("explicit", "sidecar", "embedded", "whisper", "none")


# 모델 가중치 취득 실패로 취급할 예외들. 지연 조회하는 이유: huggingface_hub는
# STT 백엔드에 딸려 오는 간접 의존이라 백엔드가 없는 환경에서는 없을 수 있고,
# 버전에 따라 있는 예외 이름이 다르다 — 없는 이름은 조용히 건너뛴다.
_HF_ERROR_NAMES = (
    "LocalEntryNotFoundError",   # 캐시에 없고 네트워크로도 못 받음
    "OfflineModeIsEnabled",      # HF_HUB_OFFLINE=1
    "HfHubHTTPError",            # 5xx·프록시 차단 등
    "GatedRepoError",            # 승인 필요한 저장소
    "RepositoryNotFoundError",
    "EntryNotFoundError",
)


def _model_fetch_error_types() -> tuple[type[BaseException], ...]:
    try:
        from huggingface_hub import errors as hf
    except ImportError:
        types: tuple[type[BaseException], ...] = ()
    else:
        types = tuple(t for t in (getattr(hf, n, None) for n in _HF_ERROR_NAMES)
                      if isinstance(t, type) and issubclass(t, BaseException))
    return types + (ConnectionError, TimeoutError)


@contextlib.contextmanager
def model_download_guard(model_ref: str):
    """모델 가중치 취득 실패를 종료코드 4(환경 결손)로 변환한다.

    가중치는 패키지에 들어 있지 않고 첫 전사 때 HuggingFace에서 내려온다
    (tiny 약 74MB ~ large 약 3.1GB). 그래서 오프라인·프록시 차단·HF 장애는
    버그가 아니라 환경 결손인데, 감싸지 않으면 cli.main의 포괄 except가
    exit 1 "internal"로 만들어 버린다 — 가장 흔한 결손 한 종에서
    "종료코드만으로 분기한다"는 errors.py의 계약이 통째로 깨지는 셈이다.

    예외 종류로만 판별하므로 추론 단계의 진짜 버그는 그대로 통과한다."""
    try:
        yield
    except CliError:
        raise
    except _model_fetch_error_types() as e:
        raise CliError(
            EXIT_DEPS, "stt-model-unavailable",
            f"STT 모델 '{model_ref}'을 가져올 수 없습니다: {type(e).__name__}: {e}",
            hint="첫 전사에는 모델 다운로드를 위한 네트워크가 필요합니다. "
                 "오프라인이면 온라인 상태에서 같은 --model로 한 번 실행해 캐시를 만든 뒤 "
                 "재실행하세요. 캐시 위치·상태는 'analysis-video doctor'가 보고합니다.",
        ) from e


def build_source(kind: str, *, path: str | None = None, track: int | None = None,
                 format: str | None = None, language: str | None = None,
                 n_cues: int = 0, coverage: float = 0.0,
                 span: tuple[float, float] | list[float] | None = None,
                 notes: list[str] | None = None) -> dict:
    """이 전사가 **어디서 왔는가**의 기록. 모든 키가 항상 존재한다.

    언어 칸이 둘인 것은 물음이 둘이기 때문이다. `language`는 **이 전사가 실제로
    무슨 언어인가**이고, `target_language`는 **사용자가 원한 언어**(--sub-lang 또는
    시스템 로케일)다. 둘을 한 칸에 담으면 "영어 자막밖에 없어 영어로 전사했다"와
    "한국어를 원했고 한국어로 전사했다"가 같은 모양이 된다.

    그중 target_language만 인자가 아니라 아래 mark_target_language가 채운다. 이
    함수를 부르는 쪽(자막 파서·백엔드)은 자기가 무엇에서 왔는지만 알지 사용자가
    무엇을 요청했는지는 모르고, 요청을 아는 것은 사다리를 도는 호출자뿐이다 —
    인자로 열어 두면 아무도 채우지 않는 칸이 하나 생긴다.

    `language`의 성격은 kind가 말해 준다: 자막 출처(explicit·sidecar·embedded)에서는
    파일명이나 컨테이너가 **선언한** 값이고, whisper에서는 모델이 **감지한** 값이다.
    감지 결과도 기록한다 — 추론이라는 이유로 비워 두면 "영어 영상을 한국어로 잘못
    받아썼다"를 산출물만 보고는 말할 수 없다(실측으로 language=None이던 자리다).
    칸 하나를 더 만들어 선언·감지를 구분하지 않는 이유는 kind가 이미 그 구분이기
    때문이다.

    자막을 쓰기 시작하면 같은 transcript.json이라도 신뢰도가 천차만별이 된다 —
    사람이 만든 자막, 강제 자막(외국어 구간만), 자동 생성 자막, whisper 추론이
    전부 같은 모양으로 들어온다. 어느 것이었는지 남기지 않으면 산출물을 읽는
    에이전트도, 나중에 결과를 의심하는 사람도 되짚을 방법이 없다.

    키를 빠뜨리지 않고 전부 채우는 이유는 manifest.build_metadata의 `"requested": []`와
    같다 — 소비자가 kind를 먼저 보고 어느 칸이 있는지 따지지 않고 곧장 읽을 수
    있어야 한다. 그래서 자막이 아닌 출처도 n_cues=0, coverage=0.0으로 **명시적으로**
    0을 적는다. 칸을 빼면 "자막 큐가 0개였다"와 "자막 출처가 아니다"가 같은
    모양(키 없음)이 되어, 읽는 쪽이 없는 칸을 짚거나 조건을 겹겹이 두게 된다.

    notes는 사다리를 내려온 이유를 쌓는 자리다(거부 사유·정제 내역·폴백 사유).
    자막을 거부하고 whisper로 내려갔다면 "왜 거부했는가"가 여기 남아야 한다 —
    거부는 stderr 로그로 흘려보내면 산출물에는 흔적이 남지 않는다.
    """
    if kind not in SOURCE_KINDS:
        # 사용자 입력이 아니라 호출 코드의 오타다 — 조용히 통과시키면 채택 사다리가
        # 인식하지 못하는 kind가 산출물에 박힌다. 내부 오류(exit 1)로 드러낸다.
        raise ValueError(f"알 수 없는 전사 출처 종류: {kind!r} (가능: {SOURCE_KINDS})")
    return {
        "kind": kind,
        "path": path,
        "track": track,
        "format": format,
        "language": lang.normalize(language),
        # 칸은 여기서 만들되 값은 mark_target_language가 넣는다 — 요청을 모르는
        # 자리에서 지어내지 않으면서도, 소비자는 kind와 무관하게 이 키를 읽는다.
        "target_language": None,
        "n_cues": n_cues,
        # 반올림 자리수는 소비자 편의일 뿐 판정에 쓰지 않는다(판정은 원값으로).
        "coverage": round(float(coverage), 4),
        "span": [round(float(span[0]), 2), round(float(span[1]), 2)] if span else None,
        "notes": list(notes or []),
    }


def build_result(text: str, segments: list[dict], words: list[dict],
                 backend: str, device: str, model: str,
                 source: dict | None = None) -> dict:
    """모든 전사 출처가 반드시 통과하는 단 하나의 조립 지점.

    source를 넘기지 않으면 kind="none"(출처 미기록)이 된다. 기본값을 둔 것은
    기존 백엔드 호출을 깨지 않기 위해서이고, 새 출처를 추가하면서 이 인자를
    빠뜨리면 감사 기록이 비어 있는 것이 산출물에서 바로 보이게 하려는 것이다 —
    그럴듯한 값을 지어내 채우지 않는다."""
    return {
        "text": text.strip(),
        "segments": segments,
        "words": words,
        "backend": backend,
        "device": device,
        "model": model,
        "source": source if source is not None else build_source("none"),
    }


def empty_result(notes: list[str] | None = None) -> dict:
    """전사할 것이 없는 영상의 결과 — 스키마는 그대로 지키고 내용만 비운다.

    cli.run_transcribe가 이 dict를 손수 만들고 있었다. 저장소에서 build_result를
    거치지 않는 유일한 자리였고, 그래서 스키마를 고칠 때마다 반드시 갈리는
    자리였다(실제로 이번 source 필드가 그랬고, 그 전에는 device="none"이 위
    스키마 독스트링의 열거에 없었다). 조립 지점을 하나로 되돌린다.

    notes에는 여기까지 내려온 사유를 넣는다 — "오디오 스트림 없음"만이 아니라
    앞 단계에서 자막을 거부한 사유까지 함께 실어야 산출물만 보고 판단 경위를
    복원할 수 있다."""
    return build_result("", [], [], backend="none", device="none", model="none",
                        source=build_source("none", notes=notes))


def add_notes(result: dict, notes: list[str]) -> dict:
    """채택 사다리를 내려오며 쌓인 사유를 완성된 전사 결과에 덧붙인다.

    whisper 백엔드는 자기가 몇 단계를 미끄러져 내려와 호출됐는지 모른다 —
    "사이드카 자막을 찾았지만 coverage 0.12로 거부했다" 같은 사유는 사다리를
    도는 쪽(cli.run_transcribe)만 안다. 그 쪽에서 result["source"]["notes"]를
    직접 만지면 empty_result가 회수한 것을 다시 흘리는 셈이라 여기로 모은다."""
    result["source"]["notes"].extend(notes)
    return result


def mark_target_language(result: dict, target: str | None,
                         requested: bool = True) -> bool:
    """목표 언어를 기록하고, 전사의 언어가 그것과 다르면 그 사실을 남긴다.
    반환은 "달랐는가" — 호출자가 결과 JSON에 그대로 실을 수 있게.

    `requested`는 그 목표가 **사용자가 밝힌 것**인지(`--sub-lang`) 아니면 시스템
    로케일에서 온 기본값인지다. 둘을 가르지 않으면 불일치 신고가 오해를 부른다:
    로케일이 `en`인 기계에서 한국어 강의를 한국어 자막으로 **올바르게** 전사해도
    `language_mismatch: true`가 서고, 그것을 받은 에이전트는 무언가 잘못됐다고
    읽는다(실제로 두 에이전트가 각각 해명 문단을 따로 써야 했다). 정책은 그대로
    두되 — 보고는 하고 개입은 안 한다 — **왜 목표가 그것이 되었는지**를 함께
    싣는다. 사용자가 요청한 적 없는 불일치와 요청한 불일치는 다른 사건이다.

    불리언을 돌려주는 것이 중복이 아닌 이유: 두 코드가 같은 언어인지는 ko ↔ kor
    동치 규칙(stt/lang.py)을 알아야 답할 수 있어, 산출물을 읽는 쪽이 두 필드를
    문자열로 비교해 스스로 구할 수 없다. 판정은 그 규칙을 가진 이쪽이 한다.

    **번역은 하지 않는다.** whisper의 `task="translate"`는 목적지가 영어로 고정이라
    한국어 목표를 애초에 만족시키지 못하고, 자막을 다른 언어로 옮겨 적는 일은 이
    도구의 소관이 아니다(대사는 원문 그대로여야 화면·시각과 대조할 수 있다).
    코어가 할 수 있는 정직한 일은 "요청과 다른 언어다"를 정확히 신고하는 데까지다.

    한쪽이라도 모르면 불일치라고 말하지 않는다. 언어 태그가 없는 자막(`강의.srt`)은
    한국어일 수도 영어일 수도 있는데, 모르는 것을 다르다고 적으면 그 경고는
    거의 모든 실행에 뜨고 곧 아무도 읽지 않는다."""
    source = result["source"]
    source["target_language"] = lang.normalize(target)
    # 목표가 어디서 왔는가. 목표 자체가 없으면(로케일도 비어 있으면) null —
    # "요청도 로케일도 없었다"와 "로케일이 정했다"는 다른 상태다.
    source["target_language_source"] = (
        None if source["target_language"] is None
        else ("requested" if requested else "locale"))
    found, want = source["language"], source["target_language"]
    if want is None or found is None or lang.matches(found, want):
        return False
    origin = ("요청한 자막 언어는" if requested
              else "시스템 로케일에서 정해진 목표 언어는")
    tail = ("" if requested else
            " (--sub-lang으로 언어를 밝히면 이 신고는 그 요청 기준이 됩니다)")
    source["notes"].append(
        f"전사의 언어는 '{found}'인데 {origin} '{want}'입니다 — "
        f"이 도구는 번역하지 않으므로 대사는 '{found}' 그대로입니다{tail}")
    return True
