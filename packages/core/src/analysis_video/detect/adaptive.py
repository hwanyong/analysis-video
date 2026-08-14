"""PySceneDetect AdaptiveDetector 래퍼 — 세 신호와 합집합으로 쓰는 보조 검출기.

AdaptiveDetector는 자체 전환추적이 없어 트리거 직후가 과도기(페이드 중간·빈 화면)일
수 있다. pick_stable_time이 +1.5초 지점의 안정성(SSIM)을 확인하고 불안정하면
+1.0초 더 미룬다 — 프로토타입 실측(§2-7) 근거.

시각 계산 규약: scenedetect의 `get_seconds()`는 프레임번호÷**선언** fps다. 컨테이너의
선언 fps가 실제와 다르면(리먹스·VFR·잘못된 헤더) 전 검출 시각이 같은 비율로 누적
왜곡된다 — 실측으로 24fps로 잘못 선언된 30fps 영상에서 최대 127초까지 벌어졌다.
그래서 프레임 **번호**만 받아 오고, 시각 변환은 호출자가 실제 PTS 배열로 한다.
이 배열은 신호 측정이 이미 만들어 둔 것(time_series)이라 추가 디코드가 없고,
PTS가 원천이므로 VFR에도 옳다. `media.py`의 "인덱스/평균fps 근사 금지" 규약과 같다.
"""
import contextlib
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .. import media

# macOS에서 cv2를 적재할 때 ObjC 런타임이 fd 2로 직접 뱉는 중복 클래스 경고.
# 원인은 상류 휠 두 개가 각자 FFmpeg를 동봉한 것이다: av(libavdevice.62)와
# opencv-python-headless(libavdevice.61)가 같은 AVFoundation 캡처 클래스를
# 각자 등록한다. 두 사본 중 어느 쪽도 우리가 뺄 수 없고(둘 다 무조건 의존이며
# 각 휠 안에 박혀 있다), 우리는 avdevice의 캡처 기능을 쓰지 않으므로 실제
# 영향은 없다 — 남는 것은 "mysterious crashes"라 겁을 주는 문구뿐이다.
#
# 그래서 **이 한 줄만** 걸러 내고 나머지 stderr는 그대로 통과시킨다. 통째로
# 묻으면 같은 적재 과정에서 나는 진짜 오류(다른 dylib 실패)까지 사라진다.
_OBJC_DUP_AVDEVICE = re.compile(
    r"^objc\[\d+\]: Class AVF\w+ is implemented in both .*libavdevice")


@contextlib.contextmanager
def _without_avdevice_noise():
    """cv2 적재 구간의 fd 2를 받아 두었다가, 알려진 경고만 빼고 되돌려 준다.

    파이썬의 sys.stderr를 바꾸는 것으로는 잡히지 않는다 — 저 문구는 ObjC
    런타임이 파일 서술자 2에 직접 쓰는 것이라 프로세스 수준에서 갈아 끼워야 한다.
    파이프가 아니라 임시 파일을 쓰는 이유는 버퍼가 차면 교착이 나기 때문이다."""
    if sys.platform != "darwin":
        yield
        return
    sys.stderr.flush()
    saved = os.dup(2)
    try:
        with tempfile.TemporaryFile() as sink:
            os.dup2(sink.fileno(), 2)
            try:
                yield
            finally:
                os.dup2(saved, 2)
                sink.seek(0)
                text = sink.read().decode("utf-8", errors="replace")
        for line in text.splitlines():
            if not _OBJC_DUP_AVDEVICE.match(line):
                print(line, file=sys.stderr)
    finally:
        os.close(saved)


def adaptive_detector_frames(video_path: Path, threshold: float = 2.0) -> list[int]:
    """장면 전환 후보의 **프레임 번호** 목록 (첫 강제 경계 0은 제외)."""
    # 지연 임포트: scenedetect(→cv2)가 깨져 있어도 doctor 등 다른 명령은 살아야 한다
    with _without_avdevice_noise():
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

    frame_times(신호 측정의 time_series)를 주면 프레임 번호를 실제 PTS로 옮긴다.
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
