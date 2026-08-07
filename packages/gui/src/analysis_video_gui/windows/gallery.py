"""갤러리 창 — 추출 프레임 전체를 썸네일 그리드로. 클릭 = 그 시각으로 seek.

R 토글 시 탈락 프레임(frames/rejected/)도 ✗ 표시와 사유를 달고 나타난다 —
"왜 버려졌는지"를 이미지로 직접 확인하는 창구.
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..session import Session
from . import fmt_time

THUMB = QSize(192, 108)


class GalleryWindow(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(980, 640)

        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(THUMB)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setSpacing(8)
        self._list.setWordWrap(True)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(
            lambda item: session.engine.seek(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self._list)

        session.store.reloaded.connect(self._populate)
        session.showRejectedChanged.connect(lambda _: self._populate())
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
        self._list.clear()
        entries = [(f, False) for f in st.frames]
        if self.session.show_rejected:
            entries += [(r, True) for r in st.rejected if r.get("image")]
        entries.sort(key=lambda e: e[0]["time"])
        for f, is_rejected in entries:
            star = "★" if "importance-point" in f["sources"] else ""
            if is_rejected:
                caption = f"✗{star} {fmt_time(f['time'])}\n{f['reject_reason']}"
            else:
                caption = f"{star} {fmt_time(f['time'])}\n{'+'.join(f['sources'])}"
            item = QListWidgetItem(self._thumb(f["image"]), caption)
            item.setData(Qt.ItemDataRole.UserRole, f["time"])
            if is_rejected:
                item.setForeground(Qt.GlobalColor.gray)
            self._list.addItem(item)
