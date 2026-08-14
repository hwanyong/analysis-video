"""adaptive 검출 시각은 선언 fps가 아니라 실제 PTS에서 나와야 한다.

컨테이너의 선언 프레임레이트는 리먹스·VFR·잘못된 헤더로 실제와 달라질 수 있고,
scenedetect의 get_seconds()는 프레임번호÷선언fps라 그 오차가 시각 전체에 누적된다.
실측 피해: 30fps 영상이 24fps로 선언되자 video3에서 최대 397초, video1에서 135초가
어긋났고, 영상 길이를 넘는 후보가 조용히 클램프돼 엉뚱한 장면이 캡처됐다.
"""
import json
import os
import sys

import pytest

from analysis_video import frames as frames_mod
from analysis_video.detect import adaptive


def test_frame_times_override_declared_fps(monkeypatch, tmp_path):
    """PTS 배열을 주면 선언 fps는 쓰이지 않는다."""
    monkeypatch.setattr(adaptive, "adaptive_detector_frames", lambda p, t=2.0: [0, 5, 10])
    monkeypatch.setattr(adaptive.media, "get_duration", lambda p: 100.0)
    monkeypatch.setattr(adaptive.media, "get_fps", lambda p: 24.0)  # 거짓 선언

    pts = [i / 30.0 for i in range(11)]  # 실제는 30fps
    got = adaptive.adaptive_detector_candidates(tmp_path / "x.mkv", frame_times=pts)
    assert got == pytest.approx([0.0, 5 / 30, 10 / 30])
    assert got != pytest.approx([0.0, 5 / 24, 10 / 24]), "선언 fps로 계산하면 안 된다"


def test_index_beyond_series_is_clamped(monkeypatch, tmp_path):
    """PTS 배열보다 큰 프레임 번호가 와도 마지막 시각으로 잡아 둔다(IndexError 금지)."""
    monkeypatch.setattr(adaptive, "adaptive_detector_frames", lambda p, t=2.0: [2, 99])
    monkeypatch.setattr(adaptive.media, "get_duration", lambda p: 1.0)
    pts = [0.0, 0.1, 0.2, 0.3]
    assert adaptive.adaptive_detector_candidates(
        tmp_path / "x.mkv", frame_times=pts) == pytest.approx([0.2, 0.3])


def test_fps_fallback_raises_when_times_exceed_duration(monkeypatch, tmp_path):
    """PTS가 없어 fps 근사로 폴백할 때, 시간축이 어긋나면 조용히 넘어가지 않는다."""
    monkeypatch.setattr(adaptive, "adaptive_detector_frames", lambda p, t=2.0: [100, 4000])
    monkeypatch.setattr(adaptive.media, "get_duration", lambda p: 100.0)
    monkeypatch.setattr(adaptive.media, "get_fps", lambda p: 24.0)
    with pytest.raises(adaptive.AdaptiveTimebaseError, match="넘습니다"):
        adaptive.adaptive_detector_candidates(tmp_path / "x.mkv")


def test_v1_adaptive_cache_is_rejected(monkeypatch, tmp_path):
    """구버전 캐시(리스트)는 틀린 시각을 담고 있다 — 재사용하면 수정이 적용되지 않는다."""
    out = tmp_path / "a.analysis"
    out.mkdir()
    (out / "detect_adaptive.json").write_text(
        json.dumps([{"detected_at": 1989.67, "time": 1600.58}]), encoding="utf-8")

    monkeypatch.setattr(adaptive, "adaptive_detector_candidates",
                        lambda p, threshold=2.0, frame_times=None: [12.5])
    monkeypatch.setattr(adaptive, "pick_stable_time",
                        lambda p, t, d, **kw: t + 1.5)

    entries = frames_mod._cached_adaptive(tmp_path / "v.mkv", out, 100.0, [0.0, 1.0])
    assert entries == [{"detected_at": 12.5, "time": 14.0}], "구 캐시를 버리고 재검출"

    stored = json.loads((out / "detect_adaptive.json").read_text())
    assert stored["schema"] == frames_mod.ADAPTIVE_SCHEMA
    assert frames_mod._cached_adaptive(tmp_path / "v.mkv", out, 100.0, [0.0, 1.0]) == entries


# ─── cv2 적재 소음 ───────────────────────────────────────────────────────
DUP_CLASS = (
    "objc[123]: Class AVFAudioReceiver is implemented in both "
    "/x/av/.dylibs/libavdevice.62.3.102.dylib (0x1) and "
    "/x/cv2/.dylibs/libavdevice.61.3.100.dylib (0x2). This may cause spurious "
    "casting failures and mysterious crashes. One of the duplicates must be "
    "removed or renamed.")


@pytest.mark.skipif(sys.platform != "darwin", reason="ObjC 런타임이 있는 곳에서만 의미가 있다")
def test_only_the_known_avdevice_warning_is_filtered(capfd):
    """상류 휠 두 개가 각자 FFmpeg를 동봉해 나는 경고다 — 우리가 뺄 수 있는
    사본이 없고 쓰지도 않는 기능이라 영향이 없다. 통째로 묻으면 같은 적재
    과정의 진짜 오류까지 사라지므로, 걸러 내는 것은 이 한 줄뿐이어야 한다."""
    with adaptive._without_avdevice_noise():
        # ObjC 런타임처럼 fd 2에 직접 쓴다 — sys.stderr 교체로는 잡히지 않는 경로다
        os.write(2, (DUP_CLASS + "\n").encode())
        os.write(2, b"objc[123]: Class Foo is implemented in both /a and /b.\n")
        os.write(2, "dlopen 실패: libssl.dylib\n".encode())

    err = capfd.readouterr().err
    assert "libavdevice" not in err, "알려진 경고는 사용자에게 보이지 않아야 한다"
    assert "Class Foo" in err, "다른 중복 클래스 경고까지 삼키면 안 된다"
    assert "dlopen 실패" in err, "적재 실패는 그대로 보여야 한다"
