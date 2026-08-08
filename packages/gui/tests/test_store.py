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
    assert st.series is not None, "detect_signals.npz를 못 읽었다(키 불일치 의심)"
    for key in ("times", "anchor", "rate", "area",
                "anchor_threshold", "rate_threshold", "cut_area_threshold"):
        assert key in st.series, f"series에 {key}가 없다"
    n = len(st.series["times"])
    assert len(st.series["anchor"]) == n and len(st.series["rate"]) == n
    assert len(st.series["area"]) == n, "컷 면적 시계열 길이가 어긋난다"

    sv = st.series_at(st.duration / 2)
    assert sv is not None and len(sv) == 3, "판독은 (anchor, rate, area) 셋을 낸다"
    assert all(isinstance(v, float) for v in sv)


def test_transitions_are_scoped_to_the_unit(qapp, analyzed):
    """검출 캐시(npz)는 영상 전체분이다. 부분 단위가 그걸 그대로 노출하면
    구간 밖 전환이 이 단위의 결과인 척 범례에 세어지고, 순회(↓/↑)도 안 본
    구간으로 착지한다."""
    from analysis_video import cli

    video, root = analyzed
    # 합성 영상은 2초마다 슬라이드가 바뀐다 → 사건이 2·4·6초. 3~5초는 하나만 문다
    assert cli.main(["frames", str(video), "--out", str(root), "--range", "3-5"]) == 0

    st_full = Store(video, root, unit="full")
    st_part = Store(video, root, unit="00003_0-00005_0")
    assert st_part.window == [3.0, 5.0]
    assert st_full.transitions, "전체 단위에 전환이 하나도 없으면 검증이 무의미"

    lo, hi = st_part.window
    # 거르는 기준은 **사건 시각**이다. 직후 촬영점은 구간 끝을 몇 프레임 넘을 수
    # 있는데(변화가 경계에서 일어났으면 당연하다) 그걸로 거르면 경계의 사건이 통째로 사라진다
    assert all(lo <= t <= hi for t, _ in st_part.transitions), \
        f"구간 밖 사건이 남았다: {st_part.transitions}"
    assert len(st_part.transitions) < len(st_full.transitions)
    assert st_part.mark_times("transition") == sorted(
        a for a, _ in st_part.transitions), "순회 착지점도 같은 목록을 써야 한다"


def test_source_counts_span_composites(qapp, tmp_path):
    out = tmp_path / "y.analysis"
    _write(out,
           frames=[{"time": 1.0, "interval": [1.0, 2.0], "sources": ["screen-start"]},
                   {"time": 2.0, "interval": [2.0, 3.0],
                    "sources": ["screen-start", "screen-end"]}],
           rejected=[])
    st = Store(tmp_path / "nonexistent.mkv", out)
    counts = st.source_counts()
    assert counts["screen-start"] == 2 and counts["screen-end"] == 1
