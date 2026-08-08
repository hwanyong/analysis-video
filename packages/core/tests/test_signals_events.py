"""측정(signals)과 판단(events)의 분리, 그리고 세 신호의 상호보완.

여기서 못박는 것 둘:
1. 측정은 **오버레이 띠를 뺀 본문**에서만 한다. 안 그러면 번인 자막이 화면
   전환으로 계상된다 — 실측 video3에서 컷 임계 0.02일 때 봉우리 129개 중
   90개(70%)가 자막이었다.
2. 사건은 **봉우리 자체**이고 촬영 지점은 사건 주변에서만 고른다. 이전 구조는
   임계를 넘으면 걸어 잠그고 잦아들 때까지 기다렸다가 찍어, 촬영 지점이
   사건에서 최대 2.54초까지 밀려났다(video1).
"""
import numpy as np
import pytest

from analysis_video.detect import events, signals


def _frames(seq):
    return iter([(i / 30.0, f.astype(np.float32)) for i, f in enumerate(seq)])


@pytest.fixture
def stub(monkeypatch):
    def _set(seq):
        monkeypatch.setattr(signals.media, "get_fps", lambda p: 30.0)
        monkeypatch.setattr(signals.media, "decode_gray_frames", lambda p, **kw: _frames(seq))
    return _set


def _blank(h=36, w=64):
    return np.zeros((h, w), dtype=np.float32)


def _with(base, rows, value=90.0, cols=None):
    f = base.copy()
    f[rows[0]:rows[1], :cols if cols is not None else base.shape[1]] = value
    return f


# ---------- 측정: 띠를 빼야 자막이 신호가 되지 않는다 ----------

def test_overlay_band_is_excluded_from_measurement(stub, tmp_path):
    """아래 3행(자막)만 매 프레임 바뀌는 영상. 띠를 빼면 신호가 0이어야 한다."""
    a = _blank()
    seq = [a if i % 2 else _with(a, (33, 36)) for i in range(12)]
    stub(seq)

    full = signals.measure(tmp_path / "v.mkv", (0.0, 1.0), anchor_threshold=0.02,
                           rate_threshold=0.0015, cut_area_threshold=0.02)
    assert full["area_series"].max() > 0.02, "띠를 포함하면 자막이 컷으로 잡힌다"

    body = signals.measure(tmp_path / "v.mkv", (0.0, 33 / 36), anchor_threshold=0.02,
                           rate_threshold=0.0015, cut_area_threshold=0.02)
    assert body["area_series"].max() == 0.0, "본문만 보면 자막은 신호가 아니다"
    assert events.find(body, anchor_threshold=0.02, rate_threshold=0.0015,
                       cut_area_threshold=0.02) == []


def test_scan_rows_finds_the_busy_band(stub, tmp_path):
    a = _blank()
    stub([a if i % 2 else _with(a, (33, 36)) for i in range(12)])
    freq = signals.scan_rows(tmp_path / "v.mkv")
    assert len(freq) == 36
    assert freq[:33].max() == 0.0 and freq[33:].min() > 0.0


# ---------- 판단: 사건은 봉우리, 촬영은 그 주변 ----------

def _measured(rate, area=None, anchor=None, fps=30.0):
    n = len(rate)
    return {"fps": fps, "band": (0.0, 1.0),
            "time_series": np.arange(n) / fps,
            "rate_series": np.array(rate, dtype=float),
            "area_series": np.array(area if area is not None else [0.0] * n, dtype=float),
            "anchor_series": np.array(anchor if anchor is not None else [0.0] * n, dtype=float)}


def test_capture_points_bracket_the_event():
    area = [0.0] * 6 + [0.10] + [0.0] * 6
    rate = [0.0] * 5 + [0.02, 0.05, 0.02] + [0.0] * 5
    ev = events.find(_measured(rate, area), anchor_threshold=0.02,
                     rate_threshold=0.0015, cut_area_threshold=0.02)
    assert len(ev) == 1
    e = ev[0]
    assert e["index"] == 6 and e["signals"] == ["cut", "rate"]
    assert e["before_idx"] == 4, "변화가 시작되기 전 마지막 조용한 프레임"
    assert e["after_idx"] == 8, "변화가 끝난 뒤 첫 조용한 프레임"


def test_three_signals_are_complementary():
    """셋이 서로 다른 것을 집어야 합집합이 의미가 있다."""
    n = 70                                    # 봉우리 간격 > 병합창(0.5초=15프레임)
    area = [0.0] * n; area[5] = 0.10                     # 컷만
    anchor = [0.0] * n; anchor[30] = 0.05                # 점진 누적만
    rate = [0.0] * n; rate[55] = 0.05                    # 큰 스파이크만
    ev = events.find(_measured(rate, area, anchor), anchor_threshold=0.02,
                     rate_threshold=0.0015, cut_area_threshold=0.02)
    assert [e["signals"] for e in ev] == [["cut"], ["anchor"], ["rate"]]
    assert [e["index"] for e in ev] == [5, 30, 55]


def test_nearby_peaks_merge_into_one_event():
    """한 번의 전환이 세 신호에 몇 프레임씩 어긋나 봉우리를 낸다 — 하나로 봐야 한다."""
    n = 30
    area = [0.0] * n; area[10] = 0.10
    anchor = [0.0] * n; anchor[12] = 0.05
    rate = [0.0] * n; rate[11] = 0.05
    ev = events.find(_measured(rate, area, anchor), anchor_threshold=0.02,
                     rate_threshold=0.0015, cut_area_threshold=0.02)
    assert len(ev) == 1
    assert ev[0]["signals"] == ["anchor", "cut", "rate"]
    assert ev[0]["index"] == 10, "대표는 가장 이른 봉우리"


def test_capture_never_crosses_a_neighbouring_event():
    """이웃 사건을 넘어가면 다른 화면을 찍는다. 조용한 프레임이 없어도 넘지 않는다."""
    n = 50
    area = [0.0] * n; area[10] = 0.10; area[35] = 0.10
    rate = [0.01] * n                                     # 어디도 잦아들지 않는다
    ev = events.find(_measured(rate, area), anchor_threshold=0.02,
                     rate_threshold=0.0015, cut_area_threshold=0.02)
    assert len(ev) == 2
    assert 10 <= ev[0]["after_idx"] <= 35
    assert 10 <= ev[1]["before_idx"] <= 35


def test_settle_search_is_time_bounded():
    """계속 움직이는 영상에서 멀리까지 찾아가면 다른 화면을 찍는다."""
    n = 200
    area = [0.0] * n; area[100] = 0.10
    rate = [0.01] * n; rate[0] = rate[-1] = 0.0          # 조용한 곳은 양 끝뿐
    ev = events.find(_measured(rate, area), anchor_threshold=0.02,
                     rate_threshold=0.0015, cut_area_threshold=0.02,
                     settle_limit=0.5)
    e = ev[0]
    assert abs(e["before_time"] - e["time"]) <= 0.5
    assert abs(e["after_time"] - e["time"]) <= 0.5


def test_empty_input_is_safe():
    assert events.find(_measured([]), anchor_threshold=0.02, rate_threshold=0.0015,
                       cut_area_threshold=0.02) == []
