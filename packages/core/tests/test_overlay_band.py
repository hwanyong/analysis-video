"""고정 오버레이 띠 산출과 내용량 판정 — 게이트가 무엇을 보는가.

이 두 지표가 이전 판정(전역 SSIM·평균 밝기)을 대체한 이유는 하나다:
전면 평균은 **작지만 결정적인 차이**에 눈이 멀고, 자막처럼 크지만 무의미한
차이에는 과민하다. 검출기에서 평균절대차를 컷 면적으로 바꾼 것과 같은 교정이다.
"""
import numpy as np

from analysis_video.detect import overlay


def _freq(n=36, body=0.03, bottom_rows=3, bottom=0.20):
    f = np.full(n, body)
    if bottom_rows:
        f[-bottom_rows:] = bottom
    return f


def test_bottom_subtitle_band_is_found():
    """실측 video3: 본문 0.03 대 아래 3행 0.18~0.23."""
    lo, hi = overlay.body_band(_freq())
    assert lo == 0.0
    assert 0.85 < hi < 1.0, f"아래 띠를 못 잘랐다: {hi}"


def test_no_band_when_nothing_stands_out():
    """자막 없는 영상(video1·video2)은 마스크가 없어야 한다 — 없는 띠를 만들어
    잘라내면 내용을 잃는다."""
    assert overlay.body_band(_freq(bottom_rows=0)) == overlay.FULL


def test_busy_middle_is_not_a_band():
    """한복판이 자주 바뀌는 것은 오버레이가 아니라 애니메이션이다(video1이 이
    경우 — 중앙 빈도가 가장 높다). 가장자리에 붙은 것만 띠로 인정한다."""
    f = np.full(36, 0.02)
    f[15:20] = 0.5
    assert overlay.body_band(f) == overlay.FULL


def test_band_wider_than_a_fifth_is_content_not_overlay():
    f = np.full(36, 0.02)
    f[-12:] = 0.5           # 화면의 1/3 — 자막이라기엔 너무 넓다
    assert overlay.body_band(f) == overlay.FULL


def test_crop_only_touches_rows():
    img = np.arange(100 * 7, dtype=np.uint8).reshape(100, 7)
    out = overlay.crop(img, (0.0, 0.9))
    assert out.shape == (90, 7)
    assert overlay.crop(img, overlay.FULL).shape == img.shape


def test_content_area_separates_blank_from_dark_content():
    """어두운 테마에서 평균 밝기는 내용 유무를 구분하지 못한다 — 실측 video1의
    채택(5.17~5.33)과 탈락(4.37~4.98)은 연속이고 사이에 골이 없었다."""
    blank = np.zeros((90, 160), dtype=np.uint8)
    dark_text = blank.copy()
    dark_text[40:44, 20:80] = 200        # 검은 배경 위 흰 글자 조금

    assert overlay.content_area(blank) == 0.0
    assert overlay.content_area(dark_text) > 0.001
    # 평균 밝기로는 둘 다 어둡다 — 그게 옛 게이트가 내용을 자르던 이유다
    assert dark_text.mean() < 5.0


def test_content_area_is_background_relative():
    """배경이 흰 슬라이드에서도 같은 질문에 답해야 한다."""
    white = np.full((90, 160), 235, dtype=np.uint8)
    with_text = white.copy()
    with_text[40:46, 20:80] = 20
    assert overlay.content_area(white) == 0.0
    assert overlay.content_area(with_text) > 0.001


def test_real_measured_scale_is_handled():
    """빈도는 인접 프레임 쌍 기준이라 값이 작다. 표본 간격(0.5초) 기준으로 잡은
    하한을 그대로 쓰면 실제 자막 띠가 하한에 걸려 통째로 안 잡힌다 — 실제로
    한 번 그렇게 놓쳤다. 실측값 자체를 못박는다."""
    v3 = np.full(36, 0.0009)
    v3[33:] = [0.013, 0.015, 0.014]
    lo, hi = overlay.body_band(v3)
    assert (lo, hi) != overlay.FULL, "video3 자막 띠를 못 잡았다"
    assert hi == 33 / 36

    # 자막 없는 두 영상은 최대치가 중앙값의 2.2~2.6배라 걸러져야 한다
    v1 = np.full(36, 0.0047); v1[11:16] = 0.012
    v2 = np.full(36, 0.0040); v2[14] = 0.0089
    assert overlay.body_band(v1) == overlay.FULL
    assert overlay.body_band(v2) == overlay.FULL
