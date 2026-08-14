"""읽기 예산 — context.md가 가리키는 것과 그 비용이 사실이어야 한다.

이 산출물의 소비자는 컨텍스트 창이 있는 모델이다. 그런데 전에는 장수만 말하고
비용을 말하지 않았고, 실측하면 그 침묵이 비쌌다: 원본 해상도로 저장한 프레임이
장당 1,843토큰이라 1시간 강의가 1.08M~3.95M 토큰이었다 — 여섯 편 전부 백만을 넘는다.

여기서 잠그는 것 셋.

1. **비용 산정이 맞는가** — 틀리면 예산 판단 전체가 틀린다.
2. **context.md가 가리키는 파일이 실재하는가** — 사본 디렉터리를 규칙으로 만들기
   때문에(같은 파일명, 다른 디렉터리) 규칙이 어긋나면 전 항목이 한꺼번에 깨진다.
3. **탈락한 후보의 사본이 남지 않는가** — read/의 장수가 곧 "다 열면 얼마인가"의
   분모다. 아무도 참조하지 않는 사본이 섞이면 그 숫자가 거짓이 된다.
"""
from pathlib import Path

import pytest
from PIL import Image

from analysis_video import budget


# ---------- 산정 ----------

@pytest.mark.parametrize("size,expected", [
    ((768, 432), 442),      # 읽기용 사본의 실제 크기
    ((1024, 576), 786),
    ((1920, 1080), 1843),   # 원본 — 긴 변이 1568을 넘어 한 번 더 줄어든 뒤 계산된다
    ((100, 100), 13),       # 작은 그림은 축소되지 않는다
])
def test_image_tokens_follows_the_documented_rule(size, expected):
    assert budget.image_tokens(*size) == expected


def test_the_reduced_copy_is_never_upscaled(tmp_path):
    """없는 화소를 만들어 내면 토큰만 늘고 읽히는 것은 그대로다."""
    assert budget.reduced_size(400, 300, 768) == (400, 300)
    assert budget.reduced_size(1920, 1080, 768) == (768, 432)


def test_read_path_keeps_the_filename_and_swaps_the_directory():
    assert budget.read_path("frames/scene_007_t0012.30.jpg") == \
        "read/scene_007_t0012.30.jpg"


def test_summary_carries_both_the_count_and_the_cost():
    got = budget.summary([(768, 432)] * 3)
    assert got["count"] == 3
    assert got["tokens"] == 442 * 3
    assert got["read_dir"] == budget.READ_DIRNAME
    assert got["rule"], "규칙 이름이 없으면 다른 모델의 소비자가 값을 걸러낼 수 없다"


def test_cost_is_derived_from_the_summary_not_recomputed():
    """metadata를 열지 않고도 비용을 알아야 한다 — 열지 말지를 정하는 값이라
    그것을 알려고 파일을 하나 더 여는 것은 순서가 뒤집힌 것이다."""
    images = budget.summary([(768, 432)] * 5)
    assert budget.cost(images) == {"images": 5, "image_tokens": 442 * 5,
                                   "rule": images["rule"]}


# ---------- 산출물과의 계약 ----------

# 채택 경로(사본이 채택본마다 한 장 생기고 images가 그것을 센다)는
# test_frames_screen_end.py::test_read_copies_are_made_and_counted가 덮는다.
# 여기서는 그 반대편, **탈락한 후보의 사본이 남지 않는가**를 본다 — 사본을 추출과
# 같은 디코드에서 만들기 때문에 탈락 판정은 그 뒤에 내려지고, 지우는 것을 잊으면
# 아무도 참조하지 않는 파일이 분모에 남는다.

def _blank_pipeline(monkeypatch, tmp_path, content: bool):
    """후보 하나짜리 검출 — content=False면 내용량 게이트에서 탈락한다."""
    import numpy as np

    from analysis_video import frames as frames_mod

    fps = 30.0
    monkeypatch.setattr(frames_mod, "_cached_signals", lambda vp, cd: {
        "fps": fps, "band": (0.0, 1.0),
        "anchor_series": np.zeros(60), "rate_series": np.zeros(60),
        "area_series": np.zeros(60), "time_series": np.arange(60) / fps,
        "row_change_freq": np.zeros(36)})
    monkeypatch.setattr(frames_mod.events_mod, "find", lambda m, **kw: [])
    monkeypatch.setattr(frames_mod, "_cached_adaptive", lambda vp, od, dur, ft: [])
    monkeypatch.setattr(frames_mod.media, "get_duration", lambda p: 10.0)
    monkeypatch.setattr(frames_mod.adaptive, "pick_stable_time",
                        lambda p, t, d, **kw: t + 0.5)

    def fake_extract(video_path, t, out_path, quality=90, reduced=None):
        a = np.zeros((540, 960), dtype=np.uint8)
        if content:
            a[120:360, 180:720] = 255
        img = Image.fromarray(a, mode="L").convert("RGB")
        img.save(out_path, quality=quality)
        if reduced is None:
            return img.size
        dst, long_edge = reduced
        size = budget.reduced_size(img.width, img.height, long_edge)
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.resize(size).save(dst, quality=quality)
        return size

    monkeypatch.setattr(frames_mod.media, "extract_frame", fake_extract)
    return frames_mod


def test_a_rejected_candidate_leaves_no_read_copy(monkeypatch, tmp_path):
    """read/의 장수가 곧 '다 열면 얼마인가'의 분모다 — 거짓이 되면 안 된다."""
    frames_mod = _blank_pipeline(monkeypatch, tmp_path, content=False)
    out = tmp_path / "a"
    r = frames_mod.build_frames(tmp_path / "v.mkv", out)

    assert all(c["status"] == "rejected" for c in r["records"]), "픽스처 전제가 깨졌다"
    assert list((out / budget.READ_DIRNAME).iterdir()) == [], \
        "탈락본의 사본이 남으면 비용 산정의 분모가 거짓이 된다"
    assert r["images"]["count"] == 0 and r["images"]["tokens"] == 0


def test_an_accepted_candidate_keeps_both_resolutions(monkeypatch, tmp_path):
    """사본은 원본의 대체가 아니라 추가다 — 정밀 확인·GUI는 원본을 본다."""
    frames_mod = _blank_pipeline(monkeypatch, tmp_path, content=True)
    out = tmp_path / "a"
    r = frames_mod.build_frames(tmp_path / "v.mkv", out)
    accepted = [c for c in r["records"] if c["status"] == "accepted"]

    assert accepted, "픽스처 전제가 깨졌다"
    name = Path(accepted[0]["image"]).name
    assert Image.open(out / "frames" / name).size == (960, 540)
    assert Image.open(out / budget.READ_DIRNAME / name).size == (768, 432)
    # context.md가 만드는 경로 규칙이 실제 배치와 맞는가
    ref = budget.read_path(accepted[0]["image"], r["images"]["read_dir"])
    assert (out / ref).exists(), f"context.md가 가리킬 {ref} 가 없다"
