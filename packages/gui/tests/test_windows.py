"""창 수명주기·동기·단축키 회귀 테스트."""
import gc
import weakref

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from analysis_video_gui.flags import compare_metrics
from analysis_video_gui.session import REGISTRY, Session

ALL_WINDOWS = [wid for wid, _ in REGISTRY]


def _send(app, target, key, mods=Qt.KeyboardModifier.NoModifier):
    app.sendEvent(target, QKeyEvent(QKeyEvent.Type.KeyPress, key, mods, ""))
    app.processEvents()


def test_all_windows_open_and_sync(analyzed, qapp, pump):
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        for wid in ALL_WINDOWS:
            session.open_window(wid)
        pump(1.0)
        assert set(session.windows) == set(ALL_WINDOWS)

        target = session.store.frames[-1]["time"]
        session.engine.seek(target)
        pump(1.0)
        assert session.windows["frame_sync"]._idx == session.store.frame_index_at(target)
    finally:
        session.engine.shutdown()


def test_closed_window_signals_are_disconnected(analyzed, qapp, pump):
    """닫힌 창이 세션 수명 시그널을 계속 받으면 RuntimeError가 쏟아지고 객체가 샌다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        for wid in ("player", "gallery", "timeline"):
            session.open_window(wid)
        pump(0.5)
        refs = [weakref.ref(session.windows[w]) for w in ("player", "gallery")]

        session.close_window("player")
        session.close_window("gallery")
        pump(0.4)

        session.engine.play()
        pump(1.0)
        session.toggle_rejected()
        pump(0.3)
        session.engine.pause()

        gc.collect()
        assert all(r() is None for r in refs), "닫힌 창이 누수되면 안 된다"
    finally:
        session.engine.shutdown()


def test_global_shortcuts(analyzed, qapp, pump):
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        for wid in ALL_WINDOWS:
            session.open_window(wid)
        pump(0.8)
        target = session.windows["timeline"]

        # 비교 창의 스핀박스가 포커스를 잡아도 전역 단축키는 살아 있어야 한다
        _send(qapp, target, Qt.Key.Key_Space)
        assert session.engine.playing
        _send(qapp, target, Qt.Key.Key_Space)
        assert not session.engine.playing

        # Shift+구두점은 Key_Less/Key_Greater로 전달된다
        base = session.engine.rate
        _send(qapp, target, Qt.Key.Key_Greater, Qt.KeyboardModifier.ShiftModifier)
        assert session.engine.rate > base
        _send(qapp, target, Qt.Key.Key_Less, Qt.KeyboardModifier.ShiftModifier)
        assert session.engine.rate == base

        # Ctrl/⌘ 조합은 앱·OS 몫 — 가로채지 않는다
        pos = session.engine.position()
        _send(qapp, target, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        pump(0.2)
        assert abs(session.engine.position() - pos) < 1.0

        # N: 다음 채택 프레임으로 점프
        session.engine.seek(0.0)
        pump(0.4)
        _send(qapp, target, Qt.Key.Key_N)
        pump(0.3)
        assert session.engine.position() > 0.0
    finally:
        session.engine.shutdown()


def test_flag_dedupe_and_metrics(analyzed, qapp, pump):
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.engine.seek(3.0)
        pump(0.4)
        for _ in range(5):
            session.flags.add(session.engine.position())  # F 연타
        assert len(session.flags.flags) == 1
    finally:
        session.engine.shutdown()


def test_compare_metrics():
    m = compare_metrics([10.0, 50.0, 90.0], [10.5, 51.0, 200.0], tolerance=2.0)
    assert m["recall"] == round(2 / 3, 3)
    assert m["precision"] == round(2 / 3, 3)
    assert m["missed_flags"] == [90.0]
    assert m["extra_detected"] == [200.0]
