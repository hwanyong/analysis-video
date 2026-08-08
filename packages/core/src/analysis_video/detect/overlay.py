"""고정 오버레이 띠(번인 자막·배너) 산출 — "어디를 보지 말아야 하는가".

강의 영상에는 화면 가장자리에 내용과 무관하게 계속 바뀌는 띠가 있다(번인 자막이
대표적). 이 띠는 두 판정을 동시에 망가뜨린다:

- **중복 판정이 새는 쪽**: 같은 화면인데 자막만 달라 "다르다"고 본다.
- **중복 판정이 과한 쪽**: 자막 변화가 차이의 대부분을 차지해, 본문이 실제로
  달라도 전체 차이에 묻힌다. 실측 video3에서 목차 재등장(정당한 병합)의 차이는
  1.47%, 서로 다른 판서 페이지(병합하면 안 되는 것)는 1.30% — 면적만으로는
  순서가 뒤집혀 있다. 그런데 아래 12%를 빼면 0.00% 대 0.44%로 갈라진다.
  **가르는 것은 차이의 양이 아니라 위치였다.**

띠는 영상마다 다르므로 박아 넣지 않고 산출한다: 자막은 몇 초마다, 내용은 몇십 초
마다 바뀐다 — 행별 변화 빈도가 본문보다 확연히 높은 **가장자리 연속 구간**이 그것이다.
실측 video3 아래 8%(빈도 0.18~0.23 대 본문 0.03), video1·video2는 자막이 없어
띠 없음으로 나온다. 화면 한복판이 자주 바뀌는 것은 그냥 애니메이션이므로
가장자리에 붙은 띠만 인정한다(video1이 이 경우 — 중앙 빈도가 가장 높다).
"""
import numpy as np

# 한 행에서 이 비율 넘게 픽셀이 바뀌면 "이 행이 바뀌었다"로 센다.
ROW_HIT_RATIO = 0.02
# 본문 중앙값의 몇 배부터 이상 빈발로 볼 것인가.
HOT_MULTIPLE = 4.0
# 절대 하한 — 거의 정지한 영상에서는 중앙값이 0에 수렴해 4배 조건이 무의미해진다
# (0의 4배는 0이라 잡음 한 톨도 '띠'가 된다). 빈도는 **인접 프레임** 쌍 기준이라
# 자막 한 번 교체는 30fps에서 프레임 하나에만 잡힌다 — 실측 스케일이 그만큼 작다:
# video3 자막 행 0.013~0.015 대 본문 중앙값 0.0009, 자막 없는 video1·video2는
# 최대치가 0.012·0.0089(중앙값의 2.2~2.6배로 4배 조건에서 이미 걸러진다).
MIN_HOT = 0.005
# 가장자리 띠가 화면의 이 비율을 넘으면 오버레이가 아니라 내용이다.
MAX_BAND = 0.20

FULL: tuple[float, float] = (0.0, 1.0)

# 두 그림을 견줄 때 "이 픽셀은 눈에 띄게 달라졌다"로 볼 그레이 단계 차이.
# anchor.CUT_DELTA와 같은 값·같은 뜻이다 — 코덱 잡음보다 크고 잉크↔배경보다 작다.
CHANGE_DELTA = 25.0


def body_band(row_freq: np.ndarray) -> tuple[float, float]:
    """행별 변화 빈도 → 내용이 있는 세로 구간 (시작, 끝) 비율. 띠가 없으면 (0,1)."""
    freq = np.asarray(row_freq, dtype=float)
    n = len(freq)
    if n < 8:
        return FULL  # 행이 너무 적으면 띠를 논할 해상도가 안 된다
    hot = freq > max(HOT_MULTIPLE * float(np.median(freq)), MIN_HOT)

    top = 0
    while top < n and hot[top]:
        top += 1
    bottom = n
    while bottom > top and hot[bottom - 1]:
        bottom -= 1
    # 가장자리에서 이어지지 않는 hot 행은 무시한다 — 한복판이 자주 바뀌는 것은
    # 오버레이가 아니라 애니메이션이고, 그걸 가리면 내용을 잘라내게 된다.
    if top > n * MAX_BAND:
        top = 0
    if n - bottom > n * MAX_BAND:
        bottom = n
    if top >= bottom:
        return FULL
    return (top / n, bottom / n)


def crop(img: np.ndarray, band: tuple[float, float]) -> np.ndarray:
    """세로 구간만 남긴다. 비교·해시·내용량 측정은 모두 이 결과 위에서 한다."""
    lo, hi = band
    if (lo, hi) == FULL:
        return img
    h = img.shape[0]
    a, b = int(round(h * lo)), int(round(h * hi))
    return img[a:b] if b - a >= 1 else img


def content_area(img: np.ndarray, delta: float = 25.0) -> float:
    """배경과 뚜렷이 다른 픽셀의 비율 — "이 그림에 내용이 있는가".

    평균 밝기로 이 질문에 답할 수 없다. 어두운 테마 영상(video1)에서 채택된
    프레임의 평균 밝기는 5.17~5.33, 탈락한 것은 4.37~4.98로 **연속 분포이고
    그 사이에 골이 없다** — 임계 5.0은 정상 내용을 관통해 자르고 있었다.
    실제로 탈락 46건 중 27건이 채택된 어떤 프레임보다도 밝은 픽셀이 많았다.
    배경(중앙값)에서 떨어진 픽셀의 **면적**으로 재면 완전한 암전(0.00%)과
    내용이 있는 프레임(0.21% 이상)이 범주적으로 갈린다.
    """
    a = np.asarray(img, dtype=np.float32)
    return float((np.abs(a - float(np.median(a))) > delta).mean())
