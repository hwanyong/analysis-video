"""플레이어 창 — 영상 표시 + 트랜스포트 (버튼·슬라이더·배속·음소거·시간).

슬라이더는 드래그하는 동안 화면이 따라오는 스크럽 방식이다(놓을 때 한 번 점프가
아니라). 검토 작업의 대부분이 "이 근처 어딘가"를 눈으로 찾는 일이라, 놓기 전까지
화면이 멈춰 있으면 찍고-확인하고-다시 찍는 왕복이 된다.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QStyle, QStyleOptionSlider, QVBoxLayout, QWidget)

from ..i18n import tr
from ..playback import RATES
from ..session import Session
from . import ChildWindow, fmt_time


class VideoWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._img: QImage | None = None
        self.setMinimumSize(480, 270)

    def set_image(self, img: QImage) -> None:
        self._img = img
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._img is not None:
            scaled = self._img.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawImage(x, y, scaled)
        p.end()


class SeekSlider(QSlider):
    """어디를 눌러도 그 지점을 잡는 슬라이더.

    기본 QSlider는 스타일에 따라 그루브 클릭이 페이지 스텝이라, 바를 집어 끄는
    조작이 손끝과 어긋난다. 눌린 지점을 핸들 위치로 삼고 그대로 드래그로 잇는다.
    """

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setSliderDown(True)          # sliderPressed → 스크럽 시작
            self._set_from_x(ev.position().x())
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self.isSliderDown():
            self._set_from_x(ev.position().x())
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)         # sliderReleased → 스크럽 종료
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def _set_from_x(self, x: float) -> None:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        groove = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderGroove, self)
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderHandle, self)
        span = max(groove.width() - handle.width(), 1)
        pos = int(x) - groove.x() - handle.width() // 2
        self.setValue(QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), pos, span))


class PlayerWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__(session)
        e = session.engine
        self.resize(960, 620)

        layout = QVBoxLayout(self)
        self.video = VideoWidget()
        layout.addWidget(self.video, stretch=1)

        bar = QHBoxLayout()

        def btn(text, cb, tip=""):
            b = QPushButton(text)
            b.setFixedWidth(46)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space가 버튼에 먹히지 않게
            b.clicked.connect(cb)
            if tip:
                b.setToolTip(tip)
            bar.addWidget(b)
            return b

        btn("◀10", lambda: e.seek_relative(-10), "J")
        btn("◀5", lambda: e.seek_relative(-5), "←")
        self._play_btn = btn("▶", e.toggle, "Space")
        btn("5▶", lambda: e.seek_relative(5), "→")
        btn("10▶", lambda: e.seek_relative(10), "L")

        self._rate = QComboBox()
        self._rate.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for r in RATES:
            self._rate.addItem(f"{r}x", r)
        self._rate.setCurrentIndex(RATES.index(1.0))
        self._rate.currentIndexChanged.connect(
            lambda i: e.set_rate(self._rate.itemData(i)))
        bar.addWidget(self._rate)

        self._mute = QPushButton("🔊")
        self._mute.setFixedWidth(40)
        self._mute.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mute.clicked.connect(lambda: e.set_muted(not e.muted))
        bar.addWidget(self._mute)

        self._time = QLabel("00:00.00 / 00:00.00")
        bar.addWidget(self._time)
        layout.addLayout(bar)

        self._slider = SeekSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, int(e.duration * 1000))
        self._slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._slider.sliderPressed.connect(e.begin_scrub)
        self._slider.sliderReleased.connect(e.end_scrub)
        # valueChanged로 받으면 드래그·그루브 클릭·휠이 한 경로로 들어온다.
        # 되먹임은 _on_pos의 blockSignals가 차단한다.
        self._slider.valueChanged.connect(self._on_slider_value)
        layout.addWidget(self._slider)

        self.bind(e.frameReady, self._on_frame)
        self.bind(e.positionChanged, self._on_pos)
        self.bind(e.stateChanged, self._on_state)
        self.bind(e.mutedChanged, self._on_muted)
        self.bind(e.rateChanged, self._on_rate)
        self.retranslate()

    def retranslate(self) -> None:
        """트랜스포트 버튼은 기호·키 이름이라 번역 대상이 아니다 — 설명만 갈아 끼운다."""
        self._slider.setToolTip(tr("player.slider_tip"))
        self._rate.setToolTip(tr("player.rate_tip"))
        self._mute.setToolTip(tr("player.mute_tip"))

    def _on_frame(self, img: QImage, pts: float) -> None:
        self.video.set_image(img)

    def _on_state(self, playing: bool) -> None:
        self._play_btn.setText("⏸" if playing else "▶")

    def _on_muted(self, muted: bool) -> None:
        self._mute.setText("🔇" if muted else "🔊")

    def _on_slider_value(self, v: int) -> None:
        t = v / 1000.0
        e = self.session.engine
        # 드래그 중이면 스크럽(연속), 아니면 휠·키보드 조작이므로 정식 시크
        e.scrub_to(t) if self._slider.isSliderDown() else e.seek(t)

    def _on_pos(self, t: float) -> None:
        if not self._slider.isSliderDown():
            self._slider.blockSignals(True)
            self._slider.setValue(int(t * 1000))
            self._slider.blockSignals(False)
        # 시간 표시는 드래그 중에도 갱신한다 — 스크럽 위치가 곧 현재 위치다
        self._time.setText(f"{fmt_time(t)} / {fmt_time(self.session.engine.duration)}")

    def _on_rate(self, rate: float) -> None:
        self._rate.blockSignals(True)
        self._rate.setCurrentIndex(RATES.index(rate))
        self._rate.blockSignals(False)
