"""analysis-video CLI — 에이전트 친화 계약 구현.

직렬 흐름 강제: split → transcribe → (호출 에이전트가 transcript.json을 읽고
points.json 작성 — 텍스트 중요도 분석은 패키지 밖) → frames --points → metadata.json.
stdout = 봉투 JSON 한 건(agent-guide 제외), 로그 = stderr.
state.json 덕분에 같은 명령 재실행 = 이어하기(타임아웃 내성). frames는 결정적이라
호출 시마다 재계산하며, frame --at 산출물은 requests.json 장부로 보존되어
frames 재실행 후에도 metadata.json에 다시 합쳐진다.
"""
import argparse
import json
import sys
from importlib.util import find_spec
from pathlib import Path

from . import __version__, align, errors, manifest, media, stt
from . import frames as frames_mod
from . import points as points_mod
from . import split as split_mod
from .agent_guide import GUIDE
from .detect import adaptive
from .errors import EXIT_DEPS, EXIT_INPUT, EXIT_OK, CliError, emit, log
from .stt.base import MODEL_SIZES

NEXT_POINTS_ACTION = (
    "transcript.json을 읽고 대사 기반으로 중요한 시간대를 골라 points.json을 작성한 뒤 "
    "'analysis-video frames <video> --points points.json'을 실행하세요. "
    "중요한 순간이 없다면 --no-points로 명시적으로 생략합니다."
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
    outputs = {"audio": str(audio), "video": str(vid)}
    manifest.mark_done(state, "split", outputs)
    manifest.save_state(out_dir, state)
    return {"stage": "split", "skipped": False, **outputs}


def run_transcribe(video: Path, out_dir: Path, model: str,
                   backend: str | None, language: str | None) -> dict:
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    split_info = manifest.require_done(
        state, "split", f"analysis-video split {video} 를 먼저 실행하세요")
    if manifest.is_done(state, "transcribe"):
        return {"stage": "transcribe", "skipped": True,
                **state["stages"]["transcribe"]["outputs"]}

    resolved = stt.resolve_backend(backend)
    log(f"[transcribe] STT 백엔드={resolved}, 모델={model} 로 전사 중...")
    result = stt.transcribe_audio(Path(split_info["outputs"]["audio"]),
                                  model_size=model, backend=backend, language=language)
    transcript_path = out_dir / "transcript.json"
    transcript_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    outputs = {
        "transcript": str(transcript_path),
        "backend": result["backend"], "device": result["device"], "model": result["model"],
        "n_segments": len(result["segments"]), "n_words": len(result["words"]),
    }
    manifest.mark_done(state, "transcribe", outputs)
    manifest.save_state(out_dir, state)
    return {"stage": "transcribe", "skipped": False, **outputs}


def run_frames(video: Path, out_dir: Path, points_path: Path | None) -> dict:
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    manifest.require_done(
        state, "transcribe",
        "직렬 흐름: 텍스트 분석이 끝나야 프레임 분석이 가능합니다 — "
        f"analysis-video transcribe {video} 를 먼저 실행하세요")

    transcript = json.loads((out_dir / "transcript.json").read_text())
    duration = media.get_duration(video)
    pts = [] if points_path is None else points_mod.load_points(points_path, duration)

    # frames는 결정적 재계산 — 이전 산출물이 남아 stale 이미지가 섞이지 않게 비운다
    frames_dir = out_dir / "frames"
    if frames_dir.exists():
        import shutil
        shutil.rmtree(frames_dir)

    build = frames_mod.build_frames(video, out_dir, pts)
    align.attach_dialogue(build["records"], transcript["segments"], build["duration"])

    (out_dir / "frames.json").write_text(json.dumps(
        {"records": build["records"], "anchor_events": build["anchor_events"],
         "params": build["params"]},
        ensure_ascii=False, indent=2))

    metadata = manifest.build_metadata(video, transcript, build)
    _merge_requested(out_dir, metadata)
    manifest.save_metadata(out_dir, metadata)

    n_accepted = sum(1 for r in build["records"] if r["status"] == "accepted")
    outputs = {
        "metadata": str(out_dir / "metadata.json"),
        "frames_dir": str(frames_dir),
        "n_accepted": n_accepted,
        "n_rejected": len(build["records"]) - n_accepted,
        "n_points": len(pts),
    }
    manifest.mark_done(state, "frames", outputs)
    manifest.save_state(out_dir, state)
    return {"stage": "frames", "skipped": False, **outputs}


def _requests_path(out_dir: Path) -> Path:
    return out_dir / "requested" / "requests.json"


def _merge_requested(out_dir: Path, metadata: dict) -> None:
    """frame --at 장부(requests.json)를 metadata 재생성 후에도 다시 합친다."""
    p = _requests_path(out_dir)
    if p.exists():
        metadata["requested"] = json.loads(p.read_text())


def run_frame_at(video: Path, out_dir: Path, at: float, reason: str) -> dict:
    state = manifest.load_state(out_dir)
    manifest.check_source(state, video)
    manifest.require_done(
        state, "frames",
        f"analysis-video frames {video} --points ... 를 먼저 실행하세요")
    metadata = manifest.load_metadata(out_dir)
    duration = metadata["source"]["duration"]
    if not (0.0 <= at <= duration):
        raise CliError(EXIT_INPUT, "time-out-of-range",
                       f"--at {at}: 영상 범위(0~{duration}초) 밖입니다")

    req_dir = out_dir / "requested"
    req_dir.mkdir(parents=True, exist_ok=True)

    # 주문형에도 안정화·품질 게이트 기본 적용 — 단 명시 요청이므로 게이트는 경고만
    stable = adaptive.pick_stable_time(video, at, duration, offset=0.3)
    img = req_dir / f"req_{stable:07.2f}.jpg"
    if not media.extract_frame(video, stable, img):
        raise CliError(EXIT_INPUT, "extract-failed", f"{stable:.2f}초 프레임 추출 실패")
    y = media.yavg(img)

    segments = metadata["transcript"]["segments"]
    accepted_times = [f["time"] for f in metadata["frames"]]
    prev_t = max((t for t in accepted_times if t <= stable), default=0.0)
    next_t = min((t for t in accepted_times if t > stable), default=duration)

    entry = {
        "at": at, "time": round(stable, 2), "reason": reason,
        "image": str(img.relative_to(out_dir)), "yavg": round(y, 2),
        "interval": [round(prev_t, 2), round(next_t, 2)],
        "dialogue": align.segments_in(segments, prev_t, next_t),
        "trigger_dialogue": align.find_segment_at(segments, at),
    }
    if y < 5.0:
        entry["warning"] = f"yavg={y:.1f} — 어두운/빈 화면일 수 있음"

    requests = json.loads(_requests_path(out_dir).read_text()) if _requests_path(out_dir).exists() else []
    requests.append(entry)
    _requests_path(out_dir).write_text(json.dumps(requests, ensure_ascii=False, indent=2))

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
    r = run_transcribe(video, out_dir, args.model, args.stt_backend, args.language)
    emit({"ok": True, "out_dir": str(out_dir), **r, "next_action": NEXT_POINTS_ACTION})
    return EXIT_OK


def cmd_frames(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    points_path = None if args.no_points else args.points
    r = run_frames(video, out_dir, points_path)
    emit({"ok": True, "out_dir": str(out_dir), **r,
          "next": "metadata.json의 frames[]에서 필요한 이미지(경로)를 읽으세요"})
    return EXIT_OK


def cmd_frame(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    entry = run_frame_at(video, out_dir, args.at, args.reason)
    # 봉투는 요약만 — 전체 대사는 metadata.json의 requested[]에 있다 (stdout 비대 방지)
    summary = {k: entry[k] for k in ("at", "time", "reason", "image", "yavg", "interval")}
    summary["n_dialogue"] = len(entry["dialogue"])
    if entry.get("trigger_dialogue"):
        summary["trigger_dialogue"] = entry["trigger_dialogue"]
    if entry.get("warning"):
        summary["warning"] = entry["warning"]
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
    no_points = getattr(args, "no_points", False)
    if args.until == "transcribe" or (args.points is None and not no_points):
        # 샌드위치 틈새: 텍스트 중요도 분석은 호출자의 몫 — 여기서 멈춘다
        emit({"ok": True, "out_dir": str(out_dir), "stages": stages,
              "next_action": NEXT_POINTS_ACTION})
        return EXIT_OK

    stages.append(run_frames(video, out_dir, None if no_points else args.points))
    emit({"ok": True, "out_dir": str(out_dir), "stages": stages,
          "metadata": str(out_dir / "metadata.json")})
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
               "scikit-image": "skimage", "pillow": "PIL", "imagehash": "imagehash",
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

    try:
        backend = stt.resolve_backend(None)
    except CliError:
        backend = None

    emit({"ok": backend is not None,
          "version": __version__,
          "python": sys.version.split()[0],
          "platform": {"os": sys.platform, "machine": plat.machine()},
          "modules": checks,
          "stt": {"resolved_backend": backend, "cuda_available": cuda},
          })
    return EXIT_OK if backend else EXIT_DEPS


def cmd_agent_guide(args) -> int:
    sys.stdout.write(GUIDE)
    return EXIT_OK


def cmd_debug_report(args) -> int:
    video = check_video(args.video)
    out_dir = resolve_out(video, args.out)
    state = manifest.load_state(out_dir)
    manifest.require_done(state, "frames",
                          f"analysis-video frames {video} ... 를 먼저 실행하세요")
    from . import debug_viz
    png = debug_viz.render(out_dir, args.label or video.name)
    emit({"ok": True, "out_dir": str(out_dir), "png": str(png)})
    return EXIT_OK


# ---------- 파서 ----------

def _add_video(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("video", type=Path, help="원본 비디오 파일")
    sp.add_argument("--out", type=Path, default=None,
                    help="출력 디렉토리 (기본: <video>.analysis/)")


def _add_stt_options(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--model", choices=MODEL_SIZES, default="tiny", help="Whisper 모델 크기")
    sp.add_argument("--stt-backend", choices=["auto", "mlx", "faster-whisper"],
                    default=None, help="STT 백엔드 (기본: 플랫폼별 자동 선택)")
    sp.add_argument("--language", default=None, help="음성 언어 코드 (기본: 자동 감지)")


def _add_points_options(sp: argparse.ArgumentParser, required: bool) -> None:
    group = sp.add_mutually_exclusive_group(required=required)
    group.add_argument("--points", type=Path, default=None,
                       help="points.json — 텍스트 중요도 분석 결과 (호출 에이전트 작성)")
    group.add_argument("--no-points", action="store_true",
                       help="중요 시간대 없이 장면 전환만 추출 (명시적 생략)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analysis-video",
        description="슬라이드 기반 강의 영상 → AI 소비용 컨텍스트(프레임+대사+메타데이터)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("analyze", help="오케스트레이터: split→transcribe→(points 대기)→frames")
    _add_video(sp)
    _add_stt_options(sp)
    _add_points_options(sp, required=False)
    sp.add_argument("--until", choices=["split", "transcribe", "frames"], default="frames")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("split", help="오디오/비디오 리소스 분리")
    _add_video(sp)
    sp.set_defaults(func=cmd_split)

    sp = sub.add_parser("transcribe", help="STT 전사 (split 선행 필요)")
    _add_video(sp)
    _add_stt_options(sp)
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("frames", help="프레임 검출·추출 (transcribe 선행 강제)")
    _add_video(sp)
    _add_points_options(sp, required=True)
    sp.set_defaults(func=cmd_frames)

    sp = sub.add_parser("frame", help="주문형 단일 프레임 추출 (frames 이후)")
    _add_video(sp)
    sp.add_argument("--at", type=float, required=True, help="추출 시각(초)")
    sp.add_argument("--reason", required=True, help="추출 사유 (provenance 필수)")
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
    sp.set_defaults(func=cmd_debug_report)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
