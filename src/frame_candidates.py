from pathlib import Path

import numpy as np
from scenedetect import open_video, SceneManager
from scenedetect.detectors import AdaptiveDetector
from skimage.metrics import structural_similarity as ssim

from . import ffutil


def transition_aware_anchor_diff(video_path: Path, cum_threshold: float = 0.02,
                                  rate_threshold: float = 0.0015) -> dict:
    """기준(앵커) 고정 + 비교(커서) 전진. 순간변화율(인접 프레임)이 안 잦아들면
    전환이 진행중인 것으로 보고 트리거를 보류, 커서만 계속 전진시킨다.
    안정되면(=순간변화율<rate_threshold) 그 프레임에서 트리거하고 앵커를 그 자리로 옮긴다.
    타임아웃 없음 — 실측(§transition_aware_sweep)상 최대 대기 1.1초, 슬라이드형 콘텐츠엔 불필요하다는
    사용자 판단."""
    frames = ffutil.decode_gray_frames(video_path)
    fps = ffutil.get_fps(video_path)
    n = len(frames)

    cum_series = np.zeros(n)
    rate_series = np.zeros(n)
    events = []  # [{anchor_idx, transition_start_idx, trigger_idx}, ...]

    anchor_idx = 0
    transition_start_idx = None
    for i in range(1, n):
        cum_diff = float(np.abs(frames[i] - frames[anchor_idx]).mean()) / 255.0
        inst_diff = float(np.abs(frames[i] - frames[i - 1]).mean()) / 255.0
        cum_series[i] = cum_diff
        rate_series[i] = inst_diff

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
        anchor_idx = i
        transition_start_idx = None

    return {
        "fps": fps, "n_frames": n,
        "cum_series": cum_series, "rate_series": rate_series,
        "events": events,
        "cum_threshold": cum_threshold, "rate_threshold": rate_threshold,
    }


def adaptive_detector_candidates(video_path: Path, threshold: float = 2.0) -> list[float]:
    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector(adaptive_threshold=threshold))
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    return [s[0].get_seconds() for s in scenes[1:]]  # 첫 강제 경계(0.0초) 제외


def _pick_stable_time(video_path: Path, t0: float, duration: float,
                       offset: float = 1.5, retry_offset: float = 1.0,
                       ssim_threshold: float = 0.97) -> float:
    """전환 도중(빈 화면/과도기) 프레임을 피한다 — §2-7 실측 근거."""
    t = min(t0 + offset, duration - 0.05)
    a = ffutil.extract_gray_array(video_path, t)
    t_next = min(t + 0.5, duration - 0.02)
    b = ffutil.extract_gray_array(video_path, t_next)
    if a is not None and b is not None and a.shape == b.shape:
        if ssim(a, b) < ssim_threshold:
            return min(t0 + offset + retry_offset, duration - 0.05)
    return t


def build_frame_candidates(video_path: Path, out_dir: Path,
                            yavg_floor: float = 5.0, phash_dup_distance: int = 4) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = ffutil.get_duration(video_path)

    anchor_result = transition_aware_anchor_diff(video_path)
    fps = anchor_result["fps"]
    # 전환추적된 anchor-diff 트리거는 이미 안정 상태에서 잡힌 것 — 추가 안정화 불필요
    anchor_times = [(e["trigger_idx"] / fps, e["trigger_idx"] / fps) for e in anchor_result["events"]]
    # AdaptiveDetector는 자체 전환추적이 없어 사후 안정화(_pick_stable_time)가 여전히 필요
    adaptive_times = [(t, _pick_stable_time(video_path, t, duration)) for t in adaptive_detector_candidates(video_path)]

    candidates = []
    for detected_at, stable_t in sorted(anchor_times + adaptive_times, key=lambda p: p[1]):
        img_path = out_dir / f"scene_{stable_t:07.2f}.jpg"
        if not ffutil.extract_frame(video_path, stable_t, img_path):
            continue
        y = ffutil.yavg(img_path)
        if y < yavg_floor:
            img_path.unlink()
            continue
        candidates.append({"time": stable_t, "detected_at": detected_at, "path": str(img_path), "yavg": y})

    candidates.sort(key=lambda c: c["time"])
    merged = []
    for c in candidates:
        h = ffutil.phash(Path(c["path"]))
        dup = next((m for m in merged if h - m["_hash"] <= phash_dup_distance), None)
        if dup is not None:
            Path(c["path"]).unlink()
            continue
        c["_hash"] = h
        merged.append(c)

    for c in merged:
        c["hash"] = str(c.pop("_hash"))
    return merged
