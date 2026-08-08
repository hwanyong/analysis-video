"""split 리먹스 무결성 — 분리된 video.mkv는 원본과 프레임이 1:1이어야 한다.

프레임이 유실되면 이후 모든 검출이 그 구간을 통째로 놓치는데, 산출물은 정상처럼
보인다(무성 데이터 손실). 특히 B-프레임 영상의 선두 패킷은 dts가 None으로 오므로
dts 유무로 패킷을 거르면 첫 키프레임이 사라진다.
"""
from pathlib import Path

import av
import numpy as np
import pytest

from analysis_video import media, split


def _make_video(path: Path, fps: int = 10, seconds: float = 4.0) -> None:
    """B-프레임을 쓰는 h264 (기본 x264 설정) — 선두 패킷 dts가 None으로 온다."""
    with av.open(str(path), "w") as out:
        vs = out.add_stream("libx264", rate=fps)
        vs.width, vs.height, vs.pix_fmt = 320, 180, "yuv420p"
        for i in range(int(seconds * fps)):
            arr = np.full((180, 320, 3), 200, dtype=np.uint8)
            arr[40:120, (i * 7) % 240:(i * 7) % 240 + 60] = 30
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            frame.pts = i
            for p in vs.encode(frame):
                out.mux(p)
        for p in vs.encode(None):
            out.mux(p)


@pytest.fixture
def source(tmp_path) -> Path:
    p = tmp_path / "src.mkv"
    _make_video(p)
    return p


def test_remux_preserves_every_frame(source, tmp_path):
    audio, video = split.split_media(source, tmp_path / "out")

    original = [t for t, _ in media.decode_gray_frames(source)]
    remuxed = [t for t, _ in media.decode_gray_frames(video)]

    assert len(remuxed) == len(original), "리먹스에서 프레임이 유실되면 안 된다"
    assert remuxed[0] == pytest.approx(original[0], abs=0.01), "선두 프레임 보존"
    assert remuxed[-1] == pytest.approx(original[-1], abs=0.01), "말미 프레임 보존"


def test_remux_has_no_audio(source, tmp_path):
    _audio, video = split.split_media(source, tmp_path / "out")
    with av.open(str(video)) as c:
        assert not c.streams.audio, "video.mkv는 무음이어야 한다"


def test_silent_video_returns_no_audio(source, tmp_path):
    audio, video = split.split_media(source, tmp_path / "out")
    assert audio is None, "오디오 스트림이 없는 입력은 (None, video)를 반환"
    assert video.exists()
