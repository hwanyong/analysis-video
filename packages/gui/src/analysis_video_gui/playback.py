"""M0 재생 코어 — PyAV 디코드 + sounddevice 오디오 + 자작 클록/동기.

QtMultimedia 동봉 FFmpeg가 AV1을 디코드하지 못함이 스파이크로 실증되어(0프레임),
분석 파이프라인과 동일한 PyAV 경로로 재생한다.

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
스크럽(드래그 중 실시간 미리보기)
  · 위치 시그널은 마우스를 따라 즉시, 영상은 요청 병합(미해결 요청 1건)으로
    디코더가 소화하는 만큼만 — 요청이 밀려 화면이 멎는 일이 없다
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
                    try:
                        container.seek(max(int(target / stream.time_base), 0), stream=stream)
                    except av.FFmpegError:
                        # seek 불가 스트림 — 처음부터 다시 열어 순차 진행
                        container.close()
                        container = av.open(str(self.path))
                        stream = container.streams.video[0]
                        stream.thread_type = "AUTO"
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
        push_gen = -1   # 링이 발급한 push 세대 — 링 reset이 이보다 새로우면 push 폐기됨
        it = None
        self.eof = False

        while not self.stop_flag:
            with self._lock:
                if local_gen != self.gen:
                    local_gen = self.gen
                    target = self.seek_target
                    try:
                        container.seek(max(int(target / stream.time_base), 0), stream=stream)
                    except av.FFmpegError:
                        container.close()
                        container = av.open(str(self.path))
                        stream = container.streams.audio[0]
                    it = container.decode(stream)
                    resampler = av.AudioResampler(format="flt", layout="mono", rate=AUDIO_RATE)
                    push_gen = self.ring.reset(target)
                    self.eof = False
            if it is None:
                it = container.decode(stream)
            if self.ring.buffered_seconds() > 1.0:
                _time.sleep(0.05)
                continue
            try:
                frame = next(it)
            except (StopIteration, av.error.EOFError):
                self.eof = True  # 진짜 스트림 종점 — 엔진이 벽시계로 폴백할 신호
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
                self.ring.push(push_gen, pcm)
        container.close()


class _AudioRing:
    """디코더가 push, sounddevice 콜백이 pull. played 샘플 수가 곧 오디오 클록.

    세대 규약: reset()만이 세대를 발급한다. 디코드 스레드는 자신이 수행한
    reset이 돌려준 세대로만 push하고, 그 사이 다른 주체(GUI의 _anchor_clock)가
    reset했다면 세대가 앞서 있으므로 구 위치에서 디코드된 스테일 PCM은 버려진다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.chunks: list[np.ndarray] = []
        self.offset = 0          # chunks[0] 안의 소비 위치
        self.played = 0          # 실제로 출력된 샘플 수 (클록의 원천)
        self.anchor_pts = 0.0    # played=0 시점의 미디어 시각
        self.gen = 0             # 현재 유효 세대 — reset이 발급
        self.active = False      # 오디오가 클록 마스터인가

    def reset(self, anchor_pts: float) -> int:
        with self.lock:
            self.chunks.clear()
            self.offset = 0
            self.played = 0
            self.anchor_pts = anchor_pts
            self.gen += 1
            return self.gen

    def push(self, gen: int, pcm: np.ndarray) -> None:
        with self.lock:
            if gen != self.gen:
                return  # reset 이후 구세대 데이터 — 폐기
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
        self._prime_deadline = 0.0   # 충족 불가능한 prime의 영구 대기 방지
        self._pending: tuple | None = None  # 큐에서 꺼냈지만 아직 미래인 프레임 1장

        self._scrubbing = False
        self._scrub_resume = False          # 드래그 종료 후 재생을 이어갈지
        self._scrub_target = 0.0            # 마우스가 가리키는 최신 시각
        self._scrub_served: float | None = None  # 디코더에 실제로 보낸 시각
        self._scrub_inflight = False        # 응답 대기 중인 요청이 있는가

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

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def playing(self) -> bool:
        # 스크럽 중에는 클록이 서 있어도 '드래그를 놓으면 재생'이 논리적 재생 상태다
        return self._scrub_resume if self._scrubbing else self._playing

    @property
    def scrubbing(self) -> bool:
        return self._scrubbing

    def position(self) -> float:
        if not self._playing:
            return self._pos
        if self._audio_master():
            # 오디오 스트림 종점(EOF)에서 링이 마르면 벽시계로 이어간다 —
            # 아니면 클록이 동결돼 '재생 중' 상태로 영구 정지한다 (리뷰 확정 결함)
            if getattr(self._audio_thread, "eof", False) \
                    and self._ring.buffered_seconds() <= 0.0:
                return self._pos + (_time.perf_counter() - self._wall_anchor) * self._rate
            return self._ring.position()
        return self._pos + (_time.perf_counter() - self._wall_anchor) * self._rate

    # ---------- 제어 API ----------

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def play(self) -> None:
        if self._scrubbing:
            # 드래그 중 재생 지시는 '놓는 순간부터' 이행한다 — 지금 클록을 돌리면
            # 마우스와 재생이 서로 위치를 다투게 된다
            self._scrub_resume = True
            self.stateChanged.emit(True)
            return
        if self._playing:
            return
        if self.duration and self._pos >= self.duration - 0.05:
            self.seek(0.0)
        self._playing = True
        self._prime = False  # 정지 중 걸린 prime이 재생 경로를 기아시키지 않게 해제
        self._anchor_clock(self._pos)
        self.stateChanged.emit(True)

    def pause(self) -> None:
        if self._scrubbing:
            self._scrub_resume = False
            self.stateChanged.emit(False)
            return
        if not self._playing:
            return
        self._halt()
        self.stateChanged.emit(False)

    def _halt(self) -> None:
        """클록과 오디오만 세운다 — 상태 시그널 발신은 호출자가 결정한다."""
        self._pos = self.position()
        self._playing = False
        self._ring.active = False

    def seek(self, t: float) -> None:
        t = min(max(0.0, t), max(0.0, self.duration - 0.05))
        self._drain_queue()
        self._video.request_seek(t)
        if self._audio_thread:
            self._audio_thread.request_seek(t)
        if self._playing:
            self._prime = False
            self._anchor_clock(t)
        else:
            self._pos = t
            self._arm_prime(t)
        self.positionChanged.emit(t)

    def seek_relative(self, dt: float) -> None:
        self.seek(self.position() + dt)

    # ---------- 스크럽 ----------

    def begin_scrub(self) -> None:
        """드래그 시작. 재생 중이었다면 클록·오디오를 세우되 stateChanged는 내지
        않는다 — 드래그는 일시적 조작이고, 재생 버튼이 깜빡이면 오히려 혼란스럽다."""
        if self._scrubbing:
            return
        self._scrub_resume = self._playing
        if self._playing:
            self._halt()
        self._scrubbing = True
        self._scrub_target = self._pos
        self._scrub_served = None
        self._scrub_inflight = False

    def scrub_to(self, t: float) -> None:
        """드래그 위치 갱신 — 옵저버 창들은 즉시, 영상 프레임은 디코더 속도만큼."""
        if not self._scrubbing:
            self.begin_scrub()
        t = min(max(0.0, t), max(0.0, self.duration - 0.05))
        self._pos = t
        self._scrub_target = t
        self.positionChanged.emit(t)
        self._pump_scrub()

    def end_scrub(self) -> None:
        """드래그 종료 — 최종 위치로 정식 시크(오디오 포함)하고 필요하면 재생 재개."""
        if not self._scrubbing:
            return
        self._scrubbing = False
        self._scrub_inflight = False
        self._scrub_served = None
        resume, self._scrub_resume = self._scrub_resume, False
        self.seek(self._scrub_target)
        if resume:
            self.play()

    def _pump_scrub(self) -> None:
        """요청 병합 — 디코더에 미해결 요청은 항상 한 건만 띄운다.

        응답이 오면 그 사이 움직인 최신 목표로 다시 요청하므로, 프레임 솎아내기가
        마우스 속도가 아니라 디코더 속도에 맞춰 자동으로 일어난다. 드래그 이벤트마다
        seek을 걸면 매번 세대가 바뀌어 in-flight 프레임이 전량 폐기되고, 화면이
        드래그를 놓을 때까지 한 장도 갱신되지 않는다."""
        if not self._scrubbing or self._scrub_inflight:
            return
        if self._scrub_served is not None \
                and abs(self._scrub_target - self._scrub_served) < 1e-6:
            return
        self._scrub_served = self._scrub_target
        self._scrub_inflight = True
        self._drain_queue()
        self._video.request_seek(self._scrub_target)
        self._arm_prime(self._scrub_target)

    def step_frame(self, direction: int = 1) -> None:
        self.pause()
        if direction > 0:
            self._arm_prime(self._pos + 0.4 / self.fps)
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
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._video.stop_flag = True
        if self._audio_thread:
            self._audio_thread.stop_flag = True
        self._drain_queue()  # put 대기 중인 디코드 스레드를 풀어준다
        # 인터프리터 종료와 PyAV C 코드 실행이 겹치지 않게 정리를 기다린다
        self._video.join(timeout=2.0)
        if self._audio_thread:
            self._audio_thread.join(timeout=2.0)

    # ---------- 내부 ----------

    def _arm_prime(self, target: float) -> None:
        """정지 중 1장만 표시하는 prime 요청. 영상 끝에서 목표 이상 프레임이
        존재하지 않을 수 있으므로 마감 시각을 둬 영구 대기를 막는다."""
        self._prime = True
        self._prime_target = target
        self._prime_deadline = _time.perf_counter() + 2.0

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
        if self._prime and not self._playing:
            # 정지 중 seek/스텝: 목표 이전 프레임은 버리고 첫 프레임 1장 표시
            while True:
                try:
                    gen, pts, img = self._q.get_nowait()
                except queue.Empty:
                    break
                if gen != self._video.gen:
                    continue
                if pts < self._prime_target - 0.6 / self.fps:
                    continue
                self._prime = False
                self.frameReady.emit(img, pts)
                if self._scrubbing:
                    # 드래그 중 위치의 원천은 마우스다. 디코드된 pts로 되돌리면
                    # 커서가 뒤로 튄다 — 프레임만 갱신하고 다음 목표를 요청한다.
                    self._scrub_inflight = False
                    self._pump_scrub()
                else:
                    self._pos = pts
                    self.positionChanged.emit(pts)
                return
            if _time.perf_counter() > self._prime_deadline:
                self._prime = False  # 영상 끝 등 — 목표 이상 프레임이 없음
                if self._scrubbing:
                    self._scrub_inflight = False
                    self._pump_scrub()
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
