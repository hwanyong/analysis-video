"""전사가 다시 쓰이면 frames는 미완료로 돌아가야 한다.

화면에 붙은 대사는 runs/*/metadata.json과 context.md에 **복사되어** 산다
(align.attach_dialogue가 프레임마다 그 구간의 문장을 박아 넣는다). 전사만 다시
하고 frames를 그대로 두면 그 복사본은 옛 대사인 채로 남아, AI가 읽는 산출물과
transcript.json이 서로 다른 말을 한다. 어긋남은 어디에도 표시되지 않으므로
아무도 눈치채지 못한다 — 그래서 파일이 아니라 state로 강제한다.

반대로 **재사용된 전사**는 아무것도 무효화하지 않아야 한다. 매 실행마다 frames를
지우면 이어하기(타임아웃 재실행 = 같은 명령)가 성립하지 않는다.
"""
import json
from pathlib import Path

import pytest
from analysis_video import cli, manifest
from analysis_video.errors import EXIT_ORDER, CliError


def _analysis_with_frames(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """split·transcribe·frames가 모두 끝난 분석 디렉터리.

    오디오가 없는 영상(has_audio=False)으로 둔 이유: 전사 사다리가 빈 전사에서 끝나
    whisper도 자막 파서도 타지 않는다 — 이 시험이 보는 것은 "전사를 다시 썼는가"
    하나뿐이다."""
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"

    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    state["source"]["subtitle"] = None   # 자막 없이 전사했다는 기록
    manifest.mark_done(state, "split", {"has_audio": False,
                                        "video": str(out_dir / "video.mkv"),
                                        "subtitles": []})
    manifest.mark_done(state, "transcribe", {
        "transcript": str(out_dir / "transcript.json"),
        "backend": "none", "device": "none", "model": "none", "model_size": None,
        "n_segments": 0, "n_words": 0, "source_kind": "none", "source_path": None,
        "language": None, "target_language": None, "language_mismatch": False})
    manifest.mark_done(state, "frames", {"runs": ["full"],
                                         "index": str(out_dir / "context.md")})
    manifest.save_state(out_dir, state)
    monkeypatch.setattr(cli.media, "get_duration", lambda _v: 60.0)
    return video, out_dir


def _transcribe(video: Path, out_dir: Path, **kwargs) -> dict:
    return cli.run_transcribe(video, out_dir, None, None, None, **kwargs)


def test_rewriting_the_transcript_reopens_frames(tmp_path, monkeypatch):
    video, out_dir = _analysis_with_frames(tmp_path, monkeypatch)

    result = _transcribe(video, out_dir, force=True)

    assert result["skipped"] is False
    assert not manifest.is_done(manifest.load_state(out_dir), "frames"), \
        "옛 대사가 붙은 화면 산출물을 완료로 남기면 아무도 어긋남을 모른다"


def test_the_reopened_frames_stage_tells_the_caller_to_rerun_it(tmp_path, monkeypatch):
    """무효화는 그 자체로 끝이 아니라 다음 실행의 안내로 이어져야 한다 —
    frame --at은 옛 metadata.json을 읽는 대신 순서 위반으로 멈춘다."""
    video, out_dir = _analysis_with_frames(tmp_path, monkeypatch)
    _transcribe(video, out_dir, force=True)

    with pytest.raises(CliError) as e:
        cli.run_frame_at(video, out_dir, 10.0, "확인")

    assert e.value.code == EXIT_ORDER and e.value.kind == "stage-order"
    assert "frames" in e.value.hint


def test_reusing_the_transcript_leaves_frames_alone(tmp_path, monkeypatch):
    """--force 없이 다시 부르는 것은 이어하기다. 여기서 frames가 지워지면
    같은 명령의 재실행이 끝난 일을 되돌리는 셈이 된다."""
    video, out_dir = _analysis_with_frames(tmp_path, monkeypatch)

    result = _transcribe(video, out_dir)

    assert result["skipped"] is True
    assert manifest.is_done(manifest.load_state(out_dir), "frames")


def test_a_changed_subtitle_also_reopens_frames(tmp_path, monkeypatch):
    """--force 말고 자막 교체로 다시 전사되는 길도 같은 무효화를 거쳐야 한다 —
    무효화가 --force에만 붙어 있으면 자동 재전사가 조용히 옛 대사를 남긴다."""
    video, out_dir = _analysis_with_frames(tmp_path, monkeypatch)
    # 큐 수·커버리지 하한(stt.subtitles)을 넘겨야 채택된다 — 60초를 6개로 덮는다
    srt = tmp_path / "lecture.srt"
    srt.write_text("\n".join(
        f"{i + 1}\n00:00:{i * 10:02d},000 --> 00:00:{i * 10 + 9:02d},000\n{i + 1}번째 문장\n"
        for i in range(6)), encoding="utf-8")

    result = _transcribe(video, out_dir)

    assert result["skipped"] is False and result["source_kind"] == "sidecar"
    assert not manifest.is_done(manifest.load_state(out_dir), "frames")
    notes = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
    assert any("자막이 바뀌어" in n for n in notes["source"]["notes"])
