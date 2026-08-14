"""review.md — 호출 AI가 쓴 분석문이 사는 자리.

지금까지 파이프라인은 `context.md`에서 끝났다. 그런데 사용자가 AI에게 시킨 것은
**분석**이고 context.md는 그 재료다. 그래서 분석 결과는 채팅에만 남고, 세션이
끝나면 사라지고, `status`는 "전부 완료"라고 말하면서 정작 시킨 일이 어디에도
없는 상태가 됐다.

여기서 코어가 소유하는 것은 **자리와 판정과 출처**뿐이다. 내용은 호출 AI가 쓴다.
패키지 안에 LLM 호출을 두지 않는다는 원칙은 그대로다.

**폐기한 points.json(샌드위치)의 재래가 아니다.** 그쪽은 AI 산출물이 *하류
결정적 스테이지의 입력*이 되어 시각 검출과 같은 출력 자리를 놓고 경쟁했다.
이쪽은 **말단**이다 — 아무것도 review.md를 소비하지 않으므로 경쟁할 자리가 없다.

## 왜 state.json에 기록하지 않는가

완료 여부를 state에 두고 싶어지지만, 저장소의 세 함수가 그것을 못 하게 한다.

- `manifest.mark_done`은 스테이지 칸을 **통째로 덮는다** → `frames`가 한 번
  돌 때마다 단위별 review 기록이 전멸한다.
- `manifest.invalidate_stage`는 `pop`이다 → 장부를 통째로 지운다.
- `cli.cmd_status`는 `state["stages"]`를 가공 없이 흘린다 → 파생값의 두 번째
  사본이 곧 거짓말을 한다.

그리고 review.md 쓰기와 `save_state`는 **서로 다른 두 파일의 두 번의 쓰기**라,
사이에서 죽으면 파일과 장부가 갈린다. 지문을 파일 머리말에 두면 쓰기가
`os.replace` 한 번으로 끝나고 이 넷이 정의상 사라진다.

## 무엇을 지문으로 삼는가

`runs/<run>/context.md`의 sha256 하나다. 그 파일이 곧 AI가 읽은 것이고,
임계 변경·대사 교체·프레임 재추출이 **전부** 거기 반영된다. 후보였다가 버린 것들:

- `transcript.json` 전체 sha — 대사와 무관한 칸(`source.notes`·`target_language`)이
  같이 들어 있어, 자막을 안 바꾸고 재전사만 해도 note 한 줄에 sha가 달라져
  모든 단위의 review가 한꺼번에 낡은 것이 된다.
- 프레임 파일명 목록 — 파일명은 전사와 무관하게 정해지므로 대사만 갈린
  재실행을 못 잡고, 파일명 규칙이 사실상 스키마가 된다.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

SCHEMA = "analysis-video/review@1"
REVIEWS_DIRNAME = "reviews"

# 본문을 무제한으로 받지 않는다. stdin이 잘못 연결되면(파이프 왼쪽이 영상 파일
# 같은 것) 수백 MB가 그대로 들어온다 — 그때 나야 할 것은 디스크가 찬 뒤의
# MemoryError가 아니라 입력 오류다.
MAX_BYTES = 1024 * 1024

# 마커에 버전을 넣지 않는다 — 넣으면 다음 버전이 구간을 못 찾아 머리말이
# 중복된다(skill.py:25-28과 같은 규약). 버전은 구간 **안**에 적는다.
BEGIN = "<!-- analysis-video:review BEGIN (생성됨 — 직접 수정하지 마세요) -->"
END = "<!-- analysis-video:review END -->"

_META = re.compile(re.escape(BEGIN) + r"\s*\n<!--\s*(\{.*?\})\s*-->", re.DOTALL)
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n*", re.DOTALL)


def reviews_dir(out_dir: Path) -> Path:
    return out_dir / REVIEWS_DIRNAME


def review_path(out_dir: Path, run: str) -> Path:
    """**분석 단위 디렉터리 밖**이다. 안에 두면 `runs.reset_unit`이
    `shutil.rmtree(unit)`으로 지운다 — 임계를 한 번 조정할 때마다 AI가 쓴 글이
    사라진다. `reset_unit`의 생존자 목록을 늘리는 방법도 있지만, 그쪽은 stash
    이름·`rmtree` 대상·복구 목적지가 전부 `requested/` 하나로 고정돼 있어
    파일 하나를 끼워 넣으면 `NotADirectoryError`가 난다. 자리를 옮기는 편이
    변경 자체를 없앤다."""
    return reviews_dir(out_dir) / f"{run}.md"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(text: str) -> str:
    """본문 정규화 — BOM·개행 형식·앞뒤 빈 줄만 손댄다.

    그 이상 손대면 "같은 본문인가"를 바이트로 물을 수 없게 된다. 이 넷을 손대는
    이유는 반대로, 내용과 무관하게 파이프·편집기·플랫폼에 따라 붙었다 떨어지는
    것들이라 그대로 두면 같은 글이 매번 다른 글로 판정되기 때문이다.

    **첫 줄의 들여쓰기는 지우지 않는다.** `strip()`으로 앞뒤를 한꺼번에 털면
    본문이 들여쓴 코드 블록으로 시작할 때 그 4칸이 사라져 마크다운이 깨진다.
    앞쪽에서 지우는 것은 빈 줄뿐이다."""
    body = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return body.lstrip("\n").rstrip() + "\n"


def render_header(*, run: str, unit_dir: Path, context_rel: str, context_sha: str,
                  video: Path, version: str, at: str) -> str:
    """코어가 소유하는 머리말. 기계용 한 줄은 HTML 주석 안의 JSON이다 —
    마크다운 표를 파싱할 필요가 없고, 렌더된 문서에서는 보이지 않으며,
    `schema` 칸을 스스로 들어 STATE/METADATA와 **독립적으로** 진화한다.

    임계·화면 수·이미지 수·전사 출처는 **적지 않는다.** 그것들은 metadata.json에서
    언제든 다시 읽히는 값이고, 파일에 굳히면 `frames`를 다른 임계로 다시 돌린
    뒤에도 옛 값을 현재 사실처럼 계속 주장한다. 머리말은 참조 경로만 적는다."""
    meta = json.dumps({"schema": SCHEMA, "run": run, "context": context_rel,
                       "context_sha256": context_sha, "at": at, "version": version},
                      ensure_ascii=False, sort_keys=True)
    return "\n".join([
        BEGIN,
        f"<!-- {meta} -->",
        f"# {video.name} — {run}",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 분석 단위 | `{run}` — `{unit_dir}` |",
        f"| 읽은 것 | `{context_rel}` · sha256 `{context_sha[:16]}…` |",
        f"| 원본 | `{video}` |",
        f"| 작성 | {at} · analysis-video {version} |",
        END,
        "",
    ])


def parse_header(text: str) -> dict | None:
    """머리말의 기계용 JSON. 없거나 깨졌으면 None — 그때는 '이 파일이 무엇을
    읽고 쓴 것인지 모른다'이므로 낡음 판정도 할 수 없다(호출부가 stale로 다룬다)."""
    m = _META.search(text)
    if m is None:
        return None
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return meta if isinstance(meta, dict) and meta.get("schema") == SCHEMA else None


def strip_header(text: str) -> str:
    """머리말을 걷어낸 본문. 재제출된 글이 '같은 본문인가'를 물으려면 코어가
    붙인 부분을 빼고 비교해야 한다 — 안 그러면 시각이 박힌 머리말 때문에
    같은 글도 매번 다르다고 판정된다."""
    return _BLOCK.sub("", text, count=1).lstrip("\n")


def compose(body: str, header: str) -> str:
    return header + normalize(body)


def status(out_dir: Path, run: str, context_path: Path) -> dict:
    """이 단위의 review가 있는가, 있다면 지금 context.md와 맞는가.

    상태 넷: `missing`(파일 없음) · `unreadable`(머리말이 없거나 깨짐) ·
    `stale`(읽은 것이 그 뒤 바뀜) · `current`."""
    path = review_path(out_dir, run)
    if not path.exists():
        return {"run": run, "state": "missing", "path": str(path)}
    text = path.read_text(encoding="utf-8")
    meta = parse_header(text)
    if meta is None:
        return {"run": run, "state": "unreadable", "path": str(path)}
    now = sha256_of(context_path) if context_path.exists() else None
    state = "current" if now is not None and meta["context_sha256"] == now else "stale"
    return {"run": run, "state": state, "path": str(path),
            "at": meta.get("at"), "context_sha256": meta["context_sha256"],
            "context_sha256_now": now}


def decide(previous: str | None, body: str, prev_sha: str | None, now_sha: str,
           force: bool) -> str:
    """무엇을 할 것인가 — `create` | `unchanged` | `refresh` | `update` | `conflict`.

    **`unchanged` 판정이 낡음 검사보다 뒤에 온다.** 앞에 두면 "본문은 그대로인데
    읽은 것이 바뀐" 상태에서 아무리 재제출해도 낡음이 풀리지 않는다. `next`는
    계속 "다시 읽고 다시 넣으세요"를 안내하고, 재제출 한 번마다 이미지 토큰
    수만이 타면서 상태는 그대로인 교착이 된다. `refresh`는 "본문을 다시 검토했고
    그대로 유효하다"의 기록이라 지문과 시각을 갱신한다."""
    if previous is None:
        return "create"
    same_body = strip_header(previous) == normalize(body)
    if same_body and prev_sha == now_sha:
        return "unchanged"
    if same_body:
        return "refresh"
    if prev_sha != now_sha or force:
        return "update"
    return "conflict"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
