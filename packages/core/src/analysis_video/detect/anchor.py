"""전환추적 anchor-diff — 사용자 고안 알고리즘 (전역 장면 전환 검출기).

기준(앵커) 고정 + 비교(커서) 전진. 순간변화율(인접 프레임)이 안 잦아들면
전환이 진행중인 것으로 보고 트리거를 보류, 커서만 계속 전진시킨다.
안정되면(순간변화율 < rate_threshold) 그 프레임에서 트리거하고 앵커를 옮긴다.
타임아웃 없음 — 실측상 최대 대기 1.1초, 슬라이드형 콘텐츠엔 불필요하다는 사용자 판단.

프레임은 스트리밍으로 소비한다: 앵커와 직전 프레임 2장만 유지하므로
메모리 사용량이 영상 길이와 무관하다.
"""
from pathlib import Path

import numpy as np

from .. import media


def transition_aware_anchor_diff(video_path: Path, cum_threshold: float = 0.02,
                                 rate_threshold: float = 0.0015) -> dict:
    fps = media.get_fps(video_path)
    it = media.decode_gray_frames(video_path)

    cum_list = [0.0]
    rate_list = [0.0]
    events = []  # [{anchor_idx, transition_start_idx, trigger_idx}, ...]

    try:
        anchor = next(it)
    except StopIteration:
        return {"fps": fps, "n_frames": 0,
                "cum_series": np.zeros(0), "rate_series": np.zeros(0), "events": [],
                "cum_threshold": cum_threshold, "rate_threshold": rate_threshold}

    prev = anchor
    anchor_idx = 0
    transition_start_idx = None
    i = 0
    for f in it:
        i += 1
        cum_diff = float(np.abs(f - anchor).mean()) / 255.0
        inst_diff = float(np.abs(f - prev).mean()) / 255.0
        cum_list.append(cum_diff)
        rate_list.append(inst_diff)
        prev = f

        if cum_diff <= cum_threshold:
            continue
        if transition_start_idx is None:
            transition_start_idx = i
        if inst_diff > rate_threshold:
            continue  # 아직 전환 진행중 — 트리거 보류, 커서만 전진

        events.append({
            "anchor_idx": anchor_idx,
            "transition_start_idx": transition_start_idx,
            "trigger_idx": i,
        })
        anchor = f
        anchor_idx = i
        transition_start_idx = None

    return {
        "fps": fps, "n_frames": i + 1,
        "cum_series": np.array(cum_list), "rate_series": np.array(rate_list),
        "events": events,
        "cum_threshold": cum_threshold, "rate_threshold": rate_threshold,
    }
