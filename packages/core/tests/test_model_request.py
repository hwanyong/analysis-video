"""모델에 대한 안내는 **사용자가 --model을 준 실행**에서만 나간다.

재사용 note("기존 전사(모델=tiny)를 재사용했습니다 — --force를 지정하세요")는
호출 에이전트에게 해결해야 할 불일치로 읽힌다. 그래서 이 문장이 뜨는 조건이 곧
"헛된 재전사(가중치 다운로드 + 추론)를 몇 번 유발하는가"다.

파서가 --model의 기본값을 채우면 그 조건이 사용자의 요청이 아니라 **그날의
DEFAULT_MODEL 값**이 된다: tiny → small로 상수를 한 번 올린 순간, 아무도 모델을
요청한 적 없는데도 기존 분석 디렉터리를 다시 여는 모든 실행이 불일치를 호소했다.
여기서 잠그는 것은 그 경계다 — 요청이 없으면 침묵하고, 요청이 있으면 말한다.
"""
from pathlib import Path

import pytest
from analysis_video import cli, manifest
from analysis_video.stt.base import DEFAULT_MODEL, build_result, build_source


def _done_analysis(tmp_path: Path, monkeypatch, *, model_size: str | None,
                   source_kind: str, language: str | None = None) -> tuple[Path, Path]:
    """전사까지 끝난 분석 디렉터리. 다시 열면 재사용 경로만 탄다."""
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"

    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    # 완료된 전사가 **자막 없이** 만들어졌음을 기록해 둔다. 이 값이 지금 탐색
    # 결과(영상 옆에 자막이 없다)와 같아야 재사용 경로를 탄다(check_subtitle_input) —
    # 자막이 바뀐 것으로 잡히면 무엇 때문에 note가 났는지가 흐려진다.
    state["source"]["subtitle"] = None
    manifest.mark_done(state, "split", {"has_audio": True,
                                        "video": str(out_dir / "video.mkv"),
                                        "subtitles": []})
    manifest.mark_done(state, "transcribe", {
        "transcript": str(out_dir / "transcript.json"),
        "backend": "mlx", "device": "metal", "model": model_size or "srt",
        "model_size": model_size, "n_segments": 1, "n_words": 3,
        "source_kind": source_kind,
        "source_path": None if source_kind == "whisper" else str(tmp_path / "a.srt"),
        "language": language, "target_language": None, "language_mismatch": False,
    })
    manifest.save_state(out_dir, state)
    monkeypatch.setattr(cli.media, "get_duration", lambda _v: 60.0)
    return video, out_dir


def _transcribe(video: Path, out_dir: Path, *flags: str) -> dict:
    """파서를 거쳐 실행한다 — 고장난 자리가 파서의 기본값이었으므로
    args를 건너뛰고 run_transcribe를 직접 부르면 회귀를 못 잡는다."""
    args = cli.build_parser().parse_args(["transcribe", str(video), *flags])
    return cli.run_transcribe(video, out_dir, args.model, args.stt_backend,
                              args.language, force=args.force,
                              transcript=args.transcript,
                              no_subtitles=args.no_subtitles,
                              sub_lang=args.sub_lang)


# ─── 재사용 note의 발화 조건 ─────────────────────────────────────────────
def test_reopening_without_the_flag_says_nothing_about_the_model(tmp_path, monkeypatch):
    """옛 기본값(tiny)으로 만든 전사를 옵션 없이 다시 열어도 조용해야 한다."""
    video, out_dir = _done_analysis(tmp_path, monkeypatch,
                                    model_size="tiny", source_kind="whisper")

    result = _transcribe(video, out_dir)

    assert result["skipped"] is True
    assert "note" not in result, \
        "기본값이 움직인 것을 사용자의 요청으로 착각하면 헛된 재전사를 부른다"


def test_asking_for_another_model_still_says_so(tmp_path, monkeypatch):
    """명시한 모델이 디스크의 것과 다르면 note는 그대로 떠야 한다."""
    video, out_dir = _done_analysis(tmp_path, monkeypatch,
                                    model_size="tiny", source_kind="whisper")

    result = _transcribe(video, out_dir, "--model", "medium")

    assert "tiny" in result["note"] and "--force" in result["note"]


def test_asking_for_the_model_on_disk_says_nothing(tmp_path, monkeypatch):
    video, out_dir = _done_analysis(tmp_path, monkeypatch,
                                    model_size="tiny", source_kind="whisper")

    assert "note" not in _transcribe(video, out_dir, "--model", "tiny")


def test_subtitle_source_explains_the_flag_only_when_it_was_given(tmp_path, monkeypatch):
    """자막에서 온 전사에는 모델 크기가 없다. 그 사실은 --model을 준 사람에게만
    할 말이다 — 기본값과 비교하면 기본 모델을 명시한 사람만 침묵당한다."""
    video, out_dir = _done_analysis(tmp_path, monkeypatch,
                                    model_size=None, source_kind="sidecar")

    assert "note" not in _transcribe(video, out_dir)

    note = _transcribe(video, out_dir, "--model", DEFAULT_MODEL)["note"]
    assert "sidecar" in note and DEFAULT_MODEL in note


# ─── 요청이 없을 때 실제로 도는 모델 ─────────────────────────────────────
def test_a_fresh_run_transcribes_with_the_default_model(tmp_path, monkeypatch):
    """요청 없음(None)은 재사용 판정에서만 쓰는 값이다 — whisper에는 반드시
    기본 모델로 굳어져 닿아야 한다."""
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
    monkeypatch.setattr(cli.stt, "resolve_backend",
                        lambda _b, notes=None: "mlx")

    asked = {}

    def fake_transcribe(media_path, model_size=None, backend=None, language=None):
        asked["model_size"] = model_size
        asked["media_path"] = media_path
        return build_result("대사", [], [], backend="mlx", device="metal",
                            model=model_size, source=build_source("whisper"))

    monkeypatch.setattr(cli.stt, "transcribe_audio", fake_transcribe)

    result = _transcribe(video, out_dir)

    assert asked["model_size"] == DEFAULT_MODEL
    assert result["model_size"] == DEFAULT_MODEL
    # 백엔드가 받는 것은 **원본 영상**이다. 중간 wav는 더 이상 만들지 않고,
    # 분리된 video.mkv를 넘기면 무음이라 decode(audio=0)이 IndexError로 죽는다.
    assert asked["media_path"] == video
    assert asked["media_path"] != out_dir / "video.mkv"


# ─── 파서 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("command", ["analyze", "transcribe"])
def test_the_model_is_unrequested_until_the_flag_is_given(command):
    """--model은 analyze와 transcribe 양쪽에 있다 — 한쪽만 고치면 나머지 경로가
    같은 거짓 경고를 그대로 낸다."""
    parser = cli.build_parser()

    assert parser.parse_args([command, "v.mkv"]).model is None
    assert parser.parse_args([command, "v.mkv", "--model", "tiny"]).model == "tiny"
