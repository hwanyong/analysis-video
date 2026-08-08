"""독립 창들의 공통 베이스.

세션 수명 객체(engine/store/session/flags)의 시그널에 연결한 슬롯은 창이 닫힌 뒤에도
송신자 쪽에 남는다 — 특히 람다는 수신자 컨텍스트가 없어 자동 해제되지 않으므로,
파괴된 위젯을 건드려 RuntimeError가 쏟아지고 창 객체가 누수된다.
bind()로 연결을 장부에 기록하고 닫힐 때 전부 해제해, 연결 방식(람다/바운드 메서드)과
무관하게 수명 안전을 보장한다.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def fmt_time(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:05.2f}"


class ChildWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._conns: list[tuple] = []

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
