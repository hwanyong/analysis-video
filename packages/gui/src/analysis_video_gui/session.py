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

# 시간축 마크 종류 — (키, 표시명, 기본 순회 대상)
# STT 세그먼트는 581건짜리라 한 칸씩 넘기는 것이 의미가 없다. 레인·범례에는
# 남기되 통합 순회에서는 빼고, 필요한 사람만 필터로 켠다.
MARK_KINDS = [
    ("frame", "채택 프레임", True),
    ("rejected", "탈락 후보", True),
    ("screen", "화면 시작", False),
    ("flag", "GT 플래그", True),
    ("requested", "주문 추출", True),
    ("transition", "전환 구간", False),
    ("segment", "STT 세그먼트", False),
]
MARK_LABEL = {k: label for k, label, _ in MARK_KINDS}


class Session(QObject):
    showRejectedChanged = Signal(bool)
    windowsChanged = Signal()
    traverseChanged = Signal()           # 순회 대상 종류가 바뀜
    markJumped = Signal(str, str)        # (종류 키, 사람이 읽을 설명)

    unitChanged = Signal(str)            # 분석 단위 전환

    def __init__(self, video_path: Path, out_dir: Path, unit: str | None = None):
        super().__init__()
        self.video_path = video_path
        self.root = out_dir            # 영상 단위 — 전사·검출 캐시·GT 플래그가 여기
        self.store = Store(video_path, out_dir, unit)
        self.engine = PlayerEngine(video_path, self.store.duration)
        self.flags = FlagStore(self.root)
        self.settings = QSettings("analysis-video", "gui")
        # 탈락 후보는 기본 표시 — "왜 안 뽑혔나"가 검토의 절반이고, 실측 탈락 수는
        # 채택의 1/5 수준이라 화면을 어지럽히지 않는다. R로 끈다.
        self.show_rejected = True
        self.traverse = {k for k, _, on in MARK_KINDS if on}
        self.windows: dict[str, object] = {}
        self.router = ShortcutRouter(self)

    @property
    def out_dir(self) -> Path:
        """현재 분석 단위의 디렉토리 — 이미지·metadata·compare.json이 있는 곳.

        단위마다 달라지므로 스냅샷으로 들고 있으면 안 된다. Store가 유일한 원천이고
        여기서는 위임만 한다 — 단위를 갈아타면 이 값도 따라간다.
        영상 전체에 걸린 것(전사·GT 플래그)은 `root`."""
        return self.store.out_dir

    # ---------- 마크 순회 ----------

    def mark_times(self, kind: str) -> list[float]:
        """마크 종류별 착지 시각. 플래그만 FlagStore 소관이고 나머지는 산출물."""
        return self.flags.times() if kind == "flag" else self.store.mark_times(kind)

    def set_traverse(self, kind: str, on: bool) -> None:
        self.traverse.add(kind) if on else self.traverse.discard(kind)
        self.traverseChanged.emit()

    def jump_mark(self, forward: bool = True, kinds=None) -> float | None:
        """이전/다음 마크로 정확히 이동. kinds가 없으면 켜 둔 종류 전부를 섞는다.

        드래그로 눈대중 조준하는 대신 마크에 정확히 착지시키는 것이 목적이므로,
        후보 중 **가장 가까운 것**을 고른다(종류 우선순위 없음)."""
        kinds = self.traverse if kinds is None else set(kinds)
        now = self.engine.position()
        best: tuple[float, str] | None = None
        for kind in kinds:
            t = Store._jump(self.mark_times(kind), now, forward)
            if t is None:
                continue
            if best is None or (t < best[0] if forward else t > best[0]):
                best = (t, kind)
        if best is None:
            return None
        target, kind = best
        self.engine.seek(target)
        self.markJumped.emit(kind, self._describe_mark(kind, target))
        return target

    def _describe_mark(self, kind: str, t: float) -> str:
        times = self.mark_times(kind)
        idx = times.index(t) + 1 if t in times else 0
        return f"{MARK_LABEL.get(kind, kind)} {idx}/{len(times)} · t={t:.2f}"

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

    def set_unit(self, name: str) -> None:
        """분석 단위 전환 — 데이터만 갈아끼우면 창들이 store.reloaded로 따라온다.
        영상·클록·GT 플래그는 영상의 것이므로 그대로 둔다."""
        self.store.set_unit(name)
        self.unitChanged.emit(name)

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
