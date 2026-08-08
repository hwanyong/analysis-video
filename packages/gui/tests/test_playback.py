"""재생 엔진 회귀 테스트 — 적대적 리뷰에서 확정된 결함들이 되살아나지 않도록."""
import numpy as np

from analysis_video_gui.playback import PlayerEngine, _AudioRing


def test_ring_discards_stale_generation():
    """reset이 발급한 세대 외의 push는 폐기 — seek 직후 구 위치 오디오 혼입 방지."""
    ring = _AudioRing()
    gen = ring.reset(10.0)
    ring.push(gen, np.ones(480, dtype=np.float32))
    assert ring.buffered_seconds() > 0

    ring.reset(20.0)  # 다른 주체(GUI 클록 재앵커)가 리셋
    ring.push(gen, np.ones(4800, dtype=np.float32))  # 구세대 디코드 결과
    assert ring.buffered_seconds() == 0.0


def test_playback_advances_and_steps(video_av, pump):
    engine = PlayerEngine(video_av, duration=8.0)
    try:
        frames = []
        engine.frameReady.connect(lambda img, pts: frames.append(pts))

        engine.play()
        pump(2.0)
        engine.pause()
        assert len(frames) > 10, "재생 중 프레임이 흘러야 한다"
        assert engine.position() > 1.0

        engine.seek(4.0)
        pump(1.0)
        before = engine.position()
        for _ in range(3):
            engine.step_frame(1)
            pump(0.4)
        # 10fps 영상이므로 3프레임 ≈ 0.3초
        assert 0.2 < engine.position() - before < 0.45
    finally:
        engine.shutdown()


def test_prime_does_not_starve_playback(video_av, pump):
    """영상 끝으로 seek해 prime이 충족되지 않아도 이후 재생이 살아 있어야 한다."""
    engine = PlayerEngine(video_av, duration=8.0)
    try:
        engine.seek(7.96)   # 목표 이상 프레임이 없을 수 있는 지점
        pump(0.6)
        frames = []
        engine.frameReady.connect(lambda img, pts: frames.append(pts))
        engine.seek(2.0)
        pump(0.4)
        engine.play()
        pump(2.0)
        assert len(frames) > 10, "prime 잔류가 재생 경로를 기아시키면 안 된다"
        assert engine.position() > 3.0
    finally:
        engine.shutdown()


def test_audio_eof_does_not_stall_clock(video_short_audio, pump):
    """오디오(4초)가 비디오(8초)보다 짧아도 클록이 멈추지 않고 끝까지 진행."""
    engine = PlayerEngine(video_short_audio, duration=8.0)
    try:
        engine.seek(3.0)
        pump(0.6)
        engine.play()
        pump(6.5)
        assert engine.position() > 7.5, "오디오 EOF 이후 벽시계로 이어져야 한다"
        assert not engine.playing, "끝에 도달하면 자동 정지"
    finally:
        engine.shutdown()


def test_shutdown_joins_threads(video_av, pump):
    engine = PlayerEngine(video_av, duration=8.0)
    engine.play()
    pump(0.5)
    engine.shutdown()
    assert not engine._video.is_alive()
    assert engine._audio_thread is None or not engine._audio_thread.is_alive()
