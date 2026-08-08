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


def test_point_lands_on_the_frame_it_produced(qapp, tmp_path):
    """point 원시 시각으로 이동하면 화면에는 직전 구간 이미지가 뜬다 — 안정화(+0.3초)와
    중복 병합 때문. 착지는 그 point를 품은 프레임이어야 확인이 성립한다."""
    out = tmp_path / "p.analysis"
    _write(out,
           frames=[{"time": 10.0, "interval": [10.0, 244.4], "sources": ["anchor-diff"]},
                   {"time": 244.4, "interval": [244.4, 900.0],
                    "sources": ["importance-point"], "point_times": [244.1]},
                   {"time": 963.13, "interval": [963.13, 1600.0],
                    "sources": ["anchor-diff", "importance-point"],
                    "point_times": [1069.0]}],
           rejected=[{"time": 1069.3, "sources": ["importance-point"],
                      "reject_reason": "phash-dup(of=963.13)", "dup_of": 963.13,
                      "point_times": [1069.0]}],
           duration=1600.0)
    st = Store(tmp_path / "nonexistent.mkv", out)

    assert st.point_times == [244.1, 1069.0], "★는 원시 시각 자리에 찍힌다"
    assert st.point_landings == [244.4, 963.13], "착지는 담당 프레임"
    assert st.point_owner[1069.0] == 963.13, "병합된 point는 승계 대상이 담당"

    # 순회는 착지 시각 위에서 — 원시 시각으로 순회하면 착지 후 뒤로 가기가
    # 방금 온 자리를 다시 가리켜 제자리에 갇힌다
    assert st.next_point_time(0.0, forward=True) == 244.4
    assert st.next_point_time(244.4, forward=True) == 963.13
    assert st.next_point_time(963.13, forward=False) == 244.4
    assert st.next_point_time(244.4, forward=False) is None

    assert st.dup_target(1069.3) == 963.13, "탈락 → 중복 원본 링크"
    assert st.dup_target(500.0) is None


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
