"""analysis-video CLI — 에이전트 친화 계약 구현.

흐름: split → transcribe → frames → context.md. 중간에 멈추지 않는다.
이미지 추출 기준은 **프레임 변화량 하나**다. 예전에는 호출 에이전트가 전사를 읽고
points.json으로 "중요한 시각"을 지정하면 그 자리에서도 프레임을 뽑았는데, 그건
산출물이 선별된 부분집합이던 시절의 장치다. 지금 context.md는 모든 화면과 모든
문장을 담은 완전 분할이므로 미리 고를 이유가 없고, 오히려 화면을 보지 못한 채
텍스트만으로 고른 시각이 시각적 검출과 같은 자리를 놓고 경쟁해 기준이 흐려졌다.
사후 정밀 추출이 필요하면 `frame --at`이 그 역할을 한다 — context.md를 읽고
이미지와 대사를 **함께 본 뒤** 고르는 것이라 더 낫다.

`--range`를 여러 번 주면 그만큼의 **독립 분석 단위**가 runs/ 아래에 생긴다.
겹쳐도 무방하다(runs.py 참조). split·transcribe와 검출 캐시는 영상 전체에 대해
한 번만 만들어 공유한다.

대사는 **자막이 먼저고 whisper가 마지막**이다(run_transcribe의 사다리). 자막은
사람이 적은 원문이고 whisper는 오디오에서 추론한 텍스트라, 둘 다 있으면 고를
이유가 없다 — 판단 근거는 stt/subtitles.py 머리말에 있다. 다만 **자막 큐 경계는
화면 검출에 쓰지 않는다**: 자막이 닿는 곳은 대사 트랙뿐이고, 텍스트만 보고 고른
시각이 시각적 검출과 경쟁하면 아래 points.json과 같은 고장이 된다.

stdout = 결과 JSON 한 건(agent-guide 제외), 로그 = stderr.
state.json 덕분에 같은 명령 재실행 = 이어하기(타임아웃 내성).
"""
import argparse
import json
import sys
from importlib.util import find_spec
from pathlib import Path

from . import (__version__, align, budget, context, errors, manifest, media,
               review, runs, stt)
from . import clean as clean_mod
from . import frames as frames_mod
from . import split as split_mod
from .agent_guide import GUIDE
from .errors import EXIT_DEPS, EXIT_INPUT, EXIT_OK, CliError, emit, log
from .stt import lang, subtitles
from .stt.base import (DEFAULT_MODEL, MODEL_SIZES, add_notes, empty_result,
                       mark_target_language)

def resolve_target(args) -> tuple[Path, Path]:
    """`<video>` 커맨드 아홉 개가 공유하는 입구 — 지목한 경로와 --out을 푼다.

    manifest에 위임한다. 경로 규약(`<영상>.analysis`, 절대경로 고정, 디렉터리로도
    지목 가능)은 GUI도 쓰는 것이라 코어 한 곳에만 있어야 한다."""
    return manifest.resolve_target(args.video, args.out)


def stage_command(command: str, video: Path, out_dir: Path) -> str:
    """스테이지 명령을 그대로 실행 가능한 형태로 만든다 — hint와 next의 공통 출처.

    안내를 따랐더니 또 실패하는 일이 없어야 한다: 원본 경로가 빠지면 인자 부족으로
    exit 2가 되고, --out으로 기본 위치를 벗어난 분석은 --out 없이 재실행하면
    엉뚱한 곳을 새로 만든다. 둘 다 여기서 한 번에 막는다."""
    cmd = f"analysis-video {command} {video}"
    if out_dir != manifest.resolve_out(video, None):
        cmd += f" --out {out_dir}"
    return cmd


def stage_hint(command: str, video: Path, out_dir: Path) -> str:
    """선행 스테이지 미완료 안내 — 실행할 명령 + 한국어 안내문."""
    return f"{stage_command(command, video, out_dir)} 를 먼저 실행하세요"


def next_step(video: Path, out_dir: Path) -> dict:
    """이 영상에 대해 **지금 무엇을 하면 되는가** — 모든 `<video>` 커맨드가
    같은 모양으로 내보내는 값.

    전에는 `next`가 커맨드마다 다른 것이었다: `split`·`transcribe`는 실행 가능한
    명령 문자열, `analyze --until`은 맨 스테이지 이름, `frames`·`analyze`는 산문.
    받는 쪽이 타입을 먼저 알아내야 하니 사슬이 거기서 끊겼다. 여기서는 `do`가
    셋 중 하나로 고정되고, 각 값에 따라 읽을 칸이 정해진다.

        do="run"   → command를 그대로 실행한다
        do="read"  → read[]를 열고 나서 command(= review 제출)를 실행한다
        do="done"  → 사용자에게 답한다

    "읽었는가"를 코어는 알 수 없으므로 `do="review"` 같은 토큰은 두지 않는다 —
    발화 지점이 없는 분기가 된다. 읽기와 제출은 한 걸음이다."""
    state = manifest.load_state(out_dir)
    for stage in ("split", "transcribe", "frames"):
        if not manifest.is_done(state, stage):
            return {"do": "run", "command": stage_command("analyze", video, out_dir),
                    "why": f"'{stage}' 스테이지가 아직 완료되지 않았습니다"}

    pending = []
    for entry in runs.load_index(out_dir):
        unit = out_dir / "runs" / entry["name"]
        st = review.status(out_dir, entry["name"], unit / "context.md")
        if st["state"] != "current":
            pending.append((entry, unit, st))
    if not pending:
        return {"do": "done",
                "why": "분석과 기록이 모두 끝났습니다 — 사용자에게 답하세요"}

    entry, unit, st = pending[0]
    cmd = f"{stage_command('review', video, out_dir)} --run {entry['name']} --write -"
    step = {"do": "read", "read": [str(unit / "context.md")], "command": cmd,
            "why": {"missing": "이 분석 단위의 리뷰가 아직 없습니다",
                    "unreadable": "리뷰 파일의 머리말을 읽을 수 없습니다 — 다시 쓰세요",
                    "stale": "리뷰가 읽은 context.md가 그 뒤 바뀌었습니다"}[st["state"]],
            "remaining": [e["name"] for e, _u, _s in pending]}
    meta = unit / "metadata.json"
    if meta.exists():
        # 비용은 metadata를 열지 않고도 보여야 한다 — 열지 말지를 정하는 값이라
        # 그것을 알려고 파일을 하나 더 여는 것은 순서가 뒤집힌 것이다.
        try:
            step["cost"] = budget.cost(
                json.loads(meta.read_text(encoding="utf-8"))["images"])
        except (json.JSONDecodeError, KeyError):
            pass  # 옛 산출물 — 스키마 게이트가 실제 읽기에서 거부한다
    return step


# ---------- 스테이지 실행 (cmd_*와 analyze 오케스트레이터가 공유) ----------

def run_split(video: Path, out_dir: Path) -> dict:
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    if manifest.is_done(state, "split"):
        return {"stage": "split", "skipped": True,
                **state["stages"]["split"]["outputs"]}
    log("[split] 비디오/자막 리소스 분리 중...")
    res = split_mod.split_media(video, out_dir)
    if not res.has_audio:
        log("[split] 경고: 오디오 스트림이 없는 영상입니다")
    outputs = {"has_audio": res.has_audio,
               "video": str(res.video), "subtitles": res.subtitles}
    manifest.mark_done(state, "split", outputs)
    manifest.save_state(out_dir, state)
    return {"stage": "split", "skipped": False, **outputs}


# 자막에서 온 전사의 출처 종류 — stt.base.SOURCE_KINDS에서 whisper·none을 뺀 것.
# 여기서 갈리는 자리가 둘(재사용 note, outputs["model_size"])이라 이름을 붙여 둔다.
SUBTITLE_KINDS = ("explicit", "sidecar", "embedded")


def run_transcribe(video: Path, out_dir: Path, model: str | None,
                   backend: str | None, language: str | None,
                   force: bool = False, transcript: Path | None = None,
                   no_subtitles: bool = False, sub_lang: str | None = None) -> dict:
    """전사 출처 사다리 — ①--no-subtitles ②--transcript ③자막 후보 ④오디오 없음
    ⑤whisper. 위에서 하나가 성립하면 아래는 보지 않는다.

    ③이 '사이드카 다음에 내장 트랙'이 아니라 **한 단계**인 것이 계약이다. 두 풀을
    차례로 보면 언어는 풀 안에서만 우선이 되어, 사이드카에 영어만 있고 내장 트랙에
    목표 언어인 한국어가 있는 영상에서 영어가 이긴다. 후보는 출처와 무관하게 한
    줄로 세우고 언어를 1차 키로 비교한다(stt/subtitles.rank).

    model=None은 "모델을 요청하지 않았다"이고, 기본 모델로 굳히는 것은 재사용
    판정을 지난 뒤다(아래 주석 참조).

    언어 인자가 둘인 것은 물음이 둘이기 때문이다. sub_lang은 **어느 자막을 고를까**
    (사이드카·내장 트랙의 순위)이고, language는 **오디오를 무슨 언어로 들을까**
    (whisper의 힌트)다. 한 값으로 겸하면 "영어 강의에 한국어 자막"처럼 둘이 갈리는
    영상에서 한쪽이 반드시 틀리고, 무엇을 요청한 것인지도 산출물에서 구분되지 않는다.
    sub_lang이 없으면 시스템 로케일에서 정한다(stt/lang.from_locale).

    자막이 whisper보다 앞인 근거는 stt/subtitles.py 머리말에 있다(사람이 적은
    원문 대 오디오에서 추론한 텍스트). 이 함수의 일은 그 순서를 실행하는 것과,
    **왜 한 단계 내려갔는지를 남기는 것**이다: 사유를 stderr로만 흘리면 산출물에는
    "whisper가 돌았다"만 남아 자막이 없었는지, 있었는데 거부됐는지, 아예 보지도
    않았는지(--no-subtitles)를 나중에 구분할 수 없다. 그래서 단계마다 notes에
    쌓아 transcript.json의 source.notes로 함께 내보낸다.

    실패의 취급이 단계마다 다른 것도 계약이다. 명시 지정(--transcript)만 오류로
    멈춘다(exit 2) — 사용자가 이 파일을 쓰라고 지목했는데 조용히 다른 출처로
    바꿔치기하면 산출물이 요청과 다른 물건이 된다. 자동 탐색(사이드카·내장 트랙)은
    "찾아봤는데 못 쓴다"가 정상 경로이므로 사유를 남기고 내려간다."""
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    # 사용자가 밝힌 자막 언어. "밝혔는가"의 답은 플래그의 유무(sub_lang is None)가
    # 아니라 **정규화한 값**이다 — 둘은 값이 비거나 공백뿐인 지정(`--sub-lang ""`)에서
    # 갈리고, 그때 아래 두 자리가 함께 틀린다(실측): 목표는 로케일에서 왔는데 "요청이
    # 있었다"로 세어 로케일이 정했다는 기록이 빠지고, 재사용 경로의 note는 빈
    # 따옴표('')를 요청 언어라고 인용한다. 판정을 여기 한 번으로 모은다.
    requested = lang.normalize(sub_lang)
    # 목표 언어 = 요청, 없으면 시스템 로케일. 자막 선택과 언어 신고가 모두
    # 이 하나를 쓴다 — 두 곳에서 각자 정하면 "고른 기준"과 "다르다고 말한 기준"이 갈린다.
    target = requested or lang.from_locale()
    # 자막 후보를 사다리보다 **먼저** 정한다: 이 목록에서 지문이 나오고
    # (자막을 갈아 끼우면 재실행에 반영되어야 한다 — check_subtitle_input 참조),
    # 사다리도 같은 목록을 쓴다. 두 번 탐색하면 지문과 실제로 읽은 파일이 갈린다.
    explicit, sidecars, notes = _subtitle_sources(
        video, transcript, no_subtitles, target)
    if requested is None and target is not None:
        # 로케일이 정한 값은 명령줄 어디에도 보이지 않는다 — 남기지 않으면
        # "왜 이 자막이 골라졌나"도, "왜 언어가 다르다고 하나"도 산출물만으로
        # 설명할 수 없다.
        # 문구가 "플래그가 없어서"가 아닌 이유: `--sub-lang ""`은 플래그가 있어도
        # 언어를 밝히지 않은 실행이고, 이 note는 그 경우에도 나간다(위 requested).
        notes.insert(0, f"--sub-lang으로 자막 언어를 밝히지 않아 시스템 로케일의 "
                        f"'{target}'을 목표 언어로 삼았습니다")
    # 지문에 들어가는 것은 **영상 밖의 파일**뿐이다(check_subtitle_input의 근거).
    # 자동 탐색에서는 순위 1위 사이드카가 그 대상이다 — 목표 언어가 바뀌어 다른
    # 파일이 1위가 되면 지문도 함께 바뀌어 재전사가 걸린다. 내장 트랙은 영상
    # 지문이 이미 덮으므로 여기 넣지 않는다.
    changed = manifest.check_subtitle_input(state, _fingerprint(explicit, sidecars))
    split_info = manifest.require_done(
        state, "split", stage_hint("split", video, out_dir))
    duration = round(media.get_duration(video), 2)

    if manifest.is_done(state, "transcribe") and not force:
        prev = state["stages"]["transcribe"]["outputs"]
        if changed is None and _demand_met(prev, explicit):
            return _reuse_transcript(prev, duration, model, requested, target)
    if changed is not None:
        log(f"[transcribe] {changed}")
        notes.append(changed)
    # 요청이 없었으면(--model 없음) 여기서 비로소 기본 모델로 굳힌다. 위의 재사용
    # 판정을 지난 **뒤**여야 하는 이유는, 파서가 기본값을 미리 채우면 _reuse_transcript가
    # "사용자가 고른 모델"과 "그날의 기본 모델"을 구분할 수 없기 때문이다. 그러면
    # DEFAULT_MODEL을 한 번 올리는 것만으로, 그 전에 전사를 마친 분석은 전부 모델 불일치
    # note를 뱉고, 호출 에이전트는 그것을 해소하려 --force로 재전사(가중치 다운로드 +
    # 추론)를 돌린다 — 아무도 요청한 적 없는 불일치라 그 재전사는 전부 헛일이다.
    if model is None:
        model = DEFAULT_MODEL

    # split_media는 자막이 없어도 빈 목록을 남긴다 — 스키마 게이트를 통과한
    # state.json이면 이 칸은 반드시 있다(방어할 자리가 아니다).
    tracks = split_info["outputs"]["subtitles"]
    # ①의 나머지 절반: --no-subtitles면 자막 단계를 아예 밟지 않는다. tracks를 빈
    # 목록으로 바꿔 같은 길을 태우지 않는 이유는, 그러면 "자막 트랙이 없다"는 **거짓**
    # 사유가 산출물에 남기 때문이다 — 안 본 것과 없는 것은 다르다.
    result = None if no_subtitles else _subtitle_transcript(
        explicit, sidecars, tracks, duration, notes, target)
    if result is None:
        result = _audio_transcript(video, split_info, model, backend, language, notes)

    # 목표 언어는 출처가 정해진 **뒤에** 기록한다 — 어느 사다리 단계가 이겼든
    # "요청한 언어와 같은가"는 같은 자리에서 한 번만 판정되어야 한다.
    mismatch = mark_target_language(result, target, requested=requested is not None)
    source = result["source"]
    if mismatch:
        origin = "요청한" if requested is not None else "로케일이 정한"
        log(f"[transcribe] 알림: 전사 언어({source['language']})가 {origin} 자막 언어"
            f"({source['target_language']})와 다릅니다 — 번역은 하지 않습니다")

    manifest.write_json_atomic(out_dir / "transcript.json", result)
    outputs = {
        "transcript": str(out_dir / "transcript.json"),
        "backend": result["backend"], "device": result["device"],
        "model": result["model"],
        # whisper가 실제로 돈 경우에만 모델 크기를 남긴다. 자막 전사에 요청 모델을
        # 적어 두면 "small로 전사했다"는 거짓이 되고, 재사용 note가 그 거짓을
        # 근거로 "--force로 다시 전사하라"는 헛된 안내를 낸다.
        "model_size": model if source["kind"] == "whisper" else None,
        "n_segments": len(result["segments"]), "n_words": len(result["words"]),
        # 사유 전문은 transcript.json에 두고 여기엔 결론만 — 어느 출처가 이겼는지는
        # 호출자가 결과 JSON만 보고도 알아야 한다("내 자막이 쓰였나?").
        "source_kind": source["kind"], "source_path": source["path"],
        # 언어 세 칸: 실제 전사의 언어 / 요청한 언어(로케일이 정한 값도 여기 보인다) /
        # 둘이 다른가. 불리언을 함께 내는 이유는 mark_target_language에 있다 —
        # ko ↔ kor 동치 규칙을 모르는 소비자는 두 문자열만으로 답을 구할 수 없다.
        "language": source["language"],
        "target_language": source["target_language"],
        # 목표가 `--sub-lang`에서 왔는지 시스템 로케일에서 왔는지.
        # 이것 없이 mismatch만 보면, 사용자가 아무것도 요청하지 않은 실행에서도
        # "요청과 다르다"로 읽혀 멀쩡한 전사가 문제처럼 보인다.
        "target_language_source": source["target_language_source"],
        "language_mismatch": mismatch,
    }
    manifest.mark_done(state, "transcribe", outputs)
    # 대사가 새로 쓰였으면 그것을 화면에 붙여 둔 산출물(runs/*/metadata.json·context.md)은
    # 낡았다. 파일은 그대로 두면 아무도 그 사실을 모른 채 옛 대사를 읽으므로
    # frames를 미완료로 되돌린다 — 그다음 실행에 무엇을 해야 하는지는 require_done이
    # 안내한다. 재사용·skip 경로는 위에서 이미 반환했으므로 여기 오지 않는다.
    manifest.invalidate_stage(state, "frames")
    manifest.save_state(out_dir, state)
    return {"stage": "transcribe", "skipped": False, "duration": duration, **outputs}


def _demand_met(prev: dict, explicit: Path | None) -> bool:
    """--transcript로 지목한 파일이 완료된 전사의 실제 출처인가 (지목이 없으면 참).

    지문(자막 파일의 경로+크기)만으로는 이 요구를 지킬 수 없다. 같은 파일을
    사이드카로 이미 보고 **거부**한 뒤라면 지문은 그대로이므로 재실행이 건너뛰어지고,
    "이 자막을 쓰라"고 지목한 사용자는 그것을 쓰지 않은 전사를 exit 0으로 돌려받는다 —
    거부 사유조차 보지 못한 채로. 지목은 매번 실제 출처와 대조한다(실측으로 잡은 구멍)."""
    return explicit is None or (prev["source_kind"] == "explicit"
                                and prev["source_path"] == str(explicit))


def _reuse_transcript(prev: dict, duration: float, model: str | None,
                      requested: str | None, target: str | None) -> dict:
    """완료된 전사를 그대로 돌려준다. note는 "요청과 다른 것을 줬다"일 때만 단다.

    그래서 model=None(--model을 안 준 실행)은 모델을 두고 아무 말도 하지 않고,
    requested=None(자막 언어를 밝히지 않은 실행)은 언어를 두고 아무 말도 하지 않는다.
    기본값과 비교해 말하면 note의 뜻이 "당신이 다른 것을 요청했다"에서 "기본값이
    움직였다"로 바뀐다 — DEFAULT_MODEL이 tiny에서 small로 올라간 날 실제로 기존 분석
    전부가 불일치를 호소했고, 그것은 아무도 요청하지 않은 불일치라 해소할 방법이
    헛된 재전사밖에 없다. 로케일에서 온 자막 언어도 똑같다(노트북을 영어 로케일로
    켠 날 모든 분석이 항의한다). **말을 아끼는 것과 값을 틀리게 두는 것은 다르다** —
    언어 두 칸은 침묵하는 실행에서도 이번 요청 기준으로 다시 계산한다(아래).

    모델 비교는 whisper로 만든 전사에서만 뜻이 있다. 자막에서 온 전사에는 모델
    크기라는 개념이 자체가 없어(outputs["model_size"]가 None) 같은 비교를 그대로
    돌리면 "기존 전사(모델=None)를 재사용했습니다"라는 헛소리가 나가고, 그것을
    고치려 --force를 눌러도 결과는 같은 자막이라 사용자만 두 번 속는다.
    대신 그 경우에는 --model이 왜 안 먹었는지를 말해 준다."""
    result = {"stage": "transcribe", "skipped": True, "duration": duration, **prev}
    # 언어 두 칸은 **이번 호출**의 요청으로 다시 계산한다. state.json에 실린 값은
    # 전사를 쓸 당시의 요청이라, 그대로 흘리면 어제 --sub-lang ja로 만든 분석을
    # 오늘 --sub-lang en으로 열었을 때 "요청 언어 ja, 불일치"라는 지난 실행의 답이
    # 이번 결과로 나간다. 전사 자체(transcript.json)는 만들어질 때의 기록이므로
    # 손대지 않는다 — 그쪽은 "어떻게 만들어졌나", 이쪽은 "지금 무엇을 물었나"다.
    result["target_language"] = target
    result["language_mismatch"] = bool(
        target and prev["language"] and not lang.matches(prev["language"], target))
    notes = []
    if model is not None:
        if prev["model_size"] not in (None, model):
            notes.append(f"기존 전사(모델={prev['model_size']})를 재사용했습니다 — "
                         "다른 모델로 다시 전사하려면 --force를 지정하세요")
        elif prev["source_kind"] in SUBTITLE_KINDS:
            notes.append(f"이 분석의 전사는 자막({prev['source_kind']})에서 왔습니다 — "
                         f"지정한 --model({model})은 whisper로 전사할 때만 쓰입니다")
    # 언어가 달라도 다시 전사하지 않는다. 사이드카가 바뀌는 경우는 지문이 이미
    # 잡아내므로(check_subtitle_input), 여기까지 왔다는 것은 새 --sub-lang으로
    # 다시 골라도 같은 파일이었다는 뜻이다 — 남은 것은 그 사실을 말해 주는 일이다.
    # (언어를 모르는 전사는 위 계산에서 이미 불일치가 아니다.)
    if requested is not None and result["language_mismatch"]:
        notes.append(f"재사용한 전사의 언어는 '{prev['language']}'인데 요청한 자막 "
                     f"언어는 '{requested}'입니다 — 이 도구는 번역하지 않습니다. "
                     "다른 자막을 다시 고르려면 --force를 지정하세요")
    if notes:
        result["note"] = " / ".join(notes)
    return result


def _subtitle_sources(video: Path, transcript: Path | None, no_subtitles: bool,
                      target: str | None
                      ) -> tuple[Path | None, list[subtitles.Candidate], list[str]]:
    """사다리 ①②③ 중 **무엇을 볼 것인가** — (지목한 파일|None, 사이드카 후보, 메모).

    보기만 하고 열지는 않는다. 이 결과에서 전사 입력의 지문이 나오므로 스테이지를
    건너뛸 때(is_done)도 반드시 통과해야 하는 자리이고, 파일을 읽는 것은 그다음
    문제다. 못 찾았다는 사실도 메모로 남긴다 — 자막이 없어서 whisper가 돌았음을
    산출물만 보고 말할 수 있어야 한다(split.py 머리말과 같은 규약).

    지목(--transcript)과 자동 탐색을 한 값으로 겸하지 않는다: 지목은 거부되면
    멈추는 **요구**이고 후보 목록은 순서대로 내려가는 **탐색**이라, 같은 칸에 담으면
    호출자가 둘을 구분할 근거를 잃는다. 지목이 있으면 후보 목록은 비어 있다.

    내장 트랙을 여기서 합치지 않는 이유는 지문의 정의에 있다 — 지문은 영상 밖의
    파일만 대상으로 하므로(check_subtitle_input) 이 단계에서 필요한 것은 사이드카
    순위뿐이다. 두 풀을 가로지르는 비교는 트랙 목록이 손에 들어온 뒤
    (_subtitle_transcript) 한 번에 한다. 그때 사이드카를 다시 훑지 않도록
    여기서 세운 후보를 그대로 넘긴다."""
    if no_subtitles:
        if transcript is not None:
            raise CliError(EXIT_INPUT, "conflicting-options",
                           "--transcript와 --no-subtitles는 함께 쓸 수 없습니다",
                           hint="지정한 자막을 쓰려면 --no-subtitles를 빼세요")
        return None, [], ["--no-subtitles가 지정되어 자막을 보지 않았습니다"]
    if transcript is not None:
        path = transcript.resolve()
        if not path.is_file():
            raise CliError(EXIT_INPUT, "transcript-not-found",
                           f"--transcript로 지정한 자막 파일이 없습니다: {path}",
                           hint="자동 탐색에 맡기려면 --transcript 없이 실행하세요")
        return path, [], []
    sidecars = subtitles.rank(subtitles.sidecar_candidates(video), target)
    if not sidecars:
        return None, [], ["영상 옆에서 쓸 수 있는 자막 파일을 찾지 못했습니다"]
    return None, sidecars, []


def _fingerprint(explicit: Path | None,
                 sidecars: list[subtitles.Candidate]) -> Path | None:
    """전사 입력의 지문 대상 — 지목한 파일, 없으면 순위 1위 사이드카.

    내장 트랙은 대상이 아니다: 영상 안에 있으므로 영상 지문(check_source)이 이미
    덮는다. 1위만 보는 것은 그것이 실제로 먼저 열리는 파일이기 때문이고, 그것이
    거부돼 2위가 쓰이더라도 1위 파일이 바뀌면 순위 자체가 다시 계산되어야 하므로
    재전사 판정으로는 1위가 맞는 대상이다."""
    if explicit is not None:
        return explicit
    return sidecars[0].path if sidecars else None


def _subtitle_transcript(explicit: Path | None,
                         sidecars: list[subtitles.Candidate], tracks: list[dict],
                         duration: float, notes: list[str],
                         target: str | None) -> dict | None:
    """사다리 ②③ — 지목한 파일, 그리고 사이드카·내장 트랙을 한 줄로 세운 후보들.
    하나도 못 쓰면 None(사유는 notes에).

    notes를 제자리에서 늘리는 것은 의도적이다: 여기서 못 쓴 사유가 아래 단계
    (whisper·빈 전사)의 산출물까지 따라가야 "왜 whisper가 돌았는가"가 남는다."""
    if explicit is not None:
        # 품질 검사를 강제하지 않는다 — 후보 여럿에서 고르기 위한 검사인데 지목이
        # 그 고르기를 대신했다(subtitles.result_from_cues 독스트링). 사유는 버리지
        # 않고 메모로 따라간다.
        result, why = subtitles.result_from_file(explicit, duration, kind="explicit",
                                                 enforce_quality=False)
        if result is None:
            # 여기 오는 것은 읽지 못했거나 대사가 하나도 없는 파일뿐이다. 조용히
            # 다른 출처로 내려가면 사용자가 요청한 것과 다른 산출물이 같은 이름으로
            # 나오므로, 폴백하지 않고 멈춘다.
            raise CliError(EXIT_INPUT, "transcript-rejected",
                           f"--transcript로 지정한 자막을 쓸 수 없습니다: {' / '.join(why)}",
                           hint="다른 자막 파일을 지정하거나, 자동 탐색에 맡기려면 "
                                "--transcript 없이, 자막을 아예 무시하려면 "
                                "--no-subtitles로 실행하세요",
                           details={"path": str(explicit), "notes": why})
        for note in why:
            if note.startswith(subtitles.WAIVED):
                log(f"[transcribe] 경고: {note}")
        _log_adopted(f"지정한 자막 '{explicit.name}'", result)
        return add_notes(result, notes)

    embedded, unusable = subtitles.embedded_candidates(tracks)
    notes.extend(unusable)
    ranked = subtitles.rank([*sidecars, *embedded], target)
    for cand in ranked:
        result, why = subtitles.result_from_file(cand.path, duration, kind=cand.kind)
        if result is None:
            # 순위대로 **다음 후보로 내려간다**. 거부 사유는 전부 쌓아 둔다 —
            # 한 후보가 왜 떨어졌는지가 남지 않으면, 덜 좋은 자막이 쓰인 이유도
            # whisper까지 내려간 이유도 산출물만으로는 설명되지 않는다.
            notes.append(f"{cand.label}: {' / '.join(why)}")
            log(f"[transcribe] {cand.label} 거부: {' / '.join(why)}")
            continue
        if cand.kind == "embedded":
            # 트랙 번호와 선언 언어는 뽑아 둔 파일(subs/track{n}.srt)에 없다 —
            # 컨테이너가 선언한 사실이라 split이 남긴 엔트리에만 있고, 여기서
            # 채워야 산출물에서 원본 트랙으로 되짚을 수 있다. (result_from_file은
            # 파일만 보므로 이 두 칸을 채울 방법이 없다.)
            result["source"]["track"] = cand.track
            result["source"]["language"] = cand.language
        notes.extend(subtitles.choice_notes(cand, ranked, target))
        _log_adopted(cand.label, result)
        return add_notes(result, [*cand.notes, *notes])
    return None


def _log_adopted(label: str, result: dict) -> None:
    """채택 로그 — 출처가 섞이므로 어느 후보였는지를 이름으로 밝힌다."""
    source = result["source"]
    log(f"[transcribe] {label}을 전사로 채택 "
        f"(큐 {source['n_cues']}개, 커버리지 {source['coverage']:.0%})")


def _audio_transcript(video: Path, split_info: dict, model: str, backend: str | None,
                      language: str | None, notes: list[str]) -> dict:
    """사다리 ⑤⑥ — 오디오가 없으면 빈 전사, 있으면 whisper.

    **원본 영상을 그대로 백엔드에 넘긴다.** 중간 wav를 거치지 않는다:
    `media.load_audio_mono16k`가 컨테이너를 가리지 않고 같은 배열을 만들기 때문이다
    (실측 3편 비트 동일, split.py 머리말 참조). 여기가 이 파이프라인에서 오디오를
    건드리는 **유일한 자리**라, 자막이 이기면 오디오는 디코드조차 되지 않는다.

    분리된 video.mkv를 쓰면 안 된다 — 그쪽은 무음이다(_copy_video가 비디오
    스트림만 복사한다). 넘기면 `decode(audio=0)`이 IndexError로 죽는다.

    빈 전사도 손으로 dict를 짓지 않고 stt.base를 통과시킨다: 그 자리가 저장소에서
    스키마가 갈리던 유일한 지점이었다(base.empty_result 독스트링)."""
    # split은 오디오가 없어도 has_audio=False를 **기록한다** — 칸이 비어 있는 것과
    # 칸이 없는 것을 구분하기 위해서다. 스키마 게이트를 통과한 state.json이면
    # 이 칸은 반드시 있으므로 .get으로 없는 경우를 만들어 내지 않는다.
    if not split_info["outputs"]["has_audio"]:
        log("[transcribe] 오디오 스트림 없음 — 빈 전사를 기록합니다")
        return empty_result([*notes, "오디오 스트림이 없어 전사할 것이 없습니다"])
    # **여기가 STT 백엔드 결손이 실패가 되는 유일한 지점이다.** 백엔드는 선택
    # 설치(extra)이므로 없는 것 자체는 고장이 아니고, 자막이 하나도 없어 음성을
    # 받아써야 하는 이 자리에서 비로소 종료코드 4가 된다. 사다리가 여기까지
    # 내려온 사유(notes)를 함께 넘기는 이유는 resolve_backend의 독스트링에 있다 —
    # 그 사유는 transcript.json에 실리기 전이라 이 오류가 유일한 전달 수단이다.
    resolved = stt.resolve_backend(backend, notes=notes)
    log(f"[transcribe] STT 백엔드={resolved}, 모델={model} 로 전사 중...")
    result = stt.transcribe_audio(video, model_size=model,
                                  backend=backend, language=language)
    return add_notes(result, notes)


def _video_resource(state: dict, original: Path) -> Path:
    """사용자 흐름대로 프레임 분석은 분리된 영상 리소스(video.mkv)를 소비한다.
    산출물이 지워졌으면 동일 스트림인 원본으로 폴백한다(경고만 — 프레임은 동일).

    칸의 유무는 방어하지 않는다. 이 함수를 부르는 두 자리(run_frames·run_frame_at)는
    각각 transcribe·frames의 완료를 먼저 요구하고 그 둘은 split 이후에만 완료되므로,
    게이트를 통과한 state.json이면 split outputs와 그 안의 video는 반드시 있다.
    **파일이 지워진 경우**만 실제로 일어나는 일이라 그것만 본다."""
    v = Path(state["stages"]["split"]["outputs"]["video"])
    if v.exists():
        return v
    log(f"[frames] 경고: 분리된 영상 리소스({v})가 없어 원본을 직접 사용합니다")
    return original


def run_frames(video: Path, out_dir: Path, ranges: list[str] | None = None,
               thresholds: dict | None = None) -> dict:
    """구간마다 독립 분석 단위를 만든다. 구간이 없으면 'full' 단위 하나.

    thresholds는 세 신호의 기준선. 측정 캐시에는 안 들어가므로(임계는 판단의
    소관) 바꿔도 전 프레임 디코드를 다시 하지 않는다."""
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    manifest.require_done(
        state, "transcribe",
        "대사가 있어야 화면에 붙일 수 있습니다 — "
        + stage_hint("transcribe", video, out_dir))

    transcript = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
    video_src = _video_resource(state, video)
    duration = media.get_duration(video_src)
    units = runs.resolve(ranges, duration)

    made = []
    for rng in units:
        made.append(_run_unit(video, video_src, out_dir, rng, transcript,
                              duration, thresholds or {}))
    entries = runs.merge_index(out_dir, made)
    index = context.write_index(out_dir, video.name, duration, entries)

    manifest.mark_done(state, "frames", {"runs": [e["name"] for e in entries],
                                         "index": str(index)})
    manifest.save_state(out_dir, state)
    return {"stage": "frames", "skipped": False, "index": str(index),
            "runs": made}


def _run_unit(video: Path, video_src: Path, out_dir: Path, rng, transcript: dict,
              duration: float, thresholds: dict) -> dict:
    unit = runs.reset_unit(runs.unit_dir(out_dir, rng))  # 결정적 재계산 (주문은 보존)
    win = runs.window(rng, duration)
    log(f"[frames] 분석 단위 '{runs.name(rng)}' ({runs.label(rng)}) 시작")

    build = frames_mod.build_frames(video_src, unit, cache_dir=out_dir, window=win,
                                    **thresholds)
    screens = align.attach_dialogue(build["records"], transcript["segments"],
                                    build["duration"], build["events"], win)
    manifest.write_json_atomic(unit / "frames.json", {
        "records": build["records"], "events": build["events"],
        "params": build["params"]})
    metadata = manifest.build_metadata(video, transcript, build, screens)
    _merge_requested(unit, metadata)
    manifest.save_metadata(unit, metadata)
    context.write(unit, metadata, f"{video.name} — {runs.label(rng)}")

    n_acc = len(metadata["frames"])
    return {"name": runs.name(rng), "range": list(rng) if rng else None,
            "dir": str(unit), "n_screens": len(screens), "n_frames": n_acc,
            "n_rejected": len(metadata["rejected"])}


def _requests_path(out_dir: Path) -> Path:
    return out_dir / runs.REQUESTED / "requests.json"


def _recompute_request(entry: dict, metadata: dict) -> None:
    """requested 엔트리의 구간·대사를 현재 프레임 집합 기준으로 계산한다 —
    frames 재실행으로 프레임 집합이 바뀌어도 장부가 stale해지지 않게.

    구간은 프레임과 **같은 정의**(화면이 떠 있던 구간)를 써야 한다. 여기서만
    이웃 프레임 시각으로 따로 계산하면 같은 시각에 두 가지 대사 묶음이 생긴다."""
    segments = metadata["transcript"]["segments"]
    duration = metadata["source"]["duration"]
    t = entry["time"]
    frames = metadata["frames"]
    holder = next((f for f in frames if f["interval"][0] <= t < f["interval"][1]), None)
    if holder is None and frames:
        # 전환 구간(화면과 화면 사이, 실측 0.07초)에 떨어진 경우 — 가장 가까운 화면
        holder = min(frames, key=lambda f: min(abs(f["interval"][0] - t),
                                               abs(f["interval"][1] - t)))
    if holder is not None:
        entry["interval"] = list(holder["interval"])
        entry["dialogue"] = holder["dialogue"]
    else:
        entry["interval"] = [0.0, round(duration, 2)]
        entry["dialogue"] = align.segments_in(segments, 0.0, duration)
    # 이 시각에 실제로 무슨 말이 나왔는지는 요청의 근거이므로 따로 남긴다
    seg = align.find_segment_at(segments, entry["at"])
    entry["said_at"] = seg["text"].strip() if seg else ""


def _merge_requested(out_dir: Path, metadata: dict) -> None:
    """frame --at 장부(requests.json)를 metadata 재생성 후에도 다시 합친다."""
    p = _requests_path(out_dir)
    if not p.exists():
        return
    requests = json.loads(p.read_text(encoding="utf-8"))
    for entry in requests:
        _recompute_request(entry, metadata)
    manifest.write_json_atomic(p, requests)
    metadata["requested"] = requests


def resolve_run(out_dir: Path, name: str | None) -> Path:
    """어느 분석 단위에 대해 작업할지 — 단위가 하나뿐이면 그것으로 자동 결정."""
    entries = runs.load_index(out_dir)
    if not entries:
        raise CliError(EXIT_INPUT, "no-runs",
                       "분석 단위가 없습니다 — frames를 먼저 실행하세요",
                       hint="analysis-video frames <video>")
    names = [e["name"] for e in entries]
    if name is None:
        if len(names) > 1:
            raise CliError(EXIT_INPUT, "run-ambiguous",
                           f"분석 단위가 여럿입니다 — --run으로 고르세요: {names}")
        name = names[0]
    if name not in names:
        raise CliError(EXIT_INPUT, "run-not-found",
                       f"'{name}' 분석 단위가 없습니다 — 있는 것: {names}")
    return out_dir / "runs" / name


def run_frame_at(video: Path, out_dir: Path, at: float, reason: str,
                 run_name: str | None = None) -> dict:
    from .detect import adaptive

    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    frames_hint = stage_hint("frames", video, out_dir)
    manifest.require_done(state, "frames", frames_hint)
    unit = resolve_run(out_dir, run_name)
    metadata = manifest.load_metadata(unit, frames_hint)
    duration = metadata["source"]["duration"]
    if not (0.0 <= at <= duration):
        raise CliError(EXIT_INPUT, "time-out-of-range",
                       f"--at {at}: 영상 범위(0~{duration}초) 밖입니다")
    # build_metadata가 window를 항상 쓴다(빈 구간과 안 본 구간을 구분하려고) —
    # 게이트를 통과한 metadata.json이면 이 칸도 반드시 있다.
    lo, hi = metadata["window"]
    if not (lo <= at <= hi):
        raise CliError(EXIT_INPUT, "time-out-of-window",
                       f"--at {at}: 이 분석 단위가 다루는 구간({lo}~{hi}초) 밖입니다",
                       hint="--run으로 다른 단위를 고르거나 그 구간을 분석하세요")

    out_dir = unit          # 이하 산출물은 전부 단위 안에 쓴다
    req_dir = out_dir / runs.REQUESTED
    req_dir.mkdir(parents=True, exist_ok=True)
    requests = json.loads(_requests_path(out_dir).read_text(encoding="utf-8")) \
        if _requests_path(out_dir).exists() else []

    # 멱등: 같은 (at, reason) 요청이 이미 있으면 재추출 없이 그대로 반환 —
    # 타임아웃 후 동일 명령 재실행이 장부에 중복을 쌓지 않게
    existing = next((e for e in requests if e["at"] == at and e["reason"] == reason), None)
    if existing is not None and (out_dir / existing["image"]).exists():
        existing["skipped"] = True
        return existing

    # 주문형에도 안정화·품질 게이트 기본 적용 — 단 명시 요청이므로 게이트는 경고만
    video_src = _video_resource(state, video)
    stable = adaptive.pick_stable_time(video_src, at, duration, offset=0.3)
    img = req_dir / f"req_{stable:07.2f}.jpg"
    # 주문형 프레임은 **원본 해상도 그대로** 둔다. 축소 사본은 "수십~수백 장을
    # 훑는다"는 문제의 답이고, 여기는 호출자가 근거를 적어 한 장을 지목한 자리라
    # 정밀도가 오히려 요청의 내용인 경우가 많다. 대신 그 한 장의 값이 얼마인지는
    # 결과에 실어 준다 — 안 실으면 metadata의 images(= read/ 이야기)가 이 장을
    # 세지 않는다는 사실이 소비자에게 보이지 않는다.
    size = media.extract_frame(video_src, stable, img)
    if size is None:
        raise CliError(EXIT_INPUT, "extract-failed", f"{stable:.2f}초 프레임 추출 실패")
    y = media.yavg(img)

    entry = {
        "at": at, "time": round(stable, 2), "reason": reason,
        "image": img.relative_to(out_dir).as_posix(), "yavg": round(y, 2),
        "cost": {"images": 1, "image_tokens": budget.image_tokens(*size),
                 "rule": budget.TOKEN_RULE},
    }
    if y < 5.0:
        entry["warning"] = f"yavg={y:.1f} — 어두운/빈 화면일 수 있음"
    _recompute_request(entry, metadata)

    requests = [e for e in requests if not (e["at"] == at and e["reason"] == reason)]
    requests.append(entry)
    manifest.write_json_atomic(_requests_path(out_dir), requests)

    metadata["requested"] = requests
    manifest.save_metadata(out_dir, metadata)
    return entry


# ---------- 서브커맨드 ----------

def cmd_split(args) -> int:
    video, out_dir = resolve_target(args)
    r = run_split(video, out_dir)
    emit({"ok": True, "out_dir": str(out_dir), **r,
          "next": next_step(video, out_dir)})
    return EXIT_OK


def cmd_transcribe(args) -> int:
    video, out_dir = resolve_target(args)
    run_split(video, out_dir)  # 멱등 — 미완료면 수행
    r = run_transcribe(video, out_dir, args.model, args.stt_backend, args.language,
                       force=args.force, transcript=args.transcript,
                       no_subtitles=args.no_subtitles, sub_lang=args.sub_lang)
    emit({"ok": True, "out_dir": str(out_dir), **r,
          "next": next_step(video, out_dir)})
    return EXIT_OK


def cmd_frames(args) -> int:
    video, out_dir = resolve_target(args)
    r = run_frames(video, out_dir, args.range, _thresholds(args))
    emit({"ok": True, "out_dir": str(out_dir), **r,
          "next": next_step(video, out_dir)})
    return EXIT_OK


def cmd_frame(args) -> int:
    video, out_dir = resolve_target(args)
    entry = run_frame_at(video, out_dir, args.at, args.reason, args.run)
    # 결과 JSON은 요약만 — 전체 대사는 metadata.json의 requested[]에 있다 (stdout 비대 방지)
    summary = {k: entry[k]
               for k in ("at", "time", "reason", "image", "yavg", "interval", "cost")}
    summary["n_dialogue"] = len(entry["dialogue"])
    for key in ("said_at", "warning", "skipped"):
        if entry.get(key):
            summary[key] = entry[key]
    emit({"ok": True, "out_dir": str(out_dir), "stage": "frame", **summary,
          "detail": "전체 대사는 metadata.json의 requested[]를 읽으세요",
          "next": next_step(video, out_dir)})
    return EXIT_OK


def cmd_analyze(args) -> int:
    video, out_dir = resolve_target(args)
    stages = [run_split(video, out_dir)]
    if args.until == "split":
        emit({"ok": True, "out_dir": str(out_dir), "stages": stages,
              "next": next_step(video, out_dir)})
        return EXIT_OK

    stages.append(run_transcribe(video, out_dir, args.model, args.stt_backend,
                                 args.language, transcript=args.transcript,
                                 no_subtitles=args.no_subtitles,
                                 sub_lang=args.sub_lang))
    if args.until == "transcribe":
        emit({"ok": True, "out_dir": str(out_dir), "stages": stages,
              "next": next_step(video, out_dir)})
        return EXIT_OK

    stages.append(run_frames(video, out_dir, args.range, _thresholds(args)))
    emit({"ok": True, "out_dir": str(out_dir), "stages": stages,
          "index": str(out_dir / "context.md"), "next": next_step(video, out_dir)})
    return EXIT_OK


def cmd_status(args) -> int:
    video, out_dir = resolve_target(args)
    state = manifest.load_state(out_dir)
    units = []
    for entry in runs.load_index(out_dir):
        unit = out_dir / "runs" / entry["name"]
        units.append({**entry, "context": str(unit / "context.md"),
                      "review": review.status(out_dir, entry["name"],
                                              unit / "context.md")})
    emit({"ok": True, "out_dir": str(out_dir), "source": state.get("source"),
          "stages": state["stages"], "runs": units,
          "next": next_step(video, out_dir)})
    return EXIT_OK


def _read_stdin_body() -> str:
    """`--write -`의 본문. 바이트로 읽고 UTF-8로 **명시 디코드**한다 —
    이미 열린 파이프의 인코딩을 나중에 바꾸는 것은 플랫폼마다 다르게 동작한다.

    TTY를 먼저 막는다. 파이프 없이 부르면 read()가 영원히 기다리고, 하네스는
    그것을 타임아웃으로 끊는다 — 원인이 어디에도 남지 않는 가장 나쁜 실패다."""
    if sys.stdin is None or sys.stdin.isatty():
        raise CliError(EXIT_INPUT, "stdin-is-tty",
                       "--write - 는 표준입력으로 본문을 받습니다 (파이프가 없습니다)",
                       hint="analysis-video review <video> --write - <<'EOF'\n"
                            "...분석문...\nEOF")
    raw = sys.stdin.buffer.read(review.MAX_BYTES + 1)
    if len(raw) > review.MAX_BYTES:
        raise CliError(EXIT_INPUT, "review-too-large",
                       f"본문이 {review.MAX_BYTES}바이트를 넘습니다")
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CliError(EXIT_INPUT, "review-not-text",
                       "본문을 UTF-8로 읽을 수 없습니다") from None
    if not body.strip():
        raise CliError(EXIT_INPUT, "empty-review",
                       "본문이 비어 있습니다",
                       hint="파이프가 실제로 연결됐는지 확인하세요")
    if review.BEGIN in body or review.END in body:
        raise CliError(EXIT_INPUT, "review-contains-marker",
                       "본문에 머리말 마커가 들어 있습니다 — 코어가 붙이는 구간입니다")
    return body


def cmd_review(args) -> int:
    video, out_dir = resolve_target(args)
    unit = resolve_run(out_dir, args.run)
    run_name = unit.name
    ctx = unit / "context.md"
    # 스테이지 완료 플래그가 아니라 **파일의 존재**로 판정한다. `transcribe --force`는
    # frames를 미완료로 되돌리지만 runs/와 그 안의 context.md는 그대로 남는데
    # (invalidate_stage는 파일을 지우지 않는다), 그 창에서 플래그로 막으면
    # "낡았다"를 말하려고 만든 명령이 정작 그 순간 침묵한다.
    if not ctx.exists():
        raise CliError(errors.EXIT_ORDER, "context-missing",
                       f"'{run_name}' 단위에 context.md가 없습니다",
                       hint=stage_hint("frames", video, out_dir))

    if args.write is None:
        st = review.status(out_dir, run_name, ctx)
        emit({"ok": True, "out_dir": str(out_dir), "stage": "review", **st,
              "next": next_step(video, out_dir)})
        return EXIT_OK

    body = _read_stdin_body()
    path = review.review_path(out_dir, run_name)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    prev_meta = review.parse_header(previous) if previous else None
    now_sha = review.sha256_of(ctx)
    action = review.decide(previous if prev_meta else None, body,
                           prev_meta["context_sha256"] if prev_meta else None,
                           now_sha, args.force)
    if action == "conflict":
        raise CliError(EXIT_INPUT, "review-exists",
                       f"'{run_name}' 단위에 이미 유효한 리뷰가 있습니다",
                       hint="덮어쓰려면 --force 를 붙이세요",
                       details={"path": str(path), "at": prev_meta["at"]})
    if action == "unchanged":
        result = {"action": "unchanged", "path": str(path)}
    else:
        header = review.render_header(
            run=run_name, unit_dir=unit,
            context_rel=ctx.relative_to(out_dir).as_posix(), context_sha=now_sha,
            video=video, version=__version__, at=review.now_iso())
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text_atomic(path, review.compose(body, header))
        result = {"action": {"create": "created", "refresh": "refreshed",
                             "update": "updated"}[action], "path": str(path)}
    if args.export_dir is not None:
        result["export"] = _export_review(path, manifest.absolute(args.export_dir),
                                          video, run_name)
    emit({"ok": True, "out_dir": str(out_dir), "stage": "review", "run": run_name,
          **result, "next": next_step(video, out_dir)})
    return EXIT_OK


def _export_review(src: Path, dest_dir: Path, video: Path, run: str) -> dict:
    """정본을 쓴 **뒤** 원하는 폴더로 사본을 하나 더 만든다.

    정본을 그쪽으로 옮기지 않는 이유는 resolve_out의 독스트링이 이미 적어 둔
    사고다 — 경로 기준점이 실행마다 흔들리면 끝나 있던 작업이 어디에서도 보이지
    않는다. 게다가 `--range`로 단위가 여럿이면 한 폴더에서 파일명이 부딪친다.
    사본의 이름에 영상 이름과 단위 이름을 함께 넣어 그 충돌을 없앤다.

    사본은 **어디에도 기록하지 않는다.** 기록하면 도구가 그것의 존재를 기억하게
    되고, 사용자가 지우거나 옮긴 뒤에 끊어진 참조가 남는다."""
    if dest_dir.exists() and not dest_dir.is_dir():
        raise CliError(EXIT_INPUT, "export-not-a-directory",
                       f"{dest_dir} 는 디렉터리가 아닙니다")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / f"{video.name}.{run}.review.md"
    manifest.write_text_atomic(dst, src.read_text(encoding="utf-8"))
    return {"path": str(dst)}


def cmd_clean(args) -> int:
    video, out_dir = resolve_target(args)
    manifest.load_state(out_dir)  # 스키마 게이트 — 남의 디렉터리를 지우지 않는다
    if args.level is None:
        # 보고만 한 실행도 `next`의 모양은 같아야 한다 — 커맨드마다 타입이 다른
        # 것이 사슬을 끊던 원인이었다. 정리는 분석의 다음 걸음이 아니므로
        # 여기서도 "이 영상에 대해 다음에 할 일"을 그대로 답한다.
        emit({"ok": True, "out_dir": str(out_dir), "stage": "clean",
              **clean_mod.survey(out_dir),
              "hint": "지우려면 --level 로 고르세요 (누적입니다). "
                      "reviews/·transcript.json·read/ 는 어느 레벨에서도 지우지 않습니다",
              "next": next_step(video, out_dir)})
        return EXIT_OK
    r = clean_mod.clean(out_dir, args.level)
    log(f"[clean] {r['freed_mb']}MB 회수 ({len(r['removed'])}개 경로)")
    emit({"ok": True, "out_dir": str(out_dir), "stage": "clean", **r,
          "next": next_step(video, out_dir)})
    return EXIT_OK


# doctor가 보는 모듈. 필수는 코어의 무조건 의존이라 하나라도 없으면 이 도구는
# 아무것도 못 한다(= 환경 고장, exit 4). 선택은 extra가 주는 **능력의 실체**이고,
# 없는 것은 고장이 아니라 그 능력이 꺼져 있다는 사실일 뿐이다.
REQUIRED_MODULES = {"pyav": "av", "scenedetect": "scenedetect", "opencv": "cv2",
                    "scikit-image": "skimage", "pillow": "PIL", "numpy": "numpy"}
OPTIONAL_MODULES = {"mlx-whisper": "mlx_whisper", "faster-whisper": "faster_whisper",
                    "matplotlib": "matplotlib"}


def _stt_capability() -> dict:
    """음성 인식 능력 — 있는가, 무엇으로, 지금 가중치까지 준비돼 있는가."""
    # "무엇이 있는가"와 "auto가 무엇을 고르는가"를 둘 다 stt에게 묻는다.
    # 여기서 installed[0]으로 두 번째 답을 지어내면 선호 규칙이 두 곳에 생긴다.
    installed = list(stt.installed_backends())
    resolved = stt.preferred_backend()
    cap = {
        "available": resolved is not None,
        "installed_backends": installed,
        "resolved_backend": resolved,
        "cuda_available": stt.cuda_available(),
        # 이 능력이 없을 때 무엇을 못 하는지를 함께 적는다. "백엔드 없음"만 보고
        # 호출자가 분석 자체를 포기하는 것이 이 명령의 옛 고장이었다.
        "needed_for": "자막이 하나도 없는 영상의 대사 — 자막이 있으면 쓰이지 않습니다",
        "install": stt.INSTALL_COMMAND,
    }
    if resolved is not None:
        # 가중치 캐시 상태까지 봐야 "지금 전사가 되는가"를 답할 수 있다.
        # 캐시가 비어 있으면 첫 전사가 다운로드(tiny 약 74MB ~ large 약 3.1GB)를
        # 동반하므로, 호출자는 이 명령을 워밍업 겸 사전점검으로 쓸 수 있다.
        # doctor는 인자를 받지 않는 계약이라 기본 모델을 본다 — analyze가
        # 옵션 없이 쓰는 그 모델이므로 사전점검 대상으로도 맞다.
        cap.update(stt.model_status(resolved, DEFAULT_MODEL))
    return cap


def cmd_doctor(args) -> int:
    """환경 진단 — **능력 목록을 보고한다.** 여기서 실패를 내지 않는다.

    전에는 "STT 백엔드 없음 = 환경 고장"이라 단정해 종료코드 4를 냈다. 그래서
    자막이 있는 영상을 끝까지 분석할 수 있는 기계가 빨간불을 받았고, 스킬 문서에는
    "doctor가 안 된다고 해도 분석은 된다"는 해명을 사람이 손으로 덧붙여야 했다.
    해명이 필요한 진단은 진단이 아니다.

    exit 4가 없어진 것이 아니라 **발화 지점이 옮겨 갔다**: 필수 모듈 결손은 여기서
    (도구 자체가 못 도는 상태), 백엔드 결손은 그것이 실제로 필요해진 전사에서
    (cli._audio_transcript → stt.resolve_backend)."""
    import platform as plat

    required = {name: find_spec(mod) is not None
                for name, mod in REQUIRED_MODULES.items()}
    optional = {name: find_spec(mod) is not None
                for name, mod in OPTIONAL_MODULES.items()}
    missing = [name for name, ok in required.items() if not ok]

    result = {"ok": not missing,
              "version": __version__,
              "python": sys.version.split()[0],
              "platform": {"os": sys.platform, "machine": plat.machine()},
              "modules": {"required": required, "optional": optional},
              "capabilities": {
                  "speech-recognition": _stt_capability(),
                  # matplotlib은 debug-report 전용이다(debug_viz가 지연 임포트하고
                  # 없으면 같은 exit 4로 안내한다) — 같은 모양으로 보고한다.
                  "debug-report": {"available": optional["matplotlib"],
                                   "needed_for": "debug-report 그래프 PNG",
                                   "install": "pip install 'analysis-video[viz]'"},
              }}
    if missing:
        result["error"] = {
            "kind": "core-deps-missing",
            "message": f"필수 모듈이 없습니다: {', '.join(missing)}",
            "hint": "설치가 깨졌습니다 — 'pip install --force-reinstall "
                    "analysis-video'로 다시 설치하세요",
        }
    emit(result)
    return EXIT_OK if not missing else EXIT_DEPS


def cmd_agent_guide(args) -> int:
    sys.stdout.write(GUIDE)
    return EXIT_OK


def cmd_install_skill(args) -> int:
    from . import skill

    if args.agents_file is not None:
        result = skill.install_agents_file(args.agents_file, __version__, GUIDE)
    else:
        result = skill.install_claude_skill(__version__, args.dir)
    emit({"ok": True, "stage": "install-skill", **result,
          "next": "새 세션을 시작하면 에이전트가 이 도구를 인식합니다"})
    return EXIT_OK


def cmd_debug_report(args) -> int:
    video, out_dir = resolve_target(args)
    state = manifest.load_state(out_dir)
    manifest.require_done(state, "frames", stage_hint("frames", video, out_dir))
    unit = resolve_run(out_dir, args.run)
    from . import debug_viz
    png = debug_viz.render(out_dir, args.label or f"{video.name} — {unit.name}", unit)
    emit({"ok": True, "out_dir": str(out_dir), "run": unit.name, "png": str(png)})
    return EXIT_OK


# ---------- 파서 ----------

class _Parser(argparse.ArgumentParser):
    """인자 오류도 stdout 결과 JSON + 종료코드 2로 — 에이전트가 stderr 파싱 없이 분기하도록."""

    def error(self, message):
        raise CliError(EXIT_INPUT, "usage", message, hint=self.format_usage().strip())


def _add_video(sp: argparse.ArgumentParser) -> None:
    # 이름은 video로 둔다 — 분석 디렉터리는 원본을 가리키는 또 하나의 표기이지
    # 다른 종류의 대상이 아니다(manifest.resolve_target이 둘을 같은 쌍으로 푼다).
    sp.add_argument("video", type=Path,
                    help="원본 비디오 파일, 또는 이미 분석한 <video>.analysis 디렉토리")
    sp.add_argument("--out", type=Path, default=None,
                    help="출력 디렉토리 (기본: <video>.analysis/). "
                         "분석 디렉토리를 지목했다면 줄 수 없다")


def _add_stt_options(sp: argparse.ArgumentParser) -> None:
    # --model의 기본값은 파서가 채우지 않는다(None = 요청 없음). 여기서 굳히면
    # run_transcribe가 "사용자가 고른 모델"과 "그날의 기본 모델"을 구분할 수 없다 —
    # 해석은 재사용 판정을 지난 뒤 run_transcribe가 한다(_reuse_transcript 참조).
    # 안내 문구의 기본값은 상수에서 주입한다: 여기 문자열로 적으면 상수를 고칠 때 갈린다.
    sp.add_argument("--model", choices=MODEL_SIZES, default=None,
                    help=f"Whisper 모델 크기 (기본: {DEFAULT_MODEL})")
    sp.add_argument("--stt-backend", choices=["auto", *stt.BACKENDS],
                    default=None, help="STT 백엔드 (기본: 플랫폼별 자동 선택)")
    sp.add_argument("--language", metavar="CODE", default=None,
                    help="whisper가 오디오를 들을 때의 음성 언어 힌트 (기본: 자동 감지). "
                         "자막을 고르는 것은 --sub-lang이고 이 값은 쓰이지 않는다")


def _add_subtitle_options(sp: argparse.ArgumentParser) -> None:
    """전사 출처를 고르는 세 플래그. STT 옵션과 섞지 않는다 — 이것들은 whisper를
    어떻게 돌릴지가 아니라 **whisper를 돌릴지 말지, 무엇을 대신 읽을지**를 정하고,
    --no-subtitles를 준 순간 --model·--stt-backend의 의미가 비로소 생긴다."""
    sp.add_argument("--transcript", type=Path, default=None, metavar="PATH",
                    help="이 자막 파일을 전사로 쓴다 (.srt/.vtt/.smi). 지목한 것이므로 "
                         "강제 자막·자동 생성 자막이어도 그대로 쓰고 사유만 기록한다. "
                         "읽지 못하는 파일이면 다른 출처로 넘어가지 않고 오류로 멈춘다")
    sp.add_argument("--sub-lang", metavar="CODE", default=None,
                    help="쓸 자막의 언어 코드 (기본: 시스템 로케일, 없으면 언어 무관). "
                         "사이드카 파일과 내장 트랙의 순위에만 쓰인다 — "
                         "whisper의 음성 언어 힌트는 --language다")
    sp.add_argument("--no-subtitles", action="store_true",
                    help="자막을 아예 보지 않고 음성을 전사한다 "
                         "(자동 생성 자막이 딸려 있는 영상 등)")


# 세 신호의 기준선. 이름은 GUI 타임라인의 레인 이름과 같게 둔다 — 그래프에서
# 보고 CLI에서 바꾸는 흐름이라 두 이름이 어긋나면 매번 번역해야 한다.
THRESHOLDS = [
    ("anchor-threshold", "anchor_threshold", frames_mod.DEFAULT_ANCHOR_THRESHOLD,
     "anchor diff(앵커와의 거리) — 넘으면 사건. 판서가 조금씩 쌓이는 점진 변화를 잡는다"),
    ("rate-threshold", "rate_threshold", frames_mod.DEFAULT_RATE_THRESHOLD,
     "순간 변화율(직전 프레임 대비) — 안정 판정선이자, 이것의 8배를 넘는 스파이크는 사건"),
    ("cut-area-threshold", "cut_area_threshold", frames_mod.DEFAULT_CUT_AREA_THRESHOLD,
     "컷 면적(확 바뀐 픽셀 비율) — 넘으면 사건. 평균이 아니라 면적이라 희석되지 않는다"),
]


def _add_thresholds(sp: argparse.ArgumentParser) -> None:
    for flag, dest, default, help_text in THRESHOLDS:
        sp.add_argument(f"--{flag}", dest=dest, type=float, default=default,
                        metavar="값", help=f"{help_text} (기본 {default})")
    # 임계 셋과 성질이 다르다 — 이건 판정선이 아니라 **읽기용 사본의 크기**이고
    # 정수다. THRESHOLDS 목록에 끼워 넣으면 float으로 파싱되고, "세 신호의
    # 기준선"이라는 그 목록의 뜻도 흐려진다.
    sp.add_argument("--read-long-edge", dest="read_long_edge", type=int,
                    default=budget.READ_LONG_EDGE, metavar="픽셀",
                    help=f"context.md가 가리키는 읽기용 사본의 긴 변 "
                         f"(기본 {budget.READ_LONG_EDGE}). 원본 해상도는 frames/에 "
                         f"그대로 남는다")


def _thresholds(args) -> dict:
    """build_frames에 그대로 넘길 인자 묶음."""
    out = {dest: getattr(args, dest) for _f, dest, _d, _h in THRESHOLDS}
    out["read_long_edge"] = args.read_long_edge
    return out


def _add_range(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--range", action="append", metavar="시작-끝", default=None,
                    help="분석할 구간(초). 여러 번 주면 그만큼 독립 분석이 생긴다. "
                         "겹쳐도 된다. 예: --range 120-300 --range 900-1200")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="analysis-video",
        description="슬라이드 기반 강의 영상 → AI 소비용 컨텍스트(프레임+대사+메타데이터)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("analyze", help="오케스트레이터: split→transcribe→frames (끝까지)")
    _add_video(sp)
    _add_subtitle_options(sp)
    _add_stt_options(sp)
    _add_range(sp)
    _add_thresholds(sp)
    sp.add_argument("--until", choices=["split", "transcribe", "frames"], default="frames",
                    help="이 스테이지까지만 실행 (기본: frames — context.md까지)")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("split", help="오디오/비디오 리소스 분리")
    _add_video(sp)
    sp.set_defaults(func=cmd_split)

    sp = sub.add_parser("transcribe", help="전사 (자막 우선, whisper 폴백 — split 선행 필요)")
    _add_video(sp)
    _add_subtitle_options(sp)
    _add_stt_options(sp)
    sp.add_argument("--force", action="store_true",
                    help="완료된 전사를 무시하고 다시 전사 (모델 교체 시). "
                         "자막 파일이 바뀐 경우는 이것 없이도 자동으로 다시 한다")
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("frames", help="프레임 검출·추출 (transcribe 선행 필요)")
    _add_video(sp)
    _add_range(sp)
    _add_thresholds(sp)
    sp.set_defaults(func=cmd_frames)

    sp = sub.add_parser("frame", help="주문형 단일 프레임 추출 (frames 이후)")
    _add_video(sp)
    sp.add_argument("--at", type=float, required=True, help="추출 시각(초)")
    sp.add_argument("--reason", required=True, help="추출 사유 (provenance 필수)")
    sp.add_argument("--run", default=None,
                    help="분석 단위 이름 (단위가 여럿일 때 필수)")
    sp.set_defaults(func=cmd_frame)

    sp = sub.add_parser("review", help="분석문 기록·조회 (frames 이후)")
    _add_video(sp)
    sp.add_argument("--run", default=None,
                    help="분석 단위 이름 (단위가 여럿일 때 필수)")
    # 값을 '-'로 못박는다. 파일 경로를 받으면 "코어가 임의 경로를 읽는다"가 되고,
    # 무엇보다 잘못 쓴 값이 조용히 파일명으로 해석되는 것을 막는다.
    sp.add_argument("--write", choices=["-"], default=None,
                    help="표준입력으로 분석문 본문을 받아 기록한다 "
                         "(생략하면 지금 상태만 조회)")
    sp.add_argument("--force", action="store_true",
                    help="읽은 context.md가 그대로인데 다른 본문으로 덮어쓴다")
    sp.add_argument("--export-dir", type=Path, default=None, metavar="DIR",
                    help="정본을 쓴 뒤 이 폴더로 사본을 하나 더 만든다 "
                         "(정본 위치는 바뀌지 않는다)")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("clean", help="되만들 수 있는 산출물 정리 (기본은 보고만)")
    _add_video(sp)
    sp.add_argument("--level", choices=list(clean_mod.LEVELS), default=None,
                    help="지울 범위(누적). 생략하면 무엇이 얼마나 있는지만 보고한다")
    sp.set_defaults(func=cmd_clean)

    sp = sub.add_parser("status", help="스테이지 진행 상태 + 다음에 할 일")
    _add_video(sp)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("doctor",
                        help="환경 진단 — 능력 목록 보고 "
                             "(필수 모듈이 없을 때만 종료코드 4)")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("agent-guide", help="에이전트 온보딩 문서 출력 (markdown)")
    sp.set_defaults(func=cmd_agent_guide)

    sp = sub.add_parser("install-skill",
                        help="에이전트가 이 도구를 찾도록 사용법을 설치 (멱등)")
    sp.add_argument("--dir", type=Path, default=None,
                    help="Claude Code 스킬 디렉토리 (기본: ~/.claude/skills)")
    sp.add_argument("--agents-file", type=Path, default=None,
                    help="Claude Code 대신 규칙 파일에 설치 (예: AGENTS.md) — "
                         "마커 구간을 교체하므로 여러 번 실행해도 중복되지 않음. "
                         "마커가 짝을 이루지 않으면 쓰지 않고 종료코드 2")
    sp.set_defaults(func=cmd_install_skill)

    sp = sub.add_parser("debug-report", help="디버그 그래프 생성 ([viz] extra 필요)")
    _add_video(sp)
    sp.add_argument("--label", default=None,
                    help="그래프에 그릴 제목 (기본: <video> — <분석 단위>)")
    sp.add_argument("--run", default=None, help="분석 단위 이름 (여럿일 때 필수)")
    sp.set_defaults(func=cmd_debug_report)

    return p


def main(argv: list[str] | None = None) -> int:
    # Windows cp949 등 로케일 콘솔에서 한국어 JSON이 UnicodeEncodeError로 죽지 않게
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except CliError as e:
        emit(e.as_json())
        return e.code
    except Exception as e:  # 내부 오류도 결과 JSON으로 — 에이전트 파싱 실패 방지
        emit({"ok": False, "error": {"kind": "internal",
                                     "message": f"{type(e).__name__}: {e}"}})
        return errors.EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
