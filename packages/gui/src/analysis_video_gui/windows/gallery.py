"""갤러리 창 — 추출 프레임 전체를 썸네일 그리드로. 클릭 = 그 시각으로 seek.

R 토글 시 탈락 프레임(frames/rejected/)도 ✗ 표시와 사유를 달고 나타난다 —
"왜 버려졌는지"를 이미지로 직접 확인하는 창구.

썸네일은 GUI 스레드에서 디코드하되 청크 단위로 나눠 넣는다: 전량 동기 디코드는
프레임이 수백 장인 긴 영상에서 창을 수 초간 얼리고, R 토글마다 반복된다.
"""
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from ..i18n import tr
from ..session import Session, source_label
from . import ChildWindow, fmt_time

THUMB = QSize(192, 108)
CHUNK = 12  # 한 틱에 디코드할 썸네일 수


class GalleryWindow(ChildWindow):
    def __init__(self, session: Session):
        super().__init__(session)
        self.resize(980, 640)

        layout = QVBoxLayout(self)
        self._status = QLabel()
        layout.addWidget(self._status)
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(THUMB)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setSpacing(8)
        self._list.setWordWrap(True)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        self._queue: list[tuple[dict, bool]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._load_chunk)

        self.bind(session.store.reloaded, self._populate)
        self.bind(session.showRejectedChanged, self._on_show_rejected)
        self._populate()

    def retranslate(self) -> None:
        """캡션이 항목마다 박혀 있어 다시 채우는 것 말고는 방법이 없다."""
        self._populate()

    def _on_item_clicked(self, item) -> None:
        self.session.engine.seek(item.data(Qt.ItemDataRole.UserRole))

    def _on_show_rejected(self, _show: bool) -> None:
        self._populate()

    def _thumb(self, rel: str) -> QIcon:
        reader = QImageReader(str(self.session.out_dir / rel))
        size = reader.size()
        if size.isValid():
            size.scale(THUMB, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(size)
        img = reader.read()
        return QIcon(QPixmap.fromImage(img)) if not img.isNull() else QIcon()

    def _populate(self) -> None:
        st = self.session.store
        self._timer.stop()
        self._list.clear()
        entries = [(f, False) for f in st.frames]
        if self.session.show_rejected:
            entries += [(r, True) for r in st.rejected if r.get("image")]
        entries.sort(key=lambda e: e[0]["time"])
        self._queue = entries
        self._total = len(entries)
        if entries:
            self._timer.start()
        self._update_status()

    def _load_chunk(self) -> None:
        for _ in range(CHUNK):
            if not self._queue:
                self._timer.stop()
                break
            f, is_rejected = self._queue.pop(0)
            star = "◐" if "screen-end" in f["sources"] else ""
            if is_rejected:
                # reject_reason은 파이프라인이 조립한 진단 코드 — 원문 그대로 (i18n 주석 참조)
                caption = f"✗{star} {fmt_time(f['time'])}\n{f['reject_reason']}"
            else:
                sources = "+".join(source_label(s) for s in f["sources"])
                caption = f"{star} {fmt_time(f['time'])}\n{sources}"
            item = QListWidgetItem(self._thumb(f["image"]), caption)
            item.setData(Qt.ItemDataRole.UserRole, f["time"])
            if is_rejected:
                item.setForeground(Qt.GlobalColor.gray)
            self._list.addItem(item)
        self._update_status()

    def _update_status(self) -> None:
        done = self._total - len(self._queue)
        suffix = ("" if not self._queue
                  else tr("gallery.loading", done=done, total=self._total))
        self._status.setText(tr("gallery.status", total=self._total, suffix=suffix))
