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


@pytest.fixture(scope="session", autouse=True)
def _isolated_settings(tmp_path_factory):
    """QSettings를 임시 디렉토리로 격리한다.

    테스트가 언어·레이아웃·창 위치를 저장하는데, 기본 NativeFormat은 실제 사용자
    설정(macOS plist)에 그대로 쓴다 — 테스트를 한 번 돌리면 개발자가 쓰던 GUI의
    언어가 바뀌어 있다. NativeFormat은 macOS에서 setPath를 무시하므로 형식 자체를
    IniFormat으로 바꿔 경로를 잡는다. 첫 QSettings 생성 전에 걸려야 하므로
    세션 스코프 autouse.
    """
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp("qsettings")))
    yield


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _default_language():
    """언어는 프로세스 전역 상태다 — 앞 테스트가 바꿔 두면 다음 테스트의 문구
    단언이 이유 없이 깨진다. 매 테스트를 기본 언어에서 시작시킨다."""
    from analysis_video_gui import i18n

    i18n.set_language(i18n.DEFAULT)
    yield
    i18n.set_language(i18n.DEFAULT)


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
        # **무음이어야 한다.** 재생 테스트는 진짜 오디오 장치를 연다(오디오 클록이
        # 재생 마스터라 대역으로 바꾸면 검증할 것이 없어진다) — 즉 스피커로 그대로
        # 나간다. 예전에는 440Hz 사인파였는데 그게 정확히 경고음('라' 음)이라
        # 테스트를 돌릴 때마다 삐 소리가 났다. 클록은 재생된 **샘플 수**를 세지
        # 진폭을 보지 않으므로 무음으로 두어도 잃는 검증이 없다 — 소리를 넣지 말 것.
        pcm = np.zeros(int(audio_seconds * 48000), dtype=np.float32)
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
    """CLI 파이프라인을 실제로 돌려 .analysis 산출물을 만든다 (GUI의 입력 계약).

    transcribe에 `--model tiny`를 **명시**한다. 이 픽스처의 영상에는 무음 오디오
    트랙이 있고 자막은 없어서 사다리 끝의 whisper까지 내려가는데, 기본값이
    small로 바뀌면서 기본값에 맡기면 매 실행마다 약 460MB(tiny는 약 71MB)를
    받는다. 더구나 CI의 가중치 캐시 키(ci.yml `hf-tiny-*`)는 이미 존재하는
    키를 덮어쓰지 않으므로, 캐시에는 tiny만 든 채 매 실행이 small을 새로
    내려받는다. GUI 테스트가 검증하는 것은 **산출물의 형태**이지 전사 품질이
    아니므로 가장 작은 모델로 고정하는 것이 맞다."""
    from analysis_video import cli

    out_dir = tmp_path / "out.analysis"
    assert cli.main(["split", str(video_av), "--out", str(out_dir)]) == 0
    assert cli.main(["transcribe", str(video_av), "--out", str(out_dir),
                     "--model", "tiny"]) == 0
    assert cli.main(["frames", str(video_av), "--out", str(out_dir)]) == 0
    return video_av, out_dir
