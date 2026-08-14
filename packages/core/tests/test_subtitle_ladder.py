"""자막 후보의 순위는 **출처가 아니라 언어**가 먼저다.

전에는 사다리가 출처 우선이었다: 사이드카에서 하나를 고르고, 그것이 거부되어야
내장 트랙을 봤다. 그래서 사이드카에 영어만 있고 내장 트랙에 목표 언어인 한국어가
있는 영상에서 영어가 이겼다 — 언어가 풀 **안에서만** 우선이었기 때문이다.
이 파일이 잠그는 것 셋:

- 두 풀을 가로지르는 비교가 실제로 일어난다(언어 > 출처).
- 거부된 후보는 폴백의 끝이 아니라 **다음 순위로 내려가는 자리**다.
- 왜 그것이 뽑혔고 나머지는 왜 떨어졌는지가 전부 transcript.json에 남는다.
"""
import json
from pathlib import Path

import pytest
from analysis_video import cli, manifest
from analysis_video.stt import subtitles as sub
from analysis_video.stt.base import build_result, build_source

LOCALE_VARS = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")


@pytest.fixture(autouse=True)
def _no_ambient_locale(monkeypatch):
    """로케일이 목표 언어의 기본값이므로(--sub-lang 미지정) 지우지 않으면 시험
    결과가 실행하는 기계에 따라 달라진다."""
    for var in LOCALE_VARS:
        monkeypatch.delenv(var, raising=False)


def _srt(n: int = 6) -> str:
    """60초 영상 기준으로 검증을 통과하는 SRT. n을 줄이면 큐 하한(MIN_CUES)에
    걸려 거부되는 자막이 된다 — 폴백 시험이 그 형태를 쓴다."""
    return "\n".join(f"{i + 1}\n00:00:{i * 10:02d},000 --> 00:00:{i * 10 + 9:02d},000\n"
                     f"대사 {i}\n" for i in range(n))


def _ready(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """split까지 끝난 분석 디렉터리 — 전사 사다리만 돌게 한다."""
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    manifest.mark_done(state, "split", {"has_audio": True,
                                        "video": str(out_dir / "video.mkv"),
                                        "subtitles": []})
    manifest.save_state(out_dir, state)
    monkeypatch.setattr(cli.media, "get_duration", lambda _v: 60.0)
    return video, out_dir


def _track(out_dir: Path, index: int, language: str | None, *,
           default: bool = False, cues: int = 6) -> dict:
    """split.extract_subtitles가 남기는 모양 그대로 — 칸을 빠뜨리면 후보 수집이
    방어 없이 짚는다(그것이 그 함수의 계약이다)."""
    path = out_dir / "subs" / f"track{index}.srt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_srt(cues), encoding="utf-8")
    return {"track": index, "codec": "subrip", "language": language, "title": None,
            "default": default, "forced": False, "hearing_impaired": False,
            "path": str(path), "format": "srt", "n_cues": cues,
            "skipped": None, "notes": []}


def _tracks(out_dir: Path, *entries: dict) -> None:
    state = manifest.load_state(out_dir)
    state["stages"]["split"]["outputs"]["subtitles"] = list(entries)
    manifest.save_state(out_dir, state)


def _sidecar(tmp_path: Path, name: str, cues: int = 6) -> Path:
    path = tmp_path / name
    path.write_text(_srt(cues), encoding="utf-8")
    return path


def _notes(out_dir: Path) -> list[str]:
    return json.loads((out_dir / "transcript.json").read_text(
        encoding="utf-8"))["source"]["notes"]


# ─── 두 풀을 가로지르는 비교 ─────────────────────────────────────────────
def test_an_embedded_track_in_the_target_language_beats_a_foreign_sidecar(
        tmp_path, monkeypatch):
    """이번 변경의 핵심. 출처 우선이던 시절에는 사이드카의 영어가 이겼고, 내장의
    한국어는 열어 보지도 않았다 — 사용자가 고른 것은 '언어 우선'이다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    _sidecar(tmp_path, "lecture.en.srt")
    _tracks(out_dir, _track(out_dir, 3, "kor", default=True))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["source_kind"] == "embedded"
    assert result["language"] == "kor"          # kor은 ko와 같은 언어다
    assert result["language_mismatch"] is False
    notes = _notes(out_dir)
    assert any("내장 자막 트랙 3" in n and "사이드카 자막 'lecture.en.srt'" in n
               for n in notes), notes


def test_the_sidecar_wins_when_the_language_ties(tmp_path, monkeypatch):
    """2차 키. 언어가 같은 등급이면 사용자가 직접 둔 파일이 컨테이너에 묻어 온
    트랙보다 앞이다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    sidecar = _sidecar(tmp_path, "lecture.ko.srt")
    _tracks(out_dir, _track(out_dir, 3, "kor", default=True))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["source_kind"] == "sidecar"
    assert result["source_path"] == str(sidecar)


def test_without_the_target_language_the_undeclared_candidate_wins(
        tmp_path, monkeypatch):
    """목표 언어가 어디에도 없으면 기본 자막으로 내려간다 — 언어를 선언하지 않은
    후보가 다른 언어를 선언한 후보보다 앞이고, 이 비교도 풀을 가로지른다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    _sidecar(tmp_path, "lecture.ja.srt")
    _tracks(out_dir, _track(out_dir, 2, None))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["source_kind"] == "embedded"
    assert result["language"] is None
    # 언어를 모르는 자막을 '다르다'고 적지 않는다
    assert result["language_mismatch"] is False


def test_nothing_usable_anywhere_falls_to_whisper(tmp_path, monkeypatch):
    """자막이 한 장도 없으면 whisper다. 두 풀이 각각 왜 비었는지가 남아야
    '자막이 없었나, 있었는데 거부됐나'를 나중에 구분할 수 있다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.stt, "resolve_backend",
                        lambda _b, notes=None: "mlx")
    monkeypatch.setattr(cli.stt, "transcribe_audio", lambda *a, **k: build_result(
        "hello", [], [], backend="mlx", device="metal", model="tiny",
        source=build_source("whisper", language="en")))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["source_kind"] == "whisper"
    notes = _notes(out_dir)
    assert any("영상 옆에서" in n for n in notes), notes
    assert any("컨테이너 안에" in n for n in notes), notes


# ─── 거부되면 다음 후보로 ────────────────────────────────────────────────
def test_a_rejected_first_choice_falls_to_the_next_candidate(tmp_path, monkeypatch):
    """1순위가 거부되어도 사다리가 whisper까지 떨어지지 않는다. 예전에는 사이드카
    하나가 거부되면 곧장 내장 풀로 갔고, 그래서 '2순위 사이드카'라는 자리가 아예
    없었다 — 이제는 출처와 무관하게 순위대로 내려간다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    _sidecar(tmp_path, "lecture.ko.srt", cues=3)       # 큐 하한 미달 → 거부
    second = _sidecar(tmp_path, "lecture.ko.vtt")      # 같은 언어의 2순위
    _tracks(out_dir, _track(out_dir, 1, "kor"))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["source_path"] == str(second)
    notes = _notes(out_dir)
    assert any("lecture.ko.srt" in n and "큐가 3개" in n for n in notes), notes


def test_every_rejection_is_recorded_before_whisper(tmp_path, monkeypatch):
    """후보가 전부 거부되면 whisper로 가되, 각 사유가 하나도 빠지지 않고 남는다.
    stderr로만 흘리면 산출물에는 'whisper가 돌았다'만 남아 자막이 없었는지
    거부됐는지 구분할 수 없다."""
    video, out_dir = _ready(tmp_path, monkeypatch)
    _sidecar(tmp_path, "lecture.ko.srt", cues=3)
    _tracks(out_dir, _track(out_dir, 1, "kor", cues=2))
    monkeypatch.setattr(cli.stt, "resolve_backend",
                        lambda _b, notes=None: "mlx")
    monkeypatch.setattr(cli.stt, "transcribe_audio", lambda *a, **k: build_result(
        "hello", [], [], backend="mlx", device="metal", model="tiny",
        source=build_source("whisper", language="ko")))

    result = cli.run_transcribe(video, out_dir, None, None, None, sub_lang="ko")

    assert result["source_kind"] == "whisper"
    notes = _notes(out_dir)
    assert any("사이드카 자막 'lecture.ko.srt'" in n for n in notes), notes
    assert any("내장 자막 트랙 1(subrip)" in n for n in notes), notes


# ─── CLI 없이 판정되는 순위 ──────────────────────────────────────────────
def _cand(kind: str, name: str, language: str | None, **kw) -> sub.Candidate:
    return sub.Candidate(kind=kind, path=Path(name), format=Path(name).suffix[1:],
                         language=language, label=name, **kw)


def test_the_ranking_is_decidable_without_running_the_cli():
    """순위는 순수 함수다 — 영상도 상태 파일도 없이 답이 나와야 규칙을 시험할 수 있다."""
    sidecar = _cand("sidecar", "lecture.en.srt", "en")
    embedded = _cand("embedded", "track1.srt", "kor", track=1)

    assert sub.rank([sidecar, embedded], "ko") == [embedded, sidecar]
    assert sub.rank([sidecar, embedded], "en") == [sidecar, embedded]
    # 목표 언어가 없으면(로케일도 없음) 둘 다 등급 2라 출처가 가른다
    assert sub.rank([embedded, sidecar], None) == [sidecar, embedded]


def test_the_tail_keys_keep_each_pool_s_own_order():
    """3차 키부터는 각 풀이 쓰던 규칙 그대로다: 내장은 default 비트 > 스트림 순,
    사이드카는 forced 최후 > 포맷 > 이름 순. 언어 등급이 같을 때만 여기서 갈린다."""
    late_default = _cand("embedded", "track5.srt", None, track=5, default=True)
    early = _cand("embedded", "track0.srt", None, track=0)
    assert sub.rank([early, late_default], None) == [late_default, early]

    forced = _cand("sidecar", "lecture.forced.srt", None, forced=True)
    vtt = _cand("sidecar", "lecture.vtt", None)
    srt = _cand("sidecar", "lecture.srt", None)
    assert sub.rank([forced, vtt, srt], None) == [srt, vtt, forced]
