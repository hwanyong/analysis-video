"""STT 백엔드가 없는 환경 — 무엇이 되고, 무엇이 언제 실패하는가.

백엔드(mlx-whisper·faster-whisper)는 `analysis-video[stt]` extra로만 들어온다.
그래서 "백엔드가 없는 환경"은 고장이 아니라 **기본 설치**이고, 이 파일은 그
환경에서 갈리는 세 갈래를 잠근다:

- `doctor`는 능력이 하나 없다고 보고할 뿐 실패하지 않는다 (exit 0).
- 자막이 있는 영상은 처음부터 끝까지 분석된다 — whisper를 쳐다보지도 않는다.
- 자막을 하나도 못 쓴 영상에서만, 음성을 받아써야 하는 그 순간에 exit 4가 난다.

셋이 갈리지 않으면 어떻게 되는지는 겪어 봤다: `doctor`가 "백엔드 없음 = 환경
고장"이라 단정하던 시절, 자막만으로 끝까지 분석되는 기계가 빨간불을 받았고
스킬 문서에는 "doctor가 안 된다고 해도 자막이 있는 영상은 분석된다"는 해명을
사람이 손으로 덧붙여야 했다. 그 해명이 필요 없어지는 것이 이 변경의 성공
신호이므로, 여기서 굳히는 것은 종료코드 4의 **폐지가 아니라 발화 지점**이다.
"""
import json
from pathlib import Path

import av
import numpy as np
import pytest

from analysis_video import cli, manifest, stt
from analysis_video.errors import EXIT_DEPS, EXIT_OK, CliError

# 5개 큐로 6초 중 5초를 덮는다 — 큐 하한(MIN_CUES=5)과 커버리지 하한(30%)을 모두
# 넘겨야 자막이 채택되고, 그래야 이 파일이 보려는 "자막 경로"가 실제로 돈다.
SRT = "\n".join(f"{i + 1}\n00:00:0{i},200 --> 00:00:0{i + 1},200\n{i + 1}번째 대사\n"
                for i in range(5))


@pytest.fixture(autouse=True)
def _no_ambient_backend_choice(monkeypatch):
    """ANALYSIS_VIDEO_STT가 켜져 있는 기계에서 결과가 달라지지 않게 —
    이 변수는 --stt-backend와 같은 자리를 차지한다(stt.resolve_backend)."""
    monkeypatch.delenv("ANALYSIS_VIDEO_STT", raising=False)


@pytest.fixture
def no_stt(monkeypatch):
    """백엔드가 하나도 설치되지 않은 환경 = extra 없이 설치한 기본 상태.

    find_spec을 가로채는 것으로 충분하다: 설치 여부를 보는 자리가 stt 모듈의
    그 한 곳뿐이라(installed_backends·resolve_backend), 실제 그 환경과 **같은
    코드 경로**가 돈다. 대역으로 resolve_backend 자체를 갈아 끼우면 정작 이
    파일이 시험하려는 판정이 사라진다."""
    monkeypatch.setattr(stt, "find_spec", lambda _module: None)


def _write_video(path: Path, seconds: float = 6.0, fps: int = 10) -> None:
    """화면이 바뀌는 짧은 영상 + **무음** 오디오 트랙.

    오디오를 넣는 것이 이 파일의 핵심이다: has_audio=False면 전사 사다리가
    자막을 못 써도 빈 전사로 끝나(exit 0) 백엔드를 부르지 않는다. 그러면
    "자막이 없으면 exit 4"를 시험할 수단이 없다. 소리는 넣지 않는다 —
    테스트를 돌릴 때마다 스피커로 나가기 때문이다(gui conftest의 같은 자리)."""
    with av.open(str(path), "w") as out:
        vs = out.add_stream("libx264", rate=fps)
        vs.width, vs.height, vs.pix_fmt = 320, 180, "yuv420p"
        audio = out.add_stream("aac", rate=48000)
        audio.layout = "mono"

        for i in range(int(seconds * fps)):
            arr = np.full((180, 320, 3), 235, dtype=np.uint8)
            slide = i // (fps * 2)          # 2초마다 화면이 바뀐다
            arr[30:120, 20 + slide * 70:100 + slide * 70] = 40
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            frame.pts = i
            for packet in vs.encode(frame):
                out.mux(packet)

        pcm = np.zeros(int(seconds * 48000), dtype=np.float32)
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=48000)
        af = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="flt", layout="mono")
        af.sample_rate = 48000
        for resampled in resampler.resample(af):
            for packet in audio.encode(resampled):
                out.mux(packet)
        for packet in audio.encode(None):
            out.mux(packet)
        for packet in vs.encode(None):
            out.mux(packet)


def _result(capsys) -> dict:
    """stdout의 결과 JSON 한 건 — 에이전트가 읽는 것과 같은 자리."""
    return json.loads(capsys.readouterr().out)


# ─── 진단은 능력을 보고한다 ──────────────────────────────────────────────
def test_doctor_calls_a_missing_backend_a_capability_not_a_fault(no_stt, capsys):
    code = cli.main(["doctor"])

    result = _result(capsys)
    assert code == EXIT_OK, "백엔드 부재는 환경 고장이 아니다"
    assert result["ok"] is True and "error" not in result
    cap = result["capabilities"]["speech-recognition"]
    assert cap["available"] is False
    assert cap["installed_backends"] == [] and cap["resolved_backend"] is None
    # 없는 능력에는 "그래서 무엇을 하면 되는가"가 붙어야 한다
    assert "analysis-video[stt]" in cap["install"]
    assert cap["needed_for"]


def test_doctor_still_fails_when_a_required_library_is_gone(monkeypatch, capsys):
    """exit 4가 없어진 것이 아니다. 필수 의존(코어의 무조건 의존)이 없으면
    이 도구는 자막이 있든 없든 아무것도 못 하므로, 그것은 여전히 환경 고장이다."""
    real = cli.find_spec
    monkeypatch.setattr(cli, "find_spec",
                        lambda module: None if module == "av" else real(module))

    code = cli.main(["doctor"])

    result = _result(capsys)
    assert code == EXIT_DEPS and result["ok"] is False
    assert result["error"]["kind"] == "core-deps-missing"
    assert "pyav" in result["error"]["message"]


# ─── 자막이 있는 영상은 끝까지 간다 ──────────────────────────────────────
def test_a_subtitled_video_is_analysed_end_to_end_without_any_backend(
        tmp_path, no_stt, capsys):
    """이 변경의 존재 이유. 백엔드가 없는 기본 설치에서도 split→transcribe→frames가
    전부 돌고 context.md에 대사까지 실린다."""
    video = tmp_path / "lecture.mkv"
    _write_video(video)
    (tmp_path / "lecture.ko.srt").write_text(SRT, encoding="utf-8")

    code = cli.main(["analyze", str(video)])

    assert code == EXIT_OK
    result = _result(capsys)
    transcribe = next(s for s in result["stages"] if s["stage"] == "transcribe")
    assert transcribe["source_kind"] == "sidecar"
    assert transcribe["backend"] == "subtitle"
    context = Path(result["out_dir"]) / "runs" / "full" / "context.md"
    assert "1번째 대사" in context.read_text(encoding="utf-8")


# ─── 백엔드가 필요해진 그 순간에만 실패한다 ──────────────────────────────
def test_a_video_without_subtitles_fails_at_the_moment_whisper_is_needed(
        tmp_path, no_stt, capsys):
    video = tmp_path / "lecture.mkv"
    _write_video(video)                      # 자막을 두지 않는다

    code = cli.main(["analyze", str(video)])

    assert code == EXIT_DEPS
    error = _result(capsys)["error"]
    assert error["kind"] == "stt-backend-missing"
    # 안내를 따르면 해결되어야 한다 — 설치 명령이 hint에 그대로 있다
    assert "analysis-video[stt]" in error["hint"]
    # 자막을 두는 편이 더 싼 해결이므로 그쪽도 말해 준다
    assert "자막" in error["hint"]
    # 사다리가 왜 여기까지 내려왔는지가 함께 나가야 한다. 이 사유는 아직
    # transcript.json에 실리기 전이라, 실리지 못한 채 끝나는 이 실행에서는
    # 오류가 유일한 전달 수단이다.
    assert any("영상 옆에서" in note for note in error["details"]["notes"])
    # 실패 지점이 진짜로 옮겨 갔는가: split은 통과했고 transcribe에서 멈췄다
    state = manifest.load_state(Path(f"{video}.analysis"))
    assert manifest.is_done(state, "split")
    assert not manifest.is_done(state, "transcribe")


def test_naming_a_backend_that_is_not_installed_is_still_exit_4(no_stt):
    """--stt-backend로 지목한 백엔드가 없으면 조용한 폴백 없이 멈춘다(계약 유지)."""
    with pytest.raises(CliError) as excinfo:
        stt.resolve_backend("mlx")

    assert excinfo.value.code == EXIT_DEPS
    assert excinfo.value.kind == "stt-backend-missing"
    assert "analysis-video[stt]" in excinfo.value.hint


def test_asking_which_backends_exist_never_raises(no_stt):
    """능력을 묻는 자리는 답이 '없음'이어도 예외를 던지지 않는다 — 던지면
    doctor가 그것을 다시 고장으로 번역하게 되고, 옛 고장이 그렇게 생겼다."""
    assert stt.installed_backends() == ()
    assert stt.preferred_backend() is None
