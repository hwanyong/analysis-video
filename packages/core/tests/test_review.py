"""분석문(review)은 파이프라인이 소유하되 파이프라인이 지우지 않아야 한다.

이 파일이 잠그는 것 둘.

**하나 — 자리.** review.md는 호출 AI가 컨텍스트를 태워 쓴 글이고, 이 디렉터리에서
유일하게 **되만들 수 없는** 산출물이다. 그런데 임계를 조정하며 frames를 다시 도는
것은 정상 흐름이고, 그때 `runs.reset_unit`은 단위 디렉터리를 `shutil.rmtree`한다.
그래서 review.md는 단위 **밖**에 산다. 여기 회귀 시험이 없으면 "가까이 두는 게
자연스럽다"는 이유로 언제든 안으로 옮겨질 수 있고, 그 순간 조용히 사라진다.

**둘 — 교착 없는 상태기계.** 낡음 판정이 본문 동일 판정보다 **앞에** 오면,
"본문은 그대로인데 읽은 것이 바뀐" 상태에서 재제출이 `unchanged`로 끝나 낡음이
영영 풀리지 않는다. `next`는 계속 "다시 읽고 다시 넣으세요"를 안내하고, 재제출
한 번마다 이미지 토큰 수만이 탄다.
"""
import io
import json
import sys

import pytest

from analysis_video import cli, manifest, review, runs


def _unit(tmp_path, text="# 화면 1\n대사\n"):
    unit = tmp_path / "runs" / "full"
    unit.mkdir(parents=True)
    (unit / "context.md").write_text(text, encoding="utf-8")
    return unit


def _write(tmp_path, body, *, force=False):
    """review 한 번 제출 — cmd_review가 하는 판정을 그대로 밟는다."""
    unit = tmp_path / "runs" / "full"
    ctx = unit / "context.md"
    path = review.review_path(tmp_path, "full")
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    meta = review.parse_header(previous) if previous else None
    now = review.sha256_of(ctx)
    action = review.decide(previous if meta else None, body,
                           meta["context_sha256"] if meta else None, now, force)
    if action in ("create", "refresh", "update"):
        header = review.render_header(
            run="full", unit_rel="runs/full", context_rel="runs/full/context.md",
            context_sha=now, video_name="v.mkv", version="9.9.9",
            at="2026-01-01T00:00:00+09:00")
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text_atomic(path, review.compose(body, header))
    return action


# ---------- 자리 ----------

def test_the_review_survives_a_unit_reset(tmp_path):
    """임계를 조정해 frames를 다시 돌아도 AI가 쓴 글은 남아야 한다."""
    unit = _unit(tmp_path)
    _write(tmp_path, "## 요약\n행렬은 공간을 변환한다.\n")
    (unit / "frames").mkdir()
    (unit / "frames" / "scene_000.jpg").write_bytes(b"old")

    runs.reset_unit(unit)

    kept = review.review_path(tmp_path, "full")
    assert kept.exists(), "reset_unit이 리뷰를 지웠다 — 단위 밖에 두는 이유가 이것이다"
    assert "행렬은 공간을 변환한다." in kept.read_text(encoding="utf-8")
    assert not (unit / "frames").exists(), "검출기의 판정은 갈아엎어야 한다"


def test_the_review_lives_outside_every_unit_directory(tmp_path):
    """경로 자체를 잠근다 — 안으로 옮기는 변경이 이 단정에서 먼저 걸린다."""
    path = review.review_path(tmp_path, "full")
    assert runs.unit_dir(tmp_path, None) not in path.parents


# ---------- 상태기계 ----------

def test_a_first_submission_is_created(tmp_path):
    _unit(tmp_path)
    assert _write(tmp_path, "본문\n") == "create"
    assert review.status(tmp_path, "full",
                         tmp_path / "runs/full/context.md")["state"] == "current"


def test_resubmitting_the_same_body_writes_nothing(tmp_path):
    _unit(tmp_path)
    _write(tmp_path, "본문\n")
    before = review.review_path(tmp_path, "full").read_text(encoding="utf-8")
    assert _write(tmp_path, "본문\n") == "unchanged"
    assert review.review_path(tmp_path, "full").read_text(encoding="utf-8") == before


def test_a_different_body_needs_force_while_the_review_is_current(tmp_path):
    _unit(tmp_path)
    _write(tmp_path, "본문\n")
    assert _write(tmp_path, "다른 본문\n") == "conflict"
    assert _write(tmp_path, "다른 본문\n", force=True) == "update"


def test_rewriting_context_makes_the_review_stale(tmp_path):
    unit = _unit(tmp_path)
    _write(tmp_path, "본문\n")
    unit.joinpath("context.md").write_text("# 화면 1\n바뀐 대사\n", encoding="utf-8")
    assert review.status(tmp_path, "full", unit / "context.md")["state"] == "stale"


def test_the_same_body_clears_staleness_without_force(tmp_path):
    """교착 방지 — 이 단정이 깨지면 낡은 리뷰를 푸는 길이 --force밖에 없고,
    그것은 '다시 읽었다'와 '읽지도 않고 도장만 찍었다'를 구분하지 못한다."""
    unit = _unit(tmp_path)
    _write(tmp_path, "본문\n")
    unit.joinpath("context.md").write_text("# 화면 1\n바뀐 대사\n", encoding="utf-8")

    assert _write(tmp_path, "본문\n") == "refresh"
    assert review.status(tmp_path, "full", unit / "context.md")["state"] == "current"


def test_a_missing_review_is_missing_not_stale(tmp_path):
    unit = _unit(tmp_path)
    assert review.status(tmp_path, "full", unit / "context.md")["state"] == "missing"


def test_a_review_without_a_header_is_unreadable(tmp_path):
    """사람이 손으로 만든 파일 — 무엇을 읽고 쓴 것인지 모르므로 낡음도 판정할 수 없다."""
    unit = _unit(tmp_path)
    path = review.review_path(tmp_path, "full")
    path.parent.mkdir(parents=True)
    path.write_text("머리말 없는 글\n", encoding="utf-8")
    assert review.status(tmp_path, "full", unit / "context.md")["state"] == "unreadable"


# ---------- 머리말 ----------

def test_the_header_round_trips(tmp_path):
    unit = _unit(tmp_path)
    _write(tmp_path, "본문\n")
    text = review.review_path(tmp_path, "full").read_text(encoding="utf-8")
    meta = review.parse_header(text)
    assert meta["schema"] == review.SCHEMA
    assert meta["run"] == "full"
    assert meta["context_sha256"] == review.sha256_of(unit / "context.md")
    assert review.strip_header(text) == "본문\n", "본문이 머리말과 함께 오염됐다"


def test_the_header_records_what_was_read_not_what_it_contained(tmp_path):
    """임계·화면 수·전사 출처를 굳히지 않는다 — 다시 투사되지 않는 값이라
    frames를 다시 돌린 뒤에도 옛 값을 현재 사실처럼 주장하게 된다."""
    _unit(tmp_path)
    _write(tmp_path, "본문\n")
    meta = review.parse_header(
        review.review_path(tmp_path, "full").read_text(encoding="utf-8"))
    assert set(meta) == {"schema", "run", "context", "context_sha256", "at", "version"}


def test_normalize_only_touches_bom_newlines_and_blank_edges():
    assert review.normalize("﻿가\r\n나\r\n\n\n") == "가\n나\n"
    assert review.normalize("\n\n본문\n") == "본문\n"


def test_normalize_keeps_a_leading_indent(tmp_path):
    """본문이 들여쓴 코드 블록으로 시작할 수 있다. 앞뒤를 한꺼번에 털면
    그 4칸이 사라져 마크다운이 깨진다."""
    assert review.normalize("    def f():\n        pass\n") == \
        "    def f():\n        pass\n"


@pytest.mark.parametrize("marker", [review.BEGIN, review.END])
def test_a_body_carrying_the_marker_is_refused(marker):
    """본문에 마커가 섞이면 다음 실행의 머리말 파싱이 엉뚱한 곳을 짚는다.
    (cmd_review가 이 판정을 하고, 여기서는 마커가 실제로 구간을 여닫는지만 본다)"""
    assert marker in f"앞\n{marker}\n뒤"


# ---------- 지문의 선택 ----------

def test_the_fingerprint_follows_context_not_the_transcript(tmp_path):
    """transcript.json 전체 sha를 쓰면 대사와 무관한 칸(source.notes 등)이 바뀌어도
    모든 단위의 리뷰가 한꺼번에 낡은 것이 된다. 지문은 실제로 읽은 파일 하나다."""
    unit = _unit(tmp_path)
    _write(tmp_path, "본문\n")
    (tmp_path / "transcript.json").write_text(
        json.dumps({"segments": [], "source": {"notes": ["새 note"]}}), encoding="utf-8")
    assert review.status(tmp_path, "full", unit / "context.md")["state"] == "current"


# ---------- 머리말이 실어 나르는 것 ----------

class _Stdin:
    """`--write -`가 보는 표준입력. isatty()가 False여야 본문 읽기로 들어간다."""

    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)

    def isatty(self):
        return False


def test_the_written_header_carries_no_host_path(tmp_path, monkeypatch, capsys):
    """머리말에 절대경로를 적으면 홈 디렉터리 이름이 남에게 그대로 간다.

    이 파일은 `clean`이 어느 레벨에서도 지우지 않는 유일한 산출물이고
    `--export-dir`은 그것을 남에게 보내라고 있는 옵션이다. 실제로 저장소의
    예시 리뷰(docs/media/*.review.md)가 `/Users/<이름>/...` 두 줄을 싣고
    나갈 뻔했다.

    **cmd_review를 통째로 밟는다.** render_header만 보면 상대경로를 넣어
    부르는 시험이 되어, 절대경로를 만들어 넘기던 **호출부**의 회귀를 못 잡는다."""
    video = tmp_path / "home" / "이름" / "v.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"\0")
    out_dir = tmp_path / "home" / "이름" / "v.mkv.analysis"
    unit = out_dir / "runs" / "full"
    unit.mkdir(parents=True)
    (unit / "context.md").write_text("# 화면 1\n대사\n", encoding="utf-8")
    (out_dir / "runs" / "index.json").write_text(
        json.dumps([{"name": "full", "range": None, "dir": str(unit)}]),
        encoding="utf-8")

    monkeypatch.setattr(sys, "stdin", _Stdin("## 요약\n본문\n".encode()))
    assert cli.main(["review", str(video), "--run", "full", "--write", "-"]) == 0
    capsys.readouterr()

    text = review.review_path(out_dir, "full").read_text(encoding="utf-8")
    assert str(tmp_path) not in text, "머리말이 호스트 절대경로를 실었다"
    assert "runs/full" in text, "단위는 out_dir 기준 상대경로로 남아야 한다"
    assert "v.mkv" in text, "어느 영상의 분석인지는 남아야 한다"
