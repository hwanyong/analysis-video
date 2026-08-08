"""GUI 테스트 공통 픽스처 — 오프스크린 Qt + 합성 미디어.

테스트용 영상은 매번 생성한다(testdata는 사용자 로컬 자산이라 CI에 없음).
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def pump(qapp):
    def _pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.004)
    return _pump


def _slide_frame(i: int, fps: int) -> "av.VideoFrame":
    """슬라이드형 화면 — 밝은 배경에 2초마다 배치가 바뀌는 어두운 블록.

    검출기가 실제로 트리거되려면 전역 diff가 임계값을 넘는 '장면 전환'이 있어야
    하고, YAVG 게이트를 통과하려면 화면이 충분히 밝아야 한다.
    """
    slide = i // (fps * 2)
    arr = np.full((180, 320, 3), 235, dtype=np.uint8)
    # 슬라이드마다 다른 위치·개수의 블록 → 전역 변화량이 크게 벌어진다
    for k in range(slide + 1):
        y = 20 + (k * 45) % 130
        x = 20 + (slide * 60 + k * 40) % 220
        arr[y:y + 35, x:x + 80] = 40 + 30 * k
    frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
    frame.pts = i
    return frame


def _write_video(path: Path, seconds: float, audio_seconds: float | None,
                 fps: int = 10) -> None:
    out = av.open(str(path), "w")
    # 스트림은 첫 mux(=헤더 기록) 전에 모두 선언해야 한다
    vs = out.add_stream("libx264", rate=fps)
    vs.width, vs.height, vs.pix_fmt = 320, 180, "yuv420p"
    a = None
    if audio_seconds:
        a = out.add_stream("aac", rate=48000)
        a.layout = "mono"

    for i in range(int(seconds * fps)):
        for p in vs.encode(_slide_frame(i, fps)):
            out.mux(p)

    if a is not None:
        t = np.linspace(0, audio_seconds, int(audio_seconds * 48000), endpoint=False)
        pcm = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=48000)
        af = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="flt", layout="mono")
        af.sample_rate = 48000
        for rf in resampler.resample(af):
            for p in a.encode(rf):
                out.mux(p)
        for p in a.encode(None):
            out.mux(p)

    for p in vs.encode(None):
        out.mux(p)
    out.close()


@pytest.fixture
def video_av(tmp_path) -> Path:
    """8초 영상 + 8초 오디오."""
    p = tmp_path / "av.mkv"
    _write_video(p, 8.0, 8.0)
    return p


@pytest.fixture
def video_short_audio(tmp_path) -> Path:
    """비디오 8초 / 오디오 4초 — 오디오 EOF 이후 클록 거동 검증용."""
    p = tmp_path / "short_audio.mkv"
    _write_video(p, 8.0, 4.0)
    return p


@pytest.fixture
def analyzed(video_av, tmp_path) -> tuple[Path, Path]:
    """CLI 파이프라인을 실제로 돌려 .analysis 산출물을 만든다 (GUI의 입력 계약)."""
    from analysis_video import cli

    out_dir = tmp_path / "out.analysis"
    assert cli.main(["split", str(video_av), "--out", str(out_dir)]) == 0
    assert cli.main(["transcribe", str(video_av), "--out", str(out_dir)]) == 0
    assert cli.main(["frames", str(video_av), "--no-points", "--out", str(out_dir)]) == 0
    return video_av, out_dir
