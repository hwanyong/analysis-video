"""앱 설정 저장소의 단일 진입점.

조직/앱 이름이 호출처마다 흩어지면 같은 앱이 서로 다른 파일에 쓰게 된다 —
언어(앱 시작 시점, Session 이전)와 레이아웃(Session 소관)이 같은 저장소를
봐야 하므로 식별자는 여기 한 곳에만 둔다.
"""
from PySide6.QtCore import QSettings

ORG = "analysis-video"
APP = "gui"


def app_settings() -> QSettings:
    """QApplication 이전에도 열 수 있다 — 생성자에 조직/앱을 직접 주기 때문.

    저장 형식을 명시적으로 넘긴다. `QSettings(조직, 앱)` 2인자 생성자는
    NativeFormat으로 고정돼 있어 `setDefaultFormat`이 통하지 않는다 —
    그러면 저장 위치를 바꿀 방법이 없어서, 테스트가 개발자의 실제 설정
    (macOS plist)에 언어와 창 위치를 써 버린다. 기본값은 그대로
    NativeFormat이므로 실사용 동작은 달라지지 않는다."""
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, ORG, APP)
