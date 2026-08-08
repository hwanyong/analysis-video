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


def _matching_stream(out, in_stream):
    """원본과 같은 코덱·해상도로 담을 출력 스트림.

    템플릿 API를 먼저 쓴다. 인코더를 만들지 않으므로 코덱 파라미터가 원본 그대로
    보존된다 — 인코더를 세우면 그것이 자기 SPS/PPS로 헤더를 덮어써서 h264가
    깨진다(실측: extradata 44B→45B, 되읽기 패킷 15145→3408).

    폴백은 AV1처럼 디코더 이름(libdav1d)≠코덱 이름(av1)이라 템플릿이 인코더 조회에
    실패하는 경우다. 이때 `rate`를 반드시 넘겨야 한다 — 생략하면 PyAV 기본값 24가
    박혀 30fps 원본이 24fps로 선언되고, 선언 fps로 시각을 계산하는 소비자
    (scenedetect의 get_seconds는 프레임번호÷fps다)가 1.25배 어긋난 시각을 낸다.
    """
    try:
        return out.add_stream_from_template(in_stream)
    except UnknownCodecError:
        cc_in = in_stream.codec_context
        enc_name = av.Codec(cc_in.codec.canonical_name, "w").name
        out_stream = out.add_stream(enc_name, rate=in_stream.average_rate)
        out_stream.time_base = in_stream.time_base
        cc_out = out_stream.codec_context
        cc_out.width = cc_in.width
        cc_out.height = cc_in.height
        if cc_in.format is not None:
            cc_out.format = cc_in.format
        if cc_in.extradata:
            cc_out.extradata = cc_in.extradata
        return out_stream


def _copy_video(src: Path, dst: Path) -> None:
    with av.open(str(src)) as inp, av.open(str(dst), "w") as out:
        in_stream = inp.streams.video[0]
        out_stream = _matching_stream(out, in_stream)
        for pkt in inp.demux(in_stream):
            # demux는 끝에 빈 flush 패킷을 낸다 — 그것만 거른다.
            # dts만 보고 거르면 B-프레임 영상의 선두 패킷(dts=None)이 버려져
            # 첫 키프레임이 사라지고, 디코더가 앞부분 전체를 폐기한다(무성 손실).
            if pkt.size == 0:
                continue
            pkt.stream = out_stream
            out.mux(pkt)
