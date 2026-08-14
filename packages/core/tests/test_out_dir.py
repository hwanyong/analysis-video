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
import json
import os
from pathlib import Path

import pytest
from analysis_video import STATE_SCHEMA, cli, manifest
from analysis_video.errors import EXIT_INPUT, CliError


def test_relative_paths_are_pinned_to_absolute(tmp_path, monkeypatch):
    (tmp_path / "lecture.mkv").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)

    out = manifest.resolve_out(manifest.check_video(Path("lecture.mkv")), None)

    assert out.is_absolute(), "cwd가 숨은 기준점이 되면 이어하기가 깨진다"
    assert out.name == "lecture.mkv.analysis"


def test_symlinked_source_keeps_its_analysis_beside_the_link(tmp_path):
    """링크로 가리킨 원본의 분석은 링크 옆에 남는다 — 실체 옆으로 옮기면 옛
    분석 디렉터리가 통째로 미아가 되고 파이프라인이 처음부터 다시 돈다."""
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir(), link.mkdir()
    (real / "L01.mkv").write_bytes(b"x")
    os.symlink(real / "L01.mkv", link / "lecture.mkv")

    video = manifest.check_video(link / "lecture.mkv")
    out = manifest.resolve_out(video, None)

    assert out == link / "lecture.mkv.analysis"
    assert not str(out).startswith(str(real)), "링크를 실체로 바꾸면 안 된다"


def test_explicit_out_follows_the_same_rule(tmp_path):
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir(), link.mkdir()
    (real / "here").mkdir()
    os.symlink(real / "here", link / "there")

    out = manifest.resolve_out(tmp_path / "lecture.mkv", link / "there")

    assert out == link / "there"


def test_hint_omits_out_when_it_is_the_default(tmp_path):
    """--out 안내가 붙고 안 붙고는 resolve_out과 같은 정규화를 써야 맞는다 —
    한쪽만 링크를 따라가면 기본 위치인데도 --out이 붙은 명령을 안내한다."""
    real, link = tmp_path / "real", tmp_path / "link"
    real.mkdir(), link.mkdir()
    (real / "L01.mkv").write_bytes(b"x")
    os.symlink(real / "L01.mkv", link / "lecture.mkv")
    video = manifest.check_video(link / "lecture.mkv")

    assert "--out" not in cli.stage_command("split", video, manifest.resolve_out(video, None))
    assert "--out" in cli.stage_command("split", video, tmp_path / "elsewhere")


# ─── 분석 디렉터리로도 지목할 수 있다 ───────────────────────────────────
def _analyzed(tmp_path: Path) -> tuple[Path, Path]:
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"
    out_dir.mkdir()
    (out_dir / "state.json").write_text(json.dumps({
        "schema": STATE_SCHEMA, "stages": {},
        "source": {"path": str(video), "size": video.stat().st_size},
    }), encoding="utf-8")
    return video, out_dir


def test_an_analysis_directory_resolves_to_the_same_pair_as_its_video(tmp_path):
    """분석이 끝난 뒤의 작업(status·review·frame·clean)에서 사용자가 손에 든
    경로는 산출물 디렉터리다. 0.1.0은 그것을 영상으로 알아듣고 뒤에 .analysis를
    한 번 더 붙여, 멀쩡히 끝난 분석을 '아직 안 됨'이라고 답했다."""
    video, out_dir = _analyzed(tmp_path)

    assert manifest.resolve_target(out_dir) == (video, out_dir)
    assert manifest.resolve_target(video) == (video, out_dir)


def test_a_directory_without_state_is_not_an_analysis(tmp_path):
    plain = tmp_path / "videos"
    plain.mkdir()

    with pytest.raises(CliError) as e:
        manifest.resolve_target(plain)

    assert e.value.kind == "not-analyzed" and e.value.code == EXIT_INPUT


def test_a_directory_whose_source_is_gone_says_so(tmp_path):
    """산출물만 옮겨 온 경우. 여기서 멈추지 않으면 아래 단계가 없는 파일을 열며
    죽고, 그때는 무엇이 없는지가 메시지에 남지 않는다."""
    video, out_dir = _analyzed(tmp_path)
    video.unlink()

    with pytest.raises(CliError) as e:
        manifest.resolve_target(out_dir)

    assert e.value.kind == "source-missing"
    assert str(video) in str(e.value)


def test_a_directory_and_out_together_is_refused(tmp_path):
    """둘 다 출력 위치를 정하는 말이라, 다르면 어느 쪽이 이겨도 나머지가 조용히
    무시된다 — 무시된 쪽이 의도였다면 엉뚱한 디렉터리를 만들고 끝난다."""
    _video, out_dir = _analyzed(tmp_path)

    with pytest.raises(CliError) as e:
        manifest.resolve_target(out_dir, tmp_path / "elsewhere")

    assert e.value.kind == "target-conflict"
    # 같은 곳을 두 번 말한 것은 모순이 아니다
    assert manifest.resolve_target(out_dir, out_dir)[1] == out_dir


def test_status_answers_about_the_directory_it_was_given(tmp_path, capsys):
    """`<video>` 커맨드 전부가 같은 입구를 쓰는지 — 대표로 status를 실제로 돌린다.
    0.1.0에서는 여기서 lecture.mkv.analysis.analysis를 만들어 답했다."""
    _video, out_dir = _analyzed(tmp_path)

    assert cli.main(["status", str(out_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["out_dir"] == str(out_dir)
