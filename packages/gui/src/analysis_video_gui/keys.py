"""물리 키 해석 — 입력 소스(한글 IME 등)와 무관하게 같은 자리가 같은 키가 되도록.

`QKeyEvent.key()`는 "누른 키"가 아니라 **그 키가 만들어 낸 문자**다. 한글 입력
상태에서 K를 누르면 `key()`가 `Key_K`가 아니라 자모 'ㅏ'(U+314F)로 온다 —
문자로 비교하는 단축키는 영문 입력일 때만 동작한다.

macOS의 한글은 "라틴 배열 + IME"가 아니라 **비-ASCII 배열 그 자체**다.
`TISCopyInputMethodKeyboardLayoutOverride()`가 `com.apple.keylayout.2SetHangul`
(asciiCapable=0)을 돌려주고, 그 uchr 데이터가 가상 키 40(K)을 U+314F로 바로
매핑한다 — 조합이 시작되기도 전에 레이아웃 단계에서 이미 한글이다. 그래서
`QShortcut`으로 바꿔도 해결되지 않는다: Qt의 라틴 대체 경로는
`QAppleKeyMapper::possibleKeyCombinations()`에서 ⌘(Command)이 눌린 경우로
한정돼 있어(qapplekeymapper.mm), 수식 없는 단일 문자 단축키에는 아예 안 탄다.

그래서 두 단계로 푼다.

  ① `key()`가 쓸 수 있는 ASCII 키(0x20~0x7E)이거나 이름 있는 키(방향키 등)면
     그대로 쓴다. AZERTY·Dvorak 사용자는 **자판에 찍힌 글자**대로 눌러야 하므로,
     라틴 문자를 만들어 내는 레이아웃에서는 문자를 우선한다.
  ② 아니면 네이티브 키코드로 되돌린다. 키코드는 자판의 **물리 위치**라 입력
     소스·레이아웃과 무관하다 — 한글 상태에서도 QWERTY 자리로 잡힌다.

키코드의 출처는 플랫폼마다 다르다.

  macOS   `nativeVirtualKey()` = Carbon 가상 키코드(kVK_*). ANSI 자리 기준이라
          입력 소스가 바뀌어도 그대로다. 값의 출처는 HIToolbox/Events.h.
          (`nativeScanCode()`는 macOS에서 **항상 0**이다 — 쓸 수 없다.)
  Windows `nativeVirtualKey()` = VK_*. 엄밀히는 이것도 레이아웃 의존이다 —
          독일어 QWERTZ에서 Z 자리는 VK_Y로 온다. 그래도 문제가 없는 이유는
          ①이 먼저 걸리기 때문이다: VK가 자리와 어긋나는 배열(QWERTZ·AZERTY)은
          전부 ASCII를 만들어 내므로 ②까지 내려오지 않는다.
  X11/Wayland `nativeScanCode()` = 하드웨어 키코드 = evdev 코드 + 8.
          `nativeVirtualKey()`는 X11에서 KeySym이라 레이아웃은 물론 Shift에도
          따라 변한다 — 쓰면 안 된다.

표는 ANSI 메인 블록 전체를 담는다. 지금 단축키가 쓰는 키만 넣으면 다음에 키를
하나 늘릴 때 조용히 한글에서만 안 먹는 구멍이 생긴다.
"""
import sys

from PySide6.QtCore import Qt

# Shift 변형은 대표 키로 접는다 — 조합 여부는 modifiers()로 따로 보므로,
# 단축키 표는 "찍히지 않은 쪽" 하나만 알면 된다. (, → <, . → >, / → ?)
_SHIFTED = {
    Qt.Key.Key_Less: Qt.Key.Key_Comma,
    Qt.Key.Key_Greater: Qt.Key.Key_Period,
    Qt.Key.Key_Question: Qt.Key.Key_Slash,
}

# (Qt.Key, macOS kVK, Windows VK, X11 keycode) — 한 줄이 한 물리 키다.
# 플랫폼마다 표를 따로 두면 서로 어긋나므로 열로 붙여 한 곳에서 관리한다.
_KEY_TABLE = (
    (Qt.Key.Key_A, 0x00, 0x41, 38),
    (Qt.Key.Key_B, 0x0B, 0x42, 56),
    (Qt.Key.Key_C, 0x08, 0x43, 54),
    (Qt.Key.Key_D, 0x02, 0x44, 40),
    (Qt.Key.Key_E, 0x0E, 0x45, 26),
    (Qt.Key.Key_F, 0x03, 0x46, 41),
    (Qt.Key.Key_G, 0x05, 0x47, 42),
    (Qt.Key.Key_H, 0x04, 0x48, 43),
    (Qt.Key.Key_I, 0x22, 0x49, 31),
    (Qt.Key.Key_J, 0x26, 0x4A, 44),
    (Qt.Key.Key_K, 0x28, 0x4B, 45),
    (Qt.Key.Key_L, 0x25, 0x4C, 46),
    (Qt.Key.Key_M, 0x2E, 0x4D, 58),
    (Qt.Key.Key_N, 0x2D, 0x4E, 57),
    (Qt.Key.Key_O, 0x1F, 0x4F, 32),
    (Qt.Key.Key_P, 0x23, 0x50, 33),
    (Qt.Key.Key_Q, 0x0C, 0x51, 24),
    (Qt.Key.Key_R, 0x0F, 0x52, 27),
    (Qt.Key.Key_S, 0x01, 0x53, 39),
    (Qt.Key.Key_T, 0x11, 0x54, 28),
    (Qt.Key.Key_U, 0x20, 0x55, 30),
    (Qt.Key.Key_V, 0x09, 0x56, 55),
    (Qt.Key.Key_W, 0x0D, 0x57, 25),
    (Qt.Key.Key_X, 0x07, 0x58, 53),
    (Qt.Key.Key_Y, 0x10, 0x59, 29),
    (Qt.Key.Key_Z, 0x06, 0x5A, 52),

    (Qt.Key.Key_0, 0x1D, 0x30, 19),
    (Qt.Key.Key_1, 0x12, 0x31, 10),
    (Qt.Key.Key_2, 0x13, 0x32, 11),
    (Qt.Key.Key_3, 0x14, 0x33, 12),
    (Qt.Key.Key_4, 0x15, 0x34, 13),
    (Qt.Key.Key_5, 0x17, 0x35, 14),
    (Qt.Key.Key_6, 0x16, 0x36, 15),
    (Qt.Key.Key_7, 0x1A, 0x37, 16),
    (Qt.Key.Key_8, 0x1C, 0x38, 17),
    (Qt.Key.Key_9, 0x19, 0x39, 18),

    (Qt.Key.Key_Minus, 0x1B, 0xBD, 20),         # VK_OEM_MINUS
    (Qt.Key.Key_Equal, 0x18, 0xBB, 21),         # VK_OEM_PLUS
    (Qt.Key.Key_BracketLeft, 0x21, 0xDB, 34),   # VK_OEM_4
    (Qt.Key.Key_BracketRight, 0x1E, 0xDD, 35),  # VK_OEM_6
    (Qt.Key.Key_Backslash, 0x2A, 0xDC, 51),     # VK_OEM_5
    (Qt.Key.Key_Semicolon, 0x29, 0xBA, 47),     # VK_OEM_1
    (Qt.Key.Key_Apostrophe, 0x27, 0xDE, 48),    # VK_OEM_7
    (Qt.Key.Key_QuoteLeft, 0x32, 0xC0, 49),     # VK_OEM_3
    (Qt.Key.Key_Comma, 0x2B, 0xBC, 59),         # VK_OEM_COMMA
    (Qt.Key.Key_Period, 0x2F, 0xBE, 60),        # VK_OEM_PERIOD
    (Qt.Key.Key_Slash, 0x2C, 0xBF, 61),         # VK_OEM_2

    (Qt.Key.Key_Escape, 0x35, 0x1B, 9),
    (Qt.Key.Key_Tab, 0x30, 0x09, 23),
    (Qt.Key.Key_Backspace, 0x33, 0x08, 22),
    (Qt.Key.Key_Return, 0x24, 0x0D, 36),
    (Qt.Key.Key_Space, 0x31, 0x20, 65),
    (Qt.Key.Key_Home, 0x73, 0x24, 110),
    (Qt.Key.Key_End, 0x77, 0x23, 115),
    (Qt.Key.Key_PageUp, 0x74, 0x21, 112),
    (Qt.Key.Key_PageDown, 0x79, 0x22, 117),
    (Qt.Key.Key_Left, 0x7B, 0x25, 113),
    (Qt.Key.Key_Up, 0x7E, 0x26, 111),
    (Qt.Key.Key_Right, 0x7C, 0x27, 114),
    (Qt.Key.Key_Down, 0x7D, 0x28, 116),
)

# 이 플랫폼에서 읽을 QKeyEvent 접근자와, 그 값 → Qt.Key 표.
if sys.platform == "darwin":
    _COLUMN, NATIVE_FIELD = 1, "nativeVirtualKey"
elif sys.platform == "win32":
    _COLUMN, NATIVE_FIELD = 2, "nativeVirtualKey"
else:
    _COLUMN, NATIVE_FIELD = 3, "nativeScanCode"

#: 이 플랫폼의 네이티브 키코드 → Qt.Key. `physical_key`의 되돌림 표이자,
#: 테스트가 "이 자리를 누른 이벤트"를 합성할 때 쓰는 유일한 출처다.
NATIVE_KEYCODES = {row[_COLUMN]: row[0] for row in _KEY_TABLE}

# 이름 있는 키(방향키·Home 등)는 문자를 만들지 않으므로 레이아웃과 무관하다.
_NAMED = frozenset(row[0] for row in _KEY_TABLE if row[0] > Qt.Key.Key_AsciiTilde)


def physical_key(ev) -> int:
    """키 이벤트에서 "어느 자리를 눌렀나"를 레이아웃·입력기와 무관하게 뽑는다.

    돌려주는 값은 항상 Shift를 걷어낸 대표 Qt.Key다 — Shift 여부는 호출부가
    `ev.modifiers()`로 따로 본다. 무엇으로도 해석되지 않으면 `ev.key()`를
    그대로 돌려준다(단축키 표에 없으면 어차피 아무 일도 일어나지 않는다).
    """
    key = _SHIFTED.get(ev.key(), ev.key())
    if Qt.Key.Key_Space <= key <= Qt.Key.Key_AsciiTilde or key in _NAMED:
        return key
    return NATIVE_KEYCODES.get(getattr(ev, NATIVE_FIELD)(), key)
