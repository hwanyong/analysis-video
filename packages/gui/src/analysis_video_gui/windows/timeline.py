"""타임라인 창 — YouTube 자막 편집기 방식의 멀티트랙 시간축 (pyqtgraph).

읽히는 그래프를 목표로 한다: 좌측 범례가 모든 색·기호의 뜻과 **현재 개수**를
같이 들고 있어서, 비어 있는 레인이 "데이터가 0건"인지 "숨겼는지"를 화면에서
바로 구분할 수 있다. 마우스를 올리면 그 시각의 프레임·대사·변화량 원값이
판독 줄에 나온다.

레인(위→아래): 채택 프레임(검출 근거별 색, 복합 근거는 흰 테두리), 탈락 후보 ✗,
주문 추출 ◆, importance-point ★, STT 세그먼트, GT 플래그, 그리고 아래 절반이
anchor-diff 진단 — 전환 구간 음영 위에 anchor diff·순간 변화율·컷 면적을 각자의
기준선과 함께 따로 쌓는다. 세 곡선은 읽는 방향이 다르다(anchor diff와 컷 면적은
넘겨야 전환 시작, 순간 변화율은 내려가야 트리거) — 겹쳐 그리면 해독이 불가능해서
분리했다. 전환 시작은 anchor diff(점진 누적)와 컷 면적(컷)의 OR라 둘 다 보여야
"왜 여기서 끊었나"를 읽을 수 있다.

드래그의 의미는 도구가 정한다. 기본은 스크럽 — 검토 작업의 대부분이 시간축을
훑는 일이라 드래그가 곧 재생 위치 이동이어야 하고, 화면은 놓기 전에 따라와야
한다. 이동(팬)은 도구 전환 없이 Space 홀드로도 되며(그림 편집기 관례), 끌지
않고 떼면 평소대로 재생/정지다.
"""
import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QSlider,
                               QToolButton, QVBoxLayout, QWidget)

from ..session import MARK_KINDS, Session
from . import ChildWindow, fmt_time

# 범례 체크박스에 쓰는 마크 종류별 색·기호 (레인에 그리는 것과 같아야 한다)
KIND_STYLE = {
    "frame": ((60, 160, 90), "■"),
    "rejected": ((187, 85, 85), "✗"),
    "requested": ((200, 140, 255), "◆"),
    "point": ((230, 194, 41), "★"),
    "segment": ((150, 150, 150), "▬"),
    "flag": ((255, 140, 0), "▲"),
    "transition": ((120, 120, 170), "▬"),
}

# ---------- 레인 기하 (y는 0=바닥, 위로 증가) ----------
Y_RANGE = (0.0, 9.0)
LANE_FRAMES = (7.95, 8.85)
LANE_REJECTED = 7.5
LANE_REQUESTED = 7.05
LANE_POINTS = 6.6
LANE_STT = (5.95, 6.3)
LANE_FLAGS = 5.5
LANE_ANCHOR = (3.4, 4.6)   # anchor diff — 기준선을 넘겨야 전환 시작(점진 누적)
LANE_RATE = (1.85, 3.05)   # 순간 변화율 — 기준선 아래로 내려가야 트리거
LANE_AREA = (0.3, 1.5)     # 컷 면적 — 기준선을 넘겨야 전환 시작(컷)
DIFF_BAND = (LANE_AREA[0], LANE_ANCHOR[1])   # 전환 구간 음영이 덮는 범위

LANE_TICKS = [
    (sum(LANE_FRAMES) / 2, "프레임"), (LANE_REJECTED, "탈락"),
    (LANE_REQUESTED, "주문"), (LANE_POINTS, "points"),
    (sum(LANE_STT) / 2, "STT"), (LANE_FLAGS, "플래그"),
    (sum(LANE_ANCHOR) / 2, "anchor diff"), (sum(LANE_RATE) / 2, "순간 변화율"),
    (sum(LANE_AREA) / 2, "컷 면적"),
]

# 정규화 배율: 임계값이 각 레인의 이 비율 위치에 오도록 잡는다
ANCHOR_FULL = 4.0   # anchor diff == 4×임계에서 레인 천장
RATE_FULL = 6.0     # rate == 6×임계에서 레인 천장
AREA_FULL = 4.0     # cut_area == 4×임계에서 레인 천장

SOURCE_COLORS = {
    "anchor-diff": (60, 160, 90),
    "anchor-diff-pre": (40, 200, 190),
    "adaptive": (70, 130, 205),
    "importance-point": (230, 194, 41),
    "initial": (150, 150, 150),
}
SOURCE_ORDER = ["importance-point", "adaptive", "anchor-diff-pre", "anchor-diff", "initial"]

MIN_SPAN = 2.0        # 최대 확대에서 보이는 시간 폭(초)
ZOOM_STEPS = 1000     # 배율 슬라이더 해상도 (로그 눈금)
SNAP_PIXELS = 12      # 클릭 스냅 허용오차 — 시간이 아니라 화면 픽셀 기준(편집기 관례)

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


def _swatch(color: tuple, glyph: str = "■") -> str:
    return f"<span style='color:rgb{color[:3]}'>{glyph}</span>"


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
        self.resize(1500, 520)

        self._tool = "scrub"
        self._space_held = False
        self._space_panned = False   # Space 홀드 중 실제로 끌었는가 (탭과 구분)
        self._dragging = False       # 재생 커서를 직접 잡고 있는가
        self._syncing_zoom = False

        outer = QVBoxLayout(self)
        outer.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        body.addWidget(self._build_legend())

        plot_col = QVBoxLayout()
        vb = _TimelineViewBox(self)
        self._pw = pg.PlotWidget(background="#181818", viewBox=vb)
        plot_col.addWidget(self._pw, stretch=1)
        self._readout = QLabel("마우스를 올리면 그 시각의 내용이 여기 나옵니다")
        self._readout.setStyleSheet("color:#aaa; padding:2px 4px;")
        self._readout.setTextFormat(Qt.TextFormat.RichText)
        plot_col.addWidget(self._readout)
        body.addLayout(plot_col, stretch=1)
        outer.addLayout(body, stretch=1)

        vb.setLimits(yMin=Y_RANGE[0] - 0.4, yMax=Y_RANGE[1] + 0.4)
        self._pw.setYRange(*Y_RANGE, padding=0)
        self._pw.getAxis("left").setTicks([LANE_TICKS])
        self._pw.setLabel("bottom", "시간(초)")

        self._playhead = pg.InfiniteLine(
            pos=0, angle=90, movable=True, pen=pg.mkPen("#ff5555", width=2),
            label="{value:0.2f}s", labelOpts={"position": 0.02, "color": "#ff8888",
                                              "movable": False, "fill": (24, 24, 24, 200)})
        self._playhead.setHoverPen(pg.mkPen("#ffaaaa", width=4))
        self._playhead.sigDragged.connect(self._on_playhead_drag)
        self._playhead.sigPositionChangeFinished.connect(self._on_playhead_drop)

        self._flags_item = pg.ScatterPlotItem(symbol="t", size=13, brush="#ff8c00",
                                              pen=None, hoverable=True,
                                              tip=lambda x, y, data: data)
        self._rejected_item = pg.ScatterPlotItem(symbol="x", size=9, brush="#bb5555",
                                                 pen=None, hoverable=True,
                                                 tip=lambda x, y, data: data)

        self._build()
        self.bind(session.store.reloaded, self._build)
        self.bind(session.flags.changed, self._on_flags_changed)
        self.bind(session.showRejectedChanged, self._on_show_rejected)
        self.bind(session.traverseChanged, self._update_legend)
        self.bind(session.markJumped, self._on_mark_jumped)
        self.bind(session.engine.positionChanged, self._on_pos)
        self._pw.scene().sigMouseClicked.connect(self._on_click)
        self._pw.scene().sigMouseMoved.connect(self._on_hover)
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
        self._zoom_slider.setFixedWidth(200)
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

    # ---------- 범례 ----------

    def _build_legend(self) -> QWidget:
        """범례이자 순회 필터. 체크박스가 곧 ↓/↑와 클릭 스냅의 대상 목록이다 —
        각 종류의 뜻·색·개수를 이미 들고 있는 자리라 필터를 따로 둘 이유가 없다."""
        box = QWidget()
        box.setFixedWidth(238)
        # 그래프를 설명하는 패널이므로 그래프와 같은 배경 — 시선이 두 번 적응하지 않게
        box.setStyleSheet("background:#181818; color:#ddd;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(1)

        self._legend_head = QLabel()
        self._legend_head.setTextFormat(Qt.TextFormat.RichText)
        self._legend_head.setWordWrap(True)
        lay.addWidget(self._legend_head)

        lay.addWidget(self._note("<span style='color:#888'>체크 = ↓/↑ 순회·클릭 스냅 대상"
                                 "</span>"))
        self._kind_boxes: dict[str, QCheckBox] = {}
        for kind, label, _default in MARK_KINDS:
            color, glyph = KIND_STYLE[kind]
            cb = QCheckBox(f"{glyph} {label}")
            cb.setChecked(kind in self.session.traverse)
            cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 전역 단축키를 뺏기지 않게
            cb.setStyleSheet(f"color: rgb{color};")
            cb.toggled.connect(lambda on, k=kind: self.session.set_traverse(k, on))
            self._kind_boxes[kind] = cb
            lay.addWidget(cb)

        self._legend_tail = QLabel()
        self._legend_tail.setTextFormat(Qt.TextFormat.RichText)
        self._legend_tail.setWordWrap(True)
        lay.addWidget(self._legend_tail)
        lay.addStretch(1)
        return box

    @staticmethod
    def _note(html: str) -> QLabel:
        lb = QLabel(html)
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setWordWrap(True)
        return lb

    def _update_legend(self) -> None:
        st = self.session.store
        counts = st.source_counts()
        head = [f"<b>프레임 채택 {len(st.frames)}</b>"]
        head += [f"&nbsp;{_swatch(SOURCE_COLORS[s])} {s} {counts.get(s, 0)}"
                 for s in SOURCE_ORDER]
        head.append("&nbsp;<span style='color:#eee'>▭</span> 흰 테두리 = 복합 근거")
        self._legend_head.setText("<br>".join(head))

        counts_by_kind = {k: len(self.session.mark_times(k)) for k, _, _ in MARK_KINDS}
        counts_by_kind["point"] = len(st.point_times)   # ★는 원시 시각 자리에 찍힌다
        for kind, label, _d in MARK_KINDS:
            glyph = KIND_STYLE[kind][1]
            extra = ""
            if kind == "rejected" and not self.session.show_rejected:
                extra = " · 숨김(R)"
            elif kind == "requested" and not counts_by_kind[kind]:
                extra = " · frame --at"
            elif kind == "flag" and not counts_by_kind[kind]:
                extra = " · F로 기입"
            self._kind_boxes[kind].setText(
                f"{glyph} {label} {counts_by_kind[kind]}{extra}")

        tail = ["<span style='color:#888'>GT 플래그 = “이 장면은 뽑혔어야 한다”는 사람의"
                " 정답. F 추가/취소, ▼ ⇧클릭 삭제, G 이동. ⑥ 비교 리포트가 검출과"
                " 대조해 recall·precision을 낸다.</span>", ""]
        if st.series is not None:
            ath = st.series["anchor_threshold"]
            rth = st.series["rate_threshold"]
            cth = st.series["cut_area_threshold"]
            tail += [
                "<span style='color:#888'>전환 시작 = anchor diff <b>또는</b> 컷 면적이"
                " 기준을 넘을 때. 그 뒤 순간 변화율이 잦아들면 트리거.</span>", "",
                f"{_swatch((90, 160, 255), '━')} anchor diff (앵커와의 거리)",
                f"&nbsp;&nbsp;<span style='color:#f55'>┈</span> {ath} <b>넘으면</b> 전환 시작",
                f"{_swatch((255, 160, 60), '━')} 순간 변화율 (직전 프레임 대비)",
                f"&nbsp;&nbsp;<span style='color:#f55'>┈</span> {rth} <b>아래로</b> 내려가면 트리거",
                f"{_swatch((190, 130, 255), '━')} 컷 면적 (확 바뀐 픽셀 비율)",
                f"&nbsp;&nbsp;<span style='color:#f55'>┈</span> {cth} <b>넘으면</b> 컷",
            ]
        else:
            tail.append("<span style='color:#777'>detect_anchor.npz 없음 — 변화량 미표시"
                        "</span>")
        self._legend_tail.setText("<br>".join(tail))

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

    @staticmethod
    def _frame_style(sources: list[str]) -> tuple:
        """복합 근거는 흰 테두리로 구분 — 색은 우선순위가 가장 높은 근거를 쓴다."""
        primary = next((s for s in SOURCE_ORDER if s in sources),
                       sources[0] if sources else "initial")
        color = SOURCE_COLORS.get(primary, (120, 120, 120))
        pen = pg.mkPen("#ffffff", width=2) if len(sources) > 1 else pg.mkPen(color)
        return pg.mkBrush(*color, 190), pen

    def _build(self) -> None:
        st = self.session.store
        self._pw.clear()
        duration = max(st.duration, 1.0)
        self._pw.setLimits(xMin=-duration * 0.02, xMax=duration * 1.02)
        self._pw.setXRange(0, duration, padding=0.01)

        # 레인 경계 — 이산 마크 영역과 변화량 영역, 그리고 세 곡선 사이를 가른다.
        # 경계가 없으면 곡선 스파이크가 위 레인의 마크처럼 읽힌다(구 레이아웃의 결함).
        for y in ((LANE_FLAGS + LANE_ANCHOR[1]) / 2,
                  (LANE_ANCHOR[0] + LANE_RATE[1]) / 2,
                  (LANE_RATE[0] + LANE_AREA[1]) / 2):
            self._pw.addItem(pg.InfiniteLine(pos=y, angle=0, movable=False,
                                             pen=pg.mkPen((70, 70, 70), width=1)))

        if st.transitions:
            # 변화량 레인 전체를 덮는 음영 — 곡선이 이 구간 안에서 오르내리다
            # 안정되어 트리거된 것이 보인다
            self._pw.addItem(pg.BarGraphItem(
                x0=[a for a, _ in st.transitions],
                x1=[max(b, a + duration * 0.0004) for a, b in st.transitions],
                y0=DIFF_BAND[0], y1=DIFF_BAND[1],
                brush=(110, 110, 160, 55), pen=None))

        if st.frames:
            starts = np.array([f["interval"][0] for f in st.frames])
            ends = np.array([f["interval"][1] for f in st.frames])
            styles = [self._frame_style(f["sources"]) for f in st.frames]
            self._pw.addItem(pg.BarGraphItem(
                x0=starts, x1=np.maximum(ends, starts + duration * 0.001),
                y0=LANE_FRAMES[0], y1=LANE_FRAMES[1],
                brushes=[b for b, _ in styles], pens=[p for _, p in styles]))

        self._rejected_item.setData(
            [r["time"] for r in st.rejected], [LANE_REJECTED] * len(st.rejected),
            data=[f"t={r['time']} {r['reject_reason']}" for r in st.rejected])
        self._rejected_item.setVisible(self.session.show_rejected)
        self._pw.addItem(self._rejected_item)

        if st.requested:
            self._pw.addItem(pg.ScatterPlotItem(
                x=[r["time"] for r in st.requested],
                y=[LANE_REQUESTED] * len(st.requested),
                symbol="d", size=13, brush="#c88cff", pen=None))

        if st.point_times:
            self._pw.addItem(pg.ScatterPlotItem(
                x=st.point_times, y=[LANE_POINTS] * len(st.point_times),
                symbol="star", size=14, brush="#e6c229", pen=None))

        if st.segments:
            self._pw.addItem(pg.BarGraphItem(
                x0=[s["start"] for s in st.segments], x1=[s["end"] for s in st.segments],
                y0=LANE_STT[0], y1=LANE_STT[1], brush=(130, 130, 130, 110), pen=None))

        if st.series is not None:
            self._plot_diff(st)

        self._update_flags()
        self._pw.addItem(self._flags_item)
        self._pw.addItem(self._playhead)
        self._apply_tool()
        self._sync_zoom_ui()
        self._update_legend()

    def _plot_diff(self, st) -> None:
        """anchor diff·순간 변화율·컷 면적을 각자의 레인에 기준선과 함께 쌓는다.

        겹쳐 그리면 안 되는 이유: 세 곡선의 읽는 방향이 다르다. 전환 시작은
        `anchor diff > 임계` **또는** `컷 면적 > 임계`(둘 다 넘겨야 하는 쪽),
        트리거는 `순간변화율 ≤ 임계`(내려가야 하는 쪽)다."""
        s = st.series
        times = s["times"]
        ath, rth, cth = (s["anchor_threshold"], s["rate_threshold"],
                         s["cut_area_threshold"])
        for series, thr, lane, full, color, label in (
                (s["anchor"], ath, LANE_ANCHOR, ANCHOR_FULL, (90, 160, 255),
                 f"{ath} ↑ 넘으면"),
                (s["rate"], rth, LANE_RATE, RATE_FULL, (255, 160, 60),
                 f"{rth} ↓ 내려가면"),
                (s["area"], cth, LANE_AREA, AREA_FULL, (190, 130, 255),
                 f"{cth} ↑ 넘으면 컷")):
            lo, hi = lane
            self._pw.addItem(pg.PlotDataItem(
                times, lo + (hi - lo) * np.clip(series / (full * thr), 0, 1),
                pen=pg.mkPen(color, width=1), autoDownsample=True))
            self._pw.addItem(pg.InfiniteLine(
                pos=lo + (hi - lo) / full, angle=0,
                pen=pg.mkPen("#f55", style=Qt.PenStyle.DashLine),
                label=label,
                # 기본 앵커는 가운데 정렬이라 왼쪽 끝에 두면 절반이 잘린다
                labelOpts={"position": 0.004, "color": "#f88", "movable": False,
                           "fill": (24, 24, 24, 200), "anchors": [(0, 1), (0, 1)]}))

    def _update_flags(self) -> None:
        flags = self.session.flags.flags
        self._flags_item.setData(
            [f["time"] for f in flags], [LANE_FLAGS] * len(flags),
            data=[f"GT {fmt_time(f['time'])}"
                  + (f" — {f['note']}" if f.get("note") else "")
                  + "  (⇧클릭 = 삭제)" for f in flags])

    def _on_flags_changed(self) -> None:
        self._update_flags()
        self._update_legend()

    def _on_show_rejected(self, show: bool) -> None:
        self._rejected_item.setVisible(show)
        self._update_legend()

    # ---------- 판독 ----------

    def _on_hover(self, scene_pos) -> None:
        vb = self._pw.getViewBox()
        if not self._pw.sceneBoundingRect().contains(scene_pos):
            return
        t = float(vb.mapSceneToView(scene_pos).x())
        st = self.session.store
        if not 0 <= t <= st.duration:
            self._readout.setText("<span style='color:#777'>영상 범위 밖</span>")
            return

        parts = [f"<b>t={t:.2f}</b> ({fmt_time(t)})"]
        i = st.frame_index_at(t)
        if i is not None and st.frames:
            f = st.frames[i]
            marks = "".join(_swatch(SOURCE_COLORS.get(s, (150, 150, 150))) for s in f["sources"])
            parts.append(f"{marks} 프레임 #{i} t={f['time']} · {'+'.join(f['sources'])}")
        j = st.segment_index_at(t)
        if j is not None:
            text = st.segments[j]["text"].strip()
            parts.append(f"<span style='color:#ccc'>“{text[:70]}”</span>")
        sv = st.series_at(t)
        if sv is not None:
            anchor_d, rate, area = sv
            ath = st.series["anchor_threshold"]
            rate_th = st.series["rate_threshold"]
            cth = st.series["cut_area_threshold"]
            parts.append(
                f"<span style='color:#6af'>anchor {anchor_d:.4f}</span>"
                f"{'↑' if anchor_d > ath else ''} · "
                f"<span style='color:#fa6'>순간 {rate:.6f}</span>"
                f"{'' if rate > rate_th else '↓'} · "
                f"<span style='color:#b8f'>면적 {area:.4f}</span>"
                f"{'↑' if area > cth else ''}")
        self._readout.setText(" &nbsp;|&nbsp; ".join(parts))

    # ---------- 동기 ----------

    def _on_pos(self, t: float) -> None:
        if not self._dragging:
            # blockSignals를 걸면 안 된다 — 커서에 붙은 시각 라벨이 setPos가 내는
            # sigPositionChanged로만 갱신되므로, 막으면 드래그로 옮길 때 말고는
            # 라벨이 0.00s에 얼어붙는다. 우리가 받는 시그널(sigDragged /
            # sigPositionChangeFinished)은 setPos가 내지 않으므로 되먹임도 없다.
            self._playhead.setPos(t)
            self._follow(t)

    def _follow(self, t: float) -> None:
        """커서가 보이는 범위를 벗어나면 재중심.

        항상 중앙에 고정하면 재생 내내 화면이 흘러 눈이 피로하다. 반대로 아예
        따라가지 않으면 확대 상태에서 점프했을 때 커서를 화면에서 잃는다
        (마크를 확대해 보려는 것이 애초 목적인데 점프한 순간 사라진다)."""
        vb = self._pw.getViewBox()
        (x0, x1), _ = vb.viewRange()
        span = x1 - x0
        if span >= self.session.store.duration * 0.999:
            return  # 전체 보기 — 따라갈 것이 없다
        margin = span * 0.05
        if x0 + margin <= t <= x1 - margin:
            return
        self.set_zoom(self._zoom_now(), center=t)

    def _snap(self, t: float) -> float:
        """가까운 마크에 달라붙는다 — 허용오차는 화면 픽셀 기준이라 배율과 무관하게
        '눈에 보이는 만큼'이다. 대상은 범례에서 켜 둔 종류(순회 대상과 동일)."""
        try:
            tol = float(self._pw.getViewBox().viewPixelSize()[0]) * SNAP_PIXELS
        except Exception:
            tol = 0.05
        best, best_d = t, tol
        for kind in self.session.traverse:
            for m in self.session.mark_times(kind):
                d = abs(m - t)
                if d < best_d:
                    best, best_d = m, d
        return best

    def _on_mark_jumped(self, _kind: str, description: str) -> None:
        self._readout.setText(f"<span style='color:#8cf'>▸ {description}</span>")

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
        if not 0 <= t <= self.session.store.duration:
            return
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # 찍은 자리에서 바로 지울 수 있어야 한다 — 화면 폭에 비례한 허용오차로
            # 잡아야 확대 배율과 무관하게 "눈에 보이는 ▼"를 집을 수 있다
            (x0, x1), _ = self._pw.getViewBox().viewRange()
            i = self.session.flags.index_at(t, within=max((x1 - x0) * 0.01, 0.2))
            if i is not None:
                self.session.flags.remove(i)
            return
        # 눈대중 좌표가 아니라 가까운 마크로 — 드래그로 조준하던 수고를 없앤다
        self.session.engine.seek(self._snap(t))
