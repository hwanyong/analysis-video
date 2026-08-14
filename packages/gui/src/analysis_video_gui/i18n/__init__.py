"""현지화 엔진 — GUI에 보이는 모든 문자열의 단일 통로.

Qt Linguist(.ts/.qm) 대신 파이썬 카탈로그를 쓴다. 이 프로젝트는 uv workspace
순수 파이썬이라 빌드 단계가 없는데, .qm은 lrelease 컴파일 산출물이라 저장소에
바이너리를 넣거나 빌드 훅을 새로 만들어야 한다. 게다가 Qt Designer .ui를 쓰지
않아 `retranslateUi`가 자동 생성되지 않으므로, 어느 쪽을 택하든 재번역은 손으로
짜야 한다 — 빌드 단계만 늘고 얻는 것이 없다.

규칙:
- 화면에 나가는 문자열은 예외 없이 `tr(키, **인자)`를 거친다(리터럴 금지).
- 카탈로그는 키 하나에 세 언어를 나란히 둔다 — 빠진 번역이 눈에 바로 띈다.
- 언어 전환은 `Session.set_language()` 하나로만 일어나고, 열린 창은
  `languageChanged` → `retranslate()`로 따라온다.
"""
from PySide6.QtCore import QLocale

from ..settings import app_settings
from .catalog import CATALOG

# (코드, 원어 표기) — 표기는 항상 그 언어로 쓴다. 지금 UI를 못 읽는 사용자도
# 자기 언어를 찾을 수 있어야 언어 선택이 제 구실을 한다.
LANGUAGES = (("ko", "한국어"), ("en", "English"), ("ja", "日本語"))
CODES = tuple(code for code, _ in LANGUAGES)
DEFAULT = "en"          # 시스템 언어를 못 알아볼 때의 최후 수단, 그리고 번역 폴백
SETTINGS_KEY = "language"

_current = DEFAULT


def current() -> str:
    return _current


def set_language(code: str) -> bool:
    """현재 언어 교체. 실제로 바뀌었으면 True — 호출자가 재번역 여부를 정한다."""
    global _current
    if code not in CODES or code == _current:
        return False
    _current = code
    return True


def _system_language() -> str | None:
    """시스템 UI 언어 선호 순서에서 우리가 아는 첫 언어. 없으면 None.

    `QLocale.system().name()`이 아니라 `uiLanguages()`를 본다. name()은 지역·형식
    로케일(날짜/숫자 표기)이라 "en_US"처럼 사용자가 읽고 싶은 언어와 어긋날 수 있다.
    uiLanguages()는 OS의 UI 언어 선호 목록을 순서대로 준다 — 우리가 아는 언어가
    나올 때까지 훑는 것이 사용자 의사에 가장 가깝다.
    태그는 "en-Latn-US"처럼 문자체계·지역이 붙어 오므로 언어 부분만 본다."""
    for tag in QLocale.system().uiLanguages():
        code = tag.split("-")[0].lower()
        if code in CODES:
            return code
    return None


def init() -> str:
    """시작 언어 = 사용자가 마지막으로 고른 것 → 시스템 UI 언어 → 기본값(영어).

    한 번이라도 고른 적이 있으면 그것이 시스템보다 우선한다 — 시스템 언어와 다른
    언어로 이 도구를 쓰는 것은 충분히 있을 수 있는 선택이고, 그 선택을 매번
    시스템이 덮어쓰면 고르는 의미가 없다.

    QApplication보다 먼저 불릴 수 있어야 한다 — argparse 도움말과 기동 실패
    메시지도 현지화 대상이고, 그 시점엔 아직 앱 객체가 없다."""
    global _current
    saved = app_settings().value(SETTINGS_KEY)
    if isinstance(saved, str) and saved in CODES:
        _current = saved
    else:
        _current = _system_language() or DEFAULT
    return _current


def has(key: str) -> bool:
    """카탈로그에 있는 키인가 — 열린 집합(파이프라인이 만든 값)을 표시할 때 쓴다."""
    return key in CATALOG


def tr(key: str, **kwargs) -> str:
    """키를 현재 언어 문자열로. 인자는 str.format 자리표시자로 채운다.

    번역이 비면 기본 언어로, 키 자체가 없으면 키를 그대로 돌려준다 — 화면에
    `hub.save_layout` 같은 날 키가 보이면 누락을 즉시 알아챌 수 있다.
    (누락 자체는 test_i18n이 전수로 막는다.)"""
    entry = CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(_current) or entry.get(DEFAULT) or key
    return text.format(**kwargs) if kwargs else text


def native_name(code: str) -> str:
    return dict(LANGUAGES).get(code, code)
