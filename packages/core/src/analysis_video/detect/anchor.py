"""전환추적 anchor-diff — 사용자 고안 알고리즘 (전역 장면 전환 검출기).

기준(앵커) 고정 + 비교(커서) 전진. 전환이 시작됐다고 판정되면 순간변화율이
잦아들 때까지 트리거를 보류하고 커서만 전진시킨다. 안정되면
(순간변화율 < rate_threshold) 그 프레임에서 트리거하고 앵커를 옮긴다.
타임아웃 없음 — 실측상 최대 대기 1.1초, 슬라이드형 콘텐츠엔 불필요하다는 사용자 판단.

전환 시작 판정은 성질이 다른 두 신호의 OR다. 하나로는 안 되는 이유:

- `anchor_diff`(앵커와의 평균절대차)는 **점진 누적**을 잡는다. 판서가 조금씩
  쌓이는 것은 어느 한 프레임도 튀지 않으므로 앵커와의 거리로만 알 수 있다.
  반면 컷에는 약하다: 화면 전체를 갈아도 실제로 색이 바뀌는 픽셀은 판서 영상
  기준 7% 남짓이고 나머지 93%는 배경↔배경이라 차이 0이다. 이 0들이 평균을
  약 13배 희석해 완전한 페이지 교체조차 0.018~0.027밖에 못 낸다 — 임계
  0.02와 겹친다(실측 분리 여유 1.19배). 게다가 앵커와의 거리는 단조롭지
  않아서(3번째 페이지가 2번째보다 1번째를 더 닮을 수 있다) 어느 전환이
  잡히고 어느 것이 새는지 예측 자체가 안 된다.
- `cut_area`(한 프레임 만에 |Δ|>CUT_DELTA 로 바뀐 픽셀의 **면적 비율**)는
  **컷**을 잡는다. 평균이 아니라 면적이라 희석되지 않는다. 실측(video3)에서
  자막 교체는 최대 0.0395, 실제 페이지 교체는 최소 0.0655로 구간이 비어 있어
  임계 0.04~0.05 어디에 둬도 검출 수가 같다. 대신 페이드·전역 밝기 변화처럼
  '넓지만 옅은' 변화는 못 잡는다 — 그건 anchor_diff의 몫이다.

전환 시작은 **래치**다. 한 번 시작됐으면 안정될 때까지 시작 조건을 재검사하지
않는다. 컷으로 잡은 전환은 새 화면이 앵커와 닮아 anchor_diff가 임계 아래인
경우가 바로 그 놓치던 상황이므로, 매 프레임 재검사하면 영원히 트리거하지 못한다.

프레임은 스트리밍으로 소비한다: 앵커와 직전 프레임 2장만 유지하므로
메모리 사용량이 영상 길이와 무관하다. 이벤트 시각은 디코더가 준 PTS를
그대로 기록한다(VFR·start_time≠0 대응) — 인덱스는 시계열 참조용으로만 유지.
"""
from pathlib import Path

import numpy as np

from .. import media
from . import overlay

# 컷 면적을 셀 때 '색이 바뀌었다'로 인정할 그레이 단계 차이. 255단계 중 25는
# JPEG/코덱 노이즈(실측 수 단계)보다 확실히 크고, 판서 잉크↔배경 전이(약 43단계)
# 보다는 작아 페이지 교체를 온전히 센다.
CUT_DELTA = 25.0


def transition_aware_anchor_diff(video_path: Path, anchor_threshold: float = 0.02,
                                 rate_threshold: float = 0.0015,
                                 cut_area_threshold: float = 0.04) -> dict:
    fps = media.get_fps(video_path)
    it = media.decode_gray_frames(video_path)

    anchor_list = [0.0]
    rate_list = [0.0]
    area_list = [0.0]
    time_list: list[float] = []
    events = []  # [{anchor_idx/_time, transition_start_idx/_time, trigger_idx/_time}, ...]

    row_hits: np.ndarray | None = None  # 행별 '바뀐 프레임 수' — 오버레이 띠 산출용
    n_pairs = 0

    def empty() -> dict:
        return {"fps": fps, "n_frames": 0,
                "anchor_series": np.zeros(0), "rate_series": np.zeros(0),
                "area_series": np.zeros(0), "time_series": np.zeros(0), "events": [],
                "row_change_freq": np.zeros(0),
                "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
                "cut_area_threshold": cut_area_threshold}

    try:
        t0, anchor = next(it)
    except StopIteration:
        return empty()

    time_list.append(t0 if t0 is not None else 0.0)
    prev = anchor
    anchor_idx = 0
    anchor_time = time_list[0]
    transition_start_idx = None
    transition_start_time = None
    i = 0
    for t, f in it:
        i += 1
        t = t if t is not None else i / fps  # PTS 없는 스트림 폴백
        time_list.append(t)
        delta = np.abs(f - prev)
        anchor_diff = float(np.abs(f - anchor).mean()) / 255.0
        inst_diff = float(delta.mean()) / 255.0
        cut_area = float((delta > CUT_DELTA).mean())
        anchor_list.append(anchor_diff)
        rate_list.append(inst_diff)
        area_list.append(cut_area)
        # 어느 '행'이 바뀌었나를 누적한다. 판정에는 쓰지 않고 통계만 모은다 —
        # 이 한 번의 디코드로 오버레이 띠를 산출할 수 있게 하는 것이 목적이고,
        # 정책(무엇을 띠로 볼 것인가)은 overlay 모듈이 나중에 결정한다.
        row_changed = (delta > CUT_DELTA).mean(axis=1) > overlay.ROW_HIT_RATIO
        row_hits = row_changed.astype(np.float64) if row_hits is None \
            else row_hits + row_changed
        n_pairs += 1
        prev = f

        if transition_start_idx is None:
            # 점진 누적(anchor_diff) 또는 컷(cut_area) — 어느 쪽이든 전환의 시작
            if anchor_diff <= anchor_threshold and cut_area <= cut_area_threshold:
                continue
            transition_start_idx = i
            transition_start_time = t
        if inst_diff > rate_threshold:
            continue  # 아직 전환 진행중 — 트리거 보류, 커서만 전진

        # 전환이 시작됐다고 **판정된** 프레임은 변화가 시작된 프레임이 아니다.
        # 점진적 변화(크로스페이드·애니메이션)는 임계를 중간에 넘으므로, 그
        # 한 칸 앞은 이미 섞여 있다(실측 video2 41%·video1 36%가 그런 경우,
        # 최대 10프레임). 조용했던 마지막 프레임까지 되짚어야 "직전"이다.
        settled_idx = transition_start_idx - 1
        while settled_idx > anchor_idx and rate_list[settled_idx] > rate_threshold:
            settled_idx -= 1
        events.append({
            "anchor_idx": anchor_idx, "anchor_time": anchor_time,
            "transition_start_idx": transition_start_idx,
            "transition_start_time": transition_start_time,
            "settled_idx": settled_idx, "settled_time": time_list[settled_idx],
            "trigger_idx": i, "trigger_time": t,
        })
        anchor = f
        anchor_idx = i
        anchor_time = t
        transition_start_idx = None
        transition_start_time = None

    return {
        "fps": fps, "n_frames": i + 1,
        "anchor_series": np.array(anchor_list), "rate_series": np.array(rate_list),
        "area_series": np.array(area_list), "time_series": np.array(time_list),
        "events": events,
        "row_change_freq": (row_hits / n_pairs) if n_pairs else np.zeros(0),
        "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
        "cut_area_threshold": cut_area_threshold,
    }
