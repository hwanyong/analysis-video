"""Store 파생 데이터 회귀 테스트 — 산출물을 GUI가 어떻게 요약하는가."""
import json

from analysis_video_gui.store import Store


def _write(out_dir, frames, rejected, duration=100.0):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metadata.json").write_text(json.dumps({
        "schema": "test", "source": {"duration": duration},
        "frames": frames, "rejected": rejected, "requested": [],
        "transcript": {"segments": []},
    }), encoding="utf-8")


def test_point_times_are_deduped(qapp, tmp_path):
    """같은 importance-point가 탈락 후보와 병합 대상 채택 프레임 양쪽에 붙는다 —
    중복을 남기면 ★가 겹치고 P 내비게이션이 한자리에 두 번 멈춘다."""
    out = tmp_path / "x.analysis"
    _write(out,
           frames=[{"time": 10.0, "interval": [10.0, 50.0], "sources": ["anchor-diff"],
                    "point_times": [42.0]}],
           rejected=[{"time": 42.3, "sources": ["importance-point"],
                      "reject_reason": "phash-dup(of=10.0)", "point_times": [42.0]}])
    st = Store(tmp_path / "nonexistent.mkv", out)
    assert st.point_times == [42.0], "같은 point가 두 번 세어지면 안 된다"


def test_source_counts_span_composites(qapp, tmp_path):
    out = tmp_path / "y.analysis"
    _write(out,
           frames=[{"time": 1.0, "interval": [1.0, 2.0], "sources": ["anchor-diff"]},
                   {"time": 2.0, "interval": [2.0, 3.0],
                    "sources": ["anchor-diff", "importance-point"]}],
           rejected=[])
    st = Store(tmp_path / "nonexistent.mkv", out)
    counts = st.source_counts()
    assert counts["anchor-diff"] == 2 and counts["importance-point"] == 1
