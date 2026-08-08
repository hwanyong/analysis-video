"""전환 직전 프레임도 후보여야 한다 + anchor 캐시는 스키마로 검증한다.

트리거는 "변화가 끝나고 안정된 첫 프레임"이라 컷에서는 곧 **새 화면**이다.
전환 지속이 실측 중앙값 1프레임(43건 중 41건)이라, 트리거만 잡으면 사라지려던
화면 — 판서 영상에서는 완성된 판서 — 을 매번 잃는다. 실측: video3 t=248.60의
완성 판서(발산·진동 정의, 예제 3·4, 그래프) 대신 t=248.67의 목차 화면이
캡처됐고, 완성본은 importance-point가 우연히 근처를 잡은 덕에만 살아남았다.

직전만 잡는 것도 답이 아니다 — 전부 한 칸씩 밀리고 마지막 화면이 사라진다.
그래서 둘 다 내고 중복 게이트에 맡긴다.
"""
import json

import numpy as np
import pytest

from analysis_video import frames as frames_mod


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """검출·추출·판정을 전부 대역으로 세우고 후보 생성만 남긴다."""
    captured = {}

    def fake_cached_anchor(video_path, out_dir, ath, rth, cth):
        return {
            "fps": 30.0, "n_frames": 12,
            "anchor_series": np.zeros(12), "rate_series": np.zeros(12),
            "area_series": np.zeros(12),
            "time_series": np.arange(12) / 30.0,
            "events": [{"anchor_idx": 0, "anchor_time": 0.0,
                        "transition_start_idx": 5, "transition_start_time": 5 / 30.0,
                        "trigger_idx": 6, "trigger_time": 6 / 30.0}],
            "anchor_threshold": ath, "rate_threshold": rth, "cut_area_threshold": cth,
        }

    monkeypatch.setattr(frames_mod, "_cached_anchor", fake_cached_anchor)
    monkeypatch.setattr(frames_mod, "_cached_adaptive",
                        lambda vp, od, dur, ft: [])
    monkeypatch.setattr(frames_mod.media, "get_duration", lambda p: 10.0)
    monkeypatch.setattr(frames_mod.adaptive, "pick_stable_time",
                        lambda p, t, d, **kw: t + 0.5)

    # 추출은 빈 파일을 만들고, 게이트는 전부 통과시킨다
    def fake_extract(video_path, t, out_path, quality=90):
        out_path.write_bytes(b"x")
        return True
    monkeypatch.setattr(frames_mod.media, "extract_frame", fake_extract)
    monkeypatch.setattr(frames_mod.media, "yavg", lambda p: 200.0)

    # 해시는 뺄셈으로 거리를 낸다(imagehash 규약). 호출마다 멀어지게 해서
    # 중복 게이트가 개입하지 않도록 — 여기서 보려는 건 후보 생성이지 중복 판정이 아니다.
    counter = iter(range(0, 100000, 1000))
    monkeypatch.setattr(frames_mod.media, "phash", lambda p: next(counter))

    # 전환 쌍 비교: 기본은 '화면이 실제로 바뀜'(서로 다른 배열)
    grays = iter(range(1, 10000))
    monkeypatch.setattr(frames_mod.media, "extract_gray_array",
                        lambda p, t, w=200, h=112: np.full((h, w), next(grays) % 250,
                                                           dtype=np.uint8))
    return captured


def test_pre_transition_candidate_is_emitted(stub_pipeline, tmp_path):
    out = tmp_path / "x.analysis"
    result = frames_mod.build_frames(tmp_path / "v.mkv", out, [])
    by_source = {tuple(r["sources"]): r for r in result["records"]}

    assert ("anchor-diff-pre",) in by_source, "전환 직전 후보가 없다"
    assert ("anchor-diff",) in by_source, "트리거 후보가 없다"
    pre = by_source[("anchor-diff-pre",)]
    trig = by_source[("anchor-diff",)]
    # transition_start_idx=5 → 직전은 인덱스 4
    assert pre["time"] == pytest.approx(4 / 30.0)
    assert trig["time"] == pytest.approx(6 / 30.0)
    assert pre["time"] < trig["time"], "직전이 트리거보다 앞서야 한다"


def test_pre_candidate_skipped_when_transition_starts_at_first_frame(
        monkeypatch, stub_pipeline, tmp_path):
    """transition_start_idx가 0이면 '직전'이 없다 — 음수 인덱스로 끝 프레임을
    집어오면 안 된다(파이썬 음수 인덱싱의 조용한 오동작)."""
    def fake_cached_anchor(video_path, out_dir, ath, rth, cth):
        return {
            "fps": 30.0, "n_frames": 12,
            "anchor_series": np.zeros(12), "rate_series": np.zeros(12),
            "area_series": np.zeros(12), "time_series": np.arange(12) / 30.0,
            "events": [{"anchor_idx": 0, "anchor_time": 0.0,
                        "transition_start_idx": 0, "transition_start_time": 0.0,
                        "trigger_idx": 3, "trigger_time": 0.1}],
            "anchor_threshold": ath, "rate_threshold": rth, "cut_area_threshold": cth,
        }
    monkeypatch.setattr(frames_mod, "_cached_anchor", fake_cached_anchor)

    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "y.analysis", [])
    sources = [tuple(r["sources"]) for r in result["records"]]
    assert ("anchor-diff-pre",) not in sources


def test_pre_candidate_dropped_when_screen_did_not_change(
        monkeypatch, stub_pipeline, tmp_path):
    """전환이 잡혔어도 화면이 실제로 안 바뀌었으면(자막만 교체 등) 전환 직전
    후보를 내지 않는다. 내면 같은 화면이 두 장 채택되고 — 전역 중복 게이트의
    pHash 사전 필터가 자막에 과민해 못 걸러낸다(실측 10표본 중 9건 통과) —
    구간이 0.07초로 퇴화하며 같은 대사가 두 이미지에 중복으로 붙는다."""
    same = np.full((225, 400), 128, dtype=np.uint8)
    monkeypatch.setattr(frames_mod.media, "extract_gray_array",
                        lambda p, t, w=200, h=112: same)

    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "s.analysis", [])
    sources = [tuple(r["sources"]) for r in result["records"]]
    assert ("anchor-diff-pre",) not in sources, "안 바뀐 화면의 직전 후보는 생략"
    assert ("anchor-diff",) in sources, "트리거는 그대로 남는다"


def test_pair_threshold_is_recorded_in_params(stub_pipeline, tmp_path):
    r = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "p.analysis", [])
    assert r["params"]["pair_dup_threshold"] == 0.93


def test_v1_anchor_cache_is_rejected(monkeypatch, tmp_path):
    """구 캐시는 키 구성이 달라(cum_series, area_series 없음) 조회하면 KeyError로
    죽는다. 스키마를 먼저 봐서 조용히 버리고 재검출해야 한다."""
    out = tmp_path / "c.analysis"
    out.mkdir()
    np.savez_compressed(
        out / "detect_anchor.npz",
        cum_series=np.zeros(3), rate_series=np.zeros(3),
        time_series=np.arange(3) / 30.0, fps=30.0,
        cum_threshold=0.02, rate_threshold=0.0015,
        events_json=json.dumps([]))

    calls = []

    def fake_detect(video_path, anchor_threshold, rate_threshold, cut_area_threshold):
        calls.append(True)
        return {"fps": 30.0, "n_frames": 0,
                "anchor_series": np.zeros(1), "rate_series": np.zeros(1),
                "area_series": np.zeros(1), "time_series": np.zeros(1), "events": [],
                "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
                "cut_area_threshold": cut_area_threshold}
    monkeypatch.setattr(frames_mod.anchor, "transition_aware_anchor_diff", fake_detect)

    r = frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.04)
    assert calls, "구 캐시를 버리고 재검출해야 한다"
    assert "area_series" in r

    # 새로 쓴 캐시는 재사용된다
    calls.clear()
    again = frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.04)
    assert not calls, "같은 파라미터면 캐시를 재사용해야 한다"
    assert again["cut_area_threshold"] == 0.04


def test_cache_invalidated_when_cut_area_threshold_changes(monkeypatch, tmp_path):
    """새 파라미터도 캐시 키에 들어가야 한다 — 아니면 임계를 바꿔도 옛 결과가 나온다."""
    out = tmp_path / "d.analysis"
    out.mkdir()
    calls = []

    def fake_detect(video_path, anchor_threshold, rate_threshold, cut_area_threshold):
        calls.append(cut_area_threshold)
        return {"fps": 30.0, "n_frames": 0,
                "anchor_series": np.zeros(1), "rate_series": np.zeros(1),
                "area_series": np.zeros(1), "time_series": np.zeros(1), "events": [],
                "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
                "cut_area_threshold": cut_area_threshold}
    monkeypatch.setattr(frames_mod.anchor, "transition_aware_anchor_diff", fake_detect)

    frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.04)
    frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.06)
    assert calls == [0.04, 0.06], "임계가 바뀌면 재검출"
