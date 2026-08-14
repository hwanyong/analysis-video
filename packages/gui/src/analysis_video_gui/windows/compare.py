"""비교 리포트 창 — 사용자 GT 플래그 vs 로직 검출의 정량 비교.

F키(또는 버튼)로 "여기서 추출됐어야 한다"를 기입하면, 허용오차 내 최근접
채택 프레임과 매칭해 precision/recall을 산출한다. compare.json으로 내보내
탐지기 튜닝의 정량 근거로 쓴다 — 초기 기획의 비교 메타데이터 출력 요건.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from analysis_video.manifest import write_json_atomic

from ..flags import compare_metrics
from ..i18n import tr
from ..session import Session
from . import ChildWindow, fmt_time


class CompareWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__(session)
        self.resize(560, 560)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self._tol_label = QLabel()
        top.addWidget(self._tol_label)
        self._tol = QDoubleSpinBox()
        # 창을 여는 것만으로 포커스를 가져가지 않게 — 그러면 전역 단축키가 죽는다.
        # 클릭(또는 Tab)했을 때만 편집 포커스를 받고, Esc로 되돌린다.
        self._tol.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._tol.setRange(0.5, 10.0)
        self._tol.setSingleStep(0.5)
        self._tol.setValue(2.0)
        self._tol.valueChanged.connect(self._recompute)
        top.addWidget(self._tol)
        top.addStretch()
        self._add_btn = QPushButton()
        self._add_btn.clicked.connect(self._add_flag_here)
        self._del_btn = QPushButton()
        self._del_btn.clicked.connect(self._delete_selected)
        self._export_btn = QPushButton()
        self._export_btn.clicked.connect(self._export)
        for b in (self._add_btn, self._del_btn, self._export_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            top.addWidget(b)
        layout.addLayout(top)

        self._summary = QLabel()
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 4)
        # 열 폭을 기본값에 두면 머리글이 언어에 따라 잘린다("Matched detection" 등).
        # 네 열이 폭을 나눠 갖게 해 어느 언어에서도 머리글이 온전히 보이게 한다.
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table)

        self._fp_label = QLabel()
        self._fp_label.setWordWrap(True)
        layout.addWidget(self._fp_label)

        self.bind(session.flags.changed, self._recompute)
        self.bind(session.store.reloaded, self._recompute)
        self.retranslate()

    def retranslate(self) -> None:
        self._tol_label.setText(tr("compare.tolerance"))
        self._tol.setToolTip(tr("compare.tolerance_tip"))
        self._add_btn.setText(tr("compare.add_flag"))
        self._del_btn.setText(tr("compare.delete_selected"))
        self._export_btn.setText(tr("compare.export"))
        self._table.setHorizontalHeaderLabels([
            tr("compare.col_gt"), tr("compare.col_detected"),
            tr("compare.col_gap"), tr("compare.col_verdict")])
        self._recompute()   # 요약·표 본문·FP 목록도 전부 문장이라 다시 계산한다

    def _add_flag_here(self) -> None:
        self.session.flags.toggle(self.session.engine.position())

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        # 표는 '이 단위의 구간 안' 플래그만 시간순으로 채운다 — 전체 배열로 인덱싱하면
        # 구간 밖 플래그가 있을 때 다른 행으로 이동한다
        flags = self._scoped_flags()
        if 0 <= row < len(flags):
            self.session.engine.seek(flags[row]["time"])

    def _scoped_flags(self) -> list[dict]:
        """GT 플래그는 영상 전체에 대해 찍히지만 분석 단위는 일부만 본다.
        분석하지 않은 구간의 GT를 분모에 넣으면 recall이 '안 본 만큼 실패'로
        찍혀 지표가 무의미해진다."""
        lo, hi = self.session.store.window or [0.0, self.session.store.duration]
        return [f for f in self.session.flags.flags if lo <= f["time"] <= hi]

    def _metrics(self) -> dict:
        detected = [f["time"] for f in self.session.store.frames]
        gt = [f["time"] for f in self._scoped_flags()]
        return compare_metrics(gt, detected, self._tol.value())

    def _recompute(self) -> None:
        m = self._metrics()
        prec = "—" if m["precision"] is None else f"{m['precision']:.1%}"
        rec = "—" if m["recall"] is None else f"{m['recall']:.1%}"
        st = self.session.store
        n_out = len(self.session.flags.flags) - m["n_flags"]
        scope = tr("compare.scope_excluded", count=n_out) if n_out else ""
        self._summary.setText(tr(
            "compare.summary", unit=st.unit, start=st.window[0], end=st.window[1],
            scope=scope, n_flags=m["n_flags"], n_detected=m["n_detected"],
            precision=prec, recall=rec))

        matched_by_flag = {x["flag"]: x for x in m["matched"]}
        flags = self._scoped_flags()
        self._table.setRowCount(len(flags))
        for row, fl in enumerate(flags):
            hit = matched_by_flag.get(fl["time"])
            cells = [fmt_time(fl["time"]),
                     fmt_time(hit["detected"]) if hit else "—",
                     f"{hit['gap']:+.2f}" if hit else "—",
                     tr("compare.tp") if hit else tr("compare.fn")]
            for col, text in enumerate(cells):
                self._table.setItem(row, col, QTableWidgetItem(text))

        if not m["n_flags"]:
            # 정답지가 없으면 검출 전부가 형식상 FP로 잡힌다 — 그 목록을 늘어놓으면
            # 로직이 다 틀린 것처럼 읽힌다. 할 일을 알려주는 편이 정직하다.
            self._fp_label.setText(tr("compare.no_gt"))
            return
        fp = m["extra_detected"]
        shown = ", ".join(fmt_time(t) for t in fp[:10])
        more = tr("compare.fp_more", count=len(fp) - 10) if len(fp) > 10 else ""
        self._fp_label.setText(
            tr("compare.fp_list", count=len(fp), shown=shown, more=more) if fp
            else tr("compare.fp_none"))

    def _delete_selected(self) -> None:
        rows = sorted({i.row() for i in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.session.flags.remove(row)

    def _export(self) -> None:
        out = self.session.out_dir / "compare.json"
        write_json_atomic(out, {"flags": self.session.flags.flags, **self._metrics()})
        self._summary.setText(self._summary.text() + tr("compare.exported", name=out.name))
