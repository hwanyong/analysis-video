"""허브 창 — 세션의 루트 창. 창 열기/닫기 토글, 레이아웃 저장/복원, 상태 표시.

이 창을 닫으면 전체 애플리케이션이 종료된다(수명주기 루트).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..session import REGISTRY, Session


class HubWindow(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.setWindowTitle(f"analysis-video 허브 — {session.video_path.name}")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>영상:</b> {session.video_path.name}"))
        layout.addWidget(self._build_units())

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
        session.store.reloaded.connect(self._sync_units)
        self._update_status()
        self._sync_checks()

    def _build_units(self) -> QGroupBox:
        """분석 단위 선택 — `--range`를 여러 번 주면 독립 결과물이 그만큼 생긴다.
        구간이 겹치면 같은 시각도 단위마다 다르게 보이므로, 무엇을 보고 있는지
        항상 드러나 있어야 한다. 전환은 데이터만 갈아끼우고 창들은 따라온다."""
        box = QGroupBox("분석 단위")
        col = QVBoxLayout(box)
        self._unit_combo = QComboBox()
        self._unit_combo.currentTextChanged.connect(self._on_unit_pick)
        col.addWidget(self._unit_combo)
        self._unit_note = QLabel()
        self._unit_note.setStyleSheet("color:gray;")
        self._unit_note.setWordWrap(True)
        col.addWidget(self._unit_note)
        self._sync_units()
        return box

    def _sync_units(self) -> None:
        st = self.session.store
        entries = st.available_units()
        self._unit_combo.blockSignals(True)
        self._unit_combo.clear()
        for e in entries:
            rng = e.get("range")
            span = "영상 전체" if rng is None else f"{rng[0]:.1f}~{rng[1]:.1f}초"
            self._unit_combo.addItem(f"{e['name']}  ({span})", e["name"])
        if st.unit is not None:
            i = self._unit_combo.findData(st.unit)
            if i >= 0:
                self._unit_combo.setCurrentIndex(i)
        self._unit_combo.blockSignals(False)
        self._unit_combo.setEnabled(len(entries) > 1)
        if len(entries) > 1:
            self._unit_note.setText(
                "단위는 서로 독립입니다 — 구간이 겹치면 같은 시각도 단위마다 "
                "다르게 나뉠 수 있습니다.")
        elif entries:
            self._unit_note.setText("분석 단위가 하나뿐입니다 "
                                    "(CLI에서 --range로 부분 분석을 추가할 수 있습니다).")
        else:
            self._unit_note.setText("분석 단위 없음 — frames를 먼저 실행하세요.")

    def _on_unit_pick(self, _text: str) -> None:
        name = self._unit_combo.currentData()
        if name:
            self.session.set_unit(name)

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
                f"단위 <b>{st.unit}</b> · 구간 {st.window[0]:.1f}~{st.window[1]:.1f}초<br>"
                f"화면 {len(st.screens)} · 채택 {len(st.frames)} / "
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
