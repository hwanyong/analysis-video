"""PySceneDetect AdaptiveDetector 래퍼 — anchor-diff와 합집합으로 쓰는 보조 검출기.

AdaptiveDetector는 자체 전환추적이 없어 트리거 직후가 과도기(페이드 중간·빈 화면)일
수 있다. pick_stable_time이 +1.5초 지점의 안정성(SSIM)을 확인하고 불안정하면
+1.0초 더 미룬다 — 프로토타입 실측(§2-7) 근거.

시각 계산 규약: scenedetect의 `get_seconds()`는 프레임번호÷**선언** fps다. 컨테이너의
선언 fps가 실제와 다르면(리먹스·VFR·잘못된 헤더) 전 검출 시각이 같은 비율로 누적
왜곡된다 — 실측으로 24fps로 잘못 선언된 30fps 영상에서 최대 127초까지 벌어졌다.
그래서 프레임 **번호**만 받아 오고, 시각 변환은 호출자가 실제 PTS 배열로 한다.
이 배열은 anchor-diff가 이미 만들어 둔 것(time_series)이라 추가 디코드가 없고,
PTS가 원천이므로 VFR에도 옳다. `media.py`의 "인덱스/평균fps 근사 금지" 규약과 같다.
"""
from collections.abc import Sequence
from pathlib import Path

from .. import media


def adaptive_detector_frames(video_path: Path, threshold: float = 2.0) -> list[int]:
    """장면 전환 후보의 **프레임 번호** 목록 (첫 강제 경계 0은 제외)."""
    # 지연 임포트: scenedetect(→cv2)가 깨져 있어도 doctor 등 다른 명령은 살아야 한다
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import AdaptiveDetector

    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector(adaptive_threshold=threshold))
    sm.detect_scenes(video, show_progress=False)
    return [s[0].get_frames() for s in sm.get_scene_list()[1:]]


def adaptive_detector_candidates(video_path: Path, threshold: float = 2.0,
                                 frame_times: Sequence[float] | None = None) -> list[float]:
    """장면 전환 후보 시각(초).

    frame_times(anchor-diff의 time_series)를 주면 프레임 번호를 실제 PTS로 옮긴다.
    없으면 선언 fps 근사로 폴백하되, 영상 길이를 넘는 후보가 나오면 시간축이
    어긋났다는 확증이므로 조용히 클램프되기 전에 예외로 세운다.
    """
    indices = adaptive_detector_frames(video_path, threshold)
    duration = media.get_duration(video_path)

    if frame_times is not None and len(frame_times):
        last = len(frame_times) - 1
        return [float(frame_times[min(i, last)]) for i in indices]

    fps = media.get_fps(video_path)
    times = [i / fps for i in indices]
    over = [t for t in times if t > duration + 0.5]
    if over:
        raise AdaptiveTimebaseError(
            f"검출 시각 {len(over)}건이 영상 길이({duration:.2f}초)를 넘습니다"
            f"(최대 {max(over):.2f}초) — 선언 {fps:.3f}fps가 실제와 다릅니다")
    return times


class AdaptiveTimebaseError(RuntimeError):
    """scenedetect의 시간축이 영상과 어긋났다 — 결과 전체를 신뢰할 수 없다."""


def pick_stable_time(video_path: Path, t0: float, duration: float,
                     offset: float = 1.5, retry_offset: float = 1.0,
                     ssim_threshold: float = 0.97) -> float:
    from skimage.metrics import structural_similarity as ssim

    t = min(t0 + offset, duration - 0.05)
    a = media.extract_gray_array(video_path, t)
    t_next = min(t + 0.5, duration - 0.02)
    b = media.extract_gray_array(video_path, t_next)
    if a is not None and b is not None and a.shape == b.shape:
        if ssim(a, b) < ssim_threshold:
            return min(t0 + offset + retry_offset, duration - 0.05)
    return t
