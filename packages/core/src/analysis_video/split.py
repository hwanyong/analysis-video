"""원본 비디오 → audio.wav(16kHz mono pcm) + video.mkv(무음, 스트림 카피).

프로토타입의 ffmpeg 서브프로세스 2회 호출과 동일한 산출물을 PyAV로 만든다.
비디오는 재인코딩 없이 패킷 리먹스(-c:v copy 상당)라 손실·시간왜곡이 없다.
"""
from pathlib import Path

import av


def split_media(video_path: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "audio.wav"
    video_only_path = out_dir / "video.mkv"
    _extract_audio(video_path, audio_path)
    _copy_video(video_path, video_only_path)
    return audio_path, video_only_path


def _extract_audio(src: Path, dst: Path) -> None:
    with av.open(str(src)) as inp, av.open(str(dst), "w") as out:
        out_stream = out.add_stream("pcm_s16le", rate=16000)
        out_stream.format = "s16"
        out_stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in inp.decode(audio=0):
            for rf in resampler.resample(frame):
                out.mux(out_stream.encode(rf))
        for rf in resampler.resample(None):
            out.mux(out_stream.encode(rf))
        out.mux(out_stream.encode(None))


def _copy_video(src: Path, dst: Path) -> None:
    with av.open(str(src)) as inp, av.open(str(dst), "w") as out:
        in_stream = inp.streams.video[0]
        out_stream = out.add_stream_from_template(in_stream)
        for pkt in inp.demux(in_stream):
            if pkt.dts is None:
                continue
            pkt.stream = out_stream
            out.mux(pkt)
