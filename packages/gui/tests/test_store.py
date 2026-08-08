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


def test_units_are_listed_and_switchable(qapp, analyzed):
    """분석 단위 전환은 out_dir를 갈아끼우고 reload하는 것 — 창들은 reloaded
    신호로 알아서 따라온다. 재생 클록·영상은 영상의 것이므로 건드리지 않는다."""
    video, root = analyzed
    st = Store(video, root)
    names = [e["name"] for e in st.available_units()]
    assert names == ["full"], "구간을 안 주면 단위는 full 하나"
    assert st.unit == "full"
    assert st.out_dir == root / "runs" / "full"
    assert st.metadata, "단위 디렉터리에서 metadata를 읽어야 한다"

    seen = []
    st.reloaded.connect(lambda: seen.append(st.unit))
    st.set_unit("full")
    assert seen == [], "같은 단위면 재로드하지 않는다"


def test_window_and_screens_are_exposed(qapp, analyzed):
    """구간과 화면 목록이 없으면 GUI가 '빈 구간'과 '안 본 구간'을 구분할 수 없다."""
    video, root = analyzed
    st = Store(video, root)
    assert st.window[0] == 0.0 and st.window[1] > 0
    assert st.screens, "screens[]가 비면 화면 레인을 그릴 수 없다"
    assert st.mark_times("screen") == [a for a, _ in st.screens]


def test_series_is_loaded_from_real_npz(qapp, analyzed):
    """Store는 npz 로딩 실패를 삼키고 series=None으로 둔다 — 키 이름이 어긋나면
    그래프만 조용히 사라지고 테스트는 통과한다. 그 침묵을 여기서 깬다."""
    video, out_dir = analyzed
    st = Store(video, out_dir)
    assert st.series is not None, "detect_anchor.npz를 못 읽었다(키 불일치 의심)"
    for key in ("times", "anchor", "rate", "area",
                "anchor_threshold", "rate_threshold", "cut_area_threshold"):
        assert key in st.series, f"series에 {key}가 없다"
    n = len(st.series["times"])
    assert len(st.series["anchor"]) == n and len(st.series["rate"]) == n
    assert len(st.series["area"]) == n, "컷 면적 시계열 길이가 어긋난다"

    sv = st.series_at(st.duration / 2)
    assert sv is not None and len(sv) == 3, "판독은 (anchor, rate, area) 셋을 낸다"
    assert all(isinstance(v, float) for v in sv)


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
