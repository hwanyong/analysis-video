"""전환 시작 판정은 anchor_diff(점진 누적)와 cut_area(컷)의 OR여야 한다.

anchor_diff 단독으로는 컷을 놓친다. 화면 전체를 갈아도 실제로 색이 바뀌는
픽셀은 판서 영상 기준 7% 남짓이고 나머지 93%는 배경↔배경이라 차이 0이다.
그 0들이 평균을 약 13배 희석해 완전한 페이지 교체조차 0.018~0.027밖에 못 내는데
임계가 0.02라 겹친다. 실측 피해: video3 첫 6초에 페이지가 3번 바뀌는데 트리거는
1번뿐이었고(t=1.367 cum=0.0183, t=2.733 cum=0.0190 → 둘 다 미달), 세 영상에서
명백한 컷의 29~52%가 이렇게 샜다.

여기 쓰는 합성 프레임은 그 조건을 그대로 재현한다 — 화면 일부만 확 바뀌어
평균은 임계 아래인데 면적은 확실히 넘는 상황.
"""
import numpy as np
import pytest

from analysis_video.detect import anchor


def _frames(seq):
    """(시각, 그레이 배열) 스트림 — decode_gray_frames 대역."""
    return iter([(i / 30.0, f.astype(np.float32)) for i, f in enumerate(seq)])


def _blank():
    return np.zeros((36, 64), dtype=np.float32)


# 면적으로는 컷이지만 평균으로는 임계 미달이 되는 변화폭. CUT_DELTA(25)보다 커야
# 면적에 계상되고, (임계 0.02 / 면적 0.056) × 255 = 91단계보다 작아야 평균이 미달이다.
# 실측 판서 전환의 잉크↔배경 전이(약 43단계)와 같은 대역.
CUT_VALUE = 40.0


def _patch(base, rows, value=CUT_VALUE, cols=None):
    """base의 위쪽 rows줄(가로 cols칸)을 value로 칠한 새 프레임."""
    f = base.copy()
    f[:rows, :cols if cols is not None else base.shape[1]] = value
    return f


@pytest.fixture
def stub(monkeypatch):
    def apply(seq):
        monkeypatch.setattr(anchor.media, "get_fps", lambda p: 30.0)
        monkeypatch.setattr(anchor.media, "decode_gray_frames", lambda p: _frames(seq))
    return apply


def test_cut_below_anchor_threshold_is_detected(stub, tmp_path):
    """평균은 임계 미달이지만 면적이 넘는 변화 = 컷. anchor_diff만 보면 놓친다."""
    a = _blank()
    b = _patch(a, 2)          # 36줄 중 2줄(5.6%)만 흰색으로 → 면적 0.056
    seq = [a] * 5 + [b] * 5
    stub(seq)

    r = anchor.transition_aware_anchor_diff(tmp_path / "v.mkv")
    peak = float(r["anchor_series"].max())
    assert peak < r["anchor_threshold"], (
        f"이 합성 입력은 anchor_diff가 임계 아래여야 의미가 있다 (실제 {peak:.5f})")
    assert float(r["area_series"].max()) > r["cut_area_threshold"]
    assert len(r["events"]) == 1, "컷 면적으로 잡아내야 한다"
    assert r["events"][0]["transition_start_idx"] == 5


def test_cut_detection_can_be_disabled_by_threshold(stub, tmp_path):
    """면적 임계를 1.0(=불가능)으로 두면 구 동작 그대로 — 같은 입력을 놓친다."""
    a = _blank()
    seq = [a] * 5 + [_patch(a, 2)] * 5
    stub(seq)
    r = anchor.transition_aware_anchor_diff(tmp_path / "v.mkv", cut_area_threshold=1.0)
    assert r["events"] == [], "면적 신호가 없으면 놓치는 것이 구 동작이었다"


def test_transition_start_latches_until_stable(stub, tmp_path):
    """전환이 시작되면 시작 조건을 재검사하지 않는다.

    래치가 없으면 컷 프레임에서만 면적이 튀고 다음 프레임엔 가라앉으므로,
    anchor_diff가 임계 아래인 컷은 영영 트리거하지 못한다."""
    a = _blank()
    b = _patch(a, 2)
    c = _patch(a, 2, value=CUT_VALUE + 1)   # b에서 1단계만 더 — 면적엔 안 잡힌다
    seq = [a] * 5 + [b, c] + [c] * 4
    stub(seq)

    r = anchor.transition_aware_anchor_diff(tmp_path / "v.mkv")
    assert len(r["events"]) == 1
    e = r["events"][0]
    assert e["transition_start_idx"] == 5, "면적이 튄 프레임에서 시작"
    assert e["trigger_idx"] > e["transition_start_idx"], "안정된 뒤에 트리거"
    assert float(r["area_series"][e["trigger_idx"]]) <= r["cut_area_threshold"], (
        "트리거 프레임에서는 면적이 이미 가라앉아 있다 — 래치 없이는 도달 불가")


def test_gradual_accumulation_still_triggers_via_anchor_diff(stub, tmp_path):
    """면적으로는 절대 안 잡히는 점진 변화도 anchor_diff가 잡아야 한다.

    매 프레임 반 줄씩 칠하면 프레임당 면적은 (1/36)×(1/2)=1.4%라 컷 임계
    0.02 미달인데, 앵커와의 거리는 계속 벌어진다."""
    a = _blank()
    half = 32  # 64칸 중 절반 → 한 줄을 다 칠하면 2.8%로 임계를 넘어버린다
    seq = [a] + [_patch(a, n, cols=half) for n in range(1, 12)] \
        + [_patch(a, 11, cols=half)] * 3
    stub(seq)

    r = anchor.transition_aware_anchor_diff(tmp_path / "v.mkv")
    assert float(r["area_series"].max()) <= r["cut_area_threshold"], (
        "이 입력은 면적 신호가 없어야 의미가 있다")
    assert len(r["events"]) >= 1, "점진 누적은 anchor_diff의 몫"


def test_empty_video_returns_all_series(stub, tmp_path):
    """프레임이 없어도 소비자가 기대하는 키가 전부 있어야 한다(KeyError 금지)."""
    stub([])
    r = anchor.transition_aware_anchor_diff(tmp_path / "v.mkv")
    for key in ("anchor_series", "rate_series", "area_series", "time_series",
                "anchor_threshold", "rate_threshold", "cut_area_threshold"):
        assert key in r
    assert r["events"] == []
