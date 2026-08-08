"""Session 허브 — 비시각 코디네이터.

독립 윈도우들은 서로를 모른다: 시간은 engine(단일 클록), 데이터는 store,
창의 생성·추적은 여기(WindowRegistry 역할)를 통해서만 흐른다.
새 기능 = 창 클래스 하나를 REGISTRY에 등록하면 허브 체크리스트에 자동 노출.
"""
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from .flags import FlagStore
from .playback import PlayerEngine
from .shortcuts import SHORTCUT_HELP, ShortcutRouter
from .store import Store


def _factories():
    from .windows.compare import CompareWindow
    from .windows.dialogue_sync import DialogueSyncWindow
    from .windows.frame_sync import FrameSyncWindow
    from .windows.gallery import GalleryWindow
    from .windows.player import PlayerWindow
    from .windows.timeline import TimelineWindow
    return {
        "player": PlayerWindow,
        "frame_sync": FrameSyncWindow,
        "dialogue": DialogueSyncWindow,
        "timeline": TimelineWindow,
        "gallery": GalleryWindow,
        "compare": CompareWindow,
    }


REGISTRY = [
    ("player", "① 플레이어"),
    ("frame_sync", "② 프레임 싱크"),
    ("dialogue", "③ 대사 싱크"),
    ("timeline", "④ 타임라인"),
    ("gallery", "⑤ 갤러리"),
    ("compare", "⑥ 비교 리포트"),
]

DEFAULT_OPEN = ["player", "frame_sync", "dialogue", "timeline"]


class Session(QObject):
    showRejectedChanged = Signal(bool)
    windowsChanged = Signal()

    def __init__(self, video_path: Path, out_dir: Path):
        super().__init__()
        self.video_path = video_path
        self.out_dir = out_dir
        self.store = Store(video_path, out_dir)
        self.engine = PlayerEngine(video_path, self.store.duration)
        self.flags = FlagStore(out_dir)
        self.settings = QSettings("analysis-video", "gui")
        # 탈락 후보는 기본 표시 — "왜 안 뽑혔나"가 검토의 절반이고, 실측 탈락 수는
        # 채택의 1/5 수준이라 화면을 어지럽히지 않는다. R로 끈다.
        self.show_rejected = True
        self.windows: dict[str, object] = {}
        self.router = ShortcutRouter(self)

    # ---------- 창 관리 ----------

    def open_window(self, wid: str):
        if wid in self.windows:
            w = self.windows[wid]
            w.raise_()
            w.activateWindow()
            return w
        w = _factories()[wid](self)
        w.setWindowTitle(f"{dict(REGISTRY)[wid]} — {self.video_path.name}")
        self.windows[wid] = w
        w.destroyed.connect(lambda _=None, wid=wid: self._on_closed(wid))
        geo = self.settings.value(f"geo/{wid}")
        if isinstance(geo, QByteArray):
            w.restoreGeometry(geo)
        w.show()
        self.windowsChanged.emit()
        return w

    def close_window(self, wid: str) -> None:
        w = self.windows.get(wid)
        if w is not None:
            w.close()

    def _on_closed(self, wid: str) -> None:
        self.windows.pop(wid, None)
        try:
            self.windowsChanged.emit()
        except RuntimeError:
            pass  # 앱 종료 중 — 수신자(허브)가 이미 파괴된 뒤의 destroyed 콜백

    def save_layout(self) -> None:
        self.settings.setValue("open_windows", list(self.windows.keys()))
        for wid, w in self.windows.items():
            self.settings.setValue(f"geo/{wid}", w.saveGeometry())
        self.settings.sync()

    def restore_layout(self) -> None:
        saved = self.settings.value("open_windows")
        # 저장된 적 없음(None) → 기본 배치. 저장된 빈 목록 → 사용자 의도이므로 존중
        wids = DEFAULT_OPEN if saved is None else (saved if isinstance(saved, list) else [saved])
        for wid in wids:
            if wid in dict(REGISTRY):
                self.open_window(wid)

    # ---------- 상태 ----------

    def toggle_rejected(self) -> None:
        self.show_rejected = not self.show_rejected
        self.showRejectedChanged.emit(self.show_rejected)

    def show_shortcut_help(self) -> None:
        if getattr(self, "_help_open", False):
            return  # 중첩 모달 방지
        self._help_open = True
        try:
            box = QMessageBox()
            box.setWindowTitle("키보드 단축키")
            box.setText(f"<pre>{SHORTCUT_HELP}</pre>")
            box.exec()
        finally:
            self._help_open = False

    def shutdown(self) -> None:
        self.engine.shutdown()
        QApplication.quit()
