"""정리는 **되만들 수 있는 것만** 지운다.

`clean`이 생기기 전까지 이 디렉터리의 모든 것은 원본 영상만 있으면 되만들 수
있었다. `review`가 생기면서 그렇지 않은 것이 하나 생겼고, 그때부터 "공간을
비우려는 한 번의 실행"이 위험해졌다. 이 파일은 그 경계를 잠근다.

보고가 기본이고 삭제는 명시했을 때만이라는 것도 함께 잠근다 — `--level` 없이
부른 실행이 무언가 지우기 시작하면, 무엇이 얼마나 있는지 물어보려던 사용자가
그것을 잃는다.
"""
import json

import pytest

from analysis_video import clean, review


def _analysis(tmp_path):
    """정리 대상과 보호 대상이 모두 들어 있는 분석 디렉터리."""
    (tmp_path / "video.mkv").write_bytes(b"v" * 4000)
    (tmp_path / "transcript.json").write_text('{"segments": []}', encoding="utf-8")
    (tmp_path / "detect_signals.npz").write_bytes(b"n" * 100)
    (tmp_path / "detect_adaptive.json").write_text("{}", encoding="utf-8")
    unit = tmp_path / "runs" / "full"
    for sub, name, blob in (("frames", "scene_000.jpg", b"f" * 2000),
                            ("read", "scene_000.jpg", b"r" * 500),
                            ("requested", "req_0042.10.jpg", b"q" * 300)):
        (unit / sub).mkdir(parents=True, exist_ok=True)
        (unit / sub / name).write_bytes(blob)
    (unit / "metadata.json").write_text("{}", encoding="utf-8")
    (unit / "context.md").write_text("# c\n", encoding="utf-8")
    rev = review.review_path(tmp_path, "full")
    rev.parent.mkdir(parents=True, exist_ok=True)
    rev.write_text("분석문\n", encoding="utf-8")
    return tmp_path


PROTECTED = [
    "reviews/full.md",                  # 되만들 수 없다 — 이 명령의 존재 이유
    "transcript.json",                  # whisper였다면 모델 추론이 다시 든다
    "runs/full/read/scene_000.jpg",     # context.md가 이것을 가리킨다
    "runs/full/requested/req_0042.10.jpg",  # 근거를 적어 주문한 것
    "runs/full/metadata.json",
    "runs/full/context.md",
    "detect_signals.npz",               # 되만드는 데 전 프레임 디코드가 든다
    "detect_adaptive.json",
]


@pytest.mark.parametrize("level", clean.LEVELS)
@pytest.mark.parametrize("kept", PROTECTED)
def test_no_level_touches_a_protected_artifact(tmp_path, level, kept):
    _analysis(tmp_path)
    clean.clean(tmp_path, level)
    assert (tmp_path / kept).exists(), f"--level {level} 이 {kept} 를 지웠다"


def test_survey_reports_without_deleting_anything(tmp_path):
    _analysis(tmp_path)
    before = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    got = clean.survey(tmp_path)
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == before
    assert [lv["level"] for lv in got["levels"]] == list(clean.LEVELS)
    assert all(lv["cost"] for lv in got["levels"]), "대가를 적지 않은 레벨이 있다"


def test_levels_are_cumulative(tmp_path):
    _analysis(tmp_path)
    levels = {lv["level"]: lv for lv in clean.survey(tmp_path)["levels"]}
    assert levels["images"]["frees_bytes"] > levels["cache"]["frees_bytes"]
    assert set(levels["cache"]["paths"]) < set(levels["images"]["paths"])


def test_cache_removes_only_the_split_video(tmp_path):
    _analysis(tmp_path)
    clean.clean(tmp_path, "cache")
    assert not (tmp_path / "video.mkv").exists()
    assert (tmp_path / "runs/full/frames/scene_000.jpg").exists()


def test_images_removes_the_full_resolution_frames(tmp_path):
    _analysis(tmp_path)
    clean.clean(tmp_path, "images")
    assert not (tmp_path / "runs/full/frames").exists()
    assert (tmp_path / "runs/full/read/scene_000.jpg").exists(), \
        "읽기용 사본까지 지우면 context.md가 깨진다"


def test_cleaning_twice_is_idempotent(tmp_path):
    _analysis(tmp_path)
    first = clean.clean(tmp_path, "images")
    second = clean.clean(tmp_path, "images")
    assert first["freed_bytes"] > 0
    assert second["freed_bytes"] == 0 and second["removed"] == []


def test_context_md_still_resolves_after_the_deepest_clean(tmp_path):
    """정리의 계약은 '용량을 줄인다'가 아니라 '읽을 수 있는 상태를 남긴다'이다."""
    _analysis(tmp_path)
    unit = tmp_path / "runs" / "full"
    unit.joinpath("context.md").write_text("![](read/scene_000.jpg)\n", encoding="utf-8")
    clean.clean(tmp_path, clean.LEVELS[-1])
    for ref in ["read/scene_000.jpg"]:
        assert (unit / ref).exists(), f"context.md가 가리키는 {ref} 가 사라졌다"
