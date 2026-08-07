"""state.json(스테이지 진행 상태·멱등 재개) + metadata.json(최종 산출) 스키마.

state.json이 있어야 ① 타임아웃으로 잘린 실행을 같은 명령 재실행만으로 이어가고
② 직렬 흐름(frames는 transcribe 이후)을 코드로 강제할 수 있다.
"""
import json
from datetime import datetime
from pathlib import Path

from . import METADATA_SCHEMA, STATE_SCHEMA
from .errors import EXIT_INPUT, EXIT_ORDER, CliError


def state_path(out_dir: Path) -> Path:
    return out_dir / "state.json"


def load_state(out_dir: Path) -> dict:
    p = state_path(out_dir)
    if not p.exists():
        return {"schema": STATE_SCHEMA, "stages": {}}
    return json.loads(p.read_text())


def save_state(out_dir: Path, state: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path(out_dir).write_text(json.dumps(state, ensure_ascii=False, indent=2))


def check_source(state: dict, video_path: Path) -> None:
    """다른 원본으로 이어서 돌리는 사고 방지 — 경로·크기 지문 대조."""
    st = video_path.stat()
    fp = {"path": str(video_path.resolve()), "size": st.st_size}
    prev = state.get("source")
    if prev is None:
        state["source"] = fp
    elif prev["path"] != fp["path"] or prev["size"] != fp["size"]:
        raise CliError(EXIT_INPUT, "source-mismatch",
                       "state.json에 기록된 원본과 다른 파일입니다",
                       hint="--out으로 새 출력 디렉토리를 지정하세요",
                       details={"state": prev, "given": fp})


def is_done(state: dict, stage: str) -> bool:
    return bool(state["stages"].get(stage, {}).get("done"))


def require_done(state: dict, stage: str, command_hint: str) -> dict:
    if not is_done(state, stage):
        raise CliError(EXIT_ORDER, "stage-order",
                       f"'{stage}' 스테이지가 먼저 완료되어야 합니다 (직렬 흐름 강제)",
                       hint=command_hint)
    return state["stages"][stage]


def mark_done(state: dict, stage: str, outputs: dict) -> None:
    state["stages"][stage] = {
        "done": True,
        "outputs": outputs,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def build_metadata(video_path: Path, transcript: dict, build: dict) -> dict:
    accepted = [r for r in build["records"] if r["status"] == "accepted"]
    rejected = [r for r in build["records"] if r["status"] == "rejected"]

    frames = []
    for r in accepted:
        f: dict = {
            "time": round(r["time"], 2),
            "image": r["image"],
            "sources": r["sources"],
            "interval": r["interval"],
            "dialogue": r["dialogue"],
        }
        if r.get("reasons"):
            f["reasons"] = r["reasons"]
        if r.get("trigger_dialogue"):
            f["trigger_dialogue"] = r["trigger_dialogue"]
        f["yavg"] = r.get("yavg")
        f["hash"] = r.get("hash")
        frames.append(f)

    return {
        "schema": METADATA_SCHEMA,
        "source": {
            "file": str(video_path.resolve()),
            "duration": round(build["duration"], 2),
            "fps": build["fps"],
        },
        "frames": frames,
        "rejected": [
            {"time": round(r["time"], 2), "sources": r["sources"],
             "reject_reason": r["reject_reason"], "image": r.get("image")}
            for r in rejected
        ],
        "transcript": {
            "backend": transcript["backend"],
            "model": transcript["model"],
            "text": transcript["text"],
            "segments": transcript["segments"],
        },
        "transcript_file": "transcript.json",
        "params": build["params"],
    }


def load_metadata(out_dir: Path) -> dict:
    p = out_dir / "metadata.json"
    if not p.exists():
        raise CliError(EXIT_ORDER, "metadata-missing",
                       "metadata.json이 없습니다 — frames 스테이지를 먼저 실행하세요",
                       hint="analysis-video frames <video> --points points.json")
    return json.loads(p.read_text())


def save_metadata(out_dir: Path, metadata: dict) -> None:
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2))
