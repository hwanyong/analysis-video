"""state.json(스테이지 진행 상태·멱등 재개) + metadata.json(최종 산출) 스키마.

state.json이 있어야 ① 타임아웃으로 잘린 실행을 같은 명령 재실행만으로 이어가고
② 직렬 흐름(frames는 transcribe 이후)을 코드로 강제할 수 있다.
모든 JSON 쓰기는 임시 파일 + os.replace 원자 교체 — kill 타이밍에 반쯤 쓰인
state/metadata가 남아 파이프라인이 영구 wedge되는 것을 방지한다.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from . import METADATA_SCHEMA, STATE_SCHEMA
from .errors import EXIT_INPUT, EXIT_ORDER, CliError


def write_json_atomic(path: Path, obj: dict | list) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def state_path(out_dir: Path) -> Path:
    return out_dir / "state.json"


def load_state(out_dir: Path) -> dict:
    p = state_path(out_dir)
    if not p.exists():
        return {"schema": STATE_SCHEMA, "stages": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(out_dir: Path, state: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(state_path(out_dir), state)


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


def invalidate_stage(state: dict, stage: str) -> None:
    state["stages"].pop(stage, None)


def build_metadata(video_path: Path, transcript: dict, build: dict,
                   screens: list[tuple[float, float]] | None = None) -> dict:
    accepted = [r for r in build["records"] if r["status"] == "accepted"]
    rejected = [r for r in build["records"] if r["status"] == "rejected"]

    frames = []
    for r in accepted:
        f: dict = {
            "time": round(r["time"], 2),
            "image": r["image"],
            "sources": r["sources"],
            "screen": r["screen"],
            "interval": r["interval"],
            "dialogue": r["dialogue"],
        }
        f["yavg"] = r.get("yavg")
        frames.append(f)

    rejected_out = []
    for r in rejected:
        entry: dict = {"time": round(r["time"], 2), "sources": r["sources"],
                       "screen": r.get("screen"),
                       "reject_reason": r["reject_reason"], "image": r.get("image")}
        # 중복 판정이 옳았는지 확인하려면 병합 대상으로 건너뛸 수 있어야 한다
        rejected_out.append(entry)

    return {
        "schema": METADATA_SCHEMA,
        "source": {
            "file": str(video_path.resolve()),
            "duration": round(build["duration"], 2),
            "fps": build["fps"],
        },
        # 이 분석이 실제로 들여다본 구간. 영상 전체면 [0, duration].
        # 없으면 소비자가 "빈 구간"과 "안 본 구간"을 구분할 수 없다.
        "window": build.get("window", [0.0, round(build["duration"], 2)]),
        # 화면 구간 목록 — 이미지가 하나도 없는 화면도 여기엔 남는다.
        # 이것이 없으면 후보가 전부 탈락한 화면이 기록에서 사라져 그동안의
        # 대사까지 함께 소실된다(실측 유실 최대 64%).
        "screens": [[round(a, 2), round(b, 2)] for a, b in (screens or [])],
        "frames": frames,
        "rejected": rejected_out,
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
    return json.loads(p.read_text(encoding="utf-8"))


def save_metadata(out_dir: Path, metadata: dict) -> None:
    write_json_atomic(out_dir / "metadata.json", metadata)
