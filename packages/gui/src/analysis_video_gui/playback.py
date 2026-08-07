"""M0 재생 코어 — PyAV 디코드 + sounddevice 오디오 + 자작 클록/동기.

QtMultimedia 동봉 FFmpeg가 AV1을 디코드하지 못함이 스파이크로 실증되어(0프레임),
분석 파이프라인과 동일한 PyAV 경로로 재생한다(결정 A9 유지).

구조
  VideoDecodeThread ─┐ (pts, QImage) 큐
                     ├─► Presenter(QTimer, GUI 스레드) ─ frameReady/positionChanged
  AudioDecodeThread ─┘ 링버퍼 → sounddevice 콜백

클록 규칙
  · 배속 1.0 + 비음소거 + 오디오 가용: 실제 재생된 샘플 수가 마스터(립싱크 보장,
    버퍼가 비면 클록이 멈춰 영상도 함께 기다림 — 자가 버퍼링)
  · 그 외(배속≠1.0, 음소거, 무음 영상): 단조 벽시계 × 배속
시킹/스텝
  · seek 세대(generation) 카운터로 디코더에 통지 — 구세대 프레임은 큐에서 폐기
  · 일시정지 중 seek/스텝은 prime 모드로 목표 pts 이상 첫 프레임 1장만 표시
"""
import queue
import threading
import time as _time
from pathlib import Path

import av
import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

AUDIO_RATE = 48000
RATES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


class _VideoDecodeThread(threading.Thread):
    def __init__(self, path: Path, out_q: queue.Queue):
        super().__init__(daemon=True)
        self.path = path
        self.out_q = out_q
        self.stop_flag = False
        self.gen = 0                # seek 세대 — 바뀌면 디코더가 seek 후 새로 시작
        self.seek_target = 0.0
        self._lock = threading.Lock()

    def request_seek(self, t: float) -> None:
        with self._lock:
            self.gen += 1
            self.seek_target = max(0.0, t)

    def run(self) -> None:
        container = av.open(str(self.path))
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        fps = float(stream.average_rate or 25)
        local_gen = -1
        it = None
        skip_until: float | None = None

        while not self.stop_flag:
            with self._lock:
                if local_gen != self.gen:
                    local_gen = self.gen
                    target = self.seek_target
                    container.seek(max(int(target / stream.time_base), 0), stream=stream)
                    it = container.decode(stream)
                    skip_until = target
            if it is None:
                it = container.decode(stream)
            try:
                frame = next(it)
            except (StopIteration, av.error.EOFError):
                _time.sleep(0.03)  # EOF — seek 요청 대기
                continue
            except av.error.FFmpegError:
                continue
            if frame.time is None:
                continue
            if skip_until is not None:
                if frame.time < skip_until - 0.6 / fps:
                    continue  # 키프레임→목표 사이 프레임은 큐에 넣지 않고 버림
                skip_until = None
            arr = frame.to_ndarray(format="rgb24")
            h, w, _ = arr.shape
            img = QImage(arr.data, w, h, arr.strides[0], QImage.Format_RGB888).copy()
            entry = (local_gen, frame.time, img)
            while not self.stop_flag:
                with self._lock:
                    if local_gen != self.gen:
                        break  # seek 발생 — 이 프레임 폐기
                try:
                    self.out_q.put(entry, timeout=0.1)
                    break
                except queue.Full:
                    continue
        container.close()


class _AudioDecodeThread(threading.Thread):
    """원본의 오디오 스트림을 float32 mono 48kHz로 디코드해 링버퍼를 채운다."""

    def __init__(self, path: Path, ring: "_AudioRing"):
        super().__init__(daemon=True)
        self.path = path
        self.ring = ring
        self.stop_flag = False
        self.gen = 0
        self.seek_target = 0.0
        self._lock = threading.Lock()

    def request_seek(self, t: float) -> None:
        with self._lock:
            self.gen += 1
            self.seek_target = max(0.0, t)

    def run(self) -> None:
        container = av.open(str(self.path))
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=AUDIO_RATE)
        local_gen = -1
        it = None

        while not self.stop_flag:
            with self._lock:
                if local_gen != self.gen:
                    local_gen = self.gen
                    target = self.seek_target
                    container.seek(max(int(target / stream.time_base), 0), stream=stream)
                    it = container.decode(stream)
                    resampler = av.AudioResampler(format="flt", layout="mono", rate=AUDIO_RATE)
                    self.ring.reset(target)
            if it is None:
                it = container.decode(stream)
            if self.ring.buffered_seconds() > 1.0:
                _time.sleep(0.05)
                continue
            try:
                frame = next(it)
            except (StopIteration, av.error.EOFError):
                _time.sleep(0.05)
                continue
            except av.error.FFmpegError:
                continue
            for rf in resampler.resample(frame):
                pcm = rf.to_ndarray().reshape(-1).astype(np.float32)
                # seek 직후 목표 이전 샘플은 잘라낸다 (키프레임 롤백 구간)
                if rf.time is not None and rf.time < self.ring.anchor_pts - 0.001:
                    cut = int((self.ring.anchor_pts - rf.time) * AUDIO_RATE)
                    if cut >= len(pcm):
                        continue
                    pcm = pcm[cut:]
                self.ring.push(local_gen, pcm)
        container.close()


class _AudioRing:
    """디코더가 push, sounddevice 콜백이 pull. played 샘플 수가 곧 오디오 클록."""

    def __init__(self):
        self.lock = threading.Lock()
        self.chunks: list[np.ndarray] = []
        self.offset = 0          # chunks[0] 안의 소비 위치
        self.played = 0          # 실제로 출력된 샘플 수 (클록의 원천)
        self.anchor_pts = 0.0    # played=0 시점의 미디어 시각
        self.gen = 0             # 현재 유효 세대
        self.active = False      # 오디오가 클록 마스터인가

    def reset(self, anchor_pts: float) -> None:
        with self.lock:
            self.chunks.clear()
            self.offset = 0
            self.played = 0
            self.anchor_pts = anchor_pts
            self.gen += 1

    def push(self, gen: int, pcm: np.ndarray) -> None:
        with self.lock:
            if gen != self.gen and self.gen != gen:  # reset 이후 구세대 데이터 폐기
                pass
            self.chunks.append(pcm)

    def buffered_seconds(self) -> float:
        with self.lock:
            total = sum(len(c) for c in self.chunks) - self.offset
        return total / AUDIO_RATE

    def position(self) -> float:
        with self.lock:
            return self.anchor_pts + self.played / AUDIO_RATE

    def pull_into(self, outdata: np.ndarray) -> None:
        n = len(outdata)
        with self.lock:
            if not self.active:
                outdata[:] = 0.0
                return
            filled = 0
            while filled < n and self.chunks:
                chunk = self.chunks[0]
                take = min(len(chunk) - self.offset, n - filled)
                outdata[filled:filled + take, 0] = chunk[self.offset:self.offset + take]
                self.offset += take
                filled += take
                if self.offset >= len(chunk):
                    self.chunks.pop(0)
                    self.offset = 0
            if filled < n:
                outdata[filled:, 0] = 0.0
            self.played += filled  # 실제 출력분만 클록 전진 — 언더런 시 클록 정지


class PlayerEngine(QObject):
    positionChanged = Signal(float)
    stateChanged = Signal(bool)          # playing 여부
    frameReady = Signal(QImage, float)   # (프레임, pts)
    rateChanged = Signal(float)
    mutedChanged = Signal(bool)

    def __init__(self, video_path: Path, duration: float, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.duration = duration
        with av.open(str(video_path)) as c:
            self.fps = float(c.streams.video[0].average_rate or 25)
            self.has_audio = len(c.streams.audio) > 0

        self._playing = False
        self._rate = 1.0
        self._muted = False
        self._pos = 0.0              # 일시정지 시각 / 클록 앵커
        self._wall_anchor = 0.0
        self._prime = False          # 정지 중 seek/스텝 후 1장만 표시
        self._prime_target = 0.0
        self._pending: tuple | None = None  # 큐에서 꺼냈지만 아직 미래인 프레임 1장

        self._q: queue.Queue = queue.Queue(maxsize=4)
        self._video = _VideoDecodeThread(video_path, self._q)
        self._video.start()
        self._video.request_seek(0.0)

        self._ring = _AudioRing()
        self._audio_thread = None
        self._stream = None
        self._audio_ok = False
        if self.has_audio:
            try:
                import sounddevice as sd
                self._stream = sd.OutputStream(
                    samplerate=AUDIO_RATE, channels=1, dtype="float32",
                    callback=lambda out, n, t, s: self._ring.pull_into(out))
                self._stream.start()
                self._audio_thread = _AudioDecodeThread(video_path, self._ring)
                self._audio_thread.start()
                self._audio_ok = True
            except Exception:
                self._audio_ok = False  # 장치 없음 등 — 벽시계 폴백

        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.seek(0.0)

    # ---------- 클록 ----------

    def _audio_master(self) -> bool:
        return (self._audio_ok and self._playing
                and self._rate == 1.0 and not self._muted)

    def position(self) -> float:
        if not self._playing:
            return self._pos
        if self._audio_master():
            return self._ring.position()
        return self._pos + (_time.perf_counter() - self._wall_anchor) * self._rate

    # ---------- 제어 API ----------

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def play(self) -> None:
        if self._playing:
            return
        if self.duration and self._pos >= self.duration - 0.05:
            self.seek(0.0)
        self._playing = True
        self._anchor_clock(self._pos)
        self.stateChanged.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._pos = self.position()
        self._playing = False
        self._ring.active = False
        self.stateChanged.emit(False)

    def seek(self, t: float) -> None:
        t = min(max(0.0, t), max(0.0, self.duration - 0.05))
        self._drain_queue()
        self._video.request_seek(t)
        if self._audio_thread:
            self._audio_thread.request_seek(t)
        if self._playing:
            self._anchor_clock(t)
        else:
            self._pos = t
            self._prime = True
            self._prime_target = t
        self.positionChanged.emit(t)

    def seek_relative(self, dt: float) -> None:
        self.seek(self.position() + dt)

    def step_frame(self, direction: int = 1) -> None:
        self.pause()
        if direction > 0:
            self._prime = True
            self._prime_target = self._pos + 0.4 / self.fps
        else:
            self.seek(self._pos - 1.1 / self.fps)

    def set_rate(self, rate: float) -> None:
        pos = self.position()
        self._rate = rate
        if self._playing:
            self._anchor_clock(pos)
        self.rateChanged.emit(rate)

    def set_muted(self, muted: bool) -> None:
        pos = self.position()
        self._muted = muted
        if self._playing:
            self._anchor_clock(pos)
        self.mutedChanged.emit(muted)

    def shutdown(self) -> None:
        self._timer.stop()
        self._video.stop_flag = True
        if self._audio_thread:
            self._audio_thread.stop_flag = True
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    # ---------- 내부 ----------

    def _anchor_clock(self, pos: float) -> None:
        self._pos = pos
        self._wall_anchor = _time.perf_counter()
        if self._audio_master():
            self._ring.reset(pos)
            if self._audio_thread:
                self._audio_thread.request_seek(pos)
            self._ring.active = True
        else:
            self._ring.active = False

    def _drain_queue(self) -> None:
        self._pending = None
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def _tick(self) -> None:
        if self._prime:
            # 정지 중 seek/스텝: 목표 이전 프레임은 버리고 첫 프레임 1장 표시
            while True:
                try:
                    gen, pts, img = self._q.get_nowait()
                except queue.Empty:
                    return
                if gen != self._video.gen:
                    continue
                if pts < self._prime_target - 0.6 / self.fps:
                    continue
                self._prime = False
                self._pos = pts
                self.frameReady.emit(img, pts)
                self.positionChanged.emit(pts)
                return

        if not self._playing:
            return

        pos = self.position()
        latest = None
        while True:
            # 보관분(_pending)을 먼저 소비 — 미래 프레임이면 큐에서 더 꺼내지 않는다
            if self._pending is not None:
                gen, pts, img = self._pending
                if gen != self._video.gen:
                    self._pending = None
                    continue
                if pts <= pos + 0.006:
                    latest = (pts, img)  # 시각이 지난 프레임 — 최신 것만 남김
                    self._pending = None
                    continue
                break
            try:
                self._pending = self._q.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self.frameReady.emit(latest[1], latest[0])
        self.positionChanged.emit(min(pos, self.duration))
        if self.duration and pos >= self.duration:
            self.pause()
