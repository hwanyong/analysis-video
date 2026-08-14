"""화면의 끝 상태도 후보여야 한다 + 측정 캐시는 스키마로 검증한다.

사건의 직후 촬영 지점은 곧 **새 화면이 시작된 순간**이다.
그 뒤 수십 초에 걸쳐 채워지는 판서는 어디에도 안 남는다 — 실측 video3의 한
화면은 105초 동안 885자를 설명하며 페이지를 채우는데, 거기 붙은 이미지는
거의 빈 페이지였고 완성된 페이지는 대사가 딴 얘기인 다음 블록에 가 있었다.

끝만 잡는 것도 답이 아니다 — "무엇에서 무엇으로 갔는가"가 사라진다.
그래서 둘 다 내되, 끝 상태는 **그 화면의 시작과 견줘** 달라졌을 때만 낸다.
"""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from analysis_video import budget
from analysis_video import frames as frames_mod

FPS = 30.0


def _measured(**over):
    base = {
        "fps": FPS, "band": (0.0, 1.0),
        # 앵커가 옮겨 간 프레임 번호들. signals.measure가 원래부터 내던 값이고,
        # 캐시가 이걸 흘리는 바람에 debug-report가 매번 KeyError로 죽었다 —
        # 대역이 이 칸을 빼면 그 회귀를 다시 못 잡는다.
        "anchor_resets": [0, 12, 40],
        "anchor_series": np.zeros(60), "rate_series": np.zeros(60),
        "area_series": np.zeros(60), "time_series": np.arange(60) / FPS,
        "row_change_freq": np.zeros(36),
    }
    base.update(over)
    return base


def _event(before_idx=30, after_idx=45, index=40):
    """시각은 첫 화면 시드(w_start+0.5초=0.5초)보다 뒤여야 이 화면의 '끝'이 된다."""
    return {"index": index, "time": index / FPS, "signals": ["cut"],
            "before_idx": before_idx, "before_time": before_idx / FPS,
            "after_idx": after_idx, "after_time": after_idx / FPS}


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """검출·추출·중복판정을 대역으로 세우고 후보 생성만 남긴다."""
    monkeypatch.setattr(frames_mod, "_cached_signals", lambda vp, cd: _measured())
    monkeypatch.setattr(frames_mod.events_mod, "find", lambda m, **kw: [_event()])
    monkeypatch.setattr(frames_mod, "_cached_adaptive", lambda vp, od, dur, ft: [])
    monkeypatch.setattr(frames_mod.media, "get_duration", lambda p: 10.0)
    monkeypatch.setattr(frames_mod.adaptive, "pick_stable_time",
                        lambda p, t, d, **kw: t + 0.5)

    # 추출은 **진짜 이미지**를 쓴다 — 내용량 게이트가 실제로 픽셀을 읽기 때문에
    # 더미 바이트를 쓰면 게이트가 예외로 죽고 테스트는 그걸 못 본다.
    #
    # 읽기용 사본까지 같은 디코드에서 낸다(reduced=(경로, 긴 변), 반환은 그 사본의
    # 크기 — 실패하면 None). 대역이 사본을 안 쓰고 True만 돌려주면 게이트가 세는
    # 장수·토큰이 실제 파일과 무관해져, read/가 통째로 비어도 테스트가 통과한다.
    def fake_extract(video_path, t, out_path, quality=90, reduced=None):
        a = np.zeros((540, 960), dtype=np.uint8)   # 원본 해상도 자리
        a[120:360, 180:720] = 255  # 배경과 뚜렷이 다른 영역 = 내용 있음
        img = Image.fromarray(a)
        img.save(out_path)
        if reduced is None:
            return img.size
        dst, long_edge = reduced
        size = budget.reduced_size(img.width, img.height, long_edge)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.resize(size).save(dst)
        return size
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
    assert ("screen-start",) in by_source, "새 화면 후보가 없다"
    end, trig = by_source[("screen-end",)], by_source[("screen-start",)]
    assert end["time"] == pytest.approx(30 / FPS), "events가 준 before 자리를 써야 한다"
    assert end["time"] < trig["time"], "끝 상태가 새 화면보다 앞선다"


def test_screen_end_uses_the_events_capture_point(monkeypatch, stub_pipeline,
                                                  tmp_path):
    """촬영 지점은 events가 정한다 — frames가 자기 나름대로 다시 고르면
    "사건 주변에서만 고른다"는 보장이 깨진다."""
    monkeypatch.setattr(frames_mod.events_mod, "find",
                        lambda m, **kw: [_event(before_idx=25)])
    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "s.analysis")
    end = [r for r in result["records"] if r["sources"] == ["screen-end"]][0]
    assert end["time"] == pytest.approx(25 / FPS), "events가 준 자리를 안 쓰고 있다"


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
    assert ("screen-start",) in sources, "새 화면 후보는 그대로 남는다"


def test_screen_end_skipped_when_it_would_precede_the_screen(monkeypatch,
                                                             stub_pipeline, tmp_path):
    """촬영 지점이 화면 시작보다 앞으로 가면 그건 이 화면의 끝이 아니다."""
    monkeypatch.setattr(frames_mod.events_mod, "find",
                        lambda m, **kw: [_event(before_idx=3, after_idx=6, index=4)])
    result = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "e.analysis")
    assert ("screen-end",) not in [tuple(r["sources"]) for r in result["records"]]


def test_gate_params_are_recorded(stub_pipeline, tmp_path):
    r = frames_mod.build_frames(tmp_path / "v.mkv", tmp_path / "p.analysis")
    p = r["params"]
    assert p["pair_dup_threshold"] == 0.93
    assert p["blank_area_threshold"] == 0.001
    assert p["body_band"] == [0.0, 1.0], "띠가 없으면 전체가 본문"
    # 사본의 긴 변도 판정 파라미터다 — 이 값을 바꾸면 사본을 다시 만들어야 하므로,
    # 산출물이 어떤 값으로 만들어졌는지 기록에 남아야 되짚을 수 있다.
    assert p["read_long_edge"] == 768


def test_read_copies_are_made_and_counted(stub_pipeline, tmp_path):
    """읽기용 사본은 **채택된 프레임마다 한 장**, 파일명은 원본과 같다.

    images 블록의 count는 곧 "다 열면 얼마인가"의 분모다. 실제로 놓인 파일보다
    많이 세면 context.md가 없는 그림을 가리키고, 적게 세면 비용이 축소 보고된다."""
    out = tmp_path / "r.analysis"
    r = frames_mod.build_frames(tmp_path / "v.mkv", out)
    accepted = [c for c in r["records"] if c["status"] == "accepted"]

    assert sorted(p.name for p in (out / "read").iterdir()) == \
        sorted(Path(c["image"]).name for c in accepted)
    # 사본은 원본이 아니라 줄인 것이다 — 960x540 → 긴 변 768 → 768x432
    assert Image.open(next((out / "read").iterdir())).size == (768, 432)
    assert Image.open(out / accepted[0]["image"]).size == (960, 540), \
        "원본 해상도는 frames/에 그대로 남는다"

    images = r["images"]
    assert images["count"] == len(accepted) == 3
    assert images["long_edge"] == 768 and images["read_dir"] == "read"
    assert images["tokens"] == 442 * len(accepted), "768x432 한 장 = 442토큰"
    assert images["rule"], "규칙 이름이 값과 함께 가야 다른 모델을 쓰는 쪽이 무시할 수 있다"


def test_signals_cache_is_schema_guarded(monkeypatch, tmp_path):
    """구 캐시는 키 구성이 달라 조회하면 KeyError로 죽는다. 스키마를 먼저 봐서
    조용히 버리고 다시 측정해야 한다."""
    out = tmp_path / "c.analysis"
    out.mkdir()
    np.savez_compressed(out / "detect_signals.npz", cum_series=np.zeros(3), fps=FPS)

    calls = []
    monkeypatch.setattr(frames_mod.signals, "scan_rows",
                        lambda vp: (calls.append("scan"), np.zeros(36))[1])
    monkeypatch.setattr(frames_mod.signals, "measure",
                        lambda vp, band, **kw: (calls.append("measure"), _measured())[1])

    r = frames_mod._cached_signals(tmp_path / "v.mkv", out)
    assert calls == ["scan", "measure"], "구 캐시를 버리고 다시 측정해야 한다"
    assert "area_series" in r and "band" in r

    calls.clear()
    again = frames_mod._cached_signals(tmp_path / "v.mkv", out)
    assert not calls, "새로 쓴 캐시는 재사용해야 한다"
    assert again["band"] == (0.0, 1.0)
    # 캐시를 왕복해도 앵커 이동 지점이 살아 있어야 한다. debug-report가 이 값으로
    # "기준이 바뀐 지점"을 그리는데, 캐시가 흘리면 그릴 것이 없어진다.
    assert list(again["anchor_resets"]) == [0, 12, 40]


def test_thresholds_do_not_invalidate_the_measurement_cache(monkeypatch, tmp_path):
    """임계는 판단의 소관이다. 바꿨다고 전 프레임을 다시 디코드하면 2단계로
    나눈 의미가 없다."""
    out = tmp_path / "d.analysis"
    out.mkdir()
    calls = []
    monkeypatch.setattr(frames_mod.signals, "scan_rows",
                        lambda vp: (calls.append("scan"), np.zeros(36))[1])
    monkeypatch.setattr(frames_mod.signals, "measure",
                        lambda vp, band, **kw: (calls.append("measure"), _measured())[1])

    frames_mod._cached_signals(tmp_path / "v.mkv", out)
    assert len(calls) == 2
    calls.clear()
    frames_mod._cached_signals(tmp_path / "v.mkv", out)
    assert calls == [], "측정 캐시는 임계와 무관하게 살아 있어야 한다"


def test_cli_thresholds_reach_build_frames(monkeypatch, tmp_path):
    """CLI로 준 기준선이 실제 판단까지 닿아야 한다. 파서에만 붙어 있고
    build_frames로 안 넘어가면 옵션이 조용히 무시된다."""
    from analysis_video import cli

    seen = {}
    monkeypatch.setattr(cli.frames_mod, "build_frames",
                        lambda vp, unit, **kw: seen.update(kw) or {
                            "records": [], "duration": 1.0, "fps": 30.0,
                            "window": [0.0, 1.0], "events": [], "params": {}})
    p = cli.build_parser()
    args = p.parse_args(["frames", "v.mkv", "--anchor-threshold", "0.017",
                         "--cut-area-threshold", "0.01", "--rate-threshold", "0.003",
                         "--read-long-edge", "512"])
    passed = cli._thresholds(args)
    assert passed == {"anchor_threshold": 0.017, "rate_threshold": 0.003,
                      "cut_area_threshold": 0.01, "read_long_edge": 512}
    # 사본의 긴 변은 판정선이 아니라 **픽셀 수**다. 임계 셋과 같이 float으로
    # 파싱하면 PIL이 크기로 못 받는다.
    assert isinstance(passed["read_long_edge"], int)


def test_cli_defaults_come_from_the_library():
    """기본값을 CLI가 따로 적으면 한쪽만 고쳤을 때 '기본값이라 표시된 값'과
    '실제로 쓰이는 값'이 갈린다."""
    import inspect

    from analysis_video import cli

    sig = inspect.signature(frames_mod.build_frames).parameters
    for _flag, dest, default, _help in cli.THRESHOLDS:
        assert sig[dest].default == default, f"{dest}의 기본값이 두 군데서 갈렸다"
    assert cli.frames_mod.DEFAULT_CUT_AREA_THRESHOLD == 0.002
    # THRESHOLDS 목록 밖에 있는 --read-long-edge도 같은 규칙을 따른다 —
    # 파서와 라이브러리가 각자 숫자를 적으면 갈릴 자리가 하나 더 생긴다.
    assert sig["read_long_edge"].default == budget.READ_LONG_EDGE == 768

    # 권장 임계는 **기본값이 아니다**. 실측상 이미지를 17~43% 줄이지만 그건
    # 예산이 모자랄 때 고르는 값이고, 플래그 없이 부른 실행은 지금과 같아야 한다.
    assert frames_mod.RECOMMENDED_CUT_AREA_THRESHOLD == 0.010
    assert sig["cut_area_threshold"].default == frames_mod.DEFAULT_CUT_AREA_THRESHOLD
    assert frames_mod.RECOMMENDED_CUT_AREA_THRESHOLD != \
        frames_mod.DEFAULT_CUT_AREA_THRESHOLD
