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


def write_text_atomic(path: Path, text: str) -> None:
    """임시 파일 + os.replace. JSON만이 아니라 **텍스트 전부**가 이래야 한다 —
    context.md가 review의 지문 원천이 되면서, 반쯤 쓰인 파일이 가짜 sha를 만들면
    멀쩡한 리뷰가 낡은 것으로 판정된다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json_atomic(path: Path, obj: dict | list) -> None:
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, indent=2))


def state_path(out_dir: Path) -> Path:
    return out_dir / "state.json"


def _require_schema(path: Path, data: dict, expected: str) -> dict:
    """읽어 들인 JSON이 **이 버전이 쓰는 형식**인지 확인한다. 아니면 거부.

    버전 필드를 쓰기만 하고 읽지 않으면 옛 산출물이 그대로 파이프라인에 들어와,
    없는 칸을 짚는 자리에서 KeyError로 죽는다. 그것은 exit 1(internal)이라 호출
    에이전트에게는 도구의 버그로 보이고 — 종료코드만으로 분기한다는 errors.py의
    계약이 그 자리에서 깨진다(버그로 오해하면 같은 명령을 재시도한다). 형식이
    맞지 않는 것은 **입력의 문제**이므로 exit 2로, 다음에 무엇을 하면 되는지와
    함께 거부한다."""
    found = data.get("schema") if isinstance(data, dict) else None
    if found != expected:
        raise CliError(EXIT_INPUT, "schema-mismatch",
                       f"{path.name}이(가) 이 버전이 읽을 수 있는 형식이 아닙니다 "
                       f"(필요: {expected} / 발견: {found or '없음'})",
                       hint="--out으로 새 디렉터리를 지정하거나, 이 디렉터리를 지우고 "
                            "처음부터 다시 분석하세요",
                       details={"path": str(path), "expected": expected, "found": found})
    return data


def load_state(out_dir: Path) -> dict:
    """없으면 빈 state를 만들어 주고, 있으면 형식을 대조한 뒤 돌려준다."""
    p = state_path(out_dir)
    if not p.exists():
        return {"schema": STATE_SCHEMA, "stages": {}}
    return _require_schema(p, json.loads(p.read_text(encoding="utf-8")), STATE_SCHEMA)


def save_state(out_dir: Path, state: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(state_path(out_dir), state)


# ─── 분석 대상 지목 ──────────────────────────────────────────────────────
# "어떤 경로가 이 분석을 가리키는가"는 state.json의 계약과 같은 것이라 여기 산다.
# CLI와 GUI가 각자 풀면 두 도구의 판단이 갈린다 — 실제로 갈렸다: GUI는 영상
# 파일과 .analysis 디렉터리를 모두 받는데 CLI는 영상만 받아, 디렉터리를 준
# `status`가 뒤에 .analysis를 한 번 더 붙여 "아직 분석 안 됨"이라 답했다.
ANALYSIS_SUFFIX = ".analysis"


def absolute(path: Path) -> Path:
    """cwd 의존만 걷어낸 절대경로 — **심볼릭 링크는 따라가지 않는다**.

    Path.resolve()를 쓰면 안 된다. 그것은 링크까지 실제 경로로 바꾸므로 원본을
    링크로 가리키는 사용자의 분석 디렉터리가 통째로 자리를 옮긴다:
    `~/videos/lecture.mkv -> /mnt/big/L01.mkv`를 분석해 두고 같은 명령을 다시
    부르면 출력이 `~/videos/lecture.mkv.analysis`가 아니라
    `/mnt/big/L01.mkv.analysis`로 잡혀, 끝나 있던 분석은 어디에서도 보이지 않고
    (state.json을 못 찾으니 이어하기가 성립하지 않는다) 전사·검출이 처음부터
    다시 돈다. 실측으로 확인한 재현이다.

    원본 동일성 판정은 여기가 아니라 check_source의 지문이 맡는다 — 그쪽은
    resolve()로 실제 경로를 보므로 링크와 실체가 같은 파일임을 안다.
    디렉터리 **이름**만 사용자가 준 경로를 따르면 된다."""
    return Path(os.path.abspath(path))


def analysis_dir(video: Path) -> Path:
    """이 영상의 기본 분석 디렉터리 — `<영상>.analysis/`."""
    return video.parent / f"{video.name}{ANALYSIS_SUFFIX}"


def resolve_out(video: Path, out: Path | None) -> Path:
    """출력 경로는 반드시 절대경로로 만든다.

    상대경로를 그대로 두면 파생 경로가 state.json에 기록되어 1회차 실행의 cwd가
    숨은 기준점이 된다. 다른 폴더에서 이어 돌리면 그 기준을 잃는데(어디였는지는
    어디에도 기록되지 않는다), 재실행해도 완료된 스테이지가 skipped=True로 같은
    상대경로를 되돌려주므로 스스로 복구되지 않는다 — 그 분석 디렉터리는 영구히
    못 쓰게 된다. 호출자가 임의의 작업 폴더에서 부르는 것이 정상 사용이므로
    (에이전트가 프로젝트를 옮겨 다닌다) 입력 형태와 무관하게 여기서 고정한다."""
    return absolute(out if out is not None else analysis_dir(video))


def check_video(path: Path) -> Path:
    if not path.exists():
        # details를 채우는 이유: GUI가 이 오류를 자기 언어의 문장으로 다시 쓴다.
        # 메시지를 파싱하게 두면 문구를 고치는 날 GUI가 조용히 갈린다.
        raise CliError(EXIT_INPUT, "video-not-found", f"비디오 파일이 없습니다: {path}",
                       details={"path": str(path)})
    # 절대경로로 고정 — 출력 JSON·hint·state.json 어디에도 cwd 의존이 남지 않게.
    # check_source가 지문을 만들 때 resolve()로 실체를 보므로 원본 대조 규칙은 그대로다.
    return absolute(path)


def resolve_target(path: Path, out: Path | None = None) -> tuple[Path, Path]:
    """지목한 경로를 (원본 영상, 분석 디렉터리)로 푼다.

    영상 파일도 받고 이미 분석한 `.analysis` 디렉터리도 받는다. 디렉터리를 받는
    쪽이 필요한 이유는 분석이 끝난 뒤의 작업(status·review·frame·clean)에서는
    사용자가 **산출물을 보고 있기 때문**이다 — 손에 든 경로가 디렉터리인데 원본
    영상 경로를 되짚어 적으라고 요구할 근거가 없다. 원본이 어디였는지는 이미
    state.json에 적혀 있다.

    디렉터리로 지목하면 --out은 줄 수 없다. 둘 다 출력 위치를 정하는 말이라
    다르면 어느 쪽이 이겨도 나머지 하나가 조용히 무시되는데, 무시된 쪽이
    사용자가 의도한 것이면 엉뚱한 디렉터리를 만들고 끝난다."""
    if not path.is_dir():
        video = check_video(path)
        return video, resolve_out(video, out)

    out_dir = absolute(path)
    if out is not None and absolute(out) != out_dir:
        raise CliError(EXIT_INPUT, "target-conflict",
                       "분석 디렉터리를 지목하면서 --out을 함께 줄 수는 없습니다",
                       hint="둘 중 하나만 주세요 — 디렉터리만 주거나, "
                            "원본 영상과 --out을 함께 주거나",
                       details={"target": str(out_dir), "out": str(absolute(out))})
    if not state_path(out_dir).exists():
        raise CliError(EXIT_INPUT, "not-analyzed",
                       f"분석 디렉터리가 아닙니다 — state.json이 없습니다: {out_dir}",
                       hint="원본 영상을 지목해 `analysis-video analyze <영상>`으로 "
                            "먼저 분석하세요",
                       details={"path": str(out_dir)})
    src = (load_state(out_dir).get("source") or {}).get("path")
    if not src:
        raise CliError(EXIT_INPUT, "not-analyzed",
                       f"분석 디렉터리에 원본 영상이 기록되어 있지 않습니다: {out_dir}",
                       hint="원본 영상을 지목해 `analysis-video analyze <영상>`으로 "
                            "먼저 분석하세요",
                       details={"path": str(out_dir)})
    video = Path(src)
    if not video.exists():
        # 산출물만 옮겨 왔거나 원본을 지운 경우. 여기서 멈추지 않으면 아래 단계가
        # 없는 파일을 열며 죽고, 그때는 무엇이 없는지가 메시지에 남지 않는다.
        raise CliError(EXIT_INPUT, "source-missing",
                       f"state.json이 가리키는 원본 영상이 없습니다: {src}",
                       hint="원본을 그 자리에 되돌려 놓거나, 원본을 지목해 "
                            "새 --out으로 다시 분석하세요",
                       details={"path": str(out_dir), "source": src})
    return absolute(video), out_dir


def check_source(state: dict, video_path: Path) -> None:
    """다른 원본으로 이어서 돌리는 사고 방지 — 경로·크기 지문 대조.

    **여기서 보는 것은 영상뿐이다.** 전사 입력으로 쓰는 자막 파일도 같은
    state["source"] 안에 칸을 하나 차지하지만(아래 check_subtitle_input) 판정이
    달라 함수를 나눴다: 영상이 바뀌면 그 디렉토리는 통째로 다른 분석이라 **중단**해야
    하고, 자막이 바뀐 것은 같은 영상의 **전사만 다시 하면 되는** 일이다. 한 함수가
    '중단'과 '다시 하라'를 함께 내면 호출자가 둘을 구분할 수 없다 — 예외와 반환값을
    같은 자리에서 읽어야 하고, 자막 하나 갈아 끼운 사용자에게 "새 --out을 지정하세요"라는
    엉뚱한 안내가 나간다.

    `state["source"]`에는 자막 지문도 함께 살지만 이 대조는 영향받지 않는다 —
    딕셔너리를 통째로 비교하지 않고 path·size 두 칸만 본다."""
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


def _subtitle_label(fp: dict | None) -> str:
    """지문 → 사람이 읽을 한 조각. 크기를 함께 적는 이유: 같은 파일을 고쳐 넣으면
    이름은 그대로고 크기만 달라진다 — 이름만 적으면 "a.srt → a.srt"가 된다."""
    return f"{Path(fp['path']).name}({fp['size']}바이트)" if fp else "없음"


def check_subtitle_input(state: dict, subtitle: Path | None) -> str | None:
    """전사가 읽을 **자막 파일**의 지문을 대조·기록한다. 완료된 전사가 쓴 것과
    달라졌으면 그 사유 문장을, 아니면 None을 돌려준다. 예외는 던지지 않는다
    (위 check_source 참조).

    이 지문이 없으면 자막을 바꿔도 재실행에 반영되지 않는다. transcribe는 완료되면
    is_done으로 건너뛰므로, 사용자가 자막 파일을 새로 넣거나 고쳐도 --force를 붙이기
    전까지 그 파일은 영영 읽히지 않고 — 무시된 이유가 어디에도 남지 않는다.
    영상 지문(경로+크기)으로는 이 변화가 보이지 않는다: 자막은 영상 **밖**의 파일이다.
    (컨테이너 내장 자막은 반대로 영상 지문이 이미 덮는다 — 영상이 그대로면 트랙도
    그대로다. 그래서 이 칸에는 외부 파일만 들어간다.)

    자막이 없으면 None을 **기록한다**. "자막 없이 전사했다"가 나중에 자막이 생겼을 때
    '바뀌었다'고 말할 근거다.

    비교 대상은 **완료된 전사**뿐이다. 전사가 아직 없으면 비교할 과거가 없으므로
    무조건 None을 돌려준다 — 지문의 유무만 보고 판정하면 첫 실행이
    "자막이 바뀌어 다시 전사했습니다(이전: 없음 → 지금: a.srt)"라는 거짓 사유를
    transcript.json에 남긴다. 바뀐 적도, 애초에 전사한 적도 없다."""
    fp = ({"path": str(subtitle.resolve()), "size": subtitle.stat().st_size}
          if subtitle is not None else None)
    # 호출 순서상 check_source가 먼저 채우지만, 그 순서에 기대지 않는다 —
    # 기대면 순서가 바뀌는 날 자막 지문이 조용히 사라진다.
    source = state.setdefault("source", {})
    prev = source.get("subtitle")
    source["subtitle"] = fp
    if not is_done(state, "transcribe") or prev == fp:
        return None
    return (f"전사에 쓸 자막이 바뀌어 다시 전사했습니다 "
            f"(이전: {_subtitle_label(prev)} → 지금: {_subtitle_label(fp)})")


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
    """스테이지를 미완료로 되돌린다 — 그 입력이 바뀌어 산출물이 낡았을 때.

    완료 표시만 지우고 파일은 지우지 않는다. 다시 도는 스테이지가 자기 산출물을
    결정적으로 갈아엎으므로(runs.reset_unit) 여기서 파일까지 건드리면 지우는
    책임이 두 곳으로 갈린다."""
    state["stages"].pop(stage, None)


def build_metadata(video_path: Path, transcript: dict, build: dict,
                   screens: list[tuple[float, float]]) -> dict:
    """screens는 필수다 — 기본값(None→[])을 두면 "프레임은 있는데 화면 목록은 빈"
    metadata를 만들 수 있고, context.render가 그 목록의 첫 구간을 짚다가 죽는다.
    실제 산출 경로에서는 align.screen_periods가 최소 하나를 보장하므로 그런 값이
    올 자리가 없고, 없는 상황을 위한 기본값만 남아 있던 셈이다."""
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
            # 채택 판정이 밝기를 재고 나서야 내려지므로(frames.gate) 채택본에는
            # 반드시 있다. 값 자체가 판정의 근거라 없을 때를 대비할 자리가 아니다.
            "yavg": r["yavg"],
        }
        frames.append(f)

    rejected_out = []
    for r in rejected:
        # 탈락 레코드에도 screen이 있다 — align.attach_dialogue가 status를 보기
        # **전에** 전 레코드에 매긴다. 후보가 전부 탈락한 화면을 기록에서 잃지 않으려는
        # 설계라, 여기서 없을 때를 대비하면 그 설계가 깨진 날 조용히 None이 실린다.
        entry: dict = {"time": round(r["time"], 2), "sources": r["sources"],
                       "screen": r["screen"],
                       "reject_reason": r["reject_reason"], "image": r["image"]}
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
        "window": build["window"],
        # 화면 구간 목록 — 이미지가 하나도 없는 화면도 여기엔 남는다.
        # 이것이 없으면 후보가 전부 탈락한 화면이 기록에서 사라져 그동안의
        # 대사까지 함께 소실된다(실측 유실 최대 64%).
        "screens": [[round(a, 2), round(b, 2)] for a, b in screens],
        # 읽기용 축소 사본이 어디에 몇 장 있고 다 열면 얼마인가(budget.summary).
        # context.render가 여기서 사본 디렉터리 이름을 읽어 `![](…)`를 만들고,
        # 결과 JSON의 next.cost가 여기서 나온다. 기본값을 두지 않는다 —
        # 없으면 스키마 게이트가 먼저 거부해야 할 옛 산출물이다.
        "images": build["images"],
        "frames": frames,
        "rejected": rejected_out,
        # 주문형 추출(frame --at). 장부가 있으면 _merge_requested가 덮어쓴다 —
        # 키 자체는 항상 있어야 소비자가 조건 없이 읽는다(주문이 없으면 빈 목록).
        "requested": [],
        "transcript": {
            "backend": transcript["backend"],
            "model": transcript["model"],
            "text": transcript["text"],
            "segments": transcript["segments"],
        },
        "transcript_file": "transcript.json",
        "params": build["params"],
    }


def load_metadata(out_dir: Path, command_hint: str | None = None) -> dict:
    """command_hint는 호출자가 준다 — require_done과 같은 규약.

    이 자리에 명령 문자열을 상수로 박아 두면 플래그가 사라져도 남는다(실제로
    --points가 그렇게 남아, 거부한 뒤 exit 2가 되는 명령을 안내하고 있었다).
    호출자만 실제 원본 경로와 --out을 알기 때문에 규약도 그쪽이 맞다."""
    p = out_dir / "metadata.json"
    if not p.exists():
        raise CliError(EXIT_ORDER, "metadata-missing",
                       "metadata.json이 없습니다 — frames 스테이지를 먼저 실행하세요",
                       hint=command_hint)
    return _require_schema(p, json.loads(p.read_text(encoding="utf-8")), METADATA_SCHEMA)


def save_metadata(out_dir: Path, metadata: dict) -> None:
    write_json_atomic(out_dir / "metadata.json", metadata)
