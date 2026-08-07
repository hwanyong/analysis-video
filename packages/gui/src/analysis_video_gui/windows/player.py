"""플레이어 창 — 영상 표시 + 트랜스포트 (버튼·슬라이더·배속·음소거·시간)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from ..playback import RATES
from ..session import Session
from . import fmt_time


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


class PlayerWindow(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        e = session.engine
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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
        self._mute.clicked.connect(lambda: e.set_muted(not e._muted))
        bar.addWidget(self._mute)

        self._time = QLabel("00:00.00 / 00:00.00")
        bar.addWidget(self._time)
        layout.addLayout(bar)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, int(e.duration * 1000))
        self._slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._slider.sliderReleased.connect(
            lambda: e.seek(self._slider.value() / 1000.0))
        self._slider.sliderMoved.connect(
            lambda v: self._time.setText(
                f"{fmt_time(v / 1000.0)} / {fmt_time(e.duration)}"))
        layout.addWidget(self._slider)

        e.frameReady.connect(lambda img, pts: self.video.set_image(img))
        e.positionChanged.connect(self._on_pos)
        e.stateChanged.connect(lambda playing: self._play_btn.setText("⏸" if playing else "▶"))
        e.mutedChanged.connect(lambda m: self._mute.setText("🔇" if m else "🔊"))
        e.rateChanged.connect(self._on_rate)

    def _on_pos(self, t: float) -> None:
        if not self._slider.isSliderDown():
            self._slider.blockSignals(True)
            self._slider.setValue(int(t * 1000))
            self._slider.blockSignals(False)
            self._time.setText(f"{fmt_time(t)} / {fmt_time(self.session.engine.duration)}")

    def _on_rate(self, rate: float) -> None:
        self._rate.blockSignals(True)
        self._rate.setCurrentIndex(RATES.index(rate))
        self._rate.blockSignals(False)
