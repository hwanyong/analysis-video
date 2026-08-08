"""타임라인 창 — YouTube 자막 편집기 방식의 멀티트랙 시간축 (pyqtgraph).

트랙(위→아래): 채택 프레임 블록(폭=interval — 커버리지 구멍이 한눈에),
탈락 후보 ✗(호버=사유), importance-point ★, STT 세그먼트, GT 플래그,
anchor-diff 변화량 곡선(누적/순간+임계선). 어디를 클릭해도 그 시각으로 seek,
빨간 재생 커서는 드래그 가능. 휠=가로 줌, 드래그=팬.
"""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..session import Session
from . import ChildWindow

LANE_TICKS = [(5.45, "프레임"), (4.5, "탈락"), (3.9, "points"),
              (3.3, "STT"), (2.4, "플래그"), (1.0, "변화량")]


class TimelineWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.resize(1400, 360)

        layout = QVBoxLayout(self)
        self._pw = pg.PlotWidget(background="#181818")
        layout.addWidget(self._pw)
        vb = self._pw.getViewBox()
        vb.setMouseEnabled(x=True, y=False)
        self._pw.setYRange(0, 6.3, padding=0)
        self._pw.getAxis("left").setTicks([LANE_TICKS])
        self._pw.setLabel("bottom", "시간(초)")

        self._playhead = pg.InfiniteLine(pos=0, angle=90, movable=True,
                                         pen=pg.mkPen("#ff5555", width=2))
        self._dragging = False
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

    def _on_show_rejected(self, show: bool) -> None:
        self._rejected_item.setVisible(show)

    def _on_playhead_drag(self, _line) -> None:
        self._dragging = True

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

    def _update_flags(self) -> None:
        times = self.session.flags.times()
        self._flags_item.setData(times, [2.4] * len(times))

    # ---------- 동기 ----------

    def _on_pos(self, t: float) -> None:
        if not self._dragging:
            self._playhead.blockSignals(True)
            self._playhead.setPos(t)
            self._playhead.blockSignals(False)

    def _on_playhead_drop(self, line) -> None:
        if self._dragging:
            self._dragging = False
            self.session.engine.seek(float(line.value()))

    def _on_click(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        p = self._pw.getViewBox().mapSceneToView(ev.scenePos())
        t = float(p.x())
        if 0 <= t <= self.session.store.duration:
            self.session.engine.seek(t)
