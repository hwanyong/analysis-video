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

stdout = 봉투 JSON 한 건(agent-guide 제외), 로그 = stderr.
state.json 덕분에 같은 명령 재실행 = 이어하기(타임아웃 내성).
"""
import argparse
import json
import shutil
import sys
from importlib.util import find_spec
from pathlib import Path

from . import __version__, align, context, errors, manifest, media, runs, stt
from . import frames as frames_mod
from . import split as split_mod
from .agent_guide import GUIDE
from .errors import EXIT_DEPS, EXIT_INPUT, EXIT_OK, CliError, emit, log
from .stt.base import MODEL_SIZES

NEXT_READ_CONTEXT = (
    "context.md를 읽으세요 — 화면별로 이미지·시간·대사만 담은 AI용 산출물입니다. "
    "특정 순간의 프레임이 더 필요하면 'analysis-video frame <video> --at <초> "
    "--reason \"...\"'로 뽑을 수 있습니다. 탈락 사유·검출 파라미터 등 전체 기록은 "
    "metadata.json에 있습니다."
)


def resolve_out(video: Path, out: Path | None) -> Path:
    return out if out is not None else video.parent / f"{video.name}.analysis"


def check_video(path: Path) -> Path:
    if not path.exists():
        raise CliError(EXIT_INPUT, "video-not-found", f"비디오 파일이 없습니다: {path}")
    return path


# ---------- 스테이지 실행 (cmd_*와 analyze 오케스트레이터가 공유) ----------

def run_split(video: Path, out_dir: Path) -> dict:
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    if manifest.is_done(state, "split"):
        return {"stage": "split", "skipped": True, **state["stages"]["split"]["outputs"]}
    log("[split] 오디오/비디오 리소스 분리 중...")
    audio, vid = split_mod.split_media(video, out_dir)
    if audio is None:
        log("[split] 경고: 오디오 스트림이 없는 영상입니다")
    outputs = {"audio": str(audio) if audio else None, "video": str(vid)}
    manifest.mark_done(state, "split", outputs)
    manifest.save_state(out_dir, state)
    return {"stage": "split", "skipped": False, **outputs}


def run_transcribe(video: Path, out_dir: Path, model: str,
                   backend: str | None, language: str | None,
                   force: bool = False) -> dict:
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    split_info = manifest.require_done(
        state, "split", f"analysis-video split {video} 를 먼저 실행하세요")
    duration = round(media.get_duration(video), 2)

    if manifest.is_done(state, "transcribe") and not force:
        prev = state["stages"]["transcribe"]["outputs"]
        result = {"stage": "transcribe", "skipped": True, "duration": duration, **prev}
        if prev.get("model_size") not in (None, model):
            result["note"] = (f"기존 전사(모델={prev['model_size']})를 재사용했습니다 — "
                              "다른 모델로 다시 전사하려면 --force를 지정하세요")
        return result

    audio = split_info["outputs"].get("audio")
    if audio is None:
        log("[transcribe] 오디오 스트림 없음 — 빈 전사를 기록합니다")
        result = {"text": "", "segments": [], "words": [],
                  "backend": "none", "device": "none", "model": "none"}
    else:
        resolved = stt.resolve_backend(backend)
        log(f"[transcribe] STT 백엔드={resolved}, 모델={model} 로 전사 중...")
        result = stt.transcribe_audio(Path(audio), model_size=model,
                                      backend=backend, language=language)
    manifest.write_json_atomic(out_dir / "transcript.json", result)
    outputs = {
        "transcript": str(out_dir / "transcript.json"),
        "backend": result["backend"], "device": result["device"],
        "model": result["model"], "model_size": model,
        "n_segments": len(result["segments"]), "n_words": len(result["words"]),
    }
    manifest.mark_done(state, "transcribe", outputs)
    manifest.save_state(out_dir, state)
    return {"stage": "transcribe", "skipped": False, "duration": duration, **outputs}


def _video_resource(state: dict, original: Path) -> Path:
    """사용자 흐름대로 프레임 분석은 분리된 영상 리소스(video.mkv)를 소비한다.
    산출물이 지워졌으면 동일 스트림인 원본으로 폴백한다(경고만 — 프레임은 동일)."""
    split_out = state["stages"].get("split", {}).get("outputs", {})
    v = Path(split_out["video"]) if split_out.get("video") else None
    if v is not None and v.exists():
        return v
    log(f"[frames] 경고: 분리된 영상 리소스({v})가 없어 원본을 직접 사용합니다")
    return original


def run_frames(video: Path, out_dir: Path, ranges: list[str] | None = None) -> dict:
    """구간마다 독립 분석 단위를 만든다. 구간이 없으면 'full' 단위 하나."""
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    manifest.require_done(
        state, "transcribe",
        "대사가 있어야 화면에 붙일 수 있습니다 — "
        f"analysis-video transcribe {video} 를 먼저 실행하세요")

    transcript = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
    video_src = _video_resource(state, video)
    duration = media.get_duration(video_src)
    units = runs.resolve(ranges, duration)

    made = []
    for rng in units:
        made.append(_run_unit(video, video_src, out_dir, rng, transcript, duration))
    entries = runs.merge_index(out_dir, made)
    index = context.write_index(out_dir, video.name, duration, entries)

    manifest.mark_done(state, "frames", {"runs": [e["name"] for e in entries],
                                         "index": str(index)})
    manifest.save_state(out_dir, state)
    return {"stage": "frames", "skipped": False, "index": str(index),
            "runs": made}


def _run_unit(video: Path, video_src: Path, out_dir: Path, rng, transcript: dict,
              duration: float) -> dict:
    unit = runs.unit_dir(out_dir, rng)
    if unit.exists():
        shutil.rmtree(unit)          # 결정적 재계산 — 이전 산출물이 섞이지 않게
    unit.mkdir(parents=True, exist_ok=True)
    win = runs.window(rng, duration)
    log(f"[frames] 분석 단위 '{runs.name(rng)}' ({runs.label(rng)}) 시작")

    build = frames_mod.build_frames(video_src, unit, cache_dir=out_dir, window=win)
    screens = align.attach_dialogue(build["records"], transcript["segments"],
                                    build["duration"], build["anchor_events"], win)
    manifest.write_json_atomic(unit / "frames.json", {
        "records": build["records"], "anchor_events": build["anchor_events"],
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
    return out_dir / "requested" / "requests.json"


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
    manifest.require_done(
        state, "frames", f"analysis-video frames {video} 를 먼저 실행하세요")
    unit = resolve_run(out_dir, run_name)
    metadata = manifest.load_metadata(unit)
    duration = metadata["source"]["duration"]
    if not (0.0 <= at <= duration):
        raise CliError(EXIT_INPUT, "time-out-of-range",
                       f"--at {at}: 영상 범위(0~{duration}초) 밖입니다")
    lo, hi = metadata.get("window", [0.0, duration])
    if not (lo <= at <= hi):
        raise CliError(EXIT_INPUT, "time-out-of-window",
                       f"--at {at}: 이 분석 단위가 다루는 구간({lo}~{hi}초) 밖입니다",
                       hint="--run으로 다른 단위를 고르거나 그 구간을 분석하세요")

    out_dir = unit          # 이하 산출물은 전부 단위 안에 쓴다
    req_dir = out_dir / "requested"
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
    if not media.extract_frame(video_src, stable, img):
        raise CliError(EXIT_INPUT, "extract-failed", f"{stable:.2f}초 프레임 추출 실패")
    y = media.yavg(img)

    entry = {
        "at": at, "time": round(stable, 2), "reason": reason,
        "image": img.relative_to(out_dir).as_posix(), "yavg": round(y, 2),
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
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    r = run_split(video, out_dir)
    emit({"ok": True, "out_dir": str(out_dir), **r, "next": "analysis-video transcribe"})
    return EXIT_OK


def cmd_transcribe(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    run_split(video, out_dir)  # 멱등 — 미완료면 수행
    r = run_transcribe(video, out_dir, args.model, args.stt_backend, args.language,
                       force=args.force)
    emit({"ok": True, "out_dir": str(out_dir), **r,
          "next": f"analysis-video frames {video}"})
    return EXIT_OK


def cmd_frames(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    r = run_frames(video, out_dir, args.range)
    emit({"ok": True, "out_dir": str(out_dir), **r, "next": NEXT_READ_CONTEXT})
    return EXIT_OK


def cmd_frame(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    entry = run_frame_at(video, out_dir, args.at, args.reason, args.run)
    # 봉투는 요약만 — 전체 대사는 metadata.json의 requested[]에 있다 (stdout 비대 방지)
    summary = {k: entry[k] for k in ("at", "time", "reason", "image", "yavg", "interval")}
    summary["n_dialogue"] = len(entry["dialogue"])
    for key in ("said_at", "warning", "skipped"):
        if entry.get(key):
            summary[key] = entry[key]
    emit({"ok": True, "out_dir": str(out_dir), "stage": "frame", **summary,
          "detail": "전체 대사는 metadata.json의 requested[]를 읽으세요"})
    return EXIT_OK


def cmd_analyze(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    stages = [run_split(video, out_dir)]
    if args.until == "split":
        emit({"ok": True, "out_dir": str(out_dir), "stages": stages, "next": "transcribe"})
        return EXIT_OK

    stages.append(run_transcribe(video, out_dir, args.model, args.stt_backend, args.language))
    if args.until == "transcribe":
        emit({"ok": True, "out_dir": str(out_dir), "stages": stages, "next": "frames"})
        return EXIT_OK

    stages.append(run_frames(video, out_dir, args.range))
    emit({"ok": True, "out_dir": str(out_dir), "stages": stages,
          "index": str(out_dir / "context.md"), "next": NEXT_READ_CONTEXT})
    return EXIT_OK


def cmd_status(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    state = manifest.load_state(out_dir)
    emit({"ok": True, "out_dir": str(out_dir), "source": state.get("source"),
          "stages": state["stages"]})
    return EXIT_OK


def cmd_doctor(args) -> int:
    import platform as plat
    modules = {"pyav": "av", "scenedetect": "scenedetect", "opencv": "cv2",
               "scikit-image": "skimage", "pillow": "PIL",
               "numpy": "numpy", "matplotlib(viz)": "matplotlib",
               "mlx-whisper": "mlx_whisper", "faster-whisper": "faster_whisper"}
    checks = {name: find_spec(mod) is not None for name, mod in modules.items()}

    cuda = False
    if checks["faster-whisper"]:
        try:
            from ctranslate2 import get_cuda_device_count
            cuda = get_cuda_device_count() > 0
        except Exception:
            cuda = False

    stt_error = None
    try:
        backend = stt.resolve_backend(None)
    except CliError as e:
        backend = None
        stt_error = e.envelope()["error"]

    envelope = {"ok": backend is not None,
                "version": __version__,
                "python": sys.version.split()[0],
                "platform": {"os": sys.platform, "machine": plat.machine()},
                "modules": checks,
                "stt": {"resolved_backend": backend, "cuda_available": cuda}}
    if stt_error is not None:
        envelope["error"] = stt_error
    emit(envelope)
    return EXIT_OK if backend else EXIT_DEPS


def cmd_agent_guide(args) -> int:
    sys.stdout.write(GUIDE)
    return EXIT_OK


def cmd_debug_report(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    state = manifest.load_state(out_dir)
    manifest.require_done(state, "frames",
                          f"analysis-video frames {video} 를 먼저 실행하세요")
    unit = resolve_run(out_dir, args.run)
    from . import debug_viz
    png = debug_viz.render(out_dir, args.label or f"{video.name} — {unit.name}", unit)
    emit({"ok": True, "out_dir": str(out_dir), "run": unit.name, "png": str(png)})
    return EXIT_OK


# ---------- 파서 ----------

class _Parser(argparse.ArgumentParser):
    """인자 오류도 stdout 봉투 + 종료코드 2로 — 에이전트가 stderr 파싱 없이 분기하도록."""

    def error(self, message):
        raise CliError(EXIT_INPUT, "usage", message, hint=self.format_usage().strip())


def _add_video(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("video", type=Path, help="원본 비디오 파일")
    sp.add_argument("--out", type=Path, default=None,
                    help="출력 디렉토리 (기본: <video>.analysis/)")


def _add_stt_options(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--model", choices=MODEL_SIZES, default="tiny", help="Whisper 모델 크기")
    sp.add_argument("--stt-backend", choices=["auto", "mlx", "faster-whisper"],
                    default=None, help="STT 백엔드 (기본: 플랫폼별 자동 선택)")
    sp.add_argument("--language", default=None, help="음성 언어 코드 (기본: 자동 감지)")


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
    _add_stt_options(sp)
    _add_range(sp)
    sp.add_argument("--until", choices=["split", "transcribe", "frames"], default="frames")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("split", help="오디오/비디오 리소스 분리")
    _add_video(sp)
    sp.set_defaults(func=cmd_split)

    sp = sub.add_parser("transcribe", help="STT 전사 (split 선행 필요)")
    _add_video(sp)
    _add_stt_options(sp)
    sp.add_argument("--force", action="store_true",
                    help="완료된 전사를 무시하고 다시 전사 (모델 교체 시)")
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("frames", help="프레임 검출·추출 (transcribe 선행 필요)")
    _add_video(sp)
    _add_range(sp)
    sp.set_defaults(func=cmd_frames)

    sp = sub.add_parser("frame", help="주문형 단일 프레임 추출 (frames 이후)")
    _add_video(sp)
    sp.add_argument("--at", type=float, required=True, help="추출 시각(초)")
    sp.add_argument("--reason", required=True, help="추출 사유 (provenance 필수)")
    sp.add_argument("--run", default=None,
                    help="분석 단위 이름 (단위가 여럿일 때 필수)")
    sp.set_defaults(func=cmd_frame)

    sp = sub.add_parser("status", help="스테이지 진행 상태")
    _add_video(sp)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("doctor", help="환경 진단 (STT 백엔드 불가 시 종료코드 4)")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("agent-guide", help="에이전트 온보딩 문서 출력 (markdown)")
    sp.set_defaults(func=cmd_agent_guide)

    sp = sub.add_parser("debug-report", help="디버그 그래프 생성 ([viz] extra 필요)")
    _add_video(sp)
    sp.add_argument("--label", default=None)
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
        emit(e.envelope())
        return e.code
    except Exception as e:  # 내부 오류도 봉투로 — 에이전트 파싱 실패 방지
        emit({"ok": False, "error": {"kind": "internal",
                                     "message": f"{type(e).__name__}: {e}"}})
        return errors.EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
