"""한글 입력 상태에서도 단축키가 살아 있는지 — 물리 키 해석 검증.

`QKeyEvent.key()`는 눌린 자리가 아니라 만들어진 **문자**다. 한글 입력원에서
K를 누르면 key()가 자모(U+314F)나 Key_unknown으로 오므로, 문자 비교로 짜인
단축키는 전부 빗나간다. 여기서는 그 상황을 이벤트로 합성해 못박는다.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from analysis_video_gui.keys import NATIVE_FIELD, NATIVE_KEYCODES, physical_key

HANGUL = 0x314F   # 'ㅏ' — 한글 입력에서 K 자리가 만들어 내는 문자
UNKNOWN = int(Qt.Key.Key_unknown)


def _native_of(qt_key) -> int:
    """그 Qt.Key에 해당하는 이 플랫폼의 네이티브 키코드."""
    return next(code for code, k in NATIVE_KEYCODES.items() if k == qt_key)


def _ev(key: int, at, mods=Qt.KeyboardModifier.NoModifier, text="") -> QKeyEvent:
    """`at` 자리를 눌렀는데 OS가 문자 `key`로 전달한 이벤트."""
    code = _native_of(at)
    scan = code if NATIVE_FIELD == "nativeScanCode" else 0
    virt = code if NATIVE_FIELD == "nativeVirtualKey" else 0
    return QKeyEvent(QKeyEvent.Type.KeyPress, key, mods, scan, virt, 0, text, False, 1)


# 전역·타임라인 단축키가 실제로 쓰는 자리 전부
SHORTCUT_KEYS = [
    Qt.Key.Key_Space, Qt.Key.Key_K, Qt.Key.Key_J, Qt.Key.Key_L, Qt.Key.Key_M,
    Qt.Key.Key_N, Qt.Key.Key_G, Qt.Key.Key_R, Qt.Key.Key_F,
    Qt.Key.Key_V, Qt.Key.Key_H, Qt.Key.Key_Z,
    Qt.Key.Key_Comma, Qt.Key.Key_Period, Qt.Key.Key_Slash,
    Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Escape,
    Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
    *[getattr(Qt.Key, f"Key_{d}") for d in range(10)],
]


@pytest.mark.parametrize("key", SHORTCUT_KEYS, ids=lambda k: k.name)
@pytest.mark.parametrize("delivered", [HANGUL, UNKNOWN], ids=["jamo", "unknown"])
def test_hangul_input_falls_back_to_the_pressed_position(key, delivered, qapp):
    """문자가 한글이거나 아예 없으면 키코드로 되돌린다 — 자리가 곧 단축키."""
    assert physical_key(_ev(delivered, key, text="ㅏ")) == key


def test_latin_layout_keeps_the_printed_letter(qapp):
    """AZERTY·Dvorak에서는 **찍힌 글자**가 우선이다 — 자리로 덮어쓰면 안 된다.

    프랑스어 자판의 A는 QWERTY의 Q 자리에 있다. 사용자는 A를 눌렀다고 여기므로
    키코드(=Q 자리)로 갈아치우면 눌러 본 적 없는 단축키가 튀어나온다.
    """
    assert physical_key(_ev(Qt.Key.Key_A, Qt.Key.Key_Q, text="a")) == Qt.Key.Key_A


@pytest.mark.parametrize("delivered,folded", [
    (Qt.Key.Key_Less, Qt.Key.Key_Comma),
    (Qt.Key.Key_Greater, Qt.Key.Key_Period),
    (Qt.Key.Key_Question, Qt.Key.Key_Slash),
])
def test_shift_variants_fold_to_the_unshifted_key(delivered, folded, qapp):
    """⇧,는 <로 온다 — Shift 여부는 modifiers()로 보므로 대표 키로 접는다."""
    ev = _ev(delivered, folded, mods=Qt.KeyboardModifier.ShiftModifier)
    assert physical_key(ev) == folded


def test_unmapped_position_passes_the_key_through(qapp):
    """표에 없는 자리(펑션키 등)는 원래 값 그대로 — 단축키에 없으니 무시된다."""
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, HANGUL, Qt.KeyboardModifier.NoModifier,
                   0xFFFF, 0xFFFF, 0, "ㅏ", False, 1)
    assert physical_key(ev) == HANGUL


def test_synthetic_events_without_native_codes_still_work(qapp):
    """네이티브 코드가 없는 합성 이벤트(QTest·자동화)도 문자만으로 통해야 한다."""
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space,
                   Qt.KeyboardModifier.NoModifier, "")
    assert physical_key(ev) == Qt.Key.Key_Space


def test_keycode_table_is_a_bijection():
    """자리 하나에 코드 하나 — 겹치면 두 단축키가 한 키에 물린다."""
    from analysis_video_gui.keys import _KEY_TABLE

    for column, what in ((1, "macOS kVK"), (2, "Windows VK"), (3, "X11 keycode")):
        codes = [row[column] for row in _KEY_TABLE]
        assert len(set(codes)) == len(codes), f"{what} 표에 중복 코드가 있다"
    keys = [row[0] for row in _KEY_TABLE]
    assert len(set(keys)) == len(keys), "같은 Qt.Key가 두 줄에 있다"
    assert set(SHORTCUT_KEYS) <= set(keys), "단축키가 쓰는 자리가 표에 빠져 있다"
