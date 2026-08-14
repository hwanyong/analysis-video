"""자막 파싱·검증 — 무엇을 받고 무엇을 거부하는가.

이 모듈의 시험은 두 갈래다. 하나는 "원문을 그대로 옮겼는가"(포맷 3종·인코딩·
마크업), 다른 하나는 "써도 되는 자막인가"(자동 생성·강제 자막·남의 자막 거부).
뒤쪽이 더 중요하다 — 잘못 파싱하면 대사가 이상해지고 끝이지만, 잘못 채택하면
사용자가 명시적으로 배제한 ASR 결과가 원문인 척 파이프라인 전체에 실린다.
"""
from pathlib import Path

import pytest
from analysis_video.stt import base
from analysis_video.stt import subtitles as sub


def _srt(n=6, step=5.0, length=4.0, body="대사 {i}"):
    """정상 SRT — 60초 영상 기준 커버리지 0.4로 검증을 통과한다."""
    out = []
    for i in range(n):
        start, end = i * step, i * step + length
        out.append(f"{i + 1}\n{_ts(start, ',')} --> {_ts(end, ',')}\n{body.format(i=i)}\n")
    return "\n".join(out)


def _ts(t: float, sep=","):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{round(t % 1 * 1000):03d}"


# ─── 포맷 3종 ────────────────────────────────────────────────────────────
def test_srt_parses_times_and_strips_markup():
    """SRT 마크업(<i>, <font>, ASS 오버라이드)은 본문에 남으면 안 된다 —
    context.py가 text를 그대로 AI에게 넘긴다."""
    text = ("1\n00:00:01,000 --> 00:00:04,500\n<i>안녕하세요</i> 여러분\n\n"
            "2\n00:01:05,250 --> 00:01:09,000\n"
            "{\\an8}오늘은 <font color=\"#ffffff\">정렬</font>을 봅니다\n")
    cues, notes = sub.parse(text, "srt")
    assert notes == []
    assert [(c.start, c.end) for c in cues] == [(1.0, 4.5), (65.25, 69.0)]
    assert cues[0].text == "안녕하세요 여러분"
    assert cues[1].text == "오늘은 정렬을 봅니다"


def test_srt_keeps_braces_that_are_not_ass_overrides():
    """강의 자막에는 코드가 나온다. `{ ... }`를 무조건 지우면 본문이 사라진다."""
    text = "1\n00:00:01,000 --> 00:00:04,000\n{\\an8}함수는 {return x;} 로 끝납니다\n"
    cues, _ = sub.parse(text, "srt")
    assert cues[0].text == "함수는 {return x;} 로 끝납니다"


def test_vtt_skips_headers_and_settings_and_keeps_speaker():
    """WEBVTT 머리말·NOTE·STYLE 블록, 큐 식별자, 큐 설정은 큐가 아니다.
    화자(<v 이름>)는 text 안에 남긴다 — segments의 별도 키에 두면 context.md가
    렌더하지 않아 AI에게 닿지 않는다."""
    text = ("WEBVTT - 강의\n\n"
            "NOTE 이 줄은 큐가 아니다\n\n"
            "STYLE\n::cue { color: white }\n\n"
            "intro\n00:00:01.000 --> 00:00:03.000 line:0 position:50% align:start\n"
            "<v 강사>오늘은 <c.highlight>정렬</c>을 봅니다\n\n"
            "01:05.500 --> 01:09.000\n두 번째 줄\n계속되는 줄\n")
    cues, _ = sub.parse(text, "vtt")
    assert len(cues) == 2, [c.text for c in cues]
    assert cues[0].text == "강사: 오늘은 정렬을 봅니다"
    # 시:분:초가 아니라 분:초로 적힌 VTT도 받는다
    assert (cues[1].start, cues[1].end) == (65.5, 69.0)
    assert cues[1].text == "두 번째 줄 계속되는 줄"


def test_windows_line_endings_and_bom(tmp_path):
    """SRT는 대부분 윈도우 도구가 만든다 — CRLF와 BOM이 기본값이다. 줄 끝을
    정규화하지 않으면 블록이 갈리지 않아 파일 전체가 큐 0개로 나온다."""
    path = tmp_path / "lecture.srt"
    path.write_bytes(_srt().replace("\n", "\r\n").encode("utf-8-sig"))
    result, notes = sub.result_from_file(path, duration=60.0, kind="explicit")
    assert result is not None, notes
    assert result["source"]["n_cues"] == 6
    assert result["segments"][0]["text"] == "대사 0"


def test_entities_are_unescaped_after_tags_are_removed():
    """작성자가 글자로 적은 `&lt;i&gt;`는 태그가 아니다. 엔티티를 먼저 풀면
    그것이 진짜 태그로 둔갑해 본문이 지워진다."""
    text = ("1\n00:00:01,000 --> 00:00:04,000\n"
            "&lt;i&gt;기울임&lt;/i&gt; 태그와 A&amp;B, &quot;인용&quot;\n")
    cues, _ = sub.parse(text, "srt")
    assert cues[0].text == '<i>기울임</i> 태그와 A&B, "인용"'


def test_entity_unescape_happens_exactly_once_across_stages():
    """`&amp;lt;i&amp;gt;`는 "화면에 &lt;i&gt;라고 보여 준다"는 뜻이고, 마크업을
    설명하는 강의 자막에 실제로 나온다. html.unescape는 멱등이 아니라 걸 때마다
    한 겹씩 벗겨진다 — 그런데 내장 트랙은 split이 정제해 파일로 쓰고 transcribe가
    그 파일을 사이드카와 구분 없이 되읽으므로 정제가 두 번 돈다. 그래서 푸는 자리는
    읽는 쪽 한 곳뿐이어야 한다."""
    payload = "&amp;lt;i&amp;gt; 는 이탤릭 태그다"

    # 쓰는 쪽(split)은 풀지 않는다 — 글자가 그대로 남아 SRT로 나간다
    written = sub.clean_text(payload, unescape=False)
    assert written == payload
    # 읽는 쪽(파서)이 한 번만 푼다 → 작성자가 의도한 화면 그대로
    assert sub.clean_text(written) == "&lt;i&gt; 는 이탤릭 태그다"

    # 양쪽에서 풀면 어떻게 망가지는지를 고정한다 — unescape 인자가 있는 이유다.
    twice = sub.clean_text(sub.clean_text(payload))
    assert twice == "<i> 는 이탤릭 태그다"          # 글자였던 것이 진짜 태그가 됐다
    assert sub.clean_text(twice) == "는 이탤릭 태그다"  # 다음 정제에서 본문째 사라진다


# ─── SMI: 종료 시각 유도 ─────────────────────────────────────────────────
SMI_DOC = """<SAMI>
<HEAD>
<STYLE TYPE="text/css">
<!--
P { margin-left: 8pt; }
.KRCC { Name: 한국어; lang: ko-KR; }
-->
</STYLE>
</HEAD>
<BODY>
<SYNC Start=1000><P Class=KRCC>첫 번째 대사입니다
<SYNC Start=3000><P Class=KRCC>&nbsp;
<SYNC Start=20000><P Class=KRCC>한참 뒤의<br>두 번째 대사
<SYNC Start=23000><P Class=KRCC>&nbsp;
</BODY>
</SAMI>
"""


def test_smi_end_comes_from_the_blank_cue():
    """SMI에는 종료 시각이 없다. 빈 큐(&nbsp;)를 못 거르면 첫 대사가 20초까지
    늘어나 그동안의 다른 화면에 통째로 배정된다 — 이 모듈에서 제일 위험한 곳."""
    cues, _ = sub.parse(SMI_DOC, "smi")
    assert len(cues) == 2
    assert (cues[0].start, cues[0].end) == (1.0, 3.0)
    assert cues[0].text == "첫 번째 대사입니다"
    assert (cues[1].start, cues[1].end) == (20.0, 23.0)
    assert cues[1].text == "한참 뒤의 두 번째 대사"   # <br>은 공백이지 삭제가 아니다


def test_smi_without_blank_cues_is_capped_not_stretched():
    """빈 큐를 안 넣은 파일에서 '다음 SYNC까지'를 그대로 믿으면 자막 하나가
    수십 초를 덮는다."""
    doc = ("<SAMI><BODY>\n"
           "<SYNC Start=1000><P Class=KRCC>짧게 말하고 오래 침묵\n"
           "<SYNC Start=60000><P Class=KRCC>다음 대사\n"
           "</BODY></SAMI>")
    cues, notes = sub.parse(doc, "smi")
    assert cues[0].end == 1.0 + sub.SMI_MAX_CUE
    assert any("잘랐습니다" in n for n in notes), notes
    # 마지막 큐도 같은 상한으로 닫힌다. </BODY></SAMI> 꼬리가 본문에 붙지 않아야 한다
    assert cues[1].text == "다음 대사"


def test_smi_picks_one_language_class_deterministically():
    """다국어 SMI(KRCC+ENCC)를 그냥 이으면 한 대사가 '안녕하세요 Hello'가 된다."""
    doc = ["<SAMI><BODY>"]
    for i in range(4):
        doc.append(f"<SYNC Start={1000 + i * 4000}><P Class=KRCC>한국어 {i}"
                   f"<P Class=ENCC>&nbsp;")
    doc.append("<SYNC Start=17000><P Class=KRCC>&nbsp;<P Class=ENCC>English only")
    doc.append("</BODY></SAMI>")
    cues, notes = sub.parse("\n".join(doc), "smi")
    assert [c.text for c in cues] == [f"한국어 {i}" for i in range(4)]
    assert any("KRCC" in n for n in notes), notes


def test_smi_is_usually_cp949():
    """한국어 SMI 배포본은 대개 CP949다. UTF-8로만 읽으려 하면 파일 전체를 잃는다."""
    raw = SMI_DOC.encode("cp949")
    text, encoding = sub.decode_bytes(raw)
    assert encoding == "cp949"
    cues, _ = sub.parse(text, "smi")
    assert cues[0].text == "첫 번째 대사입니다"


def test_utf8_is_tried_before_cp949():
    """순서가 뒤집히면 CP949가 UTF-8 문서를 '성공적으로' 깨진 글자로 읽는다."""
    text, encoding = sub.decode_bytes(SMI_DOC.encode("utf-8"))
    assert encoding == "utf-8"
    assert "첫 번째 대사입니다" in text
    text, encoding = sub.decode_bytes("한글\n".encode("utf-8-sig"))
    assert (text, encoding) == ("한글\n", "utf-8-sig")


# ─── 거부 기준 ───────────────────────────────────────────────────────────
def test_youtube_auto_captions_are_rejected():
    """사용자가 자동 생성 자막을 명시적으로 배제했고, 실수로 유입될 통로는
    파일명이 수동 자막과 같은 이 경로뿐이다. 지문은 롤업이다."""
    # 유튜브 ASR의 실제 형태: 확정된 앞부분을 그대로 물고, 새 단어만 <c>로 감싸
    # 인라인 타이밍과 함께 붙여 다시 내보낸다.
    words = ["안녕하세요", "여러분", "오늘은", "자막", "이야기를", "합니다"]
    lines = ["WEBVTT", ""]
    for i, word in enumerate(words):
        lines += [f"{_ts(i * 2, '.')} --> {_ts(i * 2 + 2, '.')} align:start position:0%",
                  " ".join(words[:i]) + f"<00:00:0{i}.500><c> {word}</c>", ""]
    cues, _ = sub.parse("\n".join(lines), "vtt")
    assert cues[2].text == "안녕하세요 여러분 오늘은"

    # duration을 짧게 잡아 커버리지가 아니라 롤업으로 걸리는 것을 못박는다
    report = sub.evaluate(cues, duration=30.0)
    assert not report.ok
    assert "자동 생성" in report.reason and report.rollup > sub.MAX_ROLLUP


def test_handwritten_repetition_is_not_a_rollup():
    """반복 대사·후렴이 몇 번 있다고 자동 생성으로 몰면 멀쩡한 자막을 잃는다."""
    text = _srt(n=8, body="{i}번째 문장")
    cues, _ = sub.parse(text.replace("2번째 문장", "1번째 문장"), "srt")
    assert sub.evaluate(cues, duration=60.0).ok


def test_forced_subtitles_are_rejected_by_coverage():
    """외국어 구간만 번역한 강제 자막을 전사로 채택하면 영상 대부분이 '(무음)'이
    된다 — 오디오에는 말이 있는데도."""
    cues, _ = sub.parse(_srt(n=6, step=40.0, length=1.5), "srt")
    report = sub.evaluate(cues, duration=300.0)
    assert not report.ok
    assert "강제 자막" in report.reason
    assert report.coverage == pytest.approx(9.0 / 300.0)


def test_too_few_cues_is_not_a_dialogue_track():
    cues, _ = sub.parse(_srt(n=3), "srt")
    report = sub.evaluate(cues, duration=60.0)
    assert not report.ok and "큐가 3개" in report.reason


def test_subtitles_of_another_video_are_rejected():
    """어간이 같아 딸려 들어온 남의 자막 — 큐가 영상 길이 밖으로 나간다."""
    cues, _ = sub.parse(_srt(n=6, step=5.0).replace("00:00:", "01:00:"), "srt")
    report = sub.evaluate(cues, duration=60.0)
    assert not report.ok and "벗어납니다" in report.reason


def test_coverage_counts_the_union_not_the_sum():
    """두 화자가 동시에 말하는 구간은 큐가 겹친다. 그냥 더하면 커버리지가
    부풀어 강제 자막 방어가 헐거워진다."""
    cues = [sub.Cue(0.0, 10.0, "가"), sub.Cue(1.0, 9.0, "나"), sub.Cue(5.0, 12.0, "다"),
            sub.Cue(50.0, 55.0, "라"), sub.Cue(56.0, 58.0, "마")]
    report = sub.evaluate(cues, duration=100.0)
    assert report.coverage == pytest.approx((12.0 + 5.0 + 2.0) / 100.0)
    assert report.span == (0.0, 58.0)


def test_good_subtitle_is_accepted():
    cues, _ = sub.parse(_srt(), "srt")
    report = sub.evaluate(cues, duration=60.0)
    assert report.ok and report.reason is None
    assert (report.n_cues, report.rollup) == (6, 0.0)


# ─── 사이드카 후보와 순위 ────────────────────────────────────────────────
def _touch(directory: Path, *names: str) -> Path:
    for name in names:
        (directory / name).write_text("x", encoding="utf-8")
    return directory / names[0]


def _ranked(video: Path, sub_lang: str | None = None) -> list:
    """사이드카 풀만 세운 순위. 내장 트랙까지 가로지르는 비교는
    test_subtitle_ladder.py가 본다."""
    return sub.rank(sub.sidecar_candidates(video), sub_lang)


def test_sidecar_accepts_the_language_code_pattern(tmp_path):
    """yt-dlp 기본 출력이 `영상.mp4` + `영상.ko.srt`다. `<어간>.<확장자>`만 보면
    가장 흔한 경우를 통째로 놓친다."""
    video = tmp_path / "강의 1강.mp4"
    video.write_text("v", encoding="utf-8")
    _touch(tmp_path, "강의 1강.ko.srt")
    ranked = _ranked(video, "ko")
    assert [c.path.name for c in ranked] == ["강의 1강.ko.srt"]
    assert ranked[0].language == "ko"
    # 후보가 하나면 고를 것이 없으니 남길 말도 없다
    assert sub.choice_notes(ranked[0], ranked, "ko") == []


def test_sidecar_accepts_full_name_form_and_ignores_strangers(tmp_path):
    video = tmp_path / "lecture.mp4"
    video.write_text("v", encoding="utf-8")
    _touch(tmp_path, "lecture.mp4.srt", "other.srt", "lecture.txt")
    ranked = _ranked(video)
    assert [c.path.name for c in ranked] == ["lecture.mp4.srt"]
    assert ranked[0].language is None       # "mp4"는 언어 코드가 아니다


def test_sidecar_choice_is_deterministic_and_explained(tmp_path):
    """여럿이면 규칙으로 고르고 이유를 남긴다 — 조용히 고르면 나중에 되짚을 수 없다."""
    video = tmp_path / "lecture.mp4"
    video.write_text("v", encoding="utf-8")
    _touch(tmp_path, "lecture.ko.forced.srt", "lecture.en.srt",
           "lecture.ko.vtt", "lecture.ko.srt", "lecture.smi")

    ranked = _ranked(video, "ko")
    assert ranked[0].path.name == "lecture.ko.srt"   # 언어 일치 + forced 아님 + 포맷
    notes = sub.choice_notes(ranked[0], ranked, "ko")
    assert len(notes) == 1 and "lecture.ko.srt" in notes[0]
    # 같은 언어 등급 안에서는 forced가 최후다
    assert [c.path.name for c in ranked[:3]] == [
        "lecture.ko.srt", "lecture.ko.vtt", "lecture.ko.forced.srt"]

    # 요청 언어가 없으면 태그 없는 것 — 도구가 붙인 이름이 아니라 사용자가
    # 직접 둔 그 자막이다. 포맷 선호(srt>smi)보다 이쪽이 앞선다.
    assert _ranked(video)[0].path.name == "lecture.smi"

    # 언어가 forced보다 앞이다. 예전에는 반대라 목표 언어의 forced 자막이 다른
    # 언어의 정상 자막에게 졌는데, 이제 거부된 후보는 다음 순위로 내려가므로
    # (cli._subtitle_transcript) 진짜 강제 자막은 커버리지 하한에서 걸러지고
    # 그 자리를 영어 자막이 받는다. 이름만 forced인 정상 한국어 자막이라면
    # 그것을 쓰는 편이 옳다 — 요청한 언어가 그쪽이다.
    for name in ("lecture.ko.srt", "lecture.ko.vtt", "lecture.smi"):
        (tmp_path / name).unlink()
    assert [c.path.name for c in _ranked(video, "ko")] == [
        "lecture.ko.forced.srt", "lecture.en.srt"]


@pytest.mark.parametrize("container", ["mkv", "avi", "mov", "ts"])
def test_container_extension_is_not_a_language_tag(tmp_path, container):
    """`강의.mkv.srt`는 agent_guide가 안내하는 배치 형태다. 어간의 마지막 마디를
    그냥 떼면 "mkv"·"avi"·"mov"·"ts"가 2~3글자라는 이유로 언어가 되어
    transcript.json의 source.language가 거짓이 되고, 사이드카 선택 순위와
    --sub-lang 일치 판정이 그 거짓 위에서 돈다."""
    video = tmp_path / f"lecture.{container}"
    video.write_text("v", encoding="utf-8")
    sidecar = tmp_path / f"lecture.{container}.srt"
    sidecar.write_text(_srt(), encoding="utf-8")

    assert _ranked(video)[0].path == sidecar
    assert sub.language_of(sidecar, f"lecture.{container}.") is None
    # 접두사를 모르는 호출(--transcript 지목)에서는 옆의 영상이 같은 증거가 된다
    assert sub.language_of(sidecar) is None
    result, _ = sub.result_from_file(sidecar, duration=60.0, kind="sidecar")
    assert result["source"]["language"] is None


def test_language_tag_is_read_after_the_video_name(tmp_path):
    """두 배치 형태(`<어간>.<언어>` · `<파일명전체>.<언어>`)를 다 살려야 한다 —
    접두사가 긴 쪽을 먼저 벗겨야 둘이 갈리지 않는다."""
    video = tmp_path / "lecture.mkv"
    video.write_text("v", encoding="utf-8")
    _touch(tmp_path, "lecture.ko.srt", "lecture.mkv.en.srt")
    assert sub.language_of(tmp_path / "lecture.ko.srt", "lecture.") == "ko"
    assert sub.language_of(tmp_path / "lecture.mkv.en.srt", "lecture.mkv.") == "en"
    assert _ranked(video, "ko")[0].path.name == "lecture.ko.srt"
    assert _ranked(video, "en")[0].path.name == "lecture.mkv.en.srt"


def test_lone_forced_sidecar_is_recorded_not_taken_silently(tmp_path):
    """forced는 순위에서 최후지만 후보가 그것뿐이면 채택된다. 후보가 하나면
    선택 메모가 생기지 않으므로, 기록하지 않으면 강제 자막을 썼다는 사실이
    산출물 어디에도 남지 않는다."""
    video = tmp_path / "movie.mp4"
    video.write_text("v", encoding="utf-8")
    sidecar = tmp_path / "movie.forced.srt"
    sidecar.write_text(_srt(), encoding="utf-8")

    ranked = _ranked(video)
    notes = sub.choice_notes(ranked[0], ranked, None)
    assert ranked[0].path == sidecar
    assert len(notes) == 1 and "forced" in notes[0] and "movie.forced.srt" in notes[0]
    # 거부까지 하지는 않는다 — 내장 트랙의 forced 비트와 달리 이건 파일명 관례일
    # 뿐이라, 거부하면 사용자가 가진 유일한 자막을 이름 때문에 잃는다.
    result, _ = sub.result_from_file(sidecar, duration=60.0, kind="sidecar")
    assert result is not None


def test_no_sidecar_is_not_an_error(tmp_path):
    video = tmp_path / "lecture.mp4"
    video.write_text("v", encoding="utf-8")
    assert sub.sidecar_candidates(video) == []


# ─── 결과 조립 ───────────────────────────────────────────────────────────
def test_result_from_file_matches_the_transcript_schema(tmp_path):
    """소비자(manifest.build_metadata·GUI)는 text/segments/backend/model만 읽는다 —
    자막 출처도 whisper와 같은 모양이어야 하고, source는 더한 키다."""
    path = tmp_path / "lecture.ko.srt"
    path.write_text(_srt(), encoding="utf-8")
    result, notes = sub.result_from_file(path, duration=60.0, kind="sidecar")

    assert result["backend"] == "subtitle" and result["device"] == "none"
    assert result["model"] == "srt"
    assert result["words"] == []          # 자막 시각은 큐 단위다 — 단어로 쪼갤 근거가 없다
    assert result["text"].startswith("대사 0 대사 1")
    assert result["segments"][0] == {"start": 0.0, "end": 4.0, "text": "대사 0"}

    source = result["source"]
    assert source["kind"] == "sidecar" and source["format"] == "srt"
    assert source["path"] == str(path.resolve())
    assert (source["language"], source["track"]) == ("ko", None)
    assert source["n_cues"] == 6 and source["span"] == [0.0, 29.0]
    assert source["coverage"] == pytest.approx(0.4)
    assert notes == source["notes"] == []


def test_result_from_file_reports_why_it_refused(tmp_path):
    """거부는 예외가 아니라 사유다 — 사이드카는 폴백해야 하고 명시 지정은
    멈춰야 하는데, 그 분기는 사다리를 아는 호출자의 몫이다."""
    path = tmp_path / "lecture.ko.srt"
    path.write_text(_srt(n=2), encoding="utf-8")
    result, notes = sub.result_from_file(path, duration=60.0, kind="sidecar")
    assert result is None
    assert len(notes) == 1 and "큐가 2개" in notes[0]

    other = tmp_path / "lecture.ass"
    other.write_text("[Script Info]", encoding="utf-8")
    result, notes = sub.result_from_file(other, duration=60.0, kind="explicit")
    assert result is None and ".ass" in notes[0]


# ─── 지목한 자막: 판정을 거부에서 신고로 ────────────────────────────────
def test_named_file_is_used_even_when_the_quality_checks_would_refuse(tmp_path):
    """--transcript로 지목한 파일은 품질 검사에 걸려도 쓴다.

    그 검사들은 도구가 스스로 찾아낸 후보 여럿에서 고르기 위한 것이다. 사용자가
    파일을 짚은 순간 고르는 일은 끝났고, 남은 것은 정보뿐이다. 0.1.0에서는
    커버리지 11%짜리 강제 자막을 지목해도 거부됐고 안내가 제시한 두 대안은
    **둘 다 그 파일을 쓰지 않아서**, 알고도 쓰겠다는 통로가 없었다."""
    path = tmp_path / "lecture.ko.srt"
    # 60초 영상에 6초만 덮는 자막 = 커버리지 0.1 → 강제 자막으로 의심되는 구간
    path.write_text(_srt(n=6, step=1.0, length=1.0), encoding="utf-8")

    refused, why = sub.result_from_file(path, duration=60.0, kind="sidecar")
    assert refused is None, "자동 탐색에서는 그대로 거부되어야 한다"
    assert "덮습니다" in why[0]

    used, notes = sub.result_from_file(path, duration=60.0, kind="explicit",
                                       enforce_quality=False)
    assert used is not None
    assert len(used["segments"]) == 6
    # 사유는 버려지지 않는다 — 산출물만 보고도 어떤 자막이었는지 알 수 있어야 한다
    waived = [n for n in notes if n.startswith(sub.WAIVED)]
    assert len(waived) == 1 and "덮습니다" in waived[0]
    assert used["source"]["notes"] == notes


def test_named_file_with_no_cues_is_still_refused(tmp_path):
    """품질이 아니라 '쓸 것이 없다'는 사실 — 통과시키면 빈 전사가 자막인 척 남는다."""
    path = tmp_path / "empty.ko.srt"
    path.write_text("", encoding="utf-8")

    result, notes = sub.result_from_file(path, duration=60.0, kind="explicit",
                                         enforce_quality=False)
    assert result is None
    assert any("대사가 하나도 없어" in n for n in notes), notes


def test_result_carries_the_encoding_and_parser_notes(tmp_path):
    path = tmp_path / "lecture.smi"
    doc = ["<SAMI><BODY>"]
    for i in range(6):
        doc.append(f"<SYNC Start={i * 5000}><P Class=KRCC>대사 {i}")
        doc.append(f"<SYNC Start={i * 5000 + 4000}><P Class=KRCC>&nbsp;")
    doc.append("</BODY></SAMI>")
    path.write_bytes("\n".join(doc).encode("cp949"))

    result, notes = sub.result_from_file(path, duration=60.0, kind="sidecar")
    assert result is not None
    assert result["model"] == "smi"
    assert any("cp949" in n for n in notes), notes
    assert result["source"]["notes"] == notes


def test_source_is_assembled_by_the_shared_builder():
    """source의 모양은 stt/base.py 한 곳에서만 만든다. 자막용 사본을 따로 두면
    자막 밖의 출처(whisper·빈 전사)와 키가 갈리고, 소비자는 '없음'과 '옛 스키마'를
    구분할 수 없게 된다."""
    cues, _ = sub.parse(_srt(), "srt")
    result, _ = sub.result_from_cues(cues, 60.0, kind="sidecar", fmt="srt")
    assert set(result["source"]) == set(base.build_source("whisper"))
    assert not hasattr(sub, "make_source"), "base.build_source와 중복된 사본"
    assert not hasattr(sub, "SOURCE_KINDS"), "base.SOURCE_KINDS와 중복된 사본"
    with pytest.raises(ValueError):
        # 오타가 조용히 산출물에 실리지 않는다 — 판정은 base.build_source가 한다
        sub.result_from_cues(cues, 60.0, kind="subtitle", fmt="srt")


def test_embedded_track_goes_through_the_same_gate():
    """내장 트랙은 컨테이너에서 큐를 직접 뽑으므로 파일 경로가 없다 —
    검증·조립은 사이드카와 같은 길을 타야 기준이 하나로 유지된다."""
    cues, _ = sub.parse(_srt(), "srt")
    result, notes = sub.result_from_cues(cues, 60.0, kind="embedded", fmt="srt",
                                         track=2, language="ko")
    assert result["source"]["track"] == 2 and result["source"]["path"] is None
    assert result["source"]["language"] == "ko"
    assert notes == []

    bad, notes = sub.result_from_cues(cues[:2], 60.0, kind="embedded", fmt="srt", track=2)
    assert bad is None and "큐가 2개" in notes[0]
