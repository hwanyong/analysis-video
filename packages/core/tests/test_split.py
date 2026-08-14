"""split 리먹스 무결성 — 분리된 video.mkv는 원본과 프레임이 1:1이어야 한다.

프레임이 유실되면 이후 모든 검출이 그 구간을 통째로 놓치는데, 산출물은 정상처럼
보인다(무성 데이터 손실). 특히 B-프레임 영상의 선두 패킷은 dts가 None으로 오므로
dts 유무로 패킷을 거르면 첫 키프레임이 사라진다.

자막 트랙이 split의 산출물에 더해지면서 반환이 (audio, video) 2원소에서
SplitResult 3원소가 됐다. 이 파일의 언패킹을 `res = split.split_media(...)` 뒤
필드 접근으로 바꾼 것은 그 때문이다 — 위치로 풀면 필드가 또 늘 때 같은 자리가
다시 터진다. 아래 자막 테스트들은 그 새 칸(SplitResult.subtitles)을 덮는다.
"""
from pathlib import Path

import av
import numpy as np
import pytest

from analysis_video import media, split
from analysis_video.stt import subtitles as sub


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


SRT_FIXTURE = """1
00:00:00,500 --> 00:00:01,500
첫 대사입니다

2
00:00:02,000 --> 00:00:03,000
두 번째 대사

3
00:00:03,200 --> 00:00:03,900
세 번째
"""

# ASS 트랙 — 오버라이드({\an8})·이스케이프(\N·\h)·벡터 드로잉({\p1})·마크업이
# 한 파일에 다 들어 있다. subrip 트랙은 이것들이 디코더 단계에서 이미 걷혀 와서
# split의 페이로드 해석을 덮지 못한다.
ASS_FIXTURE = r"""[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:01.50,Default,,0,0,0,,{\an8}첫 대사입니다
Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,{\i1}둘째{\i0}\N줄바꿈\h끝
Dialogue: 0,0:00:03.20,0:00:03.90,Default,,0,0,0,,{\p1}m 0 0 l 100 0 100 100{\p0}
Dialogue: 0,0:00:04.00,0:00:04.50,Default,,0,0,0,,a &lt; b 그리고 List<T>
"""


def _make_video_with_subtitles(path: Path, source: str, *, disposition: int,
                               language: str | None = None,
                               suffix: str = ".srt") -> None:
    """자막 트랙이 든 mkv를 **PyAV만으로** 만든다. suffix가 트랙 코덱을 정한다.

    ffmpeg CLI(`ffmpeg -i v -i a.srt -c:s srt`)로 만드는 편이 짧지만, 코어 CI는
    ubuntu·macOS·Windows 셋에서 도는데 ffmpeg 실행파일이 있는 건 ubuntu뿐이다.
    이 저장소가 PyAV로 통일한 이유(서브프로세스·실행파일 의존 제거)가 테스트에도
    그대로 적용된다.

    자막 **인코더**는 avcodec_open2가 실패해서(실측: subrip·mov_text 둘 다)
    add_stream("subrip")으로는 못 만든다. 대신 자막 파일 자체를 컨테이너로 열어
    (ffmpeg의 srt·ass 디먹서) add_stream_from_template로 그 스트림을 그대로
    복제하고 패킷을 옮겨 담는다 — split._copy_video가 비디오에 쓰는 것과 같은
    무인코딩 리먹스다."""
    # 중간 자막 파일은 영상 옆이 아니라 하위 디렉터리에 두고 다 쓰면 지운다. 영상과
    # 같은 어간으로 옆에 남겨 두면 그것이 **사이드카 자막**이 되어, 이 픽스처를
    # CLI 테스트에 쓰는 순간 내장 트랙보다 먼저 채택된다(사다리상 사이드카가
    # 내장보다 위다). 지금 이 파일에는 split만 있어 무해하지만, 조용히 엉뚱한
    # 경로를 검증하게 되는 종류의 함정이라 애초에 만들지 않는다.
    staging = path.parent / "_sub_source"
    staging.mkdir(exist_ok=True)
    srt_path = staging / f"{path.stem}{suffix}"
    srt_path.write_text(source, encoding="utf-8")
    with av.open(str(srt_path)) as sub_in:
        sub_stream = sub_in.streams.subtitles[0]
        with av.open(str(path), "w") as out:
            vs = out.add_stream("libx264", rate=10)
            vs.width, vs.height, vs.pix_fmt = 320, 180, "yuv420p"
            sub_out = out.add_stream_from_template(sub_stream)
            sub_out.disposition = disposition
            if language:
                sub_out.metadata["language"] = language
            for i in range(40):
                arr = np.full((180, 320, 3), 200, dtype=np.uint8)
                frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
                frame.pts = i
                for p in vs.encode(frame):
                    out.mux(p)
            for p in vs.encode(None):
                out.mux(p)
            for pkt in sub_in.demux(sub_stream):
                if pkt.size == 0:
                    continue
                pkt.stream = sub_out
                out.mux(pkt)
    srt_path.unlink()
    staging.rmdir()


@pytest.fixture
def source(tmp_path) -> Path:
    p = tmp_path / "src.mkv"
    _make_video(p)
    return p


def test_remux_preserves_every_frame(source, tmp_path):
    res = split.split_media(source, tmp_path / "out")

    original = [t for t, _ in media.decode_gray_frames(source)]
    remuxed = [t for t, _ in media.decode_gray_frames(res.video)]

    assert len(remuxed) == len(original), "리먹스에서 프레임이 유실되면 안 된다"
    assert remuxed[0] == pytest.approx(original[0], abs=0.01), "선두 프레임 보존"
    assert remuxed[-1] == pytest.approx(original[-1], abs=0.01), "말미 프레임 보존"


def test_remux_has_no_audio(source, tmp_path):
    res = split.split_media(source, tmp_path / "out")
    with av.open(str(res.video)) as c:
        assert not c.streams.audio, "video.mkv는 무음이어야 한다"


def test_silent_video_returns_no_audio(source, tmp_path):
    out = tmp_path / "out"
    res = split.split_media(source, out)
    assert res.has_audio is False, "오디오 스트림이 없는 입력은 has_audio=False를 반환"
    assert res.video.exists()


def test_split_never_writes_an_audio_file(source, tmp_path):
    """오디오는 **파일로 뽑지 않는다.**

    whisper가 원본 컨테이너를 직접 디코드하므로(media.load_audio_mono16k는
    컨테이너를 가리지 않고 같은 배열을 만든다 — 실측 3편 비트 동일) audio.wav는
    아무도 읽지 않는 순수 중간 산물이었고, 분석 디렉터리의 33%(분당 1.92MB)를
    차지했다. 되살아나도 다른 테스트는 아무것도 못 느끼므로 여기서 잠근다.

    파일명 하나만 보지 않고 디렉터리 전체를 보는 이유: `audio.m4a`처럼 확장자만
    다른 것으로 되살아나면 audio.wav만 보는 단정은 그대로 통과한다."""
    out = tmp_path / "out"
    split.split_media(source, out)

    assert not (out / "audio.wav").exists()
    assert sorted(p.name for p in out.iterdir()) == ["video.mkv"], \
        "무자막·무음 입력에서 split이 만드는 것은 video.mkv 하나뿐이다"


def test_video_without_subtitles_reports_empty_list(source, tmp_path):
    """자막이 없어도 None이 아니라 []. 소비자가 '자막 없음'과 '자막을 안 봤음'을
    구분할 수 있어야 한다. 이 칸이 항상 있으므로 전사 스테이지는 키의 유무를
    방어하지 않고 곧장 첨자로 읽는다(stt.subtitles.embedded_candidates)."""
    out = tmp_path / "out"
    res = split.split_media(source, out)
    assert res.subtitles == []
    assert not (out / split.SUBS_DIRNAME).exists(), \
        "자막이 하나도 없으면 subs/ 디렉터리를 만들지 않는다"


def test_text_track_is_rewritten_as_srt(tmp_path):
    """텍스트 자막 트랙은 코덱과 무관하게 SRT 한 포맷으로 나오고, 파일 이름은
    열거 순번이 아니라 컨테이너 스트림 인덱스를 쓴다(transcript.json의
    source.track과 같은 값이어야 산출물에서 원본 트랙으로 되짚을 수 있다)."""
    src = tmp_path / "with_subs.mkv"
    _make_video_with_subtitles(src, SRT_FIXTURE, disposition=split.DISP_DEFAULT,
                               language="kor")
    out = tmp_path / "out"
    res = split.split_media(src, out)

    assert len(res.subtitles) == 1
    entry = res.subtitles[0]
    assert entry["skipped"] is None
    assert entry["default"] is True and entry["forced"] is False
    assert entry["language"] == "kor"
    assert entry["format"] == split.SUBS_FORMAT
    assert entry["n_cues"] == 3
    assert Path(entry["path"]) == out / split.SUBS_DIRNAME / f"track{entry['track']}.srt"

    text = Path(entry["path"]).read_text(encoding="utf-8")
    assert "첫 대사입니다" in text and "세 번째" in text
    assert "00:00:00,500 --> 00:00:01,500" in text, "원본 큐 시각이 보존돼야 한다"


def test_forced_track_is_listed_but_not_extracted(tmp_path):
    """강제 자막은 외국어 구간만 담아 대사의 일부만 있다 — 뽑지 않는다.

    그렇다고 목록에서 지우지도 않는다. 지우면 "이 영상에는 강제 자막밖에
    없었다"는 사실이 어디에도 남지 않아, 나중에 산출물만 보고는 whisper가 돈
    이유를 설명할 수 없다."""
    src = tmp_path / "forced.mkv"
    _make_video_with_subtitles(src, SRT_FIXTURE, disposition=split.DISP_FORCED)
    out = tmp_path / "out"
    res = split.split_media(src, out)

    assert len(res.subtitles) == 1, "못 뽑은 트랙도 목록에는 남는다"
    entry = res.subtitles[0]
    assert entry["forced"] is True
    assert entry["skipped"] and "강제 자막" in entry["skipped"]
    assert entry["path"] is None and entry["n_cues"] == 0
    assert not (out / split.SUBS_DIRNAME).exists(), \
        "뽑을 트랙이 하나도 없으면 subs/를 만들지 않는다"


class _FakeRect:
    """자막 rect 중 split이 읽는 것은 dialogue 하나뿐이다."""

    def __init__(self, dialogue: str | bytes) -> None:
        self.dialogue = dialogue


@pytest.mark.parametrize("payload, expected", [
    # 이 규칙의 핵심. 강의 자막에는 코드가 나오므로 오버라이드가 아닌 중괄호를
    # 지우면 본문이 통째로 사라진다.
    ("if (n > 0) {return x;}", "if (n > 0) {return x;}"),
    ('설정은 { "key": 1 } 형태입니다', '설정은 { "key": 1 } 형태입니다'),
    # 지울 것은 여는 중괄호 뒤에 역슬래시가 오는 ASS 오버라이드뿐이다.
    (r"{\an8}위치 지정 대사", "위치 지정 대사"),
    (r"{\i1}기울임{\i0} 뒤", "기울임 뒤"),
    (r"{\an8}", ""),                        # 오버라이드밖에 없으면 대사가 아니다
    (r"{\p1}m 0 0 l 100 0{\p0}", ""),       # 벡터 드로잉 — 좌표는 대사가 아니다
    (r"첫 줄\N둘째 줄", "첫 줄\n둘째 줄"),   # 하드 줄바꿈은 큐 안에서 살린다
    (r"a\hb", "a b"),                       # 고정폭 공백
    # 마크업 정제는 사이드카 자막과 같은 규칙을 쓰되(태그는 걷고, 태그가 아닌
    # 부등호·제네릭 표기는 본문으로 남긴다) **엔티티는 여기서 풀지 않는다** —
    # 이 산출물을 되읽는 transcribe가 정제를 한 번 더 걸기 때문이다.
    ("<i>기울임</i>과 List<T>, a &lt; b", "기울임과 List<T>, a &lt; b"),
])
def test_rect_text_strips_only_ass_overrides(payload, expected):
    """오버라이드가 아닌 중괄호를 지우면 강의 자막의 코드가 본문째 사라진다.

    컨테이너를 거치는 테스트로는 이 규칙을 고정할 수 없다: PyAV의 rect.dialogue가
    오버라이드가 아닌 `{...}`를 ASS 주석으로 보고 먼저 지워 버려(실측) 코드가 든
    페이로드는 _rect_text까지 오지 않는다. 그 상류 동작에 기대면 PyAV가 규칙을
    바꾸는 날 split이 조용히 본문을 먹으므로, split 자신의 규칙을 여기서 못박는다.

    같은 페이로드를 str과 bytes 둘로 넣는다 — 디코더·PyAV 버전에 따라 dialogue가
    둘 중 하나로 오고, 한쪽만 검증하면 나머지 경로가 비어 있는 채로 남는다."""
    assert split._rect_text(_FakeRect(payload)) == expected
    assert split._rect_text(_FakeRect(payload.encode("utf-8"))) == expected


def test_ass_track_drops_markup_but_keeps_dialogue(tmp_path):
    """ASS 트랙 실측 경로 — 스타일은 사라지고 대사만 subs/track{n}.srt에 남는다.

    좌표뿐인 rect({\\p1} 드로잉)는 큐로 세지 않는다. 세면 "m 0 0 l 100 0"이
    대사로 전사에 실리고, 자막 채택 판정의 근거인 커버리지까지 부풀린다."""
    src = tmp_path / "styled.mkv"
    _make_video_with_subtitles(src, ASS_FIXTURE, disposition=split.DISP_DEFAULT,
                               suffix=".ass")
    out = tmp_path / "out"
    res = split.split_media(src, out)

    assert len(res.subtitles) == 1
    entry = res.subtitles[0]
    assert entry["skipped"] is None
    assert entry["n_cues"] == 3, "드로잉 전용 rect는 큐가 아니다"

    text = Path(entry["path"]).read_text(encoding="utf-8")
    assert "{" not in text and "m 0 0 l" not in text, "스타일·좌표가 산출물에 남으면 안 된다"
    assert "첫 대사입니다" in text
    assert "둘째\n줄바꿈 끝" in text, r"\N은 줄바꿈으로, \h는 공백으로 푼다"
    assert "a &lt; b 그리고 List<T>" in text, \
        "엔티티는 여기서 풀지 않는다 — 되읽는 쪽이 한 번만 푼다"

    # 왕복 계약. 이 산출물은 밖에서 받아 온 SRT와 **구분 없이** 취급되므로
    # 정제가 split·transcribe 두 번 돈다. html.unescape는 멱등이 아니라, 양쪽에서
    # 풀면 글자로 적은 엔티티가 2차에서 진짜 태그가 되어 본문째 사라진다.
    # 여기가 그 왕복을 실제로 밟는 유일한 자리다.
    cues, _ = sub.parse(text, "srt")
    assert any("a < b 그리고 List<T>" in c.text for c in cues), \
        "되읽으면 엔티티가 정확히 한 번 풀린다"
