"""화면의 끝 상태도 후보여야 한다 + anchor 캐시는 스키마로 검증한다.

트리거는 "변화가 끝나고 안정된 첫 프레임"이라 곧 **새 화면이 시작된 순간**이다.
그 뒤 수십 초에 걸쳐 채워지는 판서는 어디에도 안 남는다 — 실측 video3의 한
화면은 105초 동안 885자를 설명하며 페이지를 채우는데, 거기 붙은 이미지는
거의 빈 페이지였고 완성된 페이지는 대사가 딴 얘기인 다음 블록에 가 있었다.

끝만 잡는 것도 답이 아니다 — "무엇에서 무엇으로 갔는가"가 사라진다.
그래서 둘 다 내되, 끝 상태는 **그 화면의 시작과 견줘** 달라졌을 때만 낸다.
"""
import json

import numpy as np
import pytest
from PIL import Image

from analysis_video import frames as frames_mod

FPS = 30.0


def _anchor_result(events, **over):
    base = {
        "fps": FPS, "n_frames": 60,
        "anchor_series": np.zeros(60), "rate_series": np.zeros(60),
        "area_series": np.zeros(60), "time_series": np.arange(60) / FPS,
        "events": events, "row_change_freq": np.zeros(36),
        "anchor_threshold": 0.02, "rate_threshold": 0.0015,
        "cut_area_threshold": 0.04,
    }
    base.update(over)
    return base


def _event(settled_idx=30, trigger_idx=45, start_idx=40):
    """시각은 첫 화면 시드(w_start+0.5초=0.5초)보다 뒤여야 이 화면의 '끝'이 된다."""
    return {"anchor_idx": 0, "anchor_time": 0.0,
            "transition_start_idx": start_idx, "transition_start_time": start_idx / FPS,
            "settled_idx": settled_idx, "settled_time": settled_idx / FPS,
            "trigger_idx": trigger_idx, "trigger_time": trigger_idx / FPS}


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """검출·추출·중복판정을 대역으로 세우고 후보 생성만 남긴다."""
    monkeypatch.setattr(frames_mod, "_cached_anchor",
                        lambda vp, cd, a, r, c: _anchor_result([_event()]))
    monkeypatch.setattr(frames_mod, "_cached_adaptive", lambda vp, od, dur, ft: [])
    monkeypatch.setattr(frames_mod.media, "get_duration", lambda p: 10.0)
    monkeypatch.setattr(frames_mod.adaptive, "pick_stable_time",
                        lambda p, t, d, **kw: t + 0.5)

    # 추출은 **진짜 이미지**를 쓴다 — 내용량 게이트가 실제로 픽셀을 읽기 때문에
    # 더미 바이트를 쓰면 게이트가 예외로 죽고 테스트는 그걸 못 본다.
    def fake_extract(video_path, t, out_path, quality=90):
        a = np.zeros((90, 160), dtype=np.uint8)
        a[20:60, 30:120] = 255  # 배경과 뚜렷이 다른 영역 = 내용 있음
        Image.fromarray(a).save(out_path)
        return True
    monkeypatch.setattr(frames_mod.media, "extract_frame", fake_extract)

    # 화면 시작↔끝 비교: 기본은 '달라졌음'(서로 다른 배열)
    grays = iter(range(1, 10000))
    monkeypatch.setattr(frames_mod.media, "extract_gray_array",
                        lambda p, t, w=200, h=112: np.full((h, w), next(grays) % 250,
                                                           dtype=np.uint8))


def test_screen_end_candidate_is_emitted(stub_pipeline, tmp_path):
    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "x.analysis")
    by_source = {tuple(r["sources"]): r for r in result["records"]}

    assert ("screen-end",) in by_source, "화면 끝 상태 후보가 없다"
    assert ("anchor-diff",) in by_source, "트리거 후보가 없다"
    end, trig = by_source[("screen-end",)], by_source[("anchor-diff",)]
    assert end["time"] == pytest.approx(30 / FPS), "settled_idx 자리를 써야 한다"
    assert end["time"] < trig["time"], "끝 상태가 다음 화면 트리거보다 앞선다"


def test_screen_end_uses_settled_not_transition_start(monkeypatch, stub_pipeline,
                                                      tmp_path):
    """점진적 변화는 임계를 **중간에** 넘는다. transition_start-1을 집으면 이미
    섞이는 중인 프레임이 잡힌다(실측 video2 41%·video1 36%, 최대 10프레임).
    검출기가 되짚어 준 settled_idx를 그대로 써야 한다."""
    monkeypatch.setattr(frames_mod, "_cached_anchor",
                        lambda vp, cd, a, r, c: _anchor_result(
                            [_event(settled_idx=25)]))  # 시작-1 = 39가 아니라 25
    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "s.analysis")
    end = [r for r in result["records"] if r["sources"] == ["screen-end"]][0]
    assert end["time"] == pytest.approx(25 / FPS), "되짚은 자리를 안 쓰고 있다"


def test_screen_end_dropped_when_screen_never_changed(monkeypatch, stub_pipeline,
                                                      tmp_path):
    """뜬 뒤 그대로인 슬라이드는 두 장이 될 이유가 없다. 실측 video2는 24개
    화면 중 3개만 끝 상태가 필요했다 — 무조건 두 장이면 나머지는 낭비다."""
    same = np.full((225, 400), 128, dtype=np.uint8)
    monkeypatch.setattr(frames_mod.media, "extract_gray_array",
                        lambda p, t, w=200, h=112: same)
    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "n.analysis")
    sources = [tuple(r["sources"]) for r in result["records"]]
    assert ("screen-end",) not in sources, "안 바뀐 화면의 끝 상태는 생략"
    assert ("anchor-diff",) in sources, "트리거는 그대로 남는다"


def test_screen_end_skipped_when_it_would_precede_the_screen(monkeypatch,
                                                             stub_pipeline, tmp_path):
    """되짚기가 화면 시작보다 앞으로 가면 그건 이 화면의 끝이 아니다."""
    monkeypatch.setattr(frames_mod, "_cached_anchor",
                        lambda vp, cd, a, r, c: _anchor_result(
                            [_event(settled_idx=3, trigger_idx=6, start_idx=4)]))
    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "e.analysis")
    assert ("screen-end",) not in [tuple(r["sources"]) for r in result["records"]]


def test_gate_params_are_recorded(stub_pipeline, tmp_path):
    r = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "p.analysis")
    p = r["params"]
    assert p["pair_dup_threshold"] == 0.93
    assert p["blank_area_threshold"] == 0.001
    assert p["body_band"] == [0.0, 1.0], "띠가 없으면 전체가 본문"


def test_v1_anchor_cache_is_rejected(monkeypatch, tmp_path):
    """구 캐시는 키 구성이 달라 조회하면 KeyError로 죽는다. 스키마를 먼저 봐서
    조용히 버리고 재검출해야 한다."""
    out = tmp_path / "c.analysis"
    out.mkdir()
    np.savez_compressed(
        out / "detect_anchor.npz",
        cum_series=np.zeros(3), rate_series=np.zeros(3),
        time_series=np.arange(3) / FPS, fps=FPS,
        cum_threshold=0.02, rate_threshold=0.0015,
        events_json=json.dumps([]))

    calls = []

    def fake_detect(video_path, anchor_threshold, rate_threshold, cut_area_threshold):
        calls.append(True)
        return _anchor_result([], anchor_threshold=anchor_threshold,
                              rate_threshold=rate_threshold,
                              cut_area_threshold=cut_area_threshold)
    monkeypatch.setattr(frames_mod.anchor, "transition_aware_anchor_diff", fake_detect)

    r = frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.04)
    assert calls, "구 캐시를 버리고 재검출해야 한다"
    assert "area_series" in r

    calls.clear()
    again = frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.04)
    assert not calls, "같은 파라미터면 캐시를 재사용해야 한다"
    assert again["cut_area_threshold"] == 0.04
    assert "row_change_freq" in again, "띠 산출용 통계가 캐시에서 살아 나와야 한다"


def test_cache_invalidated_when_cut_area_threshold_changes(monkeypatch, tmp_path):
    """새 파라미터도 캐시 키에 들어가야 한다 — 아니면 임계를 바꿔도 옛 결과가 나온다."""
    out = tmp_path / "d.analysis"
    out.mkdir()
    calls = []

    def fake_detect(video_path, anchor_threshold, rate_threshold, cut_area_threshold):
        calls.append(cut_area_threshold)
        return _anchor_result([], cut_area_threshold=cut_area_threshold)
    monkeypatch.setattr(frames_mod.anchor, "transition_aware_anchor_diff", fake_detect)

    frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.04)
    frames_mod._cached_anchor(tmp_path / "v.mkv", out, 0.02, 0.0015, 0.06)
    assert calls == [0.04, 0.06], "임계가 바뀌면 재검출"
