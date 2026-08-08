"""신호 측정 — 영상을 훑어 세 시계열을 낸다. **판단은 하지 않는다.**

측정과 판단을 갈라 놓은 이유: 판단(어디를 사건으로 볼 것인가, 어디서 찍을
것인가)은 임계 하나만 바꿔도 결과가 달라지는데, 그때마다 전 프레임 디코드를
반복할 이유가 없다. 여기서 나온 시계열만 캐시해 두면 판단은 순수 연산으로
몇 밀리초 만에 다시 돌릴 수 있다(events 모듈).

세 신호는 서로 다른 것을 본다 — 하나로는 반드시 샌다:

- `anchor_diff` **점진 누적**. 앵커(기준 프레임)와의 평균절대차. 판서가 조금씩
  쌓이는 것은 어느 한 프레임도 튀지 않으므로 거리로만 알 수 있다.
- `cut_area` **컷**. 한 프레임 만에 확 바뀐 픽셀의 면적 비율. 평균이 아니라
  면적이라 희석되지 않는다.
- `inst_diff` **움직임의 세기**. 직전 프레임과의 평균절대차. 사건 검출에도 쓰고,
  "지금 화면이 안정돼 있는가"(촬영해도 되는가)를 재는 데도 쓴다.

실측(video3) 세 신호의 상호보완: 컷이 42개, anchor_diff가 3개, inst_diff가
2개를 단독으로 집어 합집합 50개. 컷이 등뼈지만 나머지 둘 없이는 5개를 잃는다.

**모든 측정은 고정 오버레이 띠를 뺀 본문에서 한다.** 안 그러면 번인 자막이
화면 전환으로 계상된다 — 실측 video3에서 컷 임계 0.02일 때 피크 129개 중
90개(70%)가 자막이었다. 띠는 영상마다 다르므로 1차 훑기에서 산출한다(overlay).

디코드는 두 번이다. 띠를 알아야 본문을 잴 수 있는데 띠는 전체를 봐야 나오므로
같은 패스 안에서 해결되지 않는다. 프레임을 들고 있으면 한 번으로 되지만
메모리가 영상 길이에 비례하게 되어(26분 영상 110MB) 스트리밍 원칙이 깨진다.
"""
from pathlib import Path

import numpy as np

from .. import media
from . import overlay

# 컷 면적을 셀 때 '색이 바뀌었다'로 인정할 그레이 단계 차이. 255단계 중 25는
# JPEG/코덱 노이즈(실측 수 단계)보다 확실히 크고, 판서 잉크↔배경 전이(약 43단계)
# 보다는 작아 페이지 교체를 온전히 센다.
CUT_DELTA = 25.0


def scan_rows(video_path: Path) -> np.ndarray:
    """1차 훑기 — 행별 변화 빈도. 오버레이 띠를 산출하기 위한 통계다."""
    prev = None
    hits: np.ndarray | None = None
    n = 0
    for _t, f in media.decode_gray_frames(video_path):
        if prev is not None:
            changed = (np.abs(f - prev) > CUT_DELTA).mean(axis=1) > overlay.ROW_HIT_RATIO
            hits = changed.astype(np.float64) if hits is None else hits + changed
            n += 1
        prev = f
    return (hits / n) if n else np.zeros(0)


def measure(video_path: Path, band: tuple[float, float], *,
            anchor_threshold: float, rate_threshold: float,
            cut_area_threshold: float) -> dict:
    """2차 훑기 — 본문 기준 세 시계열.

    앵커만은 온라인으로 옮겨야 한다: 컷이 났는데 앵커가 그대로면 그 뒤 모든
    프레임이 앵커에서 멀어 anchor_diff가 포화된다. 옮기는 시점은 "임계를 넘은
    뒤 움직임이 잦아든 첫 프레임" — 전환 도중의 섞인 프레임을 기준으로 삼지
    않기 위해서다. 이것은 anchor_diff라는 **신호의 내부 사정**일 뿐,
    무엇을 사건으로 볼 것인가와는 무관하다(그건 events가 정한다).
    """
    fps = media.get_fps(video_path)
    it = media.decode_gray_frames(video_path)

    times: list[float] = []
    anchor_series: list[float] = [0.0]
    rate_series: list[float] = [0.0]
    area_series: list[float] = [0.0]
    anchor_resets: list[int] = []

    def empty() -> dict:
        return {"fps": fps, "band": band, "time_series": np.zeros(0),
                "anchor_series": np.zeros(0), "rate_series": np.zeros(0),
                "area_series": np.zeros(0), "anchor_resets": []}

    try:
        t0, first = next(it)
    except StopIteration:
        return empty()

    times.append(t0 if t0 is not None else 0.0)
    anchor = overlay.crop(first, band)
    prev = anchor
    unsettled = False  # 임계를 넘은 뒤 아직 잦아들지 않았다
    i = 0
    for t, raw in it:
        i += 1
        times.append(t if t is not None else i / fps)
        f = overlay.crop(raw, band)
        delta = np.abs(f - prev)
        anchor_diff = float(np.abs(f - anchor).mean()) / 255.0
        inst_diff = float(delta.mean()) / 255.0
        cut_area = float((delta > CUT_DELTA).mean())
        anchor_series.append(anchor_diff)
        rate_series.append(inst_diff)
        area_series.append(cut_area)
        prev = f

        if not unsettled:
            unsettled = (anchor_diff > anchor_threshold
                         or cut_area > cut_area_threshold)
        elif inst_diff <= rate_threshold:
            anchor = f
            anchor_resets.append(i)
            unsettled = False

    return {
        "fps": fps, "band": band,
        "time_series": np.array(times),
        "anchor_series": np.array(anchor_series),
        "rate_series": np.array(rate_series),
        "area_series": np.array(area_series),
        "anchor_resets": anchor_resets,
    }
