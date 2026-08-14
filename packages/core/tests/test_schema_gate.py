"""옛 산출물은 **거부**되어야 한다 — 죽어서는 안 된다.

하위 호환을 두지 않기로 한 결정("초기화된 상태에서 시작한다")의 구현은 "옛
디렉터리를 만나면 KeyError로 죽는다"가 아니다. 종료코드만으로 분기하는 호출
에이전트에게 exit 1(internal)은 도구의 버그이므로, 같은 명령을 그대로 재시도하고
같은 자리에서 또 죽는다. 형식이 맞지 않는 것은 **입력의 문제**(exit 2)이고,
답은 "새 --out을 쓰거나 이 디렉터리를 지워라"이다.

버전 필드는 쓰기만 해서는 아무 일도 하지 않는다. 여기서 잠그는 것은 "@2를 쓴다"가
아니라 **"@2가 아닌 것을 읽지 않는다"**이다.
"""
import json
from pathlib import Path

import pytest
from analysis_video import STATE_SCHEMA, cli
from analysis_video.errors import EXIT_INPUT

OLD_STATE_SCHEMA = "analysis-video/state@1"
OLD_METADATA_SCHEMA = "analysis-video/metadata@1"


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    """종료코드 + stdout 결과 JSON — 에이전트가 실제로 보는 두 가지."""
    code = cli.main(argv)
    return code, json.loads(capsys.readouterr().out)


def _analysis_dir(tmp_path: Path) -> tuple[Path, Path]:
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"
    out_dir.mkdir()
    return video, out_dir


def _write_state(out_dir: Path, state: dict) -> None:
    (out_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")


def _old_state(video: Path, out_dir: Path, schema: str | None) -> dict:
    """자막을 알기 전 버전이 남긴 state.json.

    split outputs에 "subtitles"가 없다 — 게이트가 없으면 전사 스테이지가 그 칸을
    짚다가 KeyError로 죽는 바로 그 모양이다."""
    state = {
        "source": {"path": str(video.resolve()), "size": video.stat().st_size},
        "stages": {"split": {"done": True, "at": "2026-01-01T00:00:00+09:00",
                             "outputs": {"audio": str(out_dir / "audio.wav"),
                                         "video": str(out_dir / "video.mkv")}}},
    }
    if schema is not None:
        state["schema"] = schema
    return state


# ─── state.json ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("command", ["status", "transcribe", "frames"])
def test_an_old_state_is_refused_at_the_door(tmp_path, capsys, command):
    """어느 입구로 들어오든 같은 자리에서 막힌다 — 게이트는 load_state 하나다."""
    video, out_dir = _analysis_dir(tmp_path)
    _write_state(out_dir, _old_state(video, out_dir, OLD_STATE_SCHEMA))

    code, payload = _run([command, str(video), "--out", str(out_dir)], capsys)

    assert code == EXIT_INPUT, "옛 디렉터리는 입력 오류지 내부 오류가 아니다"
    assert payload["error"]["kind"] == "schema-mismatch"
    assert OLD_STATE_SCHEMA in payload["error"]["message"]
    assert STATE_SCHEMA in payload["error"]["message"]


def test_the_refusal_tells_the_caller_what_to_do_next(tmp_path, capsys):
    """거부만 하고 끝나면 에이전트는 같은 명령을 다시 부를 수밖에 없다."""
    video, out_dir = _analysis_dir(tmp_path)
    _write_state(out_dir, _old_state(video, out_dir, OLD_STATE_SCHEMA))

    _code, payload = _run(["transcribe", str(video), "--out", str(out_dir)], capsys)

    hint = payload["error"]["hint"]
    assert "--out" in hint and "지우고" in hint


def test_a_state_without_any_schema_is_refused_too(tmp_path, capsys):
    """버전을 적기 전의 산출물. '없음'을 통과시키면 게이트에 구멍이 하나 남는다."""
    video, out_dir = _analysis_dir(tmp_path)
    _write_state(out_dir, _old_state(video, out_dir, None))

    code, payload = _run(["status", str(video), "--out", str(out_dir)], capsys)

    assert code == EXIT_INPUT
    assert payload["error"]["kind"] == "schema-mismatch"
    assert payload["error"]["details"]["found"] is None


def test_a_fresh_directory_still_works(tmp_path, capsys):
    """게이트는 **없는** state.json을 막지 않는다 — 그것이 정상적인 첫 실행이다."""
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")

    code, payload = _run(["status", str(video)], capsys)

    assert code == 0 and payload["stages"] == {}


# ─── metadata.json ───────────────────────────────────────────────────────
def test_an_old_metadata_is_refused_before_it_is_read(tmp_path, capsys):
    """frame --at은 metadata.json을 읽어 구간·대사를 다시 계산한다. 옛 형식이면
    그 계산이 없는 칸을 짚기 전에 멈춰야 한다."""
    video, out_dir = _analysis_dir(tmp_path)
    state = _old_state(video, out_dir, STATE_SCHEMA)
    state["source"]["subtitle"] = None
    # 여기서 보는 것은 **state는 현행인데 metadata만 옛 형식**인 경우다. 그러니
    # 현행 스키마를 주장하는 state는 그 안의 칸도 현행 모양이어야 한다 —
    # 뽑아 둔 wav의 경로(audio)가 아니라 원본에 소리가 있었나(has_audio)다.
    outputs = state["stages"]["split"]["outputs"]
    outputs["subtitles"] = []
    outputs["has_audio"] = bool(outputs.pop("audio"))
    state["stages"]["frames"] = {"done": True, "at": "2026-01-01T00:00:00+09:00",
                                 "outputs": {"runs": ["full"],
                                             "index": str(out_dir / "context.md")}}
    _write_state(out_dir, state)

    unit = out_dir / "runs" / "full"
    unit.mkdir(parents=True)
    (out_dir / "runs" / "index.json").write_text(
        json.dumps([{"name": "full", "range": None}]), encoding="utf-8")
    (unit / "metadata.json").write_text(
        json.dumps({"schema": OLD_METADATA_SCHEMA,
                    "source": {"duration": 60.0}, "frames": []}), encoding="utf-8")

    code, payload = _run(["frame", str(video), "--out", str(out_dir),
                          "--at", "10", "--reason", "확인"], capsys)

    assert code == EXIT_INPUT
    assert payload["error"]["kind"] == "schema-mismatch"
    assert payload["error"]["details"]["path"] == str(unit / "metadata.json")
