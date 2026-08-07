"""허브 창 — 세션의 루트 창. 창 열기/닫기 토글, 레이아웃 저장/복원, 상태 표시.

이 창을 닫으면 전체 애플리케이션이 종료된다(수명주기 루트).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..session import REGISTRY, Session


class HubWindow(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.setWindowTitle(f"analysis-video 허브 — {session.video_path.name}")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>영상:</b> {session.video_path.name}"))

        group = QGroupBox("창 (체크 = 열기)")
        grid = QGridLayout(group)
        self._checks: dict[str, QCheckBox] = {}
        for i, (wid, title) in enumerate(REGISTRY):
            cb = QCheckBox(title)
            cb.toggled.connect(lambda on, wid=wid: self._on_toggle(wid, on))
            grid.addWidget(cb, i // 2, i % 2)
            self._checks[wid] = cb
        layout.addWidget(group)

        row = QHBoxLayout()
        save_btn = QPushButton("레이아웃 저장")
        save_btn.clicked.connect(session.save_layout)
        restore_btn = QPushButton("레이아웃 복원")
        restore_btn.clicked.connect(session.restore_layout)
        help_btn = QPushButton("단축키 (?)")
        help_btn.clicked.connect(session.show_shortcut_help)
        row.addWidget(save_btn)
        row.addWidget(restore_btn)
        row.addWidget(help_btn)
        layout.addLayout(row)

        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._status)

        session.windowsChanged.connect(self._sync_checks)
        session.store.reloaded.connect(self._update_status)
        self._update_status()
        self._sync_checks()

    def _on_toggle(self, wid: str, on: bool) -> None:
        if on:
            self.session.open_window(wid)
        else:
            self.session.close_window(wid)

    def _sync_checks(self) -> None:
        for wid, cb in self._checks.items():
            cb.blockSignals(True)
            cb.setChecked(wid in self.session.windows)
            cb.blockSignals(False)

    def _update_status(self) -> None:
        st = self.session.store
        if st.metadata:
            self._status.setText(
                f"{st.metadata.get('schema', '?')} · 채택 {len(st.frames)} / "
                f"탈락 {len(st.rejected)} · 세그먼트 {len(st.segments)}<br>"
                f"<span style='color:gray'>산출물 변경 감시 중 — CLI 재분석 시 자동 갱신</span>")
        else:
            self._status.setText(
                "<span style='color:#c60'>metadata.json 없음 — frames 스테이지를 먼저 "
                "실행하세요 (플레이어만 사용 가능)</span>")

    def closeEvent(self, ev) -> None:
        self.session.save_layout()
        self.session.shutdown()
        super().closeEvent(ev)
