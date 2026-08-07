"""대사 싱크 창 — Apple Music 가사 싱크 방식.

현재 재생 위치의 세그먼트를 하이라이트하고 자동 스크롤(가운데 정렬),
클릭하면 그 시점으로 seek. importance-point의 트리거 대사에는 ★ 표시.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..session import Session
from . import fmt_time

DIM = QColor(140, 140, 140)


class DialogueSyncWindow(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(460, 720)
        self._idx: int | None = None

        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.setWordWrap(True)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 전역 단축키 우선
        self._list.itemClicked.connect(
            lambda item: session.engine.seek(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self._list)

        session.engine.positionChanged.connect(self._on_pos)
        session.store.reloaded.connect(self._populate)
        self._populate()

    def _populate(self) -> None:
        st = self.session.store
        triggers = {(td["start"], td["text"])
                    for f in st.frames for td in f.get("trigger_dialogue", [])}
        self._list.clear()
        for seg in st.segments:
            star = "★ " if (seg["start"], seg["text"]) in triggers else ""
            item = QListWidgetItem(f"{star}[{fmt_time(seg['start'])}] {seg['text']}")
            item.setData(Qt.ItemDataRole.UserRole, seg["start"])
            item.setForeground(DIM)
            self._list.addItem(item)
        self._idx = None
        self._on_pos(self.session.engine.position())

    def _on_pos(self, t: float) -> None:
        idx = self.session.store.segment_index_at(t)
        if idx == self._idx:
            return
        if self._idx is not None and self._idx < self._list.count():
            prev = self._list.item(self._idx)
            prev.setForeground(DIM)
            font = prev.font()
            font.setBold(False)
            prev.setFont(font)
        self._idx = idx
        if idx is None:
            return
        item = self._list.item(idx)
        item.setForeground(self.palette().text())
        item.setFont(self._bold_font(item))
        self._list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)

    def _bold_font(self, item) -> QFont:
        font = item.font()
        font.setBold(True)
        return font
