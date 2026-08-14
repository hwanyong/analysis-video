"""현지화 회귀 — 카탈로그 완전성과 언어 전환의 실제 반영.

이 테스트가 막는 것은 두 가지 조용한 고장이다:
① 카탈로그에 없는 키를 화면에 내보내기(=UI에 날 키가 뜬다),
② 창 하나가 retranslate를 빠뜨려 그 창만 옛 언어로 남기.
둘 다 실행해 보기 전에는 티가 안 나고, 여섯 창을 세 언어로 눈으로 돌려보는
검증은 반복되지 않는다.
"""
import re
from pathlib import Path

from analysis_video_gui import i18n, origin
from analysis_video_gui.i18n.catalog import CATALOG
from analysis_video_gui.session import (MARK_KINDS, REGISTRY, Session, mark_label,
                                        source_label)
from analysis_video_gui.windows import ChildWindow
from analysis_video_gui.windows.hub import HubWindow
from analysis_video_gui.windows.timeline import LANE_TICK_KEYS, TOOLS, _lane_ticks

SRC = Path(__file__).resolve().parents[1] / "src" / "analysis_video_gui"
ALL_WINDOWS = [wid for wid, _ in REGISTRY]

# tr("키"...) / tr('키'...) 의 리터럴 첫 인자. f-string으로 조립하는 호출
# (tr(f"tool.{key}.hint") 등)은 잡히지 않으므로 아래에서 따로 못박는다.
_TR_CALL = re.compile(r"""\btr\(\s*(['"])([A-Za-z0-9_.\-]+)\1""")


def test_every_key_has_every_language():
    holes = {key: [c for c in i18n.CODES if not entry.get(c)]
             for key, entry in CATALOG.items()}
    assert not {k: v for k, v in holes.items() if v}, "번역이 빠진 키가 있다"


def test_source_files_only_use_keys_that_exist():
    unknown = []
    for path in sorted(SRC.rglob("*.py")):
        if path.is_relative_to(SRC / "i18n"):
            continue
        for _quote, key in _TR_CALL.findall(path.read_text(encoding="utf-8")):
            if key not in CATALOG:
                unknown.append(f"{path.relative_to(SRC)}: {key}")
    assert not unknown, f"카탈로그에 없는 키를 쓰고 있다: {unknown}"


def test_dynamic_key_families_are_complete():
    """f-string으로 조립하는 키는 정규식이 못 잡는다 — 집합을 여기서 직접 센다."""
    for wid, key in REGISTRY:
        assert key in CATALOG, wid
    for kind, key, _default in MARK_KINDS:
        assert key in CATALOG, kind
    for _y, key in LANE_TICK_KEYS:
        assert key in CATALOG, key
    for tool, _accel in TOOLS:
        assert f"tool.{tool}" in CATALOG and f"tool.{tool}.hint" in CATALOG, tool
    for source in ("screen-start", "screen-end", "initial"):
        assert f"source.{source}" in CATALOG, source
    # 파일 관리자 문구는 플랫폼마다 하나만 쓰인다 — 지금 이 기계에서 쓰지 않는 것도
    # 다 있어야 하고, 실제로 고른 키가 그 집합 안에 있어야 한다.
    reveal_keys = ("hub.loc.reveal_macos", "hub.loc.reveal_windows",
                   "hub.loc.reveal_other")
    for key in reveal_keys:
        assert key in CATALOG, key
    assert origin.REVEAL_LABEL_KEY in reveal_keys


def test_unknown_source_falls_back_to_the_raw_value():
    """sources는 파이프라인이 늘릴 수 있는 열린 집합 — 새 값이 와도 화면이 비면 안 된다."""
    i18n.set_language("en")
    assert source_label("screen-end") == "screen end"
    assert source_label("brand-new-source") == "brand-new-source"


def test_tr_switches_formats_and_falls_back():
    i18n.set_language("ja")
    assert i18n.tr("hub.language") == "言語"
    assert "読み込み中 3/9" in i18n.tr("gallery.loading", done=3, total=9)
    assert i18n.tr("no.such.key") == "no.such.key"
    i18n.set_language("en")
    assert i18n.tr("hub.language") == "Language"


def test_mark_label_follows_language():
    i18n.set_language("en")
    assert mark_label("flag") == "GT flags"
    i18n.set_language("ja")
    assert mark_label("flag") == "GT フラグ"


def test_saved_choice_beats_the_system_language(analyzed, qapp, monkeypatch):
    """저장된 선택 → 시스템 UI 언어 → 기본값(영어)의 우선순위.

    시스템 언어는 개발기마다 다르므로 감지 함수를 갈아 끼워 순위만 못박는다.
    실제 감지가 무엇을 주든 우리가 아는 코드이거나 None이어야 한다는 것은 따로 본다.
    """
    assert i18n._system_language() in (*i18n.CODES, None)

    video, out_dir = analyzed
    session = Session(video, out_dir)
    before = session.settings.value(i18n.SETTINGS_KEY)   # 개발자 실제 설정은 되돌린다
    try:
        monkeypatch.setattr(i18n, "_system_language", lambda: "ja")
        session.settings.remove(i18n.SETTINGS_KEY)
        session.settings.sync()
        assert i18n.init() == "ja", "고른 적 없으면 시스템 UI 언어"

        session.set_language("ko")
        assert i18n.init() == "ko", "한 번 고르면 시스템보다 우선"

        session.settings.remove(i18n.SETTINGS_KEY)
        session.settings.sync()
        monkeypatch.setattr(i18n, "_system_language", lambda: None)
        assert i18n.init() == i18n.DEFAULT == "en", "모르는 시스템 언어면 영어"
    finally:
        if before is None:
            session.settings.remove(i18n.SETTINGS_KEY)
        else:
            session.settings.setValue(i18n.SETTINGS_KEY, before)
        session.settings.sync()
        session.engine.shutdown()


def test_language_switch_reaches_every_open_window(analyzed, qapp, pump):
    """언어 전환은 열린 창 전부에 닿아야 한다 — 창 제목과 내부 문자열 양쪽."""
    video, out_dir = analyzed
    i18n.set_language("ko")     # ko → en → ja 한 바퀴
    session = Session(video, out_dir)
    try:
        hub = HubWindow(session)
        for wid in ALL_WINDOWS:
            session.open_window(wid)
        pump(0.8)
        assert "허브" in hub.windowTitle()
        assert session.windows["gallery"]._status.text().startswith("프레임")

        session.set_language("en")
        pump(0.5)
        assert "hub" in hub.windowTitle()
        assert hub._save_btn.text() == "Save layout"
        assert hub._checks["compare"].text() == "⑥ Compare report"
        assert "Gallery" in session.windows["gallery"].windowTitle()
        assert "frames" in session.windows["gallery"]._status.text()
        assert "Frames kept" in session.windows["timeline"]._legend_head.text()
        assert "Scrub" in session.windows["timeline"]._tool_buttons["scrub"].text()
        assert session.windows["compare"]._add_btn.text().startswith("Add/remove")
        assert _lane_ticks()[-1][1] == "cut area"

        session.set_language("ja")
        pump(0.5)
        assert "ハブ" in hub.windowTitle()
        assert hub._save_btn.text() == "レイアウト保存"
        assert "ギャラリー" in session.windows["gallery"].windowTitle()
        assert "採用フレーム" in session.windows["timeline"]._legend_head.text()
        assert session.windows["compare"]._add_btn.text().startswith("現在位置")
    finally:
        session.engine.shutdown()


def test_every_window_declares_retranslate(analyzed, qapp, pump):
    """베이스가 NotImplementedError를 던지므로, 선언을 빠뜨린 창은 전환 순간 터진다.
    창을 하나 더 추가할 사람에게 이 테스트가 계약을 알려 주는 자리다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        for wid in ALL_WINDOWS:
            session.open_window(wid)
        pump(0.6)
        for wid, w in session.windows.items():
            assert type(w).retranslate is not ChildWindow.retranslate, \
                f"{wid} 창이 retranslate()를 선언하지 않았다"
            w.retranslate()   # 실제로 불러 본다 — 선언만 있고 터지면 소용없다
    finally:
        session.engine.shutdown()


def test_language_switch_keeps_the_timeline_zoom(analyzed, qapp, pump):
    """언어를 바꿨다고 확대해 둔 자리를 잃으면 검토가 끊긴다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    try:
        tl = session.open_window("timeline")
        pump(0.6)
        tl.set_zoom(4.0, center=session.store.duration / 2)
        pump(0.3)
        (x0, x1), _ = tl._pw.getViewBox().viewRange()

        session.set_language("ja")
        pump(0.5)
        (nx0, nx1), _ = tl._pw.getViewBox().viewRange()
        assert abs(nx0 - x0) < 0.05 and abs(nx1 - x1) < 0.05, "보던 구간이 유지돼야 한다"
        assert "カット面積" in tl._legend_tail.text() or tl.session.store.series is None
    finally:
        session.engine.shutdown()


def test_language_is_remembered_for_the_next_run(analyzed, qapp):
    """저장이 빠지면 매번 다시 골라야 한다 — 저장과 재기동 읽기를 함께 못박는다."""
    video, out_dir = analyzed
    session = Session(video, out_dir)
    before = session.settings.value(i18n.SETTINGS_KEY)   # 개발자 실제 설정은 되돌린다
    try:
        session.set_language("ja")
        assert session.settings.value(i18n.SETTINGS_KEY) == "ja"
        i18n.set_language("ko")                          # 재시작 흉내
        assert i18n.init() == "ja"
    finally:
        if before is None:
            session.settings.remove(i18n.SETTINGS_KEY)
        else:
            session.settings.setValue(i18n.SETTINGS_KEY, before)
        session.settings.sync()
        session.engine.shutdown()
