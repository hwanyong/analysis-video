"""독립 창들의 공통 베이스.

세션 수명 객체(engine/store/session/flags)의 시그널에 연결한 슬롯은 창이 닫힌 뒤에도
송신자 쪽에 남는다 — 특히 람다는 수신자 컨텍스트가 없어 자동 해제되지 않으므로,
파괴된 위젯을 건드려 RuntimeError가 쏟아지고 창 객체가 누수된다.
bind()로 연결을 장부에 기록하고 닫힐 때 전부 해제해, 연결 방식(람다/바운드 메서드)과
무관하게 수명 안전을 보장한다.

언어 전환도 여기서 한 번만 연결한다: 세션의 languageChanged를 받아 각 창의
`retranslate()`가 불린다. 창마다 따로 연결하면 새 창이 하나만 빠져도 그 창만
옛 언어로 남는데, 그 사실을 알아챌 방법이 없다.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def fmt_time(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:05.2f}"


class ChildWindow(QWidget):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._conns: list[tuple] = []
        self.bind(session.languageChanged, self.retranslate)

    def retranslate(self) -> None:
        """현재 언어로 이 창의 모든 표시 문자열을 다시 채운다.

        기본 구현을 두지 않는 이유: 조용히 아무것도 안 하는 창이 생기면 그 창만
        옛 언어로 남고 아무도 모른다. 번역할 것이 없는 창도 그 사실을 명시적으로
        선언하게 한다."""
        raise NotImplementedError(f"{type(self).__name__}.retranslate()가 없습니다")

    def bind(self, signal, slot) -> None:
        signal.connect(slot)
        self._conns.append((signal, slot))

    def _unbind_all(self) -> None:
        for signal, slot in self._conns:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass  # 이미 해제됨 / 송신자 파괴됨
        self._conns.clear()

    def closeEvent(self, ev) -> None:
        self._unbind_all()
        super().closeEvent(ev)
