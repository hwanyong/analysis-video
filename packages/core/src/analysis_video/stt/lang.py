"""언어 코드 — 형식 정규화·동치 판정·시스템 로케일 해석의 단일 출처.

이 저장소에서 언어 코드는 세 경로로 들어오고, **표기 표준이 서로 다르다**:

- 사이드카 파일명의 태그(`강의.ko.srt` → `ko`) — yt-dlp를 비롯한 도구의 관행은
  ISO 639-1(2글자)이다.
- 컨테이너 자막 트랙이 선언한 언어(`kor`) — Matroska·MP4는 ISO 639-2(3글자)를 쓴다.
- whisper가 감지한 언어(`ko`) — 모델의 언어 토큰이라 639-1이다.

그래서 **같은 한국어 자막이 경로에 따라 `ko`도 되고 `kor`도 된다**(실측). 비교
규칙이 한 곳에 없으면 "요청한 언어와 일치한다"가 경로마다 다른 뜻이 되고, 실제로
사이드카 선택만 `ko ↔ ko-KR`을 알고 있었다.

**대조표는 넣지 않는다.** ISO 639-2/B(`ger`·`fre`·`chi`)까지 맞히려면 언어 전체의
표가 필요한데, 그것은 이 도구가 관리할 데이터가 아니고(낡으면 조용히 틀린다)
파이썬 표준 라이브러리에도 없다. 대신 접두사 규칙으로 정직한 범위만 다루고
한계를 matches에 적어 둔다. 판정이 틀려도 후보가 **탈락하지는 않는다** — 이 모듈의
결과는 자막 후보의 **순위**에만 쓰이므로, 못 맞힌 대가는 "덜 좋은 순서"이지
"쓸 수 있는 자막을 잃음"이 아니다.
"""
import os
import re
from collections.abc import Mapping

# 로케일 환경변수의 우선순위. LC_ALL > LC_MESSAGES > LANG은 POSIX가 정한 순서이고,
# LANGUAGE는 그 뒤에 붙인 GNU 확장이다(리눅스 데스크톱이 선호 언어 목록을 여기에만
# 넣는 경우가 있다). **먼저 설정된 변수 하나가 결정한다** — 아래 from_locale 참조.
_LOCALE_VARS = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")
# 로케일 문자열에서 언어 뒤에 붙는 것들: `.UTF-8`(인코딩) `@euro`(변형)
# `ko:en`(LANGUAGE의 목록). 첫 구분자 앞까지가 로케일 이름이다.
_LOCALE_TAIL = re.compile(r"[.@:]")
# "로케일 없음"의 표준 표기. 언어로 읽으면 안 된다 — C 로케일은 특정 언어가 아니라
# "어떤 언어도 가정하지 않는다"는 선언이다.
_NEUTRAL_LOCALES = ("", "c", "posix")


def normalize(tag: str | None) -> str | None:
    """언어 태그의 **형식**만 통일한다 — 소문자, 하위 태그 구분자는 `-`.

    `KO` → `ko`, `ko_KR` → `ko-kr`, `KOR` → `kor`, 빈 값 → None.

    표준 사이의 차이(`ko` ↔ `kor`)는 여기서 고치지 않는다. 3글자를 2글자로 바꾸려면
    머리말이 거부한 대조표가 필요하고, 표 없이 추측해 고쳐 적으면 산출물의
    `source.language`에 **거짓 선언**이 남는다. 그 필드는 "출처가 뭐라고 했는가"의
    감사 기록이므로 출처가 말한 코드를 그대로 두고, 같은 언어인지는 matches가 판정한다.
    형식만 통일하는 것은 그 기록을 고쳐 쓰는 것이 아니라 대소문자·구분자처럼
    **뜻이 없는 차이**를 걷어내는 것이라 안전하다(`ko_KR`과 `ko-KR`은 같은 선언이다).

    지역을 소문자로 남기는 것(`ko-kr`)은 BCP 47의 표기 관행(`ko-KR`)과 다르지만,
    이 저장소에서 태그를 쓰는 곳은 비교와 기록뿐이고 둘 다 대소문자를 보지 않는다 —
    관행을 맞추려면 하위 태그의 길이로 대문자·제목 표기를 갈라야 해서, 쓰지도 않을
    규칙이 하나 더 는다."""
    if not tag:
        return None
    return tag.strip().replace("_", "-").lower() or None


def matches(tag: str | None, want: str | None) -> bool:
    """두 코드가 같은 언어인가. 어느 한쪽이라도 없으면 False(= 판정 근거가 없다).

    세 가지를 같은 언어로 본다:

    1. 같은 코드 (`ko` = `KO`)
    2. 1차 부표(primary subtag)가 같은 것 — 지역·문자체계는 보지 않는다
       (`ko` = `ko-KR`, `zh-Hans` = `zh-Hant`). 대사를 알아들을 수 있는가가 기준이라
       표기 변종까지 갈라 세울 이유가 없다.
    3. ISO 639-1(2글자) ↔ 639-2/T(3글자) (`ko` = `kor`, `de` = `deu`)

    **3의 한계를 명시한다.** 접두사 비교라 639-2/B 변종(`de` ↔ `ger`, `fr` ↔ `fre`,
    `zh` ↔ `chi`)은 잡지 못하고, 반대로 무관한 3글자 코드를 잡는 오탐도 있다
    (`bo`(티베트어)와 `bos`(보스니아어)). 표를 들이지 않기로 한 대가이고(머리말),
    대가의 크기는 순위 한 칸이다: 이 판정은 자막 후보를 거르는 데 쓰이지 않고
    정렬 키로만 쓰이므로, 틀려도 그 자막은 여전히 후보로 남는다. 실제로 쓸 수 없는
    자막은 뒤에서 내용 검증(subtitles.evaluate)이 걸러 낸다."""
    a, b = normalize(tag), normalize(want)
    if a is None or b is None:
        return False
    if a == b:
        return True
    primary_a, primary_b = a.split("-")[0], b.split("-")[0]
    if primary_a == primary_b:
        return True
    short, long_ = sorted((primary_a, primary_b), key=len)
    return len(short) == 2 and len(long_) == 3 and long_.startswith(short)


def from_locale(env: Mapping[str, str] | None = None) -> str | None:
    """시스템 로케일이 말하는 언어. `ko_KR.UTF-8` → `ko`, `C`/`POSIX`/미설정 → None.

    `locale.getlocale()`이 아니라 환경변수를 직접 읽는 이유가 둘이다.
    ① getlocale()은 `setlocale()`을 부르기 전에는 사용자의 언어가 아니라 LC_CTYPE의
       현재 상태를 말한다. 실측(파이썬 3.12): `LANG=C`에서 `('C', 'UTF-8')`,
       `LC_ALL=en_US.UTF-8 LANG=ko_KR.UTF-8`에서는 `(None, None)`, 메시지 카테고리
       (`getlocale(LC_MESSAGES)`)는 세 경우 모두 `(None, None)`이었다 — 답이 환경마다
       다르고 정작 언어를 담고 있지 않다. 제대로 읽으려면 `setlocale(LC_ALL, "")`로
       프로세스 전역 상태를 바꿔야 하는데, 숫자·날짜 서식까지 함께 갈리는 그 부작용은
       라이브러리가 몰래 일으킬 일이 아니다. 이 문제가 없는 getdefaultlocale()은
       파이썬 3.11에서 폐기 예고된 API라 새로 기대기에 부적절하다.
    ② 테스트가 로케일을 주입할 수 있어야 한다(monkeypatch.setenv 또는 env 인자).
       같은 환경에서 늘 같은 값이 나오는 것도 여기서 나온다 — 프로세스 상태(setlocale
       호출 여부)에 좌우되지 않는다.

    **먼저 설정된 변수 하나가 결정한다**(우선순위는 _LOCALE_VARS). 값이 C/POSIX면
    거기서 None으로 끝내고 다음 변수를 보지 않는다: `LC_ALL=C` 아래에서 `LANG=ko_KR`을
    주워 오면 "이 실행에서는 언어를 가정하지 않는다"는 선언을 뒤집는 셈이다.

    돌려주는 것은 1차 부표뿐이다(`ko_KR` → `ko`). 지역은 이 도구가 쓸 데가 없고,
    `ko`로 두면 `ko`·`ko-KR`·`kor` 자막이 모두 matches를 통과한다.

    None은 오류가 아니라 "언어 무관"이다 — macOS의 GUI 실행처럼 LANG이 아예 없는
    환경이 정상적으로 존재하고, 그때는 언어를 기준으로 자막을 고르지 않을 뿐이다."""
    env = os.environ if env is None else env
    for var in _LOCALE_VARS:
        value = (env.get(var) or "").strip()
        if not value:
            continue
        primary = _LOCALE_TAIL.split(value, 1)[0].replace("_", "-").split("-")[0].lower()
        return None if primary in _NEUTRAL_LOCALES else primary
    return None
