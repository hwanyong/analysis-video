"""원본 비디오 → audio.wav(16kHz mono pcm) + video.mkv(무음, 스트림 카피).

프로토타입의 ffmpeg 서브프로세스 2회 호출과 동일한 산출물을 PyAV로 만든다.
비디오는 재인코딩 없이 패킷 리먹스(-c:v copy 상당)라 손실·시간왜곡이 없다.
"""
from pathlib import Path

import av
from av.codec.codec import UnknownCodecError


def split_media(video_path: Path, out_dir: Path) -> tuple[Path | None, Path]:
    """오디오 스트림이 없는 입력(무음 화면 녹화 등)은 (None, video)를 반환한다 —
    내부 오류가 아니라 정상 케이스로 취급하고 transcribe가 빈 전사로 잇는다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "audio.wav"
    video_only_path = out_dir / "video.mkv"
    with av.open(str(video_path)) as probe:
        has_audio = len(probe.streams.audio) > 0
    if has_audio:
        _extract_audio(video_path, audio_path)
    _copy_video(video_path, video_only_path)
    return (audio_path if has_audio else None), video_only_path


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
        try:
            out_stream = out.add_stream_from_template(in_stream)
        except UnknownCodecError:
            # AV1 등 디코더 이름(libdav1d)≠코덱 이름(av1)인 경우 템플릿 API가
            # 인코더 조회에 실패한다. canonical 이름으로 인코더를 해석해 스트림을
            # 만들고 코덱 파라미터를 직접 복사 — 패킷은 그대로 muxing되므로
            # 재인코딩은 일어나지 않는다 (인코더는 헤더 작성 시 초기화만 됨).
            enc_name = av.Codec(in_stream.codec_context.codec.canonical_name, "w").name
            out_stream = out.add_stream(enc_name)
            out_stream.time_base = in_stream.time_base
            cc_in, cc_out = in_stream.codec_context, out_stream.codec_context
            cc_out.width = cc_in.width
            cc_out.height = cc_in.height
            if cc_in.format is not None:
                cc_out.format = cc_in.format
            if cc_in.extradata:
                cc_out.extradata = cc_in.extradata
        for pkt in inp.demux(in_stream):
            if pkt.dts is None:
                continue
            pkt.stream = out_stream
            out.mux(pkt)
