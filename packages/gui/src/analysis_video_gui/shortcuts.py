"""전역 단축키 라우터 — 애플리케이션 이벤트 필터.

독립 멀티 윈도우 구조의 성립 조건 ①: 어느 창에 포커스가 있어도 같은 키가
동작해야 한다. QShortcut 대신 앱 수준 이벤트 필터로 라우팅하고,
텍스트 입력 위젯에 포커스가 있으면 가로채지 않는다(YouTube 편집기 관례).

활성 창이 `handle_shortcut(ev) -> bool`을 노출하면 전역 처리보다 먼저 기회를
준다(타임라인의 Space 홀드-이동, 도구 전환 등 창 문맥 전용 키). 이때만 키 뗌
이벤트도 전달된다 — 홀드 방식 조작에는 뗌이 필수다.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit

from .playback import RATES

SHORTCUT_HELP = """\
[재생]                              [마크로 정확히 이동]
Space / K      재생 · 일시정지          ↓ / ↑      다음/이전 마크 (켜 둔 종류 전부)
← / →          5초 뒤로/앞으로          N / ⇧N     다음/이전 채택 프레임
J / L          10초 뒤로/앞으로         P / ⇧P     다음/이전 importance-point
, / .          프레임 단위 스텝          G / ⇧G     다음/이전 GT 플래그
⇧, / ⇧.        배속 내림/올림           D          이 탈락이 '무엇의 중복'인지 원본으로
0~9            0~90% 지점으로 점프      R          탈락 후보 숨김/표시
Home/End       처음/끝                  F          GT 플래그 추가/제거(토글)
M              음소거                   ?          이 도움말

↓/↑가 훑는 종류는 타임라인 범례의 체크박스로 고릅니다(STT 세그먼트는 581건이라
기본 제외). 타임라인 클릭도 가까운 마크에 달라붙고, 점프하면 화면 밖으로 나간
재생 커서를 뷰포트가 따라갑니다.

GT 플래그 = "이 장면은 반드시 뽑혔어야 한다"는 사람의 정답 표시. 로직 검출과
대조해 ⑥ 비교 리포트가 recall(놓친 것)·precision(군더더기)을 계산합니다.
같은 자리에서 F를 다시 누르거나 타임라인의 ▼를 ⇧클릭하면 취소됩니다.

플레이어 슬라이더·타임라인은 드래그하는 동안 화면이 실시간으로 따라옵니다.
타임라인 전용:  V 스크럽 · H 이동 · Z 확대 도구 / Space 홀드+드래그 = 임시 이동
                휠 = 확대·축소 (도구 막대의 배율 슬라이더·＋－·⤢ 전체 보기)"""

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
                if press and ev.key() == Qt.Key.Key_Escape:
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
        key = ev.key()
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        repeat = ev.isAutoRepeat()

        # Shift+구두점은 OS가 시프트 문자로 전달한다(, → <, . → >)
        if key in (Qt.Key.Key_Less, Qt.Key.Key_Greater):
            self._rate_step(-1 if key == Qt.Key.Key_Less else +1)
            return True

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
        if key == Qt.Key.Key_P:
            s.jump_mark(forward=not shift, kinds=["point"])
            return True
        if key == Qt.Key.Key_G:
            s.jump_mark(forward=not shift, kinds=["flag"])
            return True
        if key == Qt.Key.Key_D:
            # 탈락 후보가 '무엇의 중복'으로 판정됐는지 그 원본으로 건너뛴다 —
            # 중복 판정이 옳았는지 확인할 유일한 수단
            target = s.store.dup_target(e.position())
            if target is not None:
                e.seek(target)
                s.markJumped.emit("frame", f"중복 판정의 원본 프레임 t={target:.2f}")
            return True
        if key == Qt.Key.Key_R:
            if not repeat:
                s.toggle_rejected()
            return True
        if key == Qt.Key.Key_F:
            if not repeat:
                s.flags.toggle(e.position())  # 같은 자리에서 다시 누르면 취소
            return True
        if key == Qt.Key.Key_Question:
            if not repeat:
                s.show_shortcut_help()
            return True
        return False

    def _rate_step(self, direction: int) -> None:
        e = self.session.engine
        i = min(range(len(RATES)), key=lambda i: abs(RATES[i] - e.rate))
        e.set_rate(RATES[max(0, min(len(RATES) - 1, i + direction))])
