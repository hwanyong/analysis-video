"""분석 단위(run) — 구간마다 독립 결과물.

병합하지 않는 것이 핵심이다. 겹치는 구간을 하나의 산출물에 담으면 같은 시각이
서로 다른 화면·이미지·대사 묶음에 속하게 되어 screens[]가 시간축의 분할이기를
그만두고, metadata에 층 개념이 생기며, GUI는 어느 층을 보는지 따져야 한다.
디렉터리로 분리하면 각 산출물의 형식이 지금과 완전히 동일해 그 전파가 없다.
"""
import pytest

from analysis_video import runs
from analysis_video.errors import CliError


def test_parse_and_sort_without_merging():
    got = runs.resolve(["250-500", "100-300"], 1000.0)
    assert got == [(100.0, 300.0), (250.0, 500.0)], "정렬만, 병합은 하지 않는다"


def test_identical_ranges_are_deduped():
    """완전히 같은 구간은 같은 분석이다 — 디렉터리 이름도 충돌한다."""
    assert runs.resolve(["100-300", "100-300"], 1000.0) == [(100.0, 300.0)]


def test_no_range_means_one_full_unit():
    assert runs.resolve(None, 500.0) == [None]
    assert runs.resolve([], 500.0) == [None]
    assert runs.name(None) == "full"


def test_unit_names_are_distinct_and_filesystem_safe():
    a, b = runs.resolve(["100-300", "250-500"], 1000.0)
    na, nb = runs.name(a), runs.name(b)
    assert na != nb
    for n in (na, nb):
        assert "." not in n and "/" not in n, f"{n}: 경로·확장자로 오해될 문자"


@pytest.mark.parametrize("bad", ["120", "300-120", "100-100", "a-b", "1-2-3"])
def test_bad_range_is_rejected(bad):
    with pytest.raises(CliError):
        runs.resolve([bad], 1000.0)


def test_range_beyond_duration_is_rejected():
    with pytest.raises(CliError, match="밖입니다"):
        runs.resolve(["100-5000"], 500.0)


def test_window_and_label():
    assert runs.window(None, 500.0) == (0.0, 500.0)
    assert runs.window((10.0, 20.0), 500.0) == (10.0, 20.0)
    assert runs.label(None) == "영상 전체"
    assert "10.0-20.0" in runs.label((10.0, 20.0))


def test_index_accumulates_and_drops_dead_units(tmp_path):
    """나중에 구간을 더 분석해도 앞서 만든 단위가 목록에서 사라지면 안 되고,
    디렉터리가 지워진 단위는 목록에도 남으면 안 된다(끊어진 참조 방지)."""
    for n in ("full", "a"):
        (tmp_path / "runs" / n).mkdir(parents=True)
    runs.merge_index(tmp_path, [{"name": "full", "range": None}])
    got = runs.merge_index(tmp_path, [{"name": "a", "range": [10.0, 20.0]}])
    assert [e["name"] for e in got] == ["full", "a"], "이전 단위가 유지된다"

    import shutil
    shutil.rmtree(tmp_path / "runs" / "a")
    got = runs.merge_index(tmp_path, [])
    assert [e["name"] for e in got] == ["full"], "사라진 단위는 목록에서도 빠진다"
