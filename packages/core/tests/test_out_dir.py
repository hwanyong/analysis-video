"""분석 디렉터리의 위치는 **사용자가 준 경로**를 따라간다.

이어하기(state.json)는 "같은 명령을 다시 부르면 같은 디렉터리를 연다"에 전부
걸려 있다. 그래서 경로 정규화가 디렉터리를 한 칸이라도 옮기면 끝나 있던 분석이
어디에서도 보이지 않고, 전사·검출이 처음부터 다시 돈다 — 실패가 아니라 조용한
재계산이라 사용자가 알아채기도 어렵다.

여기서 지키는 두 성질:

- cwd에 기대지 않는다. 상대경로를 그대로 두면 1회차 실행의 작업 폴더가 숨은
  기준점이 되어 다른 폴더에서 이어 돌릴 수 없다.
- 심볼릭 링크는 따라가지 않는다. `resolve()`는 링크를 실체로 바꾸므로 원본을
  링크로 가리키는 사용자의 분석이 링크 옆이 아니라 실체 옆으로 옮겨간다.

둘이 부딪히지 않는 이유: 원본 동일성 판정은 manifest.check_source의 지문이
따로 맡고 그쪽은 실체를 본다. 디렉터리 **이름**만 사용자가 준 경로를 따르면 된다.
"""
import os
from pathlib import Path

from analysis_video import cli


def test_relative_paths_are_pinned_to_absolute(tmp_path, monkeypatch):
    (tmp_path / "lecture.mkv").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    out = cli.resolve_out(cli.check_video(Path("lecture.mkv")), None)

    assert out.is_absolute(), "cwd가 숨은 기준점이 되면 이어하기가 깨진다"
    assert out.name == "lecture.mkv.analysis"


def test_symlinked_source_keeps_its_analysis_beside_the_link(tmp_path):
    """링크로 가리킨 원본의 분석은 링크 옆에 남는다 — 실체 옆으로 옮기면 옛
    분석 디렉터리가 통째로 미아가 되고 파이프라인이 처음부터 다시 돈다."""
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir(), link.mkdir()
    (real / "L01.mkv").write_bytes(b"x")
    os.symlink(real / "L01.mkv", link / "lecture.mkv")

    video = cli.check_video(link / "lecture.mkv")
    out = cli.resolve_out(video, None)

    assert out == link / "lecture.mkv.analysis"
    assert not str(out).startswith(str(real)), "링크를 실체로 바꾸면 안 된다"


def test_explicit_out_follows_the_same_rule(tmp_path):
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir(), link.mkdir()
    (real / "here").mkdir()
    os.symlink(real / "here", link / "there")

    out = cli.resolve_out(tmp_path / "lecture.mkv", link / "there")

    assert out == link / "there"


def test_hint_omits_out_when_it_is_the_default(tmp_path):
    """--out 안내가 붙고 안 붙고는 resolve_out과 같은 정규화를 써야 맞는다 —
    한쪽만 링크를 따라가면 기본 위치인데도 --out이 붙은 명령을 안내한다."""
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir(), link.mkdir()
    (real / "L01.mkv").write_bytes(b"x")
    os.symlink(real / "L01.mkv", link / "lecture.mkv")
    video = cli.check_video(link / "lecture.mkv")

    assert "--out" not in cli.stage_command("split", video, cli.resolve_out(video, None))
    assert "--out" in cli.stage_command("split", video, tmp_path / "elsewhere")
