"""출처 줄 회귀 — 허브가 "이 분석이 어디서 왔나"를 보여주고 그 자리로 데려간다.

오프스크린에서 못박을 수 있는 것만 본다: 어느 문자열이 어느 줄에 오르는가, 버튼이
켜지는가, 눌렀을 때 어떤 명령이 어떤 인자로 나가는가, 클립보드에 무엇이 남는가.

reveal은 **실행하지 않는다** — 테스트가 Finder 창을 열어 버리는 것은 부작용이고,
여기서 확인할 것은 인자 조립(셸을 안 거치는가, 경로가 한 인자인가)이다. 실제로
파일이 선택된 채 창이 뜨는지는 사람이 눈으로 볼 몫.
"""
import json
import sys
import types
from pathlib import Path

import pytest
from analysis_video import STATE_SCHEMA
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from analysis_video_gui import origin
from analysis_video_gui.i18n import tr
from analysis_video_gui.session import Session
from analysis_video_gui.windows.hub import (ROW_ORIGIN, ROW_SUBTITLE, ROW_VIDEO,
                                           HubWindow)

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _write_state(out_dir: Path, video: Path, subtitle: Path | None) -> None:
    """코어가 남기는 state.json — 출처 줄이 읽는 유일한 원천.

    영상이 없는 경로여도 쓴다: "분석 뒤에 원본을 옮겼다"가 실제로 흔한 상태이고,
    그때 화면이 어떻게 되는지가 이 파일의 검증 대상 중 하나다.
    """
    source = {"path": str(video),
              "size": video.stat().st_size if video.exists() else 0}
    if subtitle is not None:
        source["subtitle"] = {"path": str(subtitle), "size": subtitle.stat().st_size}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "state.json").write_text(
        json.dumps({"schema": STATE_SCHEMA, "stages": {}, "source": source}),
        encoding="utf-8")


def _resolver(monkeypatch, result) -> list[Path]:
    """코어 출처 해석기 대역 — 계약만 흉내 내고, 받은 경로를 적어 돌려준다.

    계약: `analysis_video.origin.resolve(Path) -> dict | None`, URL은 "url" 키.
    info.json·컨테이너 메타데이터를 실제로 읽어내는지는 코어 테스트의 몫이고,
    여기서 볼 것은 그 반환이 화면에 어떻게 오르는가다.
    `sys.modules`에 꽂는 이유: `from analysis_video.origin import resolve`가 캐시를
    먼저 보므로, 코어 구현의 유무·내용과 무관하게 이 계약만 검증된다.
    """
    asked: list[Path] = []
    module = types.ModuleType("analysis_video.origin")

    def resolve(path):
        asked.append(Path(path))
        return result

    module.resolve = resolve
    monkeypatch.setitem(sys.modules, "analysis_video.origin", module)
    return asked


def _shown(row) -> bool:
    """줄이 화면에 올라 있는가. isVisible()은 부모 창을 띄우지 않으면 늘 False다."""
    return not row._value.isHidden()


@pytest.fixture
def hub_of(video_av, tmp_path, qapp, pump):
    """(원본 경로, 자막) → 띄운 허브.

    URL 해석은 허브 생성 시 한 번뿐이므로 해석기 대역을 먼저 꽂아야 한다.
    창을 실제로 띄우는 이유: 레이아웃이 돌아야 레이블에 폭이 생기고, 그 폭이
    있어야 축약과 클릭 좌표가 의미를 갖는다.
    """
    sessions = []

    def build(source: Path | None = None, subtitle: Path | None = None) -> HubWindow:
        out_dir = tmp_path / f"out{len(sessions)}.analysis"
        _write_state(out_dir, source or video_av, subtitle)
        session = Session(video_av, out_dir)
        sessions.append(session)
        hub = HubWindow(session)
        hub.show()
        pump(0.2)
        return hub

    yield build
    for s in sessions:
        s.engine.shutdown()


def test_without_a_url_the_origin_row_is_the_local_file(monkeypatch, hub_of, video_av):
    _resolver(monkeypatch, None)
    hub = hub_of()

    row = hub._rows[ROW_ORIGIN]
    assert row._value.full_text() == str(video_av)
    assert row._button.isEnabled()
    assert row._button.text() == tr(origin.REVEAL_LABEL_KEY)
    assert str(video_av) in row._value.toolTip()
    assert tr("hub.loc.copy_hint") in row._value.toolTip()
    # 왜 URL이 아니라 경로인지를 그 자리에서 답해 준다
    assert tr("hub.loc.no_url") in row._value.toolTip()
    assert not _shown(hub._rows[ROW_VIDEO]), "같은 파일을 두 줄로 보여줄 이유가 없다"


def test_a_resolved_url_takes_the_origin_row_and_the_file_gets_its_own(
        monkeypatch, hub_of, video_av):
    """웹에서 받아온 영상이라도 로컬 파일에 닿는 길이 허브에 남아야 한다."""
    _resolver(monkeypatch, {"url": URL})
    hub = hub_of()

    assert hub._rows[ROW_ORIGIN]._value.full_text() == URL
    assert hub._rows[ROW_ORIGIN]._button.text() == tr("hub.loc.open_url")
    assert hub._rows[ROW_VIDEO]._value.full_text() == str(video_av)
    assert hub._rows[ROW_VIDEO]._button.text() == tr(origin.REVEAL_LABEL_KEY)


def test_the_url_button_opens_a_browser(monkeypatch, hub_of):
    _resolver(monkeypatch, {"url": URL})
    hub = hub_of()
    opened = []
    monkeypatch.setattr(origin.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()))

    hub._rows[ROW_ORIGIN]._button.click()

    assert opened == [URL]


def test_the_file_button_reveals_instead_of_opening(monkeypatch, hub_of, video_av):
    """openUrl(file://…)로 새면 영상이 **열려** 플레이어가 뜬다 — 요구는 그게 아니다."""
    _resolver(monkeypatch, None)
    hub = hub_of()
    calls, opened = [], []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(origin.subprocess, "run",
                        lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(origin.QDesktopServices, "openUrl", opened.append)

    hub._rows[ROW_ORIGIN]._button.click()

    assert calls == [(["open", "-R", str(video_av)], {"check": False})]
    assert not opened, "파일을 여는 경로로 새면 플레이어가 뜬다"


@pytest.mark.parametrize("platform,argv", [
    ("darwin", ["open", "-R", "{p}"]),
    # 쉼표 뒤에 공백을 두거나 인자를 쪼개면 explorer가 경로를 인식하지 못한다
    ("win32", ["explorer", "/select,{p}"]),
])
def test_reveal_hands_the_path_over_as_one_argument(monkeypatch, tmp_path, platform, argv):
    """경로에 공백·따옴표가 있어도 셸 문법으로 해석되면 안 된다 — 리스트로 넘긴다."""
    path = tmp_path / "a b'c $d" / "lec ture.mkv"
    path.parent.mkdir()
    path.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(origin.subprocess, "run",
                        lambda a, **kw: calls.append((a, kw)))

    origin.reveal(path)

    (sent, kwargs), = calls
    assert sent == [a.format(p=path) for a in argv]
    assert kwargs.get("shell") is not True


def test_linux_has_no_reveal_so_it_opens_the_parent_folder(monkeypatch, tmp_path):
    """파일을 선택해 폴더를 여는 표준이 없다 — 부모 폴더까지가 최선이다."""
    path = tmp_path / "lecture.mkv"
    path.write_bytes(b"x")
    calls, opened = [], []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(origin.subprocess, "run",
                        lambda a, **kw: calls.append(a))
    monkeypatch.setattr(origin.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toLocalFile()))

    origin.reveal(path)

    assert opened == [str(tmp_path)]
    assert not calls, "리눅스에는 부를 reveal 명령이 없다"


def test_clicking_the_path_copies_it_and_the_status_line_says_so(
        monkeypatch, hub_of, video_av, pump):
    _resolver(monkeypatch, None)
    hub = hub_of()
    QGuiApplication.clipboard().setText("")
    copied = tr("hub.loc.copied", name=tr("hub.loc.origin"))

    QTest.mouseClick(hub._rows[ROW_ORIGIN]._value, Qt.MouseButton.LeftButton)

    assert QGuiApplication.clipboard().text() == str(video_av)
    assert hub._status.text() == copied, "복사됐다는 피드백이 없으면 눌렀는지 알 수 없다"
    # 요약을 영구히 덮으면 안 된다 — 잠깐 빌렸다 되돌린다
    pump(2.4)
    assert hub._status.text() != copied


def test_a_core_without_the_resolver_says_so_rather_than_pretending(monkeypatch, hub_of):
    """'URL이 없다'와 '해석기를 못 불렀다'는 다른 사실이다.

    같은 화면을 내면 사용자는 내려받은 파일 쪽을 의심하며 엉뚱한 데를 파게 된다.
    (`sys.modules`에 None을 넣으면 그 이름의 import가 ImportError로 끊긴다 —
    해석기 없는 옛 코어와 조합된 상태와 같다.)
    """
    monkeypatch.setitem(sys.modules, "analysis_video.origin", None)
    hub = hub_of()

    row = hub._rows[ROW_ORIGIN]
    assert row._value.full_text() == tr("hub.loc.no_resolver")
    assert not row._button.isEnabled()
    assert row._button.toolTip() == tr("hub.loc.no_resolver")
    assert _shown(hub._rows[ROW_VIDEO]), "그래도 영상 파일에는 닿아야 한다"

    QGuiApplication.clipboard().setText("keep")
    QTest.mouseClick(row._value, Qt.MouseButton.LeftButton)
    assert QGuiApplication.clipboard().text() == "keep", \
        "붙여 넣을 곳이 없는 설명 문장이라 복사도 걸지 않는다"


def test_a_file_that_is_gone_disables_the_button_and_says_why(
        monkeypatch, hub_of, tmp_path):
    """분석 뒤 원본을 옮기면 경로는 남고 파일은 없다 — 갈 곳이 없으니 잠근다."""
    asked = _resolver(monkeypatch, {"url": URL})
    gone = tmp_path / "moved-away" / "lecture.mkv"
    hub = hub_of(source=gone)

    row = hub._rows[ROW_ORIGIN]
    assert row._value.full_text() == str(gone), "어디에 있었는지가 되찾을 단서다"
    assert not row._button.isEnabled()
    assert row._button.toolTip() == tr("hub.loc.gone")
    # URL은 파일 옆에서 읽는다 — 없는 파일을 해석기에 넘기면 그쪽 예외로 허브가 안 뜬다
    assert asked == [], "읽을 것이 없는 파일을 해석기에 물어보지 않는다"


def test_the_subtitle_row_shows_which_file_was_transcribed(monkeypatch, hub_of, tmp_path):
    """어느 자막으로 전사했는지는 결과를 읽는 데 필요한 사실이다."""
    _resolver(monkeypatch, None)
    srt = tmp_path / "lecture.ko.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n안녕\n", encoding="utf-8")
    hub = hub_of(subtitle=srt)

    row = hub._rows[ROW_SUBTITLE]
    assert _shown(row)
    assert row._value.full_text() == str(srt)
    assert row._button.isEnabled()
    assert row._button.text() == tr(origin.REVEAL_LABEL_KEY)


def test_without_a_subtitle_there_is_no_empty_row(monkeypatch, hub_of):
    _resolver(monkeypatch, None)
    hub = hub_of()

    assert not _shown(hub._rows[ROW_SUBTITLE])


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)",
                                 "ftp://host/x.mkv", ""])
def test_only_web_urls_are_offered(monkeypatch, tmp_path, url):
    """이 값의 유일한 쓰임은 openUrl이고, 그것은 스킴에 따라 임의의 핸들러를 실행한다."""
    _resolver(monkeypatch, {"url": url})

    assert origin.source_url(tmp_path / "lecture.mkv") is None


def test_a_web_url_passes_through(monkeypatch, tmp_path):
    _resolver(monkeypatch, {"url": URL})

    assert origin.source_url(tmp_path / "lecture.mkv") == URL


def test_a_long_path_is_shortened_in_the_middle_but_kept_whole_in_the_tooltip(
        monkeypatch, hub_of):
    """경로는 창을 밀어내지 않아야 하고, 전체 문자열은 어디서든 읽을 수 있어야 한다."""
    _resolver(monkeypatch, None)
    long_path = Path("/Users/uhd/" + "some-long-directory/" * 12 + "lecture.mkv")
    hub = hub_of(source=long_path)

    label = hub._rows[ROW_ORIGIN]._value
    assert label.full_text() == str(long_path)
    assert label.text() != label.full_text()
    assert "…" in label.text()
    assert label.text().endswith(".mkv"), "가운데를 줄이는 이유가 파일명을 남기는 것이다"
    assert str(long_path) in label.toolTip()


def test_a_long_path_does_not_widen_the_hub(monkeypatch, hub_of):
    """QLabel의 기본 sizeHint는 문자열 전체 폭이다 — 그대로 두면 경로 길이가 창의
    최소 폭이 되어, 한 번 열면 사용자가 창을 다시 줄일 수 없다."""
    _resolver(monkeypatch, None)
    short = hub_of(source=Path("/tmp/a.mkv"))
    long_ = hub_of(source=Path("/tmp/" + "long-directory/" * 30 + "a.mkv"))

    assert long_.minimumSizeHint().width() == short.minimumSizeHint().width()
