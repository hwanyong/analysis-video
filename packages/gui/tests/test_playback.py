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


def test_scrub_previews_during_drag(video_av, pump):
    """드래그를 놓기 전에 화면이 따라와야 한다 — 스크럽의 존재 이유."""
    engine = PlayerEngine(video_av, duration=8.0)
    try:
        pump(0.5)
        frames, positions = [], []
        engine.frameReady.connect(lambda img, pts: frames.append(pts))
        engine.positionChanged.connect(positions.append)

        engine.begin_scrub()
        for i in range(1, 13):
            engine.scrub_to(7.5 * i / 12)
            pump(0.08)
        assert len(positions) >= 12, "위치는 드래그를 그대로 따라간다"
        assert len(frames) >= 3, "드래그 도중 프레임이 갱신되어야 한다"
        assert frames == sorted(frames), "프레임이 드래그 방향대로 나와야 한다"

        engine.end_scrub()
        pump(0.6)
        assert abs(engine.position() - 7.5) < 0.3
        assert not engine.playing, "정지 상태에서 시작한 드래그는 정지로 끝난다"
    finally:
        engine.shutdown()


def test_fast_scrub_does_not_stall(video_av, pump):
    """요청 병합이 없으면 매 드래그 이벤트가 세대를 갈아 프레임이 한 장도 못 나온다."""
    engine = PlayerEngine(video_av, duration=8.0)
    try:
        pump(0.5)
        frames = []
        engine.frameReady.connect(lambda img, pts: frames.append(pts))
        engine.begin_scrub()
        for i in range(200):        # 펌프 없이 폭주 — 실제 트랙패드보다 훨씬 빠르게
            engine.scrub_to(7.5 * (i % 60) / 60)
        pump(1.2)
        assert frames, "요청이 밀려도 최신 목표의 프레임은 나와야 한다"
        engine.end_scrub()
        pump(0.5)
    finally:
        engine.shutdown()


def test_scrub_resumes_playback(video_av, pump):
    """재생 중 드래그는 오디오·클록을 세우되, 놓으면 그 자리에서 재생을 잇는다."""
    engine = PlayerEngine(video_av, duration=8.0)
    try:
        engine.seek(1.0)
        pump(0.5)
        engine.play()
        pump(0.6)

        engine.begin_scrub()
        engine.scrub_to(5.0)
        pump(0.3)
        assert not engine._playing, "드래그 중 클록은 서 있어야 한다"
        assert not engine._ring.active, "드래그 중 오디오는 나가지 않는다"
        assert engine.playing, "논리적 재생 상태는 유지"

        engine.end_scrub()
        pump(0.8)
        assert engine._playing and engine.position() > 5.0
    finally:
        engine.shutdown()


def test_shutdown_joins_threads(video_av, pump):
    engine = PlayerEngine(video_av, duration=8.0)
    engine.play()
    pump(0.5)
    engine.shutdown()
    assert not engine._video.is_alive()
    assert engine._audio_thread is None or not engine._audio_thread.is_alive()
