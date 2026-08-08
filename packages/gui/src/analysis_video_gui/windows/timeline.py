"""타임라인 창 — YouTube 자막 편집기 방식의 멀티트랙 시간축 (pyqtgraph).

트랙(위→아래): 채택 프레임 블록(폭=interval — 커버리지 구멍이 한눈에),
탈락 후보 ✗(호버=사유), importance-point ★, STT 세그먼트, GT 플래그,
anchor-diff 변화량 곡선(누적/순간+임계선).

드래그의 의미는 도구가 정한다. 기본은 스크럽 — 검토 작업의 대부분이 시간축을
훑는 일이라 드래그가 곧 재생 위치 이동이어야 하고, 화면은 놓기 전에 따라와야
한다. 이동(팬)은 도구 전환 없이 Space 홀드로도 되며(그림 편집기 관례), 끌지
않고 떼면 평소대로 재생/정지다.
"""
import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QSlider, QToolButton,
                               QVBoxLayout)

from ..session import Session
from . import ChildWindow

LANE_TICKS = [(5.45, "프레임"), (4.5, "탈락"), (3.9, "points"),
              (3.3, "STT"), (2.4, "플래그"), (1.0, "변화량")]
Y_RANGE = (0.0, 6.3)

MIN_SPAN = 2.0        # 최대 확대에서 보이는 시간 폭(초)
ZOOM_STEPS = 1000     # 배율 슬라이더 해상도 (로그 눈금)

TOOLS = [
    ("scrub", "▶ 스크럽", "V",
     "드래그 = 재생 위치 실시간 이동 · 클릭 = 그 시각으로 점프"),
    ("pan", "✋ 이동", "H",
     "드래그 = 상하좌우 이동 · 오른쪽 드래그 = 축 배율"),
    ("zoom", "🔍 확대", "Z",
     "드래그 = 사각 영역만큼 확대 · 오른쪽 드래그 = 축 배율"),
]
TOOL_HINT = {key: hint for key, _, _, hint in TOOLS}
TOOL_CURSOR = {
    "scrub": Qt.CursorShape.SizeHorCursor,
    "pan": Qt.CursorShape.OpenHandCursor,
    "zoom": Qt.CursorShape.CrossCursor,
}
COMMON_HINT = "휠 = 확대·축소 · Space 홀드+드래그 = 임시 이동"


class _TimelineViewBox(pg.ViewBox):
    """드래그의 의미를 현재 도구에 따라 갈라 보내는 뷰박스."""

    def __init__(self, owner: "TimelineWindow"):
        super().__init__()
        self._owner = owner

    def mouseDragEvent(self, ev, axis=None) -> None:
        tool = self._owner.effective_tool()
        if tool == "scrub" and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self._owner.scrub_drag(ev, float(self.mapSceneToView(ev.scenePos()).x()))
            return
        if tool == "pan" and ev.button() == Qt.MouseButton.LeftButton:
            self._owner.note_pan()
        super().mouseDragEvent(ev, axis=axis)

    def wheelEvent(self, ev, axis=None) -> None:
        # 휠 줌은 도구와 무관하게 항상 살아 있어야 한다. 기본 구현은
        # mouseEnabled가 꺼진 축을 무시하므로(스크럽 도구가 그렇다) 직접 처리한다.
        ev.accept()
        center = float(self.mapSceneToView(ev.scenePos()).x())
        # 기본 구현의 지수는 '보이는 폭'의 배율이라 배율(=duration/폭)과는 부호가 반대
        self._owner.zoom_by(1.02 ** (-ev.delta() * self.state["wheelScaleFactor"]), center)


class TimelineWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.resize(1400, 400)

        self._tool = "scrub"
        self._space_held = False
        self._space_panned = False   # Space 홀드 중 실제로 끌었는가 (탭과 구분)
        self._dragging = False       # 재생 커서를 직접 잡고 있는가
        self._syncing_zoom = False

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_toolbar())

        vb = _TimelineViewBox(self)
        self._pw = pg.PlotWidget(background="#181818", viewBox=vb)
        layout.addWidget(self._pw, stretch=1)
        vb.setLimits(yMin=Y_RANGE[0] - 0.4, yMax=Y_RANGE[1] + 0.4)
        self._pw.setYRange(*Y_RANGE, padding=0)
        self._pw.getAxis("left").setTicks([LANE_TICKS])
        self._pw.setLabel("bottom", "시간(초)")

        self._playhead = pg.InfiniteLine(pos=0, angle=90, movable=True,
                                         pen=pg.mkPen("#ff5555", width=2))
        self._playhead.setHoverPen(pg.mkPen("#ffaaaa", width=4))
        self._playhead.sigDragged.connect(self._on_playhead_drag)
        self._playhead.sigPositionChangeFinished.connect(self._on_playhead_drop)

        self._flags_item = pg.ScatterPlotItem(symbol="t", size=13, brush="#ff8c00", pen=None)
        self._rejected_item = pg.ScatterPlotItem(symbol="x", size=9, brush="#bb5555",
                                                 pen=None, hoverable=True,
                                                 tip=lambda x, y, data: data)

        self._build()
        self.bind(session.store.reloaded, self._build)
        self.bind(session.flags.changed, self._update_flags)
        self.bind(session.showRejectedChanged, self._on_show_rejected)
        self.bind(session.engine.positionChanged, self._on_pos)
        self._pw.scene().sigMouseClicked.connect(self._on_click)
        vb.sigXRangeChanged.connect(self._sync_zoom_ui)

    # ---------- 도구 막대 ----------

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons: dict[str, QToolButton] = {}
        for key, label, accel, hint in TOOLS:
            b = QToolButton()
            b.setText(f"{label} ({accel})")
            b.setCheckable(True)
            b.setChecked(key == self._tool)
            # 포커스를 잡으면 전역 단축키가 이 버튼에 먹힌다 — 도구 막대는 포커스 밖
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(hint)
            b.clicked.connect(lambda _c, k=key: self.set_tool(k))
            self._tool_group.addButton(b)
            self._tool_buttons[key] = b
            bar.addWidget(b)

        bar.addSpacing(16)
        bar.addWidget(QLabel("배율"))
        bar.addWidget(self._zoom_button("－", lambda: self.zoom_by(1 / 1.6), "축소"))

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(0, ZOOM_STEPS)
        self._zoom_slider.setFixedWidth(220)
        self._zoom_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._zoom_slider.setToolTip("전체 보기 ↔ 최대 확대")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        bar.addWidget(self._zoom_slider)

        bar.addWidget(self._zoom_button("＋", lambda: self.zoom_by(1.6), "확대"))
        bar.addWidget(self._zoom_button("⤢", self.fit_all, "전체 보기"))
        self._zoom_label = QLabel("1.0×")
        self._zoom_label.setFixedWidth(52)
        bar.addWidget(self._zoom_label)

        bar.addSpacing(12)
        self._hint = QLabel()
        self._hint.setStyleSheet("color:#999;")
        bar.addWidget(self._hint, stretch=1)
        return bar

    def _zoom_button(self, text: str, cb, tip: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda: cb())
        return b

    # ---------- 도구 ----------

    def set_tool(self, key: str) -> None:
        self._tool = key
        self._tool_buttons[key].setChecked(True)  # 그룹이 배타라 나머지는 자동 해제
        self._apply_tool()

    def effective_tool(self) -> str:
        """Space 홀드는 어떤 도구 위에서도 임시 이동으로 덮어쓴다."""
        return "pan" if self._space_held else self._tool

    def _apply_tool(self) -> None:
        tool = self.effective_tool()
        vb = self._pw.getViewBox()
        vb.setMouseMode(pg.ViewBox.RectMode if tool == "zoom" else pg.ViewBox.PanMode)
        vb.setMouseEnabled(x=tool != "scrub", y=tool != "scrub")
        self._playhead.setMovable(tool == "scrub")
        self._pw.setCursor(TOOL_CURSOR[tool])
        held = " · Space 홀드 중" if self._space_held else ""
        self._hint.setText(f"{TOOL_HINT[tool]}{held}    |    {COMMON_HINT}")

    def note_pan(self) -> None:
        if self._space_held:
            self._space_panned = True

    def handle_shortcut(self, ev) -> bool:
        """활성 창 우선권으로 받는 키 — Space는 홀드-이동, 탭은 재생/정지."""
        tool_key = {Qt.Key.Key_V: "scrub", Qt.Key.Key_H: "pan",
                    Qt.Key.Key_Z: "zoom"}.get(ev.key())
        if tool_key is not None:
            if ev.type() == QEvent.Type.KeyPress and not ev.isAutoRepeat():
                self.set_tool(tool_key)
            return True
        if ev.key() != Qt.Key.Key_Space:
            return False
        if ev.isAutoRepeat():
            return True   # 홀드 유지 — 자동 반복이 재생 토글로 새지 않게
        if ev.type() == QEvent.Type.KeyPress:
            self._space_held = True
            self._space_panned = False
            self._apply_tool()
            return True
        self._space_held = False
        self._apply_tool()
        if not self._space_panned:
            self.session.engine.toggle()  # 끌지 않았으면 평소의 Space
        return True

    # ---------- 배율 ----------

    def _zoom_max(self) -> float:
        return max(1.0, self.session.store.duration / MIN_SPAN)

    def _zoom_now(self) -> float:
        (x0, x1), _ = self._pw.getViewBox().viewRange()
        return max(1.0, self.session.store.duration / max(x1 - x0, 1e-6))

    def zoom_by(self, factor: float, center: float | None = None) -> None:
        self.set_zoom(self._zoom_now() * factor, center)

    def fit_all(self) -> None:
        self.set_zoom(1.0)
        self._pw.setYRange(*Y_RANGE, padding=0)

    def set_zoom(self, z: float, center: float | None = None) -> None:
        dur = max(self.session.store.duration, 1.0)
        span = dur / min(max(1.0, z), self._zoom_max())
        if center is None:
            # 재생 커서가 보이면 그것을 축으로 — 확대해도 보던 지점을 놓치지 않는다
            (x0, x1), _ = self._pw.getViewBox().viewRange()
            t = self.session.engine.position()
            center = t if x0 <= t <= x1 else (x0 + x1) / 2
        left = min(max(center - span / 2, 0.0), max(dur - span, 0.0))
        self._pw.setXRange(left, left + span, padding=0)

    def _on_zoom_slider(self, v: int) -> None:
        if self._syncing_zoom:
            return
        self.set_zoom(self._zoom_max() ** (v / ZOOM_STEPS))

    def _sync_zoom_ui(self, *_args) -> None:
        z = self._zoom_now()
        zmax = self._zoom_max()
        v = 0 if zmax <= 1.0 else round(ZOOM_STEPS * math.log(z) / math.log(zmax))
        self._syncing_zoom = True
        self._zoom_slider.setValue(int(min(max(v, 0), ZOOM_STEPS)))
        self._syncing_zoom = False
        self._zoom_label.setText(f"{z:.1f}×")

    # ---------- 구성 ----------

    def _build(self) -> None:
        st = self.session.store
        self._pw.clear()
        duration = max(st.duration, 1.0)
        self._pw.setLimits(xMin=-duration * 0.02, xMax=duration * 1.02)
        self._pw.setXRange(0, duration, padding=0.01)

        if st.frames:
            starts = np.array([f["interval"][0] for f in st.frames])
            ends = np.array([f["interval"][1] for f in st.frames])
            self._pw.addItem(pg.BarGraphItem(
                x0=starts, x1=np.maximum(ends, starts + duration * 0.001),
                y0=5.0, y1=5.9, brush=(60, 160, 90, 170), pen=pg.mkPen("#2a5")))

        self._rejected_item.setData(
            [r["time"] for r in st.rejected], [4.5] * len(st.rejected),
            data=[f"t={r['time']} {r['reject_reason']}" for r in st.rejected])
        self._rejected_item.setVisible(self.session.show_rejected)
        self._pw.addItem(self._rejected_item)

        if st.point_times:
            self._pw.addItem(pg.ScatterPlotItem(
                x=st.point_times, y=[3.9] * len(st.point_times),
                symbol="star", size=14, brush="#e6c229", pen=None))

        if st.segments:
            self._pw.addItem(pg.BarGraphItem(
                x0=[s["start"] for s in st.segments], x1=[s["end"] for s in st.segments],
                y0=3.0, y1=3.6, brush=(130, 130, 130, 110), pen=None))

        if st.series is not None:
            times, cum, rate = st.series["times"], st.series["cum"], st.series["rate"]
            cth, rth = st.series["cum_threshold"], st.series["rate_threshold"]
            cum_n = 2.0 * np.clip(cum / (4 * cth), 0, 1)
            rate_n = 1.0 * np.clip(rate / (6 * rth), 0, 1)
            self._pw.addItem(pg.PlotDataItem(times, cum_n, pen=pg.mkPen((90, 160, 255), width=1),
                                             autoDownsample=True))
            self._pw.addItem(pg.PlotDataItem(times, rate_n, pen=pg.mkPen((255, 160, 60, 140)),
                                             autoDownsample=True))
            self._pw.addItem(pg.InfiniteLine(pos=0.5, angle=0,
                                             pen=pg.mkPen("#f55", style=Qt.PenStyle.DashLine)))

        self._update_flags()
        self._pw.addItem(self._flags_item)
        self._pw.addItem(self._playhead)
        self._apply_tool()
        self._sync_zoom_ui()

    def _update_flags(self) -> None:
        times = self.session.flags.times()
        self._flags_item.setData(times, [2.4] * len(times))

    def _on_show_rejected(self, show: bool) -> None:
        self._rejected_item.setVisible(show)

    # ---------- 동기 ----------

    def _on_pos(self, t: float) -> None:
        if not self._dragging:
            self._playhead.blockSignals(True)
            self._playhead.setPos(t)
            self._playhead.blockSignals(False)

    def scrub_drag(self, ev, t: float) -> None:
        """뷰박스 위 좌드래그 = 재생 위치 실시간 이동."""
        e = self.session.engine
        if ev.isStart():
            e.begin_scrub()
        e.scrub_to(t)
        if ev.isFinish():
            e.end_scrub()

    def _on_playhead_drag(self, line) -> None:
        self._dragging = True
        self.session.engine.scrub_to(float(line.value()))

    def _on_playhead_drop(self, line) -> None:
        if self._dragging:
            self._dragging = False
            self.session.engine.scrub_to(float(line.value()))
            self.session.engine.end_scrub()

    def _on_click(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton or self.effective_tool() != "scrub":
            return
        p = self._pw.getViewBox().mapSceneToView(ev.scenePos())
        t = float(p.x())
        if 0 <= t <= self.session.store.duration:
            self.session.engine.seek(t)
