"""프레임 싱크 창 — 재생 위치가 속한 구간의 추출 이미지 + 메타데이터 자동 표시.

Apple Music 가사 싱크의 프레임판: 영상을 넘길 때마다 "이 구간을 대표하는
추출 이미지"와 그 근거(sources·reasons·트리거 대사)가 알아서 따라온다.
플레이어 창의 '지금 화면'과 나란히 두고 비교하는 것이 검토의 핵심 루프.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ..i18n import tr
from ..session import Session, source_label
from . import ChildWindow, fmt_time


class FrameSyncWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__(session)
        self.resize(560, 640)
        self._idx: int | None = -1  # -1 = 미초기화 (None과 구분)
        self._pixmaps: dict[str, QPixmap] = {}
        self._current_pm: QPixmap | None = None

        layout = QVBoxLayout(self)
        self._image = QLabel("--")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(320, 180)
        self._image.setStyleSheet("background:#111; color:#888;")
        layout.addWidget(self._image, stretch=1)

        self._meta = QLabel()
        self._meta.setTextFormat(Qt.TextFormat.RichText)
        self._meta.setWordWrap(True)
        self._meta.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._meta)
        scroll.setFixedHeight(240)
        layout.addWidget(scroll)

        self.bind(session.engine.positionChanged, self._on_pos)
        self.bind(session.store.reloaded, self._refresh)
        self.bind(session.showRejectedChanged, self._on_show_rejected)
        self._on_pos(session.engine.position())

    def _on_show_rejected(self, _show: bool) -> None:
        self._refresh()

    def retranslate(self) -> None:
        """표시 내용이 전부 _render()가 조립하는 문장이라 다시 그리면 끝난다."""
        self._refresh()

    # ---------- 갱신 ----------

    def _on_pos(self, t: float) -> None:
        idx = self.session.store.frame_index_at(t)
        if idx != self._idx:
            self._idx = idx
            self._render()

    def _refresh(self) -> None:
        self._idx = -1
        self._pixmaps.clear()
        self._on_pos(self.session.engine.position())

    def _pixmap(self, rel: str) -> QPixmap | None:
        if rel not in self._pixmaps:
            p = self.session.out_dir / rel
            if not p.exists():
                return None
            if len(self._pixmaps) > 32:
                self._pixmaps.clear()
            self._pixmaps[rel] = QPixmap(str(p))
        return self._pixmaps[rel]

    def _render(self) -> None:
        st = self.session.store
        if self._idx is None or not st.frames:
            self._current_pm = None
            self._image.clear()  # setText 뒤 setPixmap()은 문구를 지운다 — 순서 주의
            self._image.setText(tr("fsync.no_frame"))
            self._meta.setText("")
            return
        f = st.frames[self._idx]
        pm = self._pixmap(f["image"])
        self._current_pm = pm
        self._apply_scaled()

        parts = [
            tr("fsync.head", time=f["time"], clock=fmt_time(f["time"]),
               start=f["interval"][0], end=f["interval"][1], yavg=f.get("yavg")),
            tr("fsync.detected",
               sources=" + ".join(source_label(s) for s in f["sources"])),
            f"<span style='color:gray'>{f['image']}</span>",
        ]
        for r in f.get("reasons", []):
            parts.append(tr("fsync.reason", reason=r))
        for td in f.get("trigger_dialogue", []):
            parts.append(tr("fsync.trigger_dialogue", clock=fmt_time(td["start"]),
                            text=td["text"]))
        parts.append(tr("fsync.dialogue_count", count=len(f.get("dialogue", []))))

        if self.session.show_rejected:
            rej = st.rejected_in(f["interval"][0], f["interval"][1])
            if rej:
                parts.append(tr("fsync.rejected_head"))
                for r in rej:
                    # reject_reason은 파이프라인이 조립한 진단 코드(`blank(<=0.002)`)라
                    # 번역하려면 GUI가 그 문자열 형식을 파싱해야 한다 — 원문 그대로 둔다
                    parts.append(tr(
                        "fsync.rejected_item", time=r["time"],
                        reason=r["reject_reason"],
                        extra="".join(f" ★{x}" for x in r.get("reasons", []))))
        self._meta.setText("<br>".join(parts))

    def _apply_scaled(self) -> None:
        pm = self._current_pm
        if pm is None:
            self._image.clear()
            self._image.setText(tr("fsync.no_image"))
            return
        self._image.setPixmap(pm.scaled(
            self._image.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev) -> None:
        self._apply_scaled()
        super().resizeEvent(ev)
