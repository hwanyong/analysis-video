"""비교 리포트 창 — 사용자 GT 플래그 vs 로직 검출의 정량 비교.

F키(또는 버튼)로 "여기서 추출됐어야 한다"를 기입하면, 허용오차 내 최근접
채택 프레임과 매칭해 precision/recall을 산출한다. compare.json으로 내보내
탐지기 튜닝의 정량 근거로 쓴다 — 초기 기획의 비교 메타데이터 출력 요건.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from analysis_video.manifest import write_json_atomic

from ..flags import compare_metrics
from ..session import Session
from . import ChildWindow, fmt_time


class CompareWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.resize(560, 560)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("허용오차(초):"))
        self._tol = QDoubleSpinBox()
        # 창을 여는 것만으로 포커스를 가져가지 않게 — 그러면 전역 단축키가 죽는다.
        # 클릭(또는 Tab)했을 때만 편집 포커스를 받고, Esc로 되돌린다.
        self._tol.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._tol.setRange(0.5, 10.0)
        self._tol.setSingleStep(0.5)
        self._tol.setValue(2.0)
        self._tol.setToolTip("GT 플래그와 검출 프레임을 같은 것으로 볼 시간 오차 (Esc: 편집 종료)")
        self._tol.valueChanged.connect(self._recompute)
        top.addWidget(self._tol)
        top.addStretch()
        add_btn = QPushButton("현재 시각 플래그 추가/제거 (F)")
        add_btn.clicked.connect(self._add_flag_here)
        del_btn = QPushButton("선택 삭제")
        del_btn.clicked.connect(self._delete_selected)
        export_btn = QPushButton("compare.json 내보내기")
        export_btn.clicked.connect(self._export)
        for b in (add_btn, del_btn, export_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            top.addWidget(b)
        layout.addLayout(top)

        self._summary = QLabel()
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["GT 플래그", "매칭 검출", "Δ(초)", "판정"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)

        self._fp_label = QLabel()
        self._fp_label.setWordWrap(True)
        layout.addWidget(self._fp_label)

        self.bind(session.flags.changed, self._recompute)
        self.bind(session.store.reloaded, self._recompute)
        self._recompute()

    def _add_flag_here(self) -> None:
        self.session.flags.toggle(self.session.engine.position())

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        # 테이블은 항상 flags 배열 순서(시간 오름차순)로 채워지므로 인덱스가 일치한다
        flags = self.session.flags.flags
        if 0 <= row < len(flags):
            self.session.engine.seek(flags[row]["time"])

    def _metrics(self) -> dict:
        detected = [f["time"] for f in self.session.store.frames]
        return compare_metrics(self.session.flags.times(), detected, self._tol.value())

    def _recompute(self) -> None:
        m = self._metrics()
        prec = "—" if m["precision"] is None else f"{m['precision']:.1%}"
        rec = "—" if m["recall"] is None else f"{m['recall']:.1%}"
        self._summary.setText(
            f"GT {m['n_flags']}개 · 검출 {m['n_detected']}개 &nbsp;|&nbsp; "
            f"<b>precision {prec}</b> (검출 중 GT 근방 비율) &nbsp; "
            f"<b>recall {rec}</b> (GT 중 검출된 비율)")

        matched_by_flag = {x["flag"]: x for x in m["matched"]}
        flags = self.session.flags.flags
        self._table.setRowCount(len(flags))
        for row, fl in enumerate(flags):
            hit = matched_by_flag.get(fl["time"])
            cells = [fmt_time(fl["time"]),
                     fmt_time(hit["detected"]) if hit else "—",
                     f"{hit['gap']:+.2f}" if hit else "—",
                     "TP ✓" if hit else "FN ✗ (로직이 놓침)"]
            for col, text in enumerate(cells):
                self._table.setItem(row, col, QTableWidgetItem(text))

        fp = m["extra_detected"]
        shown = ", ".join(fmt_time(t) for t in fp[:10])
        more = f" 외 {len(fp) - 10}건" if len(fp) > 10 else ""
        self._fp_label.setText(
            f"<b>GT 없는 검출(FP 후보) {len(fp)}건:</b> {shown}{more}" if fp
            else "GT 없는 검출: 없음")

    def _delete_selected(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.session.flags.remove(row)

    def _export(self) -> None:
        out = self.session.out_dir / "compare.json"
        write_json_atomic(out, {"flags": self.session.flags.flags, **self._metrics()})
        self._summary.setText(self._summary.text() +
                              f" &nbsp;<span style='color:#5a5'>→ {out.name} 저장됨</span>")
