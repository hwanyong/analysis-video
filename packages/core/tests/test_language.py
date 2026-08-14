"""자막 언어와 음성 언어는 **다른 물음**이고, 코드 표기는 경로마다 다르게 온다.

이 파일이 잠그는 세 가지:

- **로케일 해석**: --sub-lang이 없을 때 무엇이 쓰였는지가 결정적이어야 하고,
  산출물에서 보여야 한다("왜 이 자막이 골라졌나"의 답).
- **ko ↔ kor**: 같은 한국어 자막인데 사이드카는 639-1(ko), 컨테이너는 639-2(kor)로
  적는다. 규칙이 한 곳에 없으면 "일치"의 뜻이 경로마다 갈린다.
- **언어 불일치 신고**: 코어는 번역하지 않는다. 할 수 있는 정직한 일은 "요청한
  언어와 다르다"를 정확히 남기는 것까지이고, 그것이 빠지면 영어 영상을 한국어로
  분석했다고 착각한 채 산출물을 읽게 된다.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from analysis_video import cli, manifest
from analysis_video.stt import lang
from analysis_video.stt import subtitles as sub
from analysis_video.stt.base import build_result, build_source, mark_target_language

LOCALE_VARS = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")


@pytest.fixture(autouse=True)
def _no_ambient_locale(monkeypatch):
    """이 파일의 기본 상태는 '로케일 없음'이다 — 안 지우면 시험 결과가 실행하는
    기계의 로케일에 따라 달라진다(그것이야말로 이 기능이 막으려는 비결정성이다)."""
    for var in LOCALE_VARS:
        monkeypatch.delenv(var, raising=False)


# ─── 로케일 해석 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("env, expected", [
    ({"LANG": "ko_KR.UTF-8"}, "ko"),
    ({"LANG": "en_US.UTF-8"}, "en"),
    ({"LANG": "ko_KR"}, "ko"),
    ({"LANG": "ko"}, "ko"),
    # C/POSIX는 "언어를 가정하지 않는다"는 선언이다 — 언어로 읽으면 안 된다.
    ({"LANG": "C"}, None),
    ({"LANG": "C.UTF-8"}, None),
    ({"LANG": "POSIX"}, None),
    ({"LANG": ""}, None),
    ({}, None),
    # LANGUAGE는 목록이다(GNU 확장) — 첫 항목이 사용자의 1순위다.
    ({"LANGUAGE": "ko:en"}, "ko"),
    ({"LANG": "de_DE@euro"}, "de"),
])
def test_locale_is_parsed_down_to_the_language(env, expected):
    assert lang.from_locale(env) == expected


def test_the_first_set_variable_decides():
    """POSIX 우선순위 그대로다. LC_ALL=C 아래에서 LANG을 주워 오면 'C 로케일에서는
    언어를 가정하지 않는다'는 선언이 뒤집힌다."""
    assert lang.from_locale({"LC_ALL": "en_US.UTF-8", "LANG": "ko_KR.UTF-8"}) == "en"
    assert lang.from_locale({"LC_ALL": "C", "LANG": "ko_KR.UTF-8"}) is None
    assert lang.from_locale({"LC_MESSAGES": "ja_JP.UTF-8", "LANG": "ko_KR"}) == "ja"


def test_the_environment_is_the_source_and_it_is_injectable(monkeypatch):
    """인자를 안 주면 os.environ을 본다 — 테스트가 monkeypatch로 주입할 수 있어야
    하고(setlocale 호출 여부에 좌우되지 않아야 하고), 같은 환경이면 같은 값이어야 한다."""
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert lang.from_locale() == lang.from_locale() == "ko"


# ─── ko ↔ kor ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("a, b", [
    ("ko", "ko"), ("KO", "ko"), ("ko", "ko-KR"), ("ko_KR", "ko"),
    ("kor", "ko"), ("ko", "kor"), ("kor", "ko-KR"), ("deu", "de"),
    ("zh-Hans", "zh-Hant"),
])
def test_the_same_language_matches_across_standards(a, b):
    assert lang.matches(a, b)


@pytest.mark.parametrize("a, b", [
    ("ko", "en"), ("kor", "eng"), ("ko", None), (None, "ko"), (None, None),
    # 정직한 한계: 639-2/B 변종은 접두사 규칙으로 잡히지 않는다. 표를 들이지 않기로
    # 한 대가이고, 그 대가는 순위 한 칸이다(후보에서 빠지지는 않는다).
    ("de", "ger"), ("zh", "chi"),
])
def test_what_the_prefix_rule_cannot_do(a, b):
    assert not lang.matches(a, b)


def test_normalize_only_touches_the_form():
    """형식(대소문자·구분자)은 통일하지만 표준 사이의 변환은 하지 않는다 —
    source.language는 '출처가 무엇을 선언했는가'의 감사 기록이다."""
    assert lang.normalize("KO_kr") == "ko-kr"
    assert lang.normalize("kor") == "kor"      # ko로 고쳐 적지 않는다
    assert lang.normalize("") is None and lang.normalize(None) is None


def test_a_three_letter_sidecar_wins_for_a_two_letter_request(tmp_path):
    """실측으로 갈리던 자리 — 같은 한국어 자막이 파일명에서는 ko, 컨테이너에서는
    kor로 온다. 사이드카 선택이 kor을 못 알아보면 영어 자막이 뽑힌다."""
    video = tmp_path / "lecture.mp4"
    video.write_text("v", encoding="utf-8")
    for name in ("lecture.en.srt", "lecture.kor.srt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    ranked = sub.rank(sub.sidecar_candidates(video), "ko")

    assert ranked[0].path.name == "lecture.kor.srt"
    assert "lecture.kor.srt" in sub.choice_notes(ranked[0], ranked, "ko")[0]


def test_a_mismatch_only_costs_a_rank(tmp_path):
    """일치하는 자막이 없다고 자막을 버리지는 않는다 — 잘못된 언어의 자막이라도
    자막이 없는 것보다 낫고, 다르다는 사실은 따로 신고된다."""
    video = tmp_path / "lecture.mp4"
    video.write_text("v", encoding="utf-8")
    (tmp_path / "lecture.ko.srt").write_text("x", encoding="utf-8")

    ranked = sub.rank(sub.sidecar_candidates(video), "ja")

    assert [c.path.name for c in ranked] == ["lecture.ko.srt"]


# ─── whisper가 감지한 언어 ───────────────────────────────────────────────
def test_the_mlx_backend_records_the_detected_language(monkeypatch):
    mlx_whisper = pytest.importorskip("mlx_whisper")
    from analysis_video.stt import backend_mlx

    monkeypatch.setattr(mlx_whisper, "transcribe", lambda *a, **k: {
        "text": "hello", "language": "en",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello", "words": []}]})

    result = backend_mlx.transcribe(audio=None, model_size="tiny")

    assert result["source"]["language"] == "en"


def test_the_faster_whisper_backend_records_the_detected_language(monkeypatch):
    pytest.importorskip("faster_whisper")
    from analysis_video.stt import backend_fwhisper

    class _Model:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, audio, **kw):
            segment = SimpleNamespace(start=0.0, end=1.0, text=" hello", words=[])
            # 언어 감지는 세그먼트 생성 **전에** 끝나 info에 실려 온다
            return iter([segment]), SimpleNamespace(language="en")

    monkeypatch.setattr("faster_whisper.WhisperModel", _Model)

    result = backend_fwhisper.transcribe(audio=None, model_size="tiny", device="cpu")

    assert result["source"]["language"] == "en"


# ─── 목표 언어와 불일치 신고 ─────────────────────────────────────────────
def _whisper_result(language: str | None) -> dict:
    return build_result("hello", [], [], backend="mlx", device="metal", model="tiny",
                        source=build_source("whisper", language=language))


def test_a_different_language_is_stated_not_translated():
    result = _whisper_result("en")

    assert mark_target_language(result, "ko") is True
    source = result["source"]
    assert (source["language"], source["target_language"]) == ("en", "ko")
    assert any("번역하지 않으므로" in n for n in source["notes"]), source["notes"]


@pytest.mark.parametrize("found, target", [
    ("kor", "ko"),        # 같은 언어의 다른 표기는 불일치가 아니다
    ("ko", None),         # 요청이 없으면 비교할 것이 없다
    (None, "ko"),         # 언어를 모르는 자막을 '다르다'고 적지 않는다
])
def test_silence_when_there_is_nothing_to_report(found, target):
    result = _whisper_result(found)

    assert mark_target_language(result, target) is False
    assert result["source"]["notes"] == []
    assert result["source"]["target_language"] == lang.normalize(target)


# ─── CLI 배선 ────────────────────────────────────────────────────────────
def _srt(n: int = 6) -> str:
    return "\n".join(f"{i + 1}\n00:00:{i * 10:02d},000 --> 00:00:{i * 10 + 9:02d},000\n"
                     f"대사 {i}\n" for i in range(n))


def _ready(tmp_path: Path, monkeypatch, *, audio: bool = True,
           tracks: list[dict] | None = None) -> tuple[Path, Path]:
    """split까지 끝난 분석 디렉터리 — 전사 사다리만 돌게 한다."""
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    manifest.mark_done(state, "split", {
        "has_audio": audio,
        "video": str(out_dir / "video.mkv"), "subtitles": tracks or []})
    manifest.save_state(out_dir, state)
    monkeypatch.setattr(cli.media, "get_duration", lambda _v: 60.0)
    return video, out_dir


def _track(out_dir: Path, index: int, language: str | None, *, default: bool) -> dict:
    """split.extract_subtitles가 남기는 모양 그대로 — 칸을 빠뜨리면 사다리가
    방어 없이 짚는다(그것이 그 함수의 계약이다)."""
    path = out_dir / "subs" / f"track{index}.srt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_srt(), encoding="utf-8")
    return {"track": index, "codec": "subrip", "language": language, "title": None,
            "default": default, "forced": False, "hearing_impaired": False,
            "path": str(path), "format": "srt", "n_cues": 6,
            "skipped": None, "notes": []}


def test_sub_lang_picks_the_subtitle_and_language_does_not(tmp_path, monkeypatch):
    """이 저장소가 고친 고장: --language 하나가 '음성 힌트'와 '자막 선택'을 겸했다.
    두 값이 갈리는 실행에서 자막은 --sub-lang을 따라야 한다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    for name in ("lecture.ko.srt", "lecture.en.srt"):
        (tmp_path / name).write_text(_srt(), encoding="utf-8")

    result = cli.run_transcribe(video, out_dir, None, None, "en", sub_lang="ko")

    assert result["source_path"] == str(tmp_path / "lecture.ko.srt")
    assert result["language"] == "ko"


def test_the_locale_decides_when_the_flag_is_absent_and_it_is_recorded(
        tmp_path, monkeypatch):
    """기본값이 무엇이었는지가 산출물에 없으면 '왜 이 자막이 골라졌나'를 설명할 수 없다."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    video, out_dir = _ready(tmp_path, monkeypatch)
    for name in ("lecture.ko.srt", "lecture.en.srt"):
        (tmp_path / name).write_text(_srt(), encoding="utf-8")

    result = cli.run_transcribe(video, out_dir, None, None, None)

    assert result["source_path"] == str(tmp_path / "lecture.en.srt")
    assert result["target_language"] == "en"
    notes = json.loads((out_dir / "transcript.json").read_text(
        encoding="utf-8"))["source"]["notes"]
    assert any("시스템 로케일" in n and "'en'" in n for n in notes), notes


def test_an_embedded_track_is_chosen_by_the_same_language_rule(tmp_path, monkeypatch):
    """내장 트랙 선택은 사이드카와 같은 규칙을 쓴다 — 컨테이너가 kor로 적어도
    --sub-lang ko가 그 트랙을 고른다. default 비트보다 요청이 앞선다."""
    video, out_dir = _ready(tmp_path, monkeypatch, tracks=[])
    tracks = [_track(out_dir, 0, "eng", default=True),
              _track(out_dir, 1, "kor", default=False)]
    state = manifest.load_state(out_dir)
    state["stages"]["split"]["outputs"]["subtitles"] = tracks
    manifest.save_state(out_dir, state)

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    transcript = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
    assert transcript["source"]["track"] == 1
    assert transcript["source"]["language"] == "kor"   # 선언한 코드를 고쳐 적지 않는다
    assert result["language_mismatch"] is False        # kor은 ko와 같은 언어다


def test_the_whisper_language_reaches_the_result_and_the_mismatch_is_flagged(
        tmp_path, monkeypatch):
    """실측으로 비어 있던 자리 — 영어 음성 영상의 source.language가 None이었다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.stt, "resolve_backend",
                        lambda _b, notes=None: "mlx")
    monkeypatch.setattr(cli.stt, "transcribe_audio",
                        lambda *a, **k: _whisper_result("en"))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert (result["language"], result["target_language"]) == ("en", "ko")
    assert result["language_mismatch"] is True
    transcript = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
    assert any("번역하지 않으므로" in n for n in transcript["source"]["notes"])


def test_reopening_with_another_sub_lang_says_what_you_got(tmp_path, monkeypatch):
    """다른 언어를 요청했는데 재사용됐다면 그 사실이 결과에 있어야 한다.
    반대로 플래그가 없는 실행은 조용해야 한다 — 로케일이 움직였다는 이유로
    끝난 분석이 매번 항의하면 그 문장은 곧 읽히지 않는다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    (tmp_path / "lecture.ko.srt").write_text(_srt(), encoding="utf-8")
    cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert "note" not in cli.run_transcribe(video, out_dir, None, None, None)

    again = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ja")
    assert again["skipped"] is True
    assert "ko" in again["note"] and "ja" in again["note"]
    assert (again["target_language"], again["language_mismatch"]) == ("ja", True)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_flag_is_not_a_request(tmp_path, monkeypatch, blank):
    """`--sub-lang ""`은 언어를 밝힌 것이 아니다. 플래그의 유무로 "요청했는가"를
    대신 세면 이 입력에서 둘이 갈리고, 실측으로 두 자리가 함께 틀렸다: 목표는
    로케일에서 왔는데 그 사실이 기록되지 않았고, 재사용 note는 빈 따옴표('')를
    요청 언어라고 인용했다. 판정은 정규화한 값 하나로만 한다."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    video, out_dir = _ready(tmp_path, monkeypatch)
    (tmp_path / "lecture.ko.srt").write_text(_srt(), encoding="utf-8")

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang=blank)

    assert result["target_language"] == "en"
    notes = json.loads((out_dir / "transcript.json").read_text(
        encoding="utf-8"))["source"]["notes"]
    assert any("시스템 로케일" in n and "'en'" in n for n in notes), notes

    again = cli.run_transcribe(video, out_dir, None, None, None, sub_lang=blank)
    assert again["skipped"] is True and again["language_mismatch"] is True
    assert "note" not in again, "밝히지 않은 언어를 두고 항의하지 않는다"


def test_a_reused_transcript_answers_this_call_not_the_last_one(tmp_path, monkeypatch):
    """state.json에 실린 언어 두 칸은 전사를 쓸 당시의 요청이다. 그대로 흘리면
    어제 --sub-lang ja로 만든 분석을 오늘 ko로 열었을 때 지난 실행의 답('불일치')이
    이번 결과로 나간다 — 호출 에이전트는 있지도 않은 문제를 풀려 든다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    (tmp_path / "lecture.ko.srt").write_text(_srt(), encoding="utf-8")
    stale = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ja")
    assert stale["language_mismatch"] is True   # 전사는 이 상태로 기록된다

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["skipped"] is True
    assert (result["target_language"], result["language_mismatch"]) == ("ko", False)
    assert "note" not in result


@pytest.mark.parametrize("command", ["analyze", "transcribe"])
def test_both_commands_take_the_flag_and_keep_the_two_roles_apart(command):
    args = cli.build_parser().parse_args(
        [command, "v.mkv", "--sub-lang", "ko", "--language", "en"])

    assert (args.sub_lang, args.language) == ("ko", "en")
    assert cli.build_parser().parse_args([command, "v.mkv"]).sub_lang is None
