"""창 수명주기·동기·단축키 회귀 테스트."""
import gc
import weakref

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QInputMethodQueryEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from analysis_video_gui.flags import compare_metrics
from analysis_video_gui.i18n import tr
from analysis_video_gui.session import REGISTRY, Session, mark_label
from analysis_video_gui.shortcuts import _EDIT_WIDGETS
from analysis_video_gui.windows.hub import HubWindow

ALL_WINDOWS = [wid for wid, _ in REGISTRY]


class _ClickEvent:
    """pyqtgraph 씬 클릭 이벤트 대역 — QTest로는 뷰박스 좌표를 지정할 수 없다."""

    def __init__(self, timeline, t, modifiers):
        from PySide6.QtCore import QPointF
        self._mods = modifiers
        self._pos = timeline._pw.getViewBox().mapViewToScene(QPointF(t, 5.5))

    def button(self):
        return Qt.MouseButton.LeftButton

    def modifiers(self):
        return self._mods

    def scenePos(self):
        return self._pos


class _FakeWheel:
    """pyqtgraph 휠 이벤트 대역 — QTest에는 휠 시뮬레이터가 없다."""

    def __init__(self, delta, viewbox, t):
        import pyqtgraph as pg
        self._delta = delta
        self._pos = viewbox.mapViewToScene(pg.Point(t, 3.0))

    def delta(self):
        return self._delta

    def scenePos(self):
        return self._pos

    def accept(self):
        pass


def _send(app, target, key, mods=Qt.KeyboardModifier.NoModifier):
    app.sendEvent(target, QKeyEvent(QKeyEvent.Type.KeyPress, key, mods, ""))
    app.processEvents()


def _hangul(key, mods=Qt.KeyboardModifier.NoModifier, type_=QKeyEvent.Type.KeyPress):
    """한글 입력원에서 `key` 자리를 누른 이벤트 — 문자는 자모로 온다."""
    from analysis_video_gui.keys import NATIVE_FIELD, NATIVE_KEYCODES

    code = next(c for c, k in NATIVE_KEYCODES.items() if k == key)
    scan = code if NATIVE_FIELD == "nativeScanCode" else 0
    virt = code if NATIVE_FIELD == "nativeVirtualKey" else 0
    return QKeyEvent(type_, 0x314F, mods, scan, virt, 0, "ㅏ", False, 1)


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


def test_hub_is_neither_globally_topmost_nor_a_tool_window(analyzed, qapp):
    """허브의 "위"는 이 앱 안에서만이다 — 전역 최상위·Tool 창으로 되돌아가지 못하게 막는다.

    `WindowStaysOnTopHint`는 이 앱이 비활성일 때도 브라우저·에디터 위에 남고,
    `Qt.Tool`은 macOS에서 NSPanel이 되어 앱 비활성 시 통째로 숨거나(기본) 숨김을
    끄면 다른 앱 위로 뜬다. 둘 다 눈으로 보기 전에는 티가 안 나는 회귀라 플래그
    자체를 못박는다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        flags = HubWindow(session).windowFlags()
        assert not (flags & Qt.WindowType.WindowStaysOnTopHint), \
            "전역 최상위는 다른 앱 위로도 뜬다"
        assert int(flags & Qt.WindowType.WindowType_Mask) == int(Qt.WindowType.Window), \
            "허브는 평범한 최상위 창이어야 한다(Tool/Dialog 아님)"
    finally:
        session.engine.shutdown()


def test_hub_rides_above_siblings_without_taking_focus(analyzed, qapp, pump):
    """허브는 형제 창이 앞으로 나올 때마다 따라 올라오되 포커스는 건드리지 않는다.

    `raise_`/`activateWindow`를 가로채 확인한다 — 오프스크린에서는 실제 창 순서를
    볼 수 없고, 여기서 못박을 것은 "언제 올리고 언제 올리지 않는가"라는 판단
    자체이기 때문이다. 실제로 위에 뜨는지는 사람이 눈으로 확인할 몫."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    hub = HubWindow(session)
    hub.show()
    pump(0.3)
    raised, activated = [], []
    hub.raise_ = lambda: raised.append("raise")
    hub.activateWindow = lambda: activated.append("activate")
    try:
        player = session.open_window("player")
        pump(0.5)
        assert raised, "창이 새로 열리면 허브가 그 위로 올라와야 한다"

        raised.clear()
        qapp.focusWindowChanged.emit(player.windowHandle())
        assert raised == ["raise"], "형제 창이 포커스를 잡으면 허브가 올라온다"
        assert not activated, "포커스를 훔치면 스크럽·타이핑 도중 창을 못 쓴다"

        # 포커스가 다른 앱으로 넘어감(None) — 여기서 올리면 브라우저 위로 튀어나온다
        raised.clear()
        qapp.focusWindowChanged.emit(None)
        assert not raised, "다른 앱으로 나갈 때 올리면 시스템 전역 최상위와 같아진다"

        # 허브 자신 → 다시 올리지 않는다. 재진입(올림 → 포커스 변화 → 올림)이
        # 성립하지 않는다는 뜻이라 별도의 재귀 방지 장치가 필요 없다.
        qapp.focusWindowChanged.emit(hub.windowHandle())
        assert not raised

        # 세션 장부에 없는 창 = 모달 도움말·콤보박스 팝업 — 덮으면 안 된다
        stranger = QWidget()
        stranger.show()
        pump(0.2)
        qapp.focusWindowChanged.emit(stranger.windowHandle())
        assert not raised, "앱 모달을 덮으면 클릭이 막혀 아무것도 못 하게 된다"
        stranger.close()

        # 닫힌 허브에 앱 수명 시그널이 계속 배달되면 파괴된 위젯을 건드리게 된다.
        # shutdown은 대역으로 둔다 — 여기서 QApplication.quit()이 돌면 테스트
        # 프로세스가 공유하는 앱 객체가 끝난다.
        session.shutdown = lambda: None
        hub.close()
        raised.clear()
        qapp.focusWindowChanged.emit(player.windowHandle())
        assert not raised, "닫힌 허브가 포커스 변경을 계속 받으면 안 된다"
    finally:
        session.engine.shutdown()


def test_images_resolve_against_the_analysis_unit(analyzed, qapp, pump):
    """metadata의 image는 **단위 디렉토리** 기준 상대경로다. 루트 기준으로 풀면
    파일이 하나도 안 잡혀 모든 창이 조용히 '이미지 파일 없음'만 띄운다 —
    창은 정상으로 보이고 테스트도 통과하므로, 경로가 실제로 풀리는지를 여기서 못박는다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        assert session.out_dir == session.store.out_dir, "이미지 기준은 단위 디렉토리"
        frames = session.store.frames
        assert frames, "픽스처가 프레임을 하나도 안 뽑았다 — 테스트가 무의미해진다"
        for f in frames:
            assert (session.out_dir / f["image"]).exists(), \
                f"{f['image']}가 {session.out_dir} 기준으로 풀리지 않는다"

        fs = session.open_window("frame_sync")
        gal = session.open_window("gallery")
        session.engine.seek(frames[-1]["time"])
        pump(1.0)
        assert fs._image.pixmap() and not fs._image.pixmap().isNull(), \
            "프레임 싱크가 그림 대신 안내 문구를 띄우고 있다"
        assert gal._list.count() >= len(frames)
        assert not gal._list.item(0).icon().isNull(), "갤러리 썸네일이 비었다"
    finally:
        session.engine.shutdown()


def test_out_dir_follows_unit_switch(analyzed, qapp):
    """단위를 갈아타면 이미지가 있는 곳도 같이 바뀐다 — 세션이 경로를 스냅샷으로
    들고 있으면 전환 후 이전 단위의 그림을 찾다가 전부 놓친다."""
    from analysis_video import cli

    video, out_dir = analyzed
    assert cli.main(["frames", str(video), "--out", str(out_dir), "--range", "2-6"]) == 0
    session = Session(video, out_dir)
    try:
        names = [e["name"] for e in session.store.available_units()]
        assert len(names) == 2, f"단위가 둘이어야 한다: {names}"
        other = next(n for n in names if n != session.store.unit)
        session.set_unit(other)
        assert session.out_dir == out_dir / "runs" / other
        for f in session.store.frames:
            assert (session.out_dir / f["image"]).exists()
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

        # Shift+구두점은 Key_Less/Key_Greater로 전달된다 — 대표 키로 접혀야 한다
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


def test_shortcuts_survive_a_hangul_input_source(analyzed, qapp, pump):
    """입력원이 한글이어도 **같은 자리는 같은 동작**이어야 한다.

    한글 입력에서 K를 누르면 OS는 Key_K가 아니라 자모('ㅏ')를 실어 보낸다.
    문자로 비교하던 예전 라우터는 영문 입력일 때만 동작했다 — 사용자가 글을
    쓰다 돌아오면 단축키가 통째로 죽는, 눈에 잘 안 띄는 회귀다.
    """
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.8)
        tl = session.windows["timeline"]

        qapp.sendEvent(tl, _hangul(Qt.Key.Key_K))
        qapp.processEvents()
        assert session.engine.playing, "한글 입력에서도 K는 재생/정지여야 한다"
        qapp.sendEvent(tl, _hangul(Qt.Key.Key_K))
        qapp.processEvents()
        assert not session.engine.playing

        base = session.engine.rate
        qapp.sendEvent(tl, _hangul(Qt.Key.Key_Period,
                                   Qt.KeyboardModifier.ShiftModifier))
        qapp.processEvents()
        assert session.engine.rate > base, "⇧.(배속 올림)이 한글에서 죽었다"

        session.engine.seek(0.0)
        pump(0.4)
        qapp.sendEvent(tl, _hangul(Qt.Key.Key_N))
        pump(0.3)
        assert session.engine.position() > 0.0, "N(다음 채택 프레임)이 한글에서 죽었다"

        # 창 문맥 전용 키(도구 전환)도 같은 규칙을 따른다
        assert tl.handle_shortcut(_hangul(Qt.Key.Key_Z))
        assert tl.effective_tool() == "zoom"
        assert tl.handle_shortcut(_hangul(Qt.Key.Key_V))
        assert tl.effective_tool() == "scrub"
    finally:
        session.engine.shutdown()


def test_help_needs_shift_because_it_is_documented_as_question_mark(analyzed, qapp, pump):
    """도움말은 ⇧/(=?)에서만 열린다 — 맨 `/`는 가로채지도 않는다.

    `?`는 Shift 변형이라 라우터 안에서 대표 키 `/`로 접힌다. 접은 뒤 Shift를
    다시 요구하지 않으면 맨 `/`에도 모달이 뜬다. 실제로 여는 대신 호출 여부만
    본다 — `show_shortcut_help`는 `QMessageBox.exec()`로 막힌다.
    """
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        target = session.windows["timeline"]

        calls = []
        session.show_shortcut_help = lambda: calls.append(1)

        _send(qapp, target, Qt.Key.Key_Slash)
        assert not calls, "맨 /로는 열리지 않아야 한다"

        _send(qapp, target, Qt.Key.Key_Question, Qt.KeyboardModifier.ShiftModifier)
        assert len(calls) == 1, "⇧/(=?)로는 열려야 한다"

        # 한글 입력이어도 마찬가지 — `/`는 자리로, Shift는 수식키로 판정된다
        qapp.sendEvent(target, _hangul(Qt.Key.Key_Slash,
                                       Qt.KeyboardModifier.ShiftModifier))
        qapp.processEvents()
        assert len(calls) == 2
    finally:
        session.engine.shutdown()


def test_only_text_inputs_keep_the_input_method_on(analyzed, qapp, pump):
    """텍스트 입력 위젯이 아니면 입력기가 꺼져 있어야 한다.

    macOS는 포커스 위젯이 `WA_InputMethodEnabled`이면 키를 IME에 먼저 넘기고,
    한글 IME는 자모 조합을 시작하며 그것을 삼킨다 — 전역 단축키 라우터는
    이벤트를 **아예 못 받는다**. 자리 기준 판정(`physical_key`)으로는 못 고치는
    경로다.

    지금 쓰는 위젯들은 이 조건을 저절로 만족한다(QListWidget·QTableWidget은
    입력기를 켜지 않는다). 보장이 아니라 우연이라 여기서 못박는다 — 맨
    QListView나 QTextBrowser를 하나 넣으면 그 창에 포커스가 있는 동안만
    단축키가 죽는, 재현 조건이 까다로운 회귀가 생긴다.
    """
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        for wid in ALL_WINDOWS:
            session.open_window(wid)
        pump(1.0)

        # 이 세션의 창들만 본다 — allWidgets()는 앱 전역이라 앞 테스트가 남긴
        # 위젯(콤보 팝업 등)까지 딸려 오고, 팝업은 애초에 라우터가 양보한다.
        mine = {w.window() for w in session.windows.values()}
        q = Qt.InputMethodQuery.ImEnabled | Qt.InputMethodQuery.ImHints
        offenders = set()
        for w in qapp.allWidgets():
            if w.window() not in mine or isinstance(w, _EDIT_WIDGETS):
                continue
            if not w.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled):
                continue
            if w.focusPolicy() == Qt.FocusPolicy.NoFocus:
                continue          # 포커스를 못 잡으면 IME로 갈 일도 없다
            ev = QInputMethodQueryEvent(q)   # qnsview가 IME 위임을 정할 때와 같은 질의
            qapp.sendEvent(w, ev)
            if ev.value(Qt.InputMethodQuery.ImEnabled):
                offenders.add(f"{type(w).__name__} in {type(w.window()).__name__}")
        assert not offenders, \
            f"입력기를 켜 둔 비-입력 위젯: {sorted(offenders)} — 한글에서 단축키가 먹힌다"
    finally:
        session.engine.shutdown()


def test_player_slider_scrubs_from_click_point(analyzed, qapp, pump):
    """누른 지점이 곧 위치이고(페이지 스텝이 아니라), 끄는 동안 화면이 따라온다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("player")
        pump(0.8)
        player = session.windows["player"]
        e = session.engine
        sl = player._slider
        y = sl.height() // 2
        w = sl.width()

        frames = []
        e.frameReady.connect(lambda img, pts: frames.append(pts))

        QTest.mousePress(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(w * 0.3), y))
        pump(0.2)
        assert e.scrubbing, "누르는 순간 스크럽이 시작된다"
        assert abs(e.position() - e.duration * 0.3) < e.duration * 0.06, \
            "누른 지점으로 잡혀야 한다 — 페이지 스텝이면 거의 움직이지 않는다"

        for f in (0.4, 0.5, 0.6, 0.7, 0.8):
            QTest.mouseMove(sl, QPoint(int(w * f), y))
            pump(0.12)
        assert len(frames) >= 3, "드래그 도중 프레임이 갱신되어야 한다"

        QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(int(w * 0.8), y))
        pump(0.6)
        assert not e.scrubbing
        assert abs(e.position() - e.duration * 0.8) < e.duration * 0.06
    finally:
        session.engine.shutdown()


def test_timeline_tools_and_zoom(analyzed, qapp, pump):
    """도구가 드래그의 의미를 바꾸고, 배율 조작이 실제 보이는 구간을 바꾼다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]
        vb = tl._pw.getViewBox()

        # 기본은 스크럽 — 뷰박스 드래그(팬)를 꺼야 드래그가 재생 위치로 간다
        assert tl.effective_tool() == "scrub"
        assert vb.state["mouseEnabled"] == [False, False]

        tl.set_tool("pan")
        assert vb.state["mouseEnabled"] == [True, True], "이동은 상하좌우 모두"
        assert vb.state["mouseMode"] == vb.PanMode
        tl.set_tool("zoom")
        assert vb.state["mouseMode"] == vb.RectMode
        tl.set_tool("scrub")

        # 배율: 확대하면 보이는 폭이 줄고, 전체 보기로 되돌아온다
        tl.set_zoom(4.0, center=session.store.duration / 2)
        pump(0.2)
        (x0, x1), _ = vb.viewRange()
        assert abs((x1 - x0) - session.store.duration / 4) < session.store.duration * 0.05
        assert tl._zoom_slider.value() > 0, "슬라이더가 현재 배율을 반영해야 한다"

        tl.fit_all()
        pump(0.2)
        (x0, x1), _ = vb.viewRange()
        assert abs((x1 - x0) - session.store.duration) < session.store.duration * 0.05
        assert tl._zoom_slider.value() == 0

        # 슬라이더 조작 → 뷰 범위 변경 (되먹임 루프 없이)
        tl._zoom_slider.setValue(tl._zoom_slider.maximum())
        pump(0.2)
        (x0, x1), _ = vb.viewRange()
        assert x1 - x0 < session.store.duration / 2

        # 휠 줌은 뷰박스 마우스를 끈 스크럽 도구에서도 살아 있어야 하고,
        # 위로 굴리면 확대(= 배율 증가)여야 한다
        tl.fit_all()
        pump(0.2)
        before = tl._zoom_now()
        vb.wheelEvent(_FakeWheel(120, vb, session.store.duration / 2))
        pump(0.2)
        assert tl._zoom_now() > before, "휠 업 = 확대"
        vb.wheelEvent(_FakeWheel(-240, vb, session.store.duration / 2))
        pump(0.2)
        assert tl._zoom_now() <= before + 1e-6, "휠 다운 = 축소"
    finally:
        session.engine.shutdown()


def test_timeline_space_hold_pans_but_tap_toggles(analyzed, qapp, pump):
    """Space는 홀드하면 임시 이동, 끌지 않고 떼면 평소대로 재생/정지."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]
        press = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space,
                          Qt.KeyboardModifier.NoModifier, "")
        release = QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Space,
                            Qt.KeyboardModifier.NoModifier, "")

        was = session.engine.playing
        tl.handle_shortcut(press)
        assert tl.effective_tool() == "pan", "홀드 중에는 도구와 무관하게 이동"
        tl.note_pan()                        # 실제로 끌었다
        tl.handle_shortcut(release)
        assert tl.effective_tool() == "scrub"
        assert session.engine.playing == was, "끈 뒤 뗌은 재생을 건드리지 않는다"

        tl.handle_shortcut(press)            # 끌지 않은 탭
        tl.handle_shortcut(release)
        pump(0.2)
        assert session.engine.playing != was
        session.engine.pause()
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


def test_flag_toggle_and_timeline_delete(analyzed, qapp, pump):
    """만든 자리에서 취소되어야 한다 — 기입은 F/타임라인, 취소는 다른 창이면 막힌 것."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]

        assert session.flags.toggle(3.0) is True
        assert session.flags.times() == [3.0]
        assert session.flags.toggle(3.05) is False, "같은 자리 재입력은 취소"
        assert session.flags.times() == []

        session.flags.toggle(2.0, "a")
        session.flags.toggle(5.0, "b")
        pump(0.3)

        # 타임라인 ⇧클릭 = 그 자리 플래그 삭제 / 맨클릭 = seek
        tl._on_click(_ClickEvent(tl, 5.02, Qt.KeyboardModifier.ShiftModifier))
        pump(0.3)
        assert session.flags.times() == [2.0]

        tl._on_click(_ClickEvent(tl, 6.0, Qt.KeyboardModifier.NoModifier))
        pump(0.5)
        assert abs(session.engine.position() - 6.0) < 0.5
        assert session.flags.times() == [2.0], "맨클릭은 플래그를 지우지 않는다"
    finally:
        session.engine.shutdown()


def test_mark_traversal_and_viewport_follow(analyzed, qapp, pump):
    """↓/↑는 켜 둔 종류를 섞어 정확히 착지하고, 확대 상태에서도 커서를 놓치지 않는다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]
        frames = session.store.mark_times("frame")
        assert len(frames) >= 3, "합성 영상에서 프레임이 여러 개 나와야 의미가 있다"

        session.engine.seek(0.0)
        pump(0.4)
        jumped = []
        session.markJumped.connect(lambda k, d: jumped.append((k, d)))

        t1 = session.jump_mark(forward=True)
        assert t1 in frames, "정확히 마크에 착지"
        t2 = session.jump_mark(forward=True)
        assert t2 is not None and t2 > t1, "다음 마크로 전진"
        assert session.jump_mark(forward=False) == t1, "뒤로 = 직전 마크"
        assert len(jumped) == 3 and all("/" in d for _k, d in jumped), \
            "무엇으로 왔는지 설명이 나와야 한다"

        # 필터를 전부 끄면 갈 곳이 없다
        for kind in list(session.traverse):
            session.set_traverse(kind, False)
        assert session.jump_mark(forward=True) is None

        # 확대 상태에서 점프하면 뷰포트가 커서를 따라온다
        session.set_traverse("frame", True)
        session.engine.seek(0.0)
        pump(0.4)
        tl.set_zoom(tl._zoom_max())
        pump(0.3)
        target = session.jump_mark(forward=True)
        pump(0.5)
        (x0, x1), _ = tl._pw.getViewBox().viewRange()
        assert x0 <= target <= x1, "점프한 커서가 화면 안에 있어야 한다"
    finally:
        session.engine.shutdown()


def test_timeline_click_snaps_to_nearest_mark(analyzed, qapp, pump):
    """클릭이 생좌표로 가면 드래그 조준과 다를 게 없다 — 가까운 마크에 붙어야 한다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]
        mark = session.store.mark_times("frame")[1]

        tl._on_click(_ClickEvent(tl, mark + 0.02, Qt.KeyboardModifier.NoModifier))
        pump(0.5)
        assert abs(session.engine.position() - mark) < 0.02, "마크에 달라붙어야 한다"

        # 켜지 않은 종류에는 붙지 않는다
        session.set_traverse("frame", False)
        far = mark + 0.02
        tl._on_click(_ClickEvent(tl, far, Qt.KeyboardModifier.NoModifier))
        pump(0.5)
        assert abs(session.engine.position() - far) < 0.05
    finally:
        session.engine.shutdown()


def test_playhead_label_follows_programmatic_seek(analyzed, qapp, pump):
    """커서 시각 라벨은 setPos가 내는 시그널로만 갱신된다 — 막으면 0.00s에 언다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]
        session.engine.seek(5.0)
        pump(0.6)
        assert "5." in tl._playhead.label.textItem.toPlainText()
    finally:
        session.engine.shutdown()


def _flag_box_text(count: int, extra_key: str | None) -> str:
    return tr("timeline.kind_item", glyph="▲", label=mark_label("flag"), count=count,
              extra=tr(extra_key) if extra_key else "")


def test_timeline_legend_reports_counts(analyzed, qapp, pump):
    """비어 있는 레인이 '0건'인지 '숨김'인지 범례에서 구분되어야 한다.

    단언을 카탈로그로 조립하는 이유: 여기서 보는 것은 개수와 숨김 상태가 드러나는가
    이지 그것이 한국어인가가 아니다. 문구를 박아 두면 번역만 손봐도 테스트가 깨진다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        session.open_window("timeline")
        pump(0.6)
        tl = session.windows["timeline"]
        assert tr("timeline.legend_frames", count=len(session.store.frames)) \
            in tl._legend_head.text()
        assert tl._kind_boxes["rejected"].text().endswith(
            str(len(session.store.rejected))), "기본은 표시 상태(숨김 표기 없음)"
        assert tl._kind_boxes["flag"].text() == \
            _flag_box_text(0, "timeline.kind_need_flag")

        session.toggle_rejected()
        pump(0.2)
        assert tr("timeline.kind_hidden") in tl._kind_boxes["rejected"].text(), \
            "숨긴 상태가 드러나야 한다"

        session.flags.toggle(2.0)
        pump(0.2)
        assert tl._kind_boxes["flag"].text() == _flag_box_text(1, None)

        # 체크박스가 곧 순회 필터
        assert not tl._kind_boxes["segment"].isChecked(), "STT는 수백 건이라 기본 제외"
        tl._kind_boxes["segment"].setChecked(True)
        pump(0.2)
        assert "segment" in session.traverse
    finally:
        session.engine.shutdown()


def test_compare_metrics():
    m = compare_metrics([10.0, 50.0, 90.0], [10.5, 51.0, 200.0], tolerance=2.0)
    assert m["recall"] == round(2 / 3, 3)
    assert m["precision"] == round(2 / 3, 3)
    assert m["missed_flags"] == [90.0]
    assert m["extra_detected"] == [200.0]


def test_metrics_are_undefined_without_ground_truth():
    """정답지가 없으면 precision도 정의되지 않는다 — 0/n을 0.0%로 내보내면
    '아직 안 찍었다'가 '로직이 다 틀렸다'로 읽힌다."""
    m = compare_metrics([], [10.0, 20.0, 30.0], tolerance=2.0)
    assert m["precision"] is None and m["recall"] is None
    assert m["n_detected"] == 3
    # 검출이 없을 때도 마찬가지 — 둘 중 하나만 비어도 비교가 성립하지 않는다
    assert compare_metrics([10.0], [], tolerance=2.0)["precision"] is None
