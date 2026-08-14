"""원본 비디오 → 분석이 소비하는 리소스들로 가른다.

    video.mkv           무음·스트림 카피        — 프레임 검출 입력
    subs/track{n}.srt   컨테이너 안에 있던 텍스트 자막 트랙 — 전사 후보

비디오는 재인코딩 없이 패킷 리먹스(-c:v copy 상당)라 손실·시간왜곡이 없다.

**오디오는 파일로 뽑지 않는다.** 프로토타입이 ffmpeg를 두 번 불러 audio.wav를
만들던 것을 그대로 옮겨 적었었는데, 전사 백엔드에 닿는 입력은 그 파일이 아니라
`media.load_audio_mono16k`가 만드는 배열이고 **그 함수는 컨테이너 종류를 가리지
않는다** — 원본에서 바로 뽑은 배열과 audio.wav를 거친 배열이 비트 단위로 같다
(실측 3편, 최대차 0.0). 즉 audio.wav는 순수 중간 산물이었다.

없애는 이유는 용량만이 아니다. 자막 사다리가 이기면 그 파일은 **한 번도 읽히지
않는데**(실측 6편 중 3편, 26MB), 그때 audio.wav를 남겨 두면 "오디오 스트림이
없다"와 "있는데 아직 안 뽑았다"를 가르는 세 번째 상태가 필요해진다. 만들지
않으면 split이 답할 질문이 **"오디오 스트림이 있는가"** 하나로 줄고, 그 답은
불리언 하나로 정확히 표현된다. 분당 1.92MB(분석 디렉터리의 33%)는 덤이다.

**자막을 여기서 뽑는 이유.** 자막은 오디오와 같은 층위의 *컨테이너 안 리소스*이고,
split은 컨테이너를 리소스로 가르는 스테이지다. 전사 스테이지가 필요할 때 원본을
다시 열어 찾게 두면 "이 영상에 무엇이 들어 있었는가"가 state.json에 남지 않아,
나중에 산출물만 보고는 **자막이 없어서 whisper가 돌았는지, 자막이 있었는데
거부됐는지, 아예 보지도 않았는지**를 구분할 수 없다. split이 전수 열거해 남기면
채택·거부 판단은 전사 스테이지 하나에만 존재한다.

**자막 큐 경계는 화면 검출 신호로 쓰지 않는다.** 자막이 여기로 들어오지만 그것이
닿는 곳은 대사 트랙뿐이다. 텍스트만으로 고른 시각이 시각적 검출과 같은 자리를
놓고 경쟁하면 기준이 흐려진다 — cli.py 머리말이 points.json을 폐기한 사유와
같은 고장이다.
"""
import re
from pathlib import Path
from typing import NamedTuple

import av
from av.codec.codec import UnknownCodecError

# 자막 페이로드의 마크업·엔티티 정제는 stt.subtitles가 단일 출처다 — 사이드카
# 자막과 내장 트랙이 같은 규칙을 받아야 하고, 규칙을 두 곳에 적으면 한쪽만 바뀐다.
# 의존 방향은 split → stt 한쪽뿐이라(stt는 split을 부르지 않는다) 순환하지 않는다.
from .stt.subtitles import clean_text

# 자막 산출 디렉터리와 파일명 규약: out_dir/subs/track{스트림 인덱스}.srt.
# 번호는 열거 순번이 아니라 **컨테이너 스트림 인덱스**다 — transcript.json의
# source.track과 같은 값이어야 산출물에서 원본 트랙으로 되짚을 수 있고,
# 트랙 구성이 다른 영상끼리 파일명이 우연히 같아지는 일도 없다.
SUBS_DIRNAME = "subs"
SUBS_FORMAT = "srt"

# libavformat AV_DISPOSITION_* 비트. PyAV 버전에 따라 stream.disposition이 정수이거나
# IntFlag라 열거형 이름에 기대지 않고 비트로 읽는다(어느 쪽이든 &가 통한다).
DISP_DEFAULT = 0x0001
DISP_FORCED = 0x0040
DISP_HEARING_IMPAIRED = 0x0080

# 표시 시간을 알 수 없는 큐에 줄 길이. subrip·ass·mov_text·webvtt는 모두 패킷에
# duration이 실려 오므로 실제로는 거의 쓰이지 않는 방어값이다. 다음 큐 시작까지로
# 늘리지 않고 여기서 자르는 이유: 다음 큐가 한참 뒤면 그 침묵 전체가 "말하고 있던
# 시간"으로 잡혀 coverage(자막 채택 판정의 근거)가 부풀고, 부푼 coverage는 거부해야
# 할 자막을 통과시킨다. 모자란 쪽으로 틀리는 편이 안전하다.
FALLBACK_CUE_SECONDS = 2.0

# 벡터 드로잉 모드({\p1} 이후는 텍스트가 아니라 좌표열이다). 간판·타이포세팅용이라
# 대사가 아니며, 오버라이드 블록만 걷어내면 "m 0 0 l 100 0" 같은 좌표가 전사에 섞인다.
# 정제가 아니라 rect 하나를 통째로 버리는 판단이라 페이로드를 아는 이 자리에 둔다.
_ASS_DRAWING = re.compile(r"\{[^}]*\\p[1-9]")


class SplitResult(NamedTuple):
    """split 스테이지가 알아낸 것과 만든 것.

    첫 칸이 `audio: Path | None`(뽑아 둔 파일의 경로)에서 `has_audio: bool`(원본에
    오디오 스트림이 있는가)로 바뀌었다. 경로였을 때 그 값은 **사실과 위치를 한 칸에
    겹쳐 담고** 있었고, 소비자가 실제로 묻는 것은 사실 쪽 하나뿐이다
    (cli._audio_transcript: 있으면 whisper, 없으면 빈 전사).

    이름까지 바꾼 것은 의도다. 칸 이름을 두고 타입만 불리언으로 바꾸면
    `if outputs["audio"]:`로 읽던 코드가 조용히 통과한다 — 깨져야 할 자리가
    안 깨진다."""
    has_audio: bool
    video: Path
    subtitles: list[dict]


def split_media(video_path: Path, out_dir: Path) -> SplitResult:
    """오디오 스트림이 없는 입력(무음 화면 녹화 등)은 has_audio=False를 반환한다 —
    내부 오류가 아니라 정상 케이스로 취급하고 transcribe가 자막이나 빈 전사로 잇는다.

    subtitles는 **자막이 없어도 빈 리스트**로 항상 반환한다. None과 []를 섞으면
    소비자가 "자막 없음"과 "자막을 안 봤음"을 구분하지 못한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    video_only_path = out_dir / "video.mkv"
    with av.open(str(video_path)) as probe:
        has_audio = len(probe.streams.audio) > 0
    _copy_video(video_path, video_only_path)
    subtitles = extract_subtitles(video_path, out_dir)
    return SplitResult(has_audio, video_only_path, subtitles)


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


# ---------- 내장 자막 트랙 ----------

def extract_subtitles(video_path: Path, out_dir: Path) -> list[dict]:
    """컨테이너의 자막 트랙을 **전부 열거하고**, 쓸 수 있는 것만 파일로 뽑는다.

    반환은 트랙 하나당 dict 하나:

        {"track": int,               # 컨테이너 스트림 인덱스 (source.track과 동일)
         "codec": str,               # 원본 코덱 (subrip·mov_text·ass·hdmv_pgs_subtitle …)
         "language": str | None,     # 트랙이 선언한 언어. "und"는 None으로 정규화
         "title": str | None,        # 트랙 제목 (mkv의 title 태그)
         "default": bool,            # 재생기가 기본으로 켜는 트랙인가
         "forced": bool,
         "hearing_impaired": bool,   # SDH — [웃음] 같은 비언어 표기가 섞인다
         "path": str | None,         # 뽑아 둔 SRT 절대경로. 안 뽑았으면 None
         "format": str | None,       # 뽑았으면 "srt"
         "n_cues": int,
         "skipped": str | None,      # 미추출 사유(한국어). None이면 채택 후보
         "notes": [str]}             # 추출 중 생긴 특이사항(한국어)

    flags와 notes를 나눠 둔 것은 의도적이다: 불리언 필드는 **사실**(컨테이너가
    선언한 성질)이고 notes는 **사건**(뽑는 도중 무엇을 잃었는가)이다. 사실을
    한국어 문장으로 중복해 적으면 둘이 갈린다.

    **거부가 아니라 열거다.** 못 뽑은 트랙도 사유를 달아 남긴다 — 목록에서 지우면
    "이 영상에는 강제 자막밖에 없었다"는 사실이 어디에도 남지 않아 whisper가 돈
    이유를 사후에 설명할 수 없다. metadata의 rejected[]와 같은 규약이다.

    path를 Path가 아니라 str로 내는 이유: 이 목록은 그대로 state.json에 실린다
    (split 스테이지 outputs). JSON 직렬화 가능한 값만 담는다."""
    with av.open(str(video_path)) as probe:
        entries = [_describe_track(s) for s in probe.streams.subtitles]
    for entry in entries:
        if entry["skipped"] is None:
            _extract_track(video_path, out_dir, entry)
    return entries


def _describe_track(stream) -> dict:
    """스트림 메타데이터만으로 만드는 트랙 기술 — 디코드 전에 채택 여부를 가른다.

    두 가지를 여기서 떨어뜨린다:

    - **비트맵 자막**(dvd_subtitle·hdmv_pgs_subtitle·dvb_subtitle 등)은 글자가 아니라
      그림이다. 텍스트를 얻으려면 OCR이 필요한데 그건 이 도구가 하는 일이 아니고,
      OCR 오독이 섞인 문장은 whisper 전사보다 나을 이유가 없다.
      코덱 이름 목록을 박지 않고 ffmpeg이 코덱마다 선언해 둔 성질(text_sub)을 읽는다 —
      목록은 새 코덱이 생길 때마다 조용히 낡는다.
    - **forced 자막**은 외국어 대사·간판처럼 특정 구간만 나오도록 만들어진 트랙이라
      대사의 일부만 담는다. 그것을 전사로 채택하면 나머지 구간이 통째로 침묵으로
      기록된다. disposition은 컨테이너가 성실히 채웠을 때만 맞는 신호라서
      전사 스테이지의 coverage 하한이 뒤에서 한 번 더 받아 준다 — 여기는 값이
      있을 때 확실히 거르는 첫 관문이다.

    hearing_impaired(SDH)는 거르지 않고 표시만 한다. [웃음] 같은 비언어 표기가
    섞이긴 해도 대사 자체는 전 구간을 덮으므로, 그 표기를 어떻게 다룰지는
    자막을 읽는 쪽의 정제 문제이지 트랙을 버릴 이유는 아니다."""
    disposition = int(stream.disposition or 0)
    meta = dict(stream.metadata or {})
    language = meta.get("language") or None
    if language in ("und", "unknown"):
        # 'und'(undetermined)는 컨테이너가 언어 칸을 채우지 못했다는 뜻이다.
        # 그대로 두면 소비자가 'und'라는 언어가 있는 줄 안다.
        language = None

    entry = {
        "track": stream.index,
        "codec": _codec_name(stream),
        "language": language,
        "title": meta.get("title") or None,
        "default": bool(disposition & DISP_DEFAULT),
        "forced": bool(disposition & DISP_FORCED),
        "hearing_impaired": bool(disposition & DISP_HEARING_IMPAIRED),
        "path": None,
        "format": None,
        "n_cues": 0,
        "skipped": None,
        "notes": [],
    }

    is_text = _is_text_subtitle(stream)
    if is_text is None:
        entry["skipped"] = (f"코덱 '{entry['codec']}'을 판정할 수 없습니다 "
                            "(이 환경의 ffmpeg에 해당 디코더가 없음)")
    elif not is_text:
        entry["skipped"] = f"비트맵 자막({entry['codec']}) — 이미지라 전사로 쓸 수 없습니다"
    elif entry["forced"]:
        entry["skipped"] = "강제 자막(forced) — 일부 구간의 대사만 담고 있습니다"
    return entry


def _codec_name(stream) -> str:
    try:
        return stream.codec_context.name
    except Exception:
        return "unknown"


def _is_text_subtitle(stream) -> bool | None:
    """텍스트 자막인가. 판정 불가면 None — False(비트맵 단정)와 구분한다."""
    try:
        return bool(stream.codec_context.codec.text_sub)
    except Exception:
        # 디코더 부재(UnknownCodecError)·PyAV 버전차 등. 아는 척하지 않는다.
        return None


def _extract_track(video_path: Path, out_dir: Path, entry: dict) -> None:
    """텍스트 자막 트랙 하나 → out_dir/subs/track{n}.srt. entry를 제자리에서 채운다.

    **원본 코덱을 그대로 복사하지 않고 SRT로 다시 쓴다.** 스트림 복사는 코덱과
    컨테이너가 맞을 때만 성립한다: mkv 안의 subrip은 .srt로 나가지만 mp4의
    mov_text는 갈 곳이 없고 ass는 .ass로만 간다 — 출처마다 다른 포맷이 나오면
    읽는 쪽이 포맷별 파서를 전부 갖춰야 한다. 반면 ffmpeg의 텍스트 자막 디코더는
    코덱과 무관하게 전부 ASS rect로 내놓으므로(실측: mkv+subrip, mp4+mov_text 둘 다
    AssSubtitle) 디코드 경로도 하나, 산출 포맷도 하나로 모인다. 사이드카 자막
    파일과 같은 파서를 타게 되는 것도 이 선택의 결과다.

    스타일(<i>, {\\an8})은 이 왕복에서 사라진다. 우리가 원하는 것은 대사 텍스트라
    잃는 것이 없다 — 오히려 전사에 마크업이 섞이지 않아 정제가 준다."""
    cues, notes = _decode_cues(video_path, entry["track"])
    entry["notes"].extend(notes)
    if not cues:
        entry["skipped"] = "큐를 하나도 읽지 못했습니다"
        return
    subs_dir = out_dir / SUBS_DIRNAME
    subs_dir.mkdir(parents=True, exist_ok=True)
    path = subs_dir / f"track{entry['track']}.{SUBS_FORMAT}"
    path.write_text(_to_srt(cues), encoding="utf-8")
    entry["path"] = str(path)
    entry["format"] = SUBS_FORMAT
    entry["n_cues"] = len(cues)


def _decode_cues(video_path: Path, track: int) -> tuple[list[dict], list[str]]:
    """트랙 하나를 디코드해 (큐 목록, 특이사항 메모).

    트랙마다 컨테이너를 다시 여는 이유: demux는 스트림 끝까지 읽고 나면 파일
    포인터가 EOF에 있어, 같은 컨테이너로 두 번째 트랙을 요청하면 아무것도 나오지
    않는다. seek로 되감을 수도 있지만 자막 트랙 디먹스는 비용이 거의 없어
    (수 KB) 다시 여는 쪽이 훨씬 덜 미끄럽다.

    container.decode(stream)이 아니라 demux를 쓰는 이유: PyAV의 자막 디코드는
    rect 목록만 돌려주고 rect에는 시각이 없다. 시각은 패킷에만 있다."""
    cues: list[dict] = []
    notes: list[str] = []
    n_undecodable = 0
    with av.open(str(video_path)) as container:
        # 위치가 아니라 스트림 인덱스로 찾는다 — 둘은 보통 같지만 같다고 가정할
        # 근거가 없고, 어긋나면 엉뚱한 트랙의 자막을 그 트랙 이름으로 저장한다.
        stream = next(s for s in container.streams.subtitles if s.index == track)
        for pkt in container.demux(stream):
            # 끝의 빈 flush 패킷과 시각을 모르는 패킷은 큐가 될 수 없다.
            if pkt.size == 0 or pkt.pts is None or pkt.time_base is None:
                continue
            try:
                rects = pkt.decode()
            except Exception:
                # 패킷 하나가 깨졌다고 트랙 전체를 버리지 않는다 — 자막은 큐마다
                # 독립이라 나머지는 그대로 쓸 수 있다. 대신 몇 개를 잃었는지 남긴다.
                n_undecodable += 1
                continue
            text = "\n".join(t for t in (_rect_text(r) for r in rects) if t)
            if not text:
                # 화면을 지우는 빈 패킷(mov_text는 큐 사이마다 넣는다)이거나
                # 드로잉 전용 rect다. 큐가 아니다.
                continue
            start = float(pkt.pts * pkt.time_base)
            span = float(pkt.duration * pkt.time_base) if pkt.duration else 0.0
            cues.append({"start": max(start, 0.0),
                         "end": start + span if span > 0 else None,
                         "text": text})
    if n_undecodable:
        notes.append(f"디코드하지 못한 패킷 {n_undecodable}건을 건너뛰었습니다")
    return _close_open_cues(cues), notes


def _close_open_cues(cues: list[dict]) -> list[dict]:
    """끝 시각이 없는 큐를 닫는다. 디먹스 순서를 믿지 않고 시작 시각으로 정렬한다."""
    cues.sort(key=lambda c: c["start"])
    for i, cue in enumerate(cues):
        if cue["end"] is not None:
            continue
        limit = cue["start"] + FALLBACK_CUE_SECONDS
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        cue["end"] = min(limit, nxt) if nxt is not None else limit
    return cues


def _rect_text(rect) -> str:
    """자막 rect 하나 → 대사 한 덩어리. 대사가 아니면 빈 문자열.

    ass가 아니라 dialogue를 읽는다 — ass는 "0,0,Default,,0,0,0,,본문" 형태로
    스타일 필드가 앞에 붙어 있고 dialogue는 그 뒤 본문만이다. (TextSubtitle 쪽
    text는 최신 ffmpeg에서 늘 비어 있다: 텍스트 자막 디코더가 전부 ASS로 낸다.)

    마크업·엔티티 정제는 clean_text가 한다. 이 자리에 자체 규칙을 두면 사이드카
    자막과 내장 트랙의 정제가 갈리고, 특히 `{...}`를 통째로 지우는 규칙은 강의
    자막에 흔한 `{return x;}` 같은 코드를 본문째 날린다 — clean_text가 여는
    중괄호 **뒤에 역슬래시**가 오는 오버라이드 블록만 지우는 것이 그 이유다.
    정제를 파일로 쓰기 전에 끝내는 이유는 두 가지다: 정제 결과가 비어야 대사가
    없는 rect(mov_text가 큐 사이에 넣는 화면 지우기 패킷 등)를 걸러 낼 수 있고,
    subs/track{n}.srt 자체가 마크업 없는 산출물이어야 한다.

    ASS 이스케이프만 여기서 푼다 — 페이로드 문법이라 clean_text가 모르고,
    clean_text는 큐 하나를 한 줄로 접으므로 줄 구분도 여기서만 지킬 수 있다."""
    dialogue = getattr(rect, "dialogue", None)
    if dialogue is None:
        return ""  # 비트맵 rect — 여기까지 오지 않아야 하지만 방어
    s = dialogue.decode("utf-8", "replace") if isinstance(dialogue, bytes) else str(dialogue)
    if _ASS_DRAWING.search(s):
        return ""
    # \N(강제 줄바꿈)은 dialogue 단계에서 이미 개행으로 바뀌어 오지만, \n(소프트
    # 줄바꿈)과 \h(고정폭 공백)는 그대로 남는다.
    s = s.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    # 엔티티 해제만 끈다. 이 산출물(subs/track{n}.srt)은 transcribe가 사이드카와
    # 구분 없이 되읽으므로 clean_text가 한 번 더 걸리는데, html.unescape는 멱등이
    # 아니라 여기서 풀면 글자로 적은 `&amp;lt;i&amp;gt;`가 2차에서 진짜 태그가 되어
    # 본문째 사라진다. 푸는 자리는 읽는 쪽 한 곳뿐이어야 한다.
    return "\n".join(t for t in (clean_text(line, unescape=False)
                                 for line in s.splitlines()) if t)


def _to_srt(cues: list[dict]) -> str:
    blocks = [f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{c['text']}\n"
              for i, c in enumerate(cues, start=1)]
    return "\n".join(blocks)


def _srt_time(t: float) -> str:
    ms = max(int(round(t * 1000)), 0)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
