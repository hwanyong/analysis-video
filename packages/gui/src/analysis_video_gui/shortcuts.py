"""전역 단축키 라우터 — 애플리케이션 이벤트 필터.

독립 멀티 윈도우 구조의 성립 조건 ①: 어느 창에 포커스가 있어도 같은 키가
동작해야 한다. QShortcut 대신 앱 수준 이벤트 필터로 라우팅하고,
텍스트 입력 위젯에 포커스가 있으면 가로채지 않는다(YouTube 편집기 관례).

활성 창이 `handle_shortcut(ev) -> bool`을 노출하면 전역 처리보다 먼저 기회를
준다(타임라인의 Space 홀드-이동, 도구 전환 등 창 문맥 전용 키). 이때만 키 뗌
이벤트도 전달된다 — 홀드 방식 조작에는 뗌이 필수다.

한글 입력 상태에서도 같은 키가 같은 동작을 하려면 두 가지가 다 필요하다.

  ① 키를 문자가 아니라 **자리**로 볼 것 — `keys.physical_key` 참조.
  ② 키가 애초에 여기까지 **도달할 것**. macOS는 포커스 위젯이 입력기를 켜 두면
     (`WA_InputMethodEnabled`) 키를 IME에 먼저 넘기고, 한글 IME는 자모 조합을
     시작하며 그것을 삼킨다 — 이벤트 필터는 아무것도 못 본다. 지금은 이 조건이
     저절로 만족된다(실측): 이 앱이 쓰는 QListWidget·QTableWidget은 그 속성을
     켜지 않고, 켜는 것은 콤보박스 팝업의 QListView뿐인데 팝업이 떠 있으면
     어차피 아래에서 양보한다. 저절로 만족될 뿐 보장은 아니라서 — 맨 QListView나
     QTextBrowser를 하나 넣으면 그 창에서만 조용히 깨진다 — 테스트로 못박는다:
     `test_only_text_inputs_keep_the_input_method_on`.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit

from .keys import physical_key
from .playback import RATES

_EDIT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


class ShortcutRouter(QObject):
    def __init__(self, session):
        super().__init__(session)
        self.session = session
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, ev):
        press = ev.type() == QEvent.Type.KeyPress
        if not press and ev.type() != QEvent.Type.KeyRelease:
            return False
        app = QApplication.instance()
        # 모달 대화상자(도움말 등)·팝업(콤보박스 드롭다운)이 떠 있으면 그쪽이 우선
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return False
        # 입력 위젯 양보는 "그 입력 창을 보고 있을 때"로 한정한다. 앱 전역
        # focusWidget은 비활성 창의 것일 수도 있어(비교 창의 허용오차 스핀박스 등),
        # 그대로 믿으면 다른 창을 보는 동안 전 단축키가 죽는다.
        active = QApplication.activeWindow()
        fw = QApplication.focusWidget()
        if isinstance(fw, _EDIT_WIDGETS):
            if active is None or fw.window() is active:
                if press and physical_key(ev) == Qt.Key.Key_Escape:
                    fw.clearFocus()  # 편집 종료 → 단축키 복귀
                    return True
                return False
        # Ctrl/⌘/Alt 조합은 앱·OS 단축키(복사, 창 전환 등)의 것 — 가로채지 않는다
        blocking = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier)
        if ev.modifiers() & blocking:
            return False
        # 창 문맥 전용 키(홀드 조작 등)에 먼저 기회를 준다
        handler = getattr(active, "handle_shortcut", None)
        if handler is not None and handler(ev):
            return True
        return self._dispatch(ev) if press else False

    def _dispatch(self, ev) -> bool:
        s = self.session
        e = s.engine
        key = physical_key(ev)   # 자리 기준 — Shift 변형(<, >, ?)도 여기서 접힌다
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        repeat = ev.isAutoRepeat()

        if key in (Qt.Key.Key_Space, Qt.Key.Key_K):
            if not repeat:
                e.toggle()
            return True
        if key == Qt.Key.Key_Left:
            e.seek_relative(-5.0)
            return True
        if key == Qt.Key.Key_Right:
            e.seek_relative(5.0)
            return True
        if key == Qt.Key.Key_J:
            e.seek_relative(-10.0)
            return True
        if key == Qt.Key.Key_L:
            e.seek_relative(10.0)
            return True
        if key == Qt.Key.Key_Comma:
            self._rate_step(-1) if shift else e.step_frame(-1)
            return True
        if key == Qt.Key.Key_Period:
            self._rate_step(+1) if shift else e.step_frame(+1)
            return True
        if key == Qt.Key.Key_M:
            if not repeat:
                e.set_muted(not e.muted)
            return True
        if key == Qt.Key.Key_Home:
            e.seek(0.0)
            return True
        if key == Qt.Key.Key_End:
            e.seek(e.duration - 0.1)
            return True
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            e.seek(e.duration * (key - Qt.Key.Key_0) / 10.0)
            return True
        # ↑/↓ = 켜 둔 종류를 섞어 이전/다음 마크. 전용 키는 자주 쓰는 3종만.
        if key == Qt.Key.Key_Down:
            s.jump_mark(forward=True)
            return True
        if key == Qt.Key.Key_Up:
            s.jump_mark(forward=False)
            return True
        if key == Qt.Key.Key_N:
            s.jump_mark(forward=not shift, kinds=["frame"])
            return True
        if key == Qt.Key.Key_G:
            s.jump_mark(forward=not shift, kinds=["flag"])
            return True
        if key == Qt.Key.Key_R:
            if not repeat:
                s.toggle_rejected()
            return True
        if key == Qt.Key.Key_F:
            if not repeat:
                s.flags.toggle(e.position())  # 같은 자리에서 다시 누르면 취소
            return True
        if key == Qt.Key.Key_Slash and shift:   # ⇧/ = ? (도움말 표기와 일치)
            if not repeat:
                s.show_shortcut_help()
            return True
        return False

    def _rate_step(self, direction: int) -> None:
        e = self.session.engine
        i = min(range(len(RATES)), key=lambda i: abs(RATES[i] - e.rate))
        e.set_rate(RATES[max(0, min(len(RATES) - 1, i + direction))])
