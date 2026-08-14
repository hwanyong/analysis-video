"""타임라인 창 — YouTube 자막 편집기 방식의 멀티트랙 시간축 (pyqtgraph).

읽히는 그래프를 목표로 한다: 좌측 범례가 모든 색·기호의 뜻과 **현재 개수**를
같이 들고 있어서, 비어 있는 레인이 "데이터가 0건"인지 "숨겼는지"를 화면에서
바로 구분할 수 있다. 마우스를 올리면 그 시각의 프레임·대사·변화량 원값이
판독 줄에 나온다.

레인(위→아래): 채택 프레임(검출 근거별 색, 복합 근거는 흰 테두리), 탈락 후보 ✗,
주문 추출 ◆, 화면 경계 │, STT 세그먼트, GT 플래그, 그리고 아래 절반이
신호 진단 — 변화 구간 음영 위에 anchor diff·순간 변화율·컷 면적을 각자의
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
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLabel,
                               QScrollArea, QSlider, QToolButton, QVBoxLayout,
                               QWidget)

from ..i18n import tr
from ..keys import physical_key
from ..session import MARK_KINDS, Session, mark_label, source_label
from . import ChildWindow, fmt_time

# 범례 체크박스에 쓰는 마크 종류별 색·기호 (레인에 그리는 것과 같아야 한다)
KIND_STYLE = {
    "frame": ((60, 160, 90), "■"),
    "rejected": ((187, 85, 85), "✗"),
    "requested": ((200, 140, 255), "◆"),
    "screen": ((150, 200, 255), "│"),
    "segment": ((150, 150, 150), "▬"),
    "flag": ((255, 140, 0), "▲"),
    "transition": ((120, 120, 170), "▬"),
}

# ---------- 레인 기하 (y는 0=바닥, 위로 증가) ----------
Y_RANGE = (0.0, 9.0)
LANE_FRAMES = (7.95, 8.85)
LANE_REJECTED = 7.5
LANE_REQUESTED = 7.05
LANE_SCREENS = 6.6
LANE_STT = (5.95, 6.3)
LANE_FLAGS = 5.5
LANE_ANCHOR = (3.4, 4.6)   # anchor diff — 기준선을 넘겨야 전환 시작(점진 누적)
LANE_RATE = (1.85, 3.05)   # 순간 변화율 — 기준선 아래로 내려가야 트리거
LANE_AREA = (0.3, 1.5)     # 컷 면적 — 기준선을 넘겨야 전환 시작(컷)
DIFF_BAND = (LANE_AREA[0], LANE_ANCHOR[1])   # 전환 구간 음영이 덮는 범위

# 레인 눈금은 (y, 이름 카탈로그 키) — 상수로 굳히면 언어 전환을 못 따라간다
LANE_TICK_KEYS = [
    (sum(LANE_FRAMES) / 2, "lane.frames"), (LANE_REJECTED, "lane.rejected"),
    (LANE_REQUESTED, "lane.requested"), (LANE_SCREENS, "lane.screens"),
    (sum(LANE_STT) / 2, "lane.stt"), (LANE_FLAGS, "lane.flags"),
    (sum(LANE_ANCHOR) / 2, "lane.anchor"), (sum(LANE_RATE) / 2, "lane.rate"),
    (sum(LANE_AREA) / 2, "lane.area"),
]


def _lane_ticks() -> list[tuple[float, str]]:
    return [(y, tr(key)) for y, key in LANE_TICK_KEYS]

# 정규화 배율: 임계값이 각 레인의 이 비율 위치에 오도록 잡는다
ANCHOR_FULL = 4.0   # anchor diff == 4×임계에서 레인 천장
RATE_FULL = 6.0     # rate == 6×임계에서 레인 천장
AREA_FULL = 4.0     # cut_area == 4×임계에서 레인 천장

SOURCE_COLORS = {
    "screen-start": (60, 160, 90),
    "screen-end": (40, 200, 190),
    "initial": (150, 150, 150),
}
SOURCE_ORDER = ["screen-end", "screen-start", "initial"]

MIN_SPAN = 2.0        # 최대 확대에서 보이는 시간 폭(초)
ZOOM_STEPS = 1000     # 배율 슬라이더 해상도 (로그 눈금)
SNAP_PIXELS = 12      # 클릭 스냅 허용오차 — 시간이 아니라 화면 픽셀 기준(편집기 관례)

# (도구 키, 가속키) — 이름과 설명은 `tool.<키>` / `tool.<키>.hint`로 카탈로그에서 온다
TOOLS = [("scrub", "V"), ("pan", "H"), ("zoom", "Z")]
TOOL_CURSOR = {
    "scrub": Qt.CursorShape.SizeHorCursor,
    "pan": Qt.CursorShape.OpenHandCursor,
    "zoom": Qt.CursorShape.CrossCursor,
}


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
        super().__init__(session)
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
        self._readout = QLabel()
        self._readout.setStyleSheet("color:#aaa; padding:2px 4px;")
        self._readout.setTextFormat(Qt.TextFormat.RichText)
        plot_col.addWidget(self._readout)
        body.addLayout(plot_col, stretch=1)
        outer.addLayout(body, stretch=1)

        vb.setLimits(yMin=Y_RANGE[0] - 0.4, yMax=Y_RANGE[1] + 0.4)
        self._pw.setYRange(*Y_RANGE, padding=0)

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

        self._retranslate_chrome()  # 축 라벨·눈금·도구 이름 (_build는 그래프 본체)
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
        for key, _accel in TOOLS:
            b = QToolButton()
            b.setCheckable(True)
            b.setChecked(key == self._tool)
            # 포커스를 잡으면 전역 단축키가 이 버튼에 먹힌다 — 도구 막대는 포커스 밖
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c, k=key: self.set_tool(k))
            self._tool_group.addButton(b)
            self._tool_buttons[key] = b
            bar.addWidget(b)

        bar.addSpacing(16)
        self._zoom_title = QLabel()
        bar.addWidget(self._zoom_title)
        self._zoom_buttons: dict[str, QToolButton] = {}
        bar.addWidget(self._zoom_button("out", "－", lambda: self.zoom_by(1 / 1.6)))

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(0, ZOOM_STEPS)
        self._zoom_slider.setFixedWidth(200)
        self._zoom_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        bar.addWidget(self._zoom_slider)

        bar.addWidget(self._zoom_button("in", "＋", lambda: self.zoom_by(1.6)))
        bar.addWidget(self._zoom_button("fit", "⤢", self.fit_all))
        self._zoom_label = QLabel("1.0×")
        self._zoom_label.setFixedWidth(52)
        bar.addWidget(self._zoom_label)

        bar.addSpacing(12)
        self._hint = QLabel()
        self._hint.setStyleSheet("color:#999;")
        bar.addWidget(self._hint, stretch=1)
        return bar

    def _zoom_button(self, key: str, text: str, cb) -> QToolButton:
        b = QToolButton()
        b.setText(text)   # 기호 버튼 — 설명(툴팁)만 언어를 탄다
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda: cb())
        self._zoom_buttons[key] = b
        return b

    # ---------- 범례 ----------

    def _build_legend(self) -> QWidget:
        """범례이자 순회 필터. 체크박스가 곧 ↓/↑와 클릭 스냅의 대상 목록이다 —
        각 종류의 뜻·색·개수를 이미 들고 있는 자리라 필터를 따로 둘 이유가 없다."""
        box = QWidget()
        # 그래프를 설명하는 패널이므로 그래프와 같은 배경 — 시선이 두 번 적응하지 않게
        box.setStyleSheet("background:#181818; color:#ddd;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(1)

        self._legend_head = QLabel()
        self._legend_head.setTextFormat(Qt.TextFormat.RichText)
        self._legend_head.setWordWrap(True)
        lay.addWidget(self._legend_head)

        self._legend_check = self._note("")
        lay.addWidget(self._legend_check)
        self._kind_boxes: dict[str, QCheckBox] = {}
        for kind, _key, _default in MARK_KINDS:
            color, glyph = KIND_STYLE[kind]
            cb = QCheckBox()          # 텍스트는 _update_legend가 개수와 함께 채운다
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

        # 범례 높이는 언어(문장 길이)와 임계값 표시 유무에 따라 달라진다. 창 높이에
        # 그대로 담으면 넘치는 만큼이 조용히 잘리고, 못 본 항목을 "없는 것"으로 읽게
        # 된다 — 색·기호의 뜻을 담은 패널에서 그건 그래프를 오독시킨다.
        scroll = QScrollArea()
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(254)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 전역 단축키를 뺏기지 않게
        scroll.setStyleSheet("background:#181818;")
        return scroll

    @staticmethod
    def _note(html: str) -> QLabel:
        lb = QLabel(html)
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setWordWrap(True)
        return lb

    def _update_legend(self) -> None:
        st = self.session.store
        counts = st.source_counts()
        head = [tr("timeline.legend_frames", count=len(st.frames))]
        head += [tr("timeline.legend_source", swatch=_swatch(SOURCE_COLORS[s]),
                    label=source_label(s), count=counts.get(s, 0))
                 for s in SOURCE_ORDER]
        head.append(tr("timeline.legend_multi"))
        self._legend_head.setText("<br>".join(head))

        counts_by_kind = {k: len(self.session.mark_times(k)) for k, _, _ in MARK_KINDS}
        for kind, _key, _d in MARK_KINDS:
            glyph = KIND_STYLE[kind][1]
            extra = ""
            if kind == "rejected" and not self.session.show_rejected:
                extra = tr("timeline.kind_hidden")
            elif kind == "requested" and not counts_by_kind[kind]:
                extra = tr("timeline.kind_need_at")
            elif kind == "flag" and not counts_by_kind[kind]:
                extra = tr("timeline.kind_need_flag")
            self._kind_boxes[kind].setText(tr(
                "timeline.kind_item", glyph=glyph, label=mark_label(kind),
                count=counts_by_kind[kind], extra=extra))

        tail = [tr("timeline.legend_gt"), ""]
        if st.series is not None:
            tail += [
                tr("timeline.legend_transition"), "",
                tr("timeline.legend_anchor", swatch=_swatch((90, 160, 255), "━")),
                tr("timeline.legend_anchor_thr", value=st.series["anchor_threshold"]),
                tr("timeline.legend_rate", swatch=_swatch((255, 160, 60), "━")),
                tr("timeline.legend_rate_thr", value=st.series["rate_threshold"]),
                tr("timeline.legend_area", swatch=_swatch((190, 130, 255), "━")),
                tr("timeline.legend_area_thr", value=st.series["cut_area_threshold"]),
            ]
        else:
            tail.append(tr("timeline.no_series"))
        self._legend_tail.setText("<br>".join(tail))

    # ---------- 현지화 ----------

    def retranslate(self) -> None:
        self._retranslate_chrome()
        # 기준선 라벨이 그래프 아이템 생성 시점에 박히므로 다시 그린다. 보던 구간은
        # 지킨다 — 언어를 바꿨다고 확대해 둔 자리를 잃으면 검토가 끊긴다.
        (x0, x1), _ = self._pw.getViewBox().viewRange()
        self._build()
        self._pw.setXRange(x0, x1, padding=0)

    def _retranslate_chrome(self) -> None:
        """그래프 바깥(축·도구 막대·범례 머리말·판독 줄)의 문자열."""
        self._pw.setLabel("bottom", tr("timeline.axis_time"))
        self._pw.getAxis("left").setTicks([_lane_ticks()])
        for key, accel in TOOLS:
            b = self._tool_buttons[key]
            b.setText(tr("tool.button", label=tr(f"tool.{key}"), accel=accel))
            b.setToolTip(tr(f"tool.{key}.hint"))
        self._zoom_title.setText(tr("timeline.zoom"))
        self._zoom_slider.setToolTip(tr("timeline.zoom_slider_tip"))
        for key, tip in (("out", "timeline.zoom_out"), ("in", "timeline.zoom_in"),
                         ("fit", "timeline.fit_all")):
            self._zoom_buttons[key].setToolTip(tr(tip))
        self._legend_check.setText(tr("timeline.legend_check"))
        self._readout.setText(tr("timeline.readout_idle"))

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
        held = tr("tool.space_held") if self._space_held else ""
        self._hint.setText(
            f"{tr(f'tool.{tool}.hint')}{held}    |    {tr('tool.common_hint')}")

    def note_pan(self) -> None:
        if self._space_held:
            self._space_panned = True

    def handle_shortcut(self, ev) -> bool:
        """활성 창 우선권으로 받는 키 — Space는 홀드-이동, 탭은 재생/정지."""
        key = physical_key(ev)   # 문자가 아니라 자리 — 한글 입력에서도 같게 동작
        tool_key = {Qt.Key.Key_V: "scrub", Qt.Key.Key_H: "pan",
                    Qt.Key.Key_Z: "zoom"}.get(key)
        if tool_key is not None:
            if ev.type() == QEvent.Type.KeyPress and not ev.isAutoRepeat():
                self.set_tool(tool_key)
            return True
        if key != Qt.Key.Key_Space:
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
            # interval은 '화면이 떠 있던 구간'이라 같은 화면의 이미지들(등장 직후·
            # 사라지기 직전)이 같은 값을 갖는다. 그대로 그리면 막대가 정확히
            # 포개져 뒤의 것만 보이고 앞의 것은 클릭도 안 된다 — 표시에 한해
            # 구간을 이미지 수만큼 나눠 나란히 놓는다(데이터는 건드리지 않는다).
            share: dict[tuple, list[int]] = {}
            for i, f in enumerate(st.frames):
                share.setdefault(tuple(f["interval"]), []).append(i)
            x0 = [0.0] * len(st.frames)
            x1 = [0.0] * len(st.frames)
            for (a, b), idxs in share.items():
                w = (b - a) / len(idxs)
                for k, i in enumerate(idxs):
                    x0[i], x1[i] = a + w * k, a + w * (k + 1)
            styles = [self._frame_style(f["sources"]) for f in st.frames]
            x0 = np.array(x0)
            self._pw.addItem(pg.BarGraphItem(
                x0=x0, x1=np.maximum(np.array(x1), x0 + duration * 0.001),
                y0=LANE_FRAMES[0], y1=LANE_FRAMES[1],
                brushes=[b for b, _ in styles], pens=[p for _, p in styles]))

        self._rejected_item.setData(
            [r["time"] for r in st.rejected], [LANE_REJECTED] * len(st.rejected),
            data=[tr("timeline.rejected_tip", time=r["time"],
                     reason=r["reject_reason"]) for r in st.rejected])
        self._rejected_item.setVisible(self.session.show_rejected)
        self._pw.addItem(self._rejected_item)

        if st.requested:
            self._pw.addItem(pg.ScatterPlotItem(
                x=[r["time"] for r in st.requested],
                y=[LANE_REQUESTED] * len(st.requested),
                symbol="d", size=13, brush="#c88cff", pen=None))

        if st.screens:
            self._pw.addItem(pg.ScatterPlotItem(
                x=[a for a, _ in st.screens], y=[LANE_SCREENS] * len(st.screens),
                symbol="|", size=12, brush="#96c8ff", pen=None))

        if st.segments:
            self._pw.addItem(pg.BarGraphItem(
                x0=[s["start"] for s in st.segments], x1=[s["end"] for s in st.segments],
                y0=LANE_STT[0], y1=LANE_STT[1], brush=(130, 130, 130, 110), pen=None))

        if st.series is not None:
            self._plot_diff(st)

        self._shade_unanalyzed(st, duration)

        self._update_flags()
        self._pw.addItem(self._flags_item)
        self._pw.addItem(self._playhead)
        self._apply_tool()
        self._sync_zoom_ui()
        self._update_legend()

    def _shade_unanalyzed(self, st, duration: float) -> None:
        """분석하지 않은 구간을 덮는다. 빈 구간이 "검출된 게 없음"인지 "애초에
        안 봤음"인지 구분이 안 되면 부분 분석 결과를 읽을 수 없다.

        곡선·STT는 영상 전체분(루트 산출물)이라 구간 밖에도 그려진다 — 음영이
        그 **위**에 와야 덮이는 의미가 산다. 밑에 깔면 구간 밖도 분석된 것처럼
        보인다. 반대로 재생 헤드와 GT 플래그는 어디서든 조작해야 하므로
        이 뒤에 얹어 음영 위에 남긴다."""
        lo, hi = (st.window if st.window else [0.0, duration])
        gaps = [(a, b) for a, b in ((0.0, lo), (hi, duration))
                if b - a > duration * 1e-4]
        if not gaps:
            return
        self._pw.addItem(pg.BarGraphItem(
            x0=[a for a, _ in gaps], x1=[b for _, b in gaps],
            y0=Y_RANGE[0], y1=Y_RANGE[1], brush=(20, 20, 20, 190), pen=None))

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
                 tr("timeline.thr_anchor", value=ath)),
                (s["rate"], rth, LANE_RATE, RATE_FULL, (255, 160, 60),
                 tr("timeline.thr_rate", value=rth)),
                (s["area"], cth, LANE_AREA, AREA_FULL, (190, 130, 255),
                 tr("timeline.thr_area", value=cth))):
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
            data=[tr("timeline.flag_tip", clock=fmt_time(f["time"]),
                     note=f" — {f['note']}" if f.get("note") else "")
                  for f in flags])

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
            self._readout.setText(
                f"<span style='color:#777'>{tr('timeline.out_of_range')}</span>")
            return

        parts = [f"<b>t={t:.2f}</b> ({fmt_time(t)})"]
        i = st.frame_index_at(t)
        if i is not None and st.frames:
            f = st.frames[i]
            marks = "".join(_swatch(SOURCE_COLORS.get(s, (150, 150, 150))) for s in f["sources"])
            parts.append(marks + " " + tr(
                "timeline.hover_frame", index=i, time=f["time"],
                sources="+".join(source_label(s) for s in f["sources"])))
        j = st.segment_index_at(t)
        if j is not None:
            text = st.segments[j]["text"].strip()
            parts.append(f"<span style='color:#ccc'>“{text[:70]}”</span>")
        sv = st.series_at(t)
        if sv is not None:
            anchor_d, rate, area = sv
            parts.append(tr(
                "timeline.hover_signals",
                anchor=anchor_d,
                anchor_mark="↑" if anchor_d > st.series["anchor_threshold"] else "",
                rate=rate,
                rate_mark="" if rate > st.series["rate_threshold"] else "↓",
                area=area,
                area_mark="↑" if area > st.series["cut_area_threshold"] else ""))
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
        self._readout.setText(tr("timeline.jumped", description=description))

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
