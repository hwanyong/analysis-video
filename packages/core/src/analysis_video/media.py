"""PyAV 기반 미디어 프리미티브 — 외부 ffmpeg 바이너리 의존 없음(배포 순수성).

스케일링 보간은 BICUBIC으로 고정한다: 프로토타입이 쓰던 ffmpeg scale 필터의
기본값과 맞춰 검출 임계값(cum/rate threshold) 튜닝 결과를 보존하기 위함.
"""
from collections.abc import Iterator
from pathlib import Path

import av
import numpy as np
from PIL import Image


def get_duration(path: Path) -> float:
    with av.open(str(path)) as c:
        if c.duration is not None:
            return c.duration / av.time_base
        s = c.streams.video[0]
        if s.duration is not None and s.time_base is not None:
            return float(s.duration * s.time_base)
    raise ValueError(f"길이를 알 수 없는 컨테이너: {path}")


def get_fps(path: Path) -> float:
    with av.open(str(path)) as c:
        rate = c.streams.video[0].average_rate
        if rate is None:
            raise ValueError(f"프레임레이트를 알 수 없는 스트림: {path}")
        return float(rate)


def decode_gray_frames(path: Path, w: int = 64, h: int = 36) -> Iterator[tuple[float | None, np.ndarray]]:
    """저해상도 그레이 프레임을 (PTS초, float32 배열) 스트리밍으로 낸다. 전량 적재 금지 —
    검출기는 앵커·직전 프레임만 유지하면 되므로 메모리가 영상 길이와 무관해진다.
    PTS를 함께 내는 이유: 인덱스/평균fps 근사는 VFR·start_time≠0 입력에서
    추출 시각(seek는 PTS 기반)과 어긋나 엉뚱한 프레임을 캡처하게 된다."""
    with av.open(str(path)) as c:
        stream = c.streams.video[0]
        stream.thread_type = "AUTO"
        for frame in c.decode(stream):
            g = frame.reformat(width=w, height=h, format="gray", interpolation="BICUBIC")
            yield frame.time, g.to_ndarray().astype(np.float32)


def _frame_at(container: av.container.InputContainer, time_s: float) -> av.VideoFrame | None:
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    offset = max(int(time_s / stream.time_base), 0)
    try:
        container.seek(offset, stream=stream)
    except av.FFmpegError:
        # 인덱스(Cues)가 없는 컨테이너 등 seek 불가 스트림 — 컨테이너를 막 연
        # 직후이므로 처음부터 순차 디코드해 목표 시각까지 진행한다.
        # (실패를 전파하면 파이프라인 전체가 내부 오류로 죽는다)
        pass
    last = None
    for frame in container.decode(stream):
        if frame.time is None:
            continue
        if frame.time >= time_s - 1e-3:
            return frame
        last = frame
    return last  # time_s가 영상 끝을 살짝 넘은 경우 마지막 프레임으로 대응


def extract_frame(path: Path, time_s: float, out_path: Path, quality: int = 90) -> bool:
    """고해상도 저장 — 검출은 저해상도로 하되 산출 이미지는 원본 해상도(결정 A6)."""
    with av.open(str(path)) as c:
        frame = _frame_at(c, time_s)
        if frame is None:
            return False
        frame.to_image().save(str(out_path), quality=quality)
    return out_path.exists()


def extract_gray_array(path: Path, time_s: float, w: int = 200, h: int = 112) -> np.ndarray | None:
    with av.open(str(path)) as c:
        frame = _frame_at(c, time_s)
        if frame is None:
            return None
        return frame.reformat(width=w, height=h, format="gray", interpolation="BICUBIC").to_ndarray()


def load_audio_mono16k(path: Path) -> np.ndarray:
    """STT 백엔드 공용 입력 — float32 mono 16kHz ndarray.
    백엔드에 파일 경로 대신 배열을 넘겨, 백엔드가 몰래 ffmpeg 바이너리를
    호출하는 경로(mlx-whisper의 load_audio 등)를 원천 차단한다."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as c:
        for frame in c.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray())
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray())
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    pcm = np.concatenate(chunks, axis=1).reshape(-1)
    return pcm.astype(np.float32) / 32768.0


def yavg(img_path: Path) -> float:
    img = Image.open(img_path).convert("L")
    return float(np.mean(np.asarray(img)))
