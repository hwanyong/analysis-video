"""PySceneDetect AdaptiveDetector 래퍼 — anchor-diff와 합집합으로 쓰는 보조 검출기.

AdaptiveDetector는 자체 전환추적이 없어 트리거 직후가 과도기(페이드 중간·빈 화면)일
수 있다. pick_stable_time이 +1.5초 지점의 안정성(SSIM)을 확인하고 불안정하면
+1.0초 더 미룬다 — 프로토타입 실측(§2-7) 근거.
"""
from pathlib import Path

from .. import media


def adaptive_detector_candidates(video_path: Path, threshold: float = 2.0) -> list[float]:
    # 지연 임포트: scenedetect(→cv2)가 깨져 있어도 doctor 등 다른 명령은 살아야 한다
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import AdaptiveDetector

    video = open_video(str(video_path))
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector(adaptive_threshold=threshold))
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    return [s[0].get_seconds() for s in scenes[1:]]  # 첫 강제 경계(0.0초) 제외


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
