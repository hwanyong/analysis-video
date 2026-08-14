"""데모 영상 생성 — 저작권이 깨끗한 합성 강의 영상과 자막을 만든다.

**왜 만드나.** 공개 저장소와 PyPI 페이지에 실을 시각 자료가 필요한데, 손에 있는
강의 영상은 전부 타인의 저작물이라 한 프레임도 쓸 수 없다. 그래서 이 도구가 무엇을
하는지 설명하는 슬라이드를 직접 그려 영상으로 만든다 — 저작권이 깨끗하고, 누구나
이 스크립트로 다시 만들 수 있다. 내용도 남의 강의를 흉내 낸 것이 아니라 이 도구의
파이프라인 설명이다.

**무엇을 재현하나.** 슬라이드형 강의 영상의 두 성질이다.

1. 또렷한 화면 전환(컷) — `cut_area` 신호가 잡는 사건.
2. 점진적으로 완성되는 화면(판서형) — 어느 한 프레임도 튀지 않으면서 그림이 자라는
   화면. 이 도구가 한 화면에서 "첫 등장"과 "완성 상태" 두 장을 남기는 자리다
   (frames.build_frames 의 screen-start / screen-end).

**판서 구간을 그리는 제약.** 판서가 진행되는 동안 검출기가 **사건을 내면 안 된다** —
사건이 나면 거기서 화면이 갈라져 "한 화면이 자라는" 예시 자체가 사라진다. 신호는
64×36 으로 줄인 그레이 프레임에서 재고(media.decode_gray_frames) 완성 상태를
남길지는 400×225 의 SSIM 으로 정하므로(frames._pair_changed), 아래 세 값을 동시에
만족시켜야 한다. 괄호 안은 이 파일이 만든 영상에서 실제로 잰 값이다.

    한 프레임이 더하는 획   cut_area  < 0.002  (0.00087 — 여유 56%)
    판서가 다 찬 뒤 누적차  anchor    < 0.02   (0.00962 — 여유 52%)
    빈 판 대 완성 판의 SSIM           < 0.93   (0.8856 — 여유 0.044)

다시 재려면 인코딩한 영상에 대해 이렇게 한다(analyze 를 한 번 돌린 뒤):

    detect_signals.npz 의 anchor_series / area_series 를 10.1~29.0초로 자른 최대값,
    그리고 media.extract_gray_array(영상, 10.13/28.93, w=400, h=225) 두 장의 SSIM.

이 셋이 서로 반대로 움직인다. 판서 글자를 늘리면 SSIM 은 내려가지만(좋다) anchor 가
올라가고(나쁘다), 글꼴을 키우면 한 글자가 더하는 컷 면적이 커진다. 균형점을 찾은
방식은 이렇다 — **작은 글자를 여러 줄**(BOARD_NOTES, 28/26px 12줄)로 넓게 흩고,
**한 프레임에 한 글자만** 쓴다(BOARD_CPF=1). 커서(캐럿)는 그리지 않는다: 커서가
한 칸 옮겨 갈 때마다 사라진 자리와 나타난 자리 두 곳이 함께 바뀌어, 실측에서 컷
면적을 0.00087 에서 0.00217 로 밀어올려 판서 한복판에서 화면을 갈랐다.

세 값이 어긋나면 analyze 결과의 화면 수·이미지 수가 달라지므로 바로 드러난다.
기대값은 화면 5개 / 이미지 6장(판서 화면만 두 장)이다.

**오디오는 무음이다.** 트랙 자체는 있어야 split·transcribe 가 실제 강의 영상과 같은
경로를 지난다. 소리를 넣지 않는 이유는 테스트 픽스처와 같다(커밋 0eab81b) —
재생하면 그대로 스피커로 나간다.

**결정성.** 난수·현재 시각·로케일·시스템 글꼴을 일절 쓰지 않는다. 같은 기계에서
지우고 다시 만들면 mp4·srt 가 바이트까지 같았다(sha256 대조 확인). 기계가 바뀌면
보이는 내용은 같지만 파일이 같다고 보장하지는 못한다 — Pillow 가 안고 다니는 글꼴이
판올림에서 바뀔 수 있고, libx264 빌드가 다르면 압축 결과가 달라진다.

사용:
    uv run python examples/make_demo_video.py
    uv run analysis-video analyze docs/media/demo-pipeline.mp4
"""
import argparse
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw

from demo_style import (ACCENT, BG, HEIGHT, INK, MUTED, PANEL, RULE, WARM, WIDTH,
                        text)

FPS = 15
# 오디오 표본율 — FPS 로 나누어떨어져야 비디오 프레임 하나당 오디오 한 덩어리를
# 정확히 짝지어 넣을 수 있다(48000 / 15 = 3200).
SAMPLE_RATE = 48000

# ─── 슬라이드 ────────────────────────────────────────────────────────────────
# 각 슬라이드가 시작되는 시각(초). 마지막 값은 영상의 끝이다.
CUTS = [0.0, 5.0, 10.0, 29.0, 35.0, 41.0]

# 판서 슬라이드(CUTS 인덱스 2, 10~29초)에 한 글자씩 써 내려갈 메모. ("head"|"body", 글)
# 내용은 이 도구의 파이프라인 그대로다 — split → transcribe → frames, 그리고
# 화면마다 두 장. "a cut, a drift, a burst" 는 세 신호(cut_area / anchor_diff /
# inst_diff)를 그 성질로 부른 것이다.
BOARD_NOTES = [
    ("head", "split"),
    ("body", "audio out, video out"),
    ("body", "nothing is decided here"),
    ("head", "transcribe"),
    ("body", "subtitles first"),
    ("body", "speech only if there are none"),
    ("head", "frames"),
    ("body", "three signals: a cut, a drift, a burst"),
    ("body", "their union is the list of events"),
    ("head", "shoot twice"),
    ("body", "the screen when it appeared"),
    ("body", "and the same screen, finished"),
]
BOARD_START = 11.0   # 판서를 시작하는 시각 — 슬라이드가 뜨고 1초 뒤
BOARD_CPF = 1        # 한 프레임에 쓰는 글자 수. 위 docstring 의 cut_area 제약.
BOARD_CHARS = sum(len(s) for _kind, s in BOARD_NOTES)

FOOTER = "analysis-video / synthetic demo clip, drawn by examples/make_demo_video.py"


def _chrome(draw: ImageDraw.ImageDraw, heading: str) -> None:
    """모든 슬라이드에 같은 자리로 들어가는 제목줄과 푸터.

    푸터를 **모든 슬라이드에서 글자까지 똑같이** 두는 것은 그림 취향이 아니라 검출
    조건이다. 화면 아래쪽 행이 매번 바뀌면 오버레이 띠 산출(detect.overlay)이 그것을
    번인 자막으로 보고 잘라낼 수 있다. 위쪽도 같은 이유로 첫 40px 은 여백으로 비운다.
    """
    text(draw, (80, 64), heading, 44, INK)
    draw.rectangle((80, 124, 80 + 96, 128), fill=ACCENT)
    text(draw, (80, HEIGHT - 46), FOOTER, 19, MUTED)


def _slide_title(draw: ImageDraw.ImageDraw) -> None:
    text(draw, (80, 210), "analysis-video", 86, INK)
    draw.rectangle((80, 330, 80 + 150, 336), fill=ACCENT)
    text(draw, (80, 378), "Turn a lecture recording into context an agent can read",
         34, INK)
    text(draw, (80, 436), "keyframes, timestamps and transcript in one Markdown file",
         28, MUTED)
    text(draw, (80, HEIGHT - 46), FOOTER, 19, MUTED)


def _slide_problem(draw: ImageDraw.ImageDraw) -> None:
    _chrome(draw, "Why a recording is hard to read")
    rows = [
        ("30 frames a second", "and almost every one of them is a repeat"),
        ("words with no picture", "the transcript never says what was on screen"),
        ("no marks at all", "nothing records when a screen appeared or left"),
    ]
    y = 205
    for title, body in rows:
        draw.rectangle((80, y + 14, 92, y + 26), fill=WARM)
        text(draw, (120, y), title, 34, INK)
        text(draw, (120, y + 48), body, 27, MUTED)
        y += 128


def _slide_board(draw: ImageDraw.ImageDraw, shown: int) -> None:
    """판서 슬라이드. `shown` 글자까지 이미 쓰인 상태를 그린다.

    오른쪽 설명 블록은 **처음부터 끝까지 그대로**다. 판서 칸만 자라야 그 화면이
    "한 프레임도 튀지 않으면서 자란다"는 예시가 되기 때문이고, 덤으로 판이 아직
    비어 있는 첫 프레임도 내용량 게이트(overlay.content_area)를 넉넉히 넘긴다.
    """
    _chrome(draw, "What this tool does")
    draw.rectangle((80, 176, 740, HEIGHT - 96), fill=PANEL)
    for i, (kind, line) in enumerate(BOARD_NOTES):
        before = shown - sum(len(s) for _k, s in BOARD_NOTES[:i])  # 이 줄에 쓴 글자 수
        n = max(0, min(len(line), before))
        if not n:
            continue
        head = kind == "head"
        text(draw, (124 if head else 168, 198 + i * 35), line[:n],
             28 if head else 26, INK if head else MUTED)

    text(draw, (786, 198), "Nothing here is a cut.", 28, INK)
    text(draw, (786, 246), "Every frame is almost", 26, MUTED)
    text(draw, (786, 280), "the same as the one", 26, MUTED)
    text(draw, (786, 314), "before it.", 26, MUTED)
    text(draw, (786, 380), "A second signal watches", 26, MUTED)
    text(draw, (786, 414), "the drift away from", 26, MUTED)
    text(draw, (786, 448), "where the screen started.", 26, MUTED)
    text(draw, (786, 520), "one screen", 30, ACCENT)
    text(draw, (786, 558), "two shots", 30, ACCENT)


def _slide_output(draw: ImageDraw.ImageDraw) -> None:
    _chrome(draw, "What comes out: context.md")
    draw.rectangle((80, 176, WIDTH - 80, 470), fill=PANEL)
    lines = [
        ("## <start>-<end>s", ACCENT),
        ("![](read/<the screen when it appeared>.jpg)", INK),
        ("![](read/<the same screen, finished>.jpg)", INK),
        ("<everything that was said while it was up>", INK),
    ]
    y = 212
    for s, color in lines:
        text(draw, (124, y), s, 30, color)
        y += 62
    text(draw, (80, 512), "one section per screen - that file is all an agent reads",
         30, INK)
    text(draw, (80, 558), "the full record stays in metadata.json next to it", 27, MUTED)


def _slide_repro(draw: ImageDraw.ImageDraw) -> None:
    _chrome(draw, "Reproduce this clip")
    draw.rectangle((80, 190, WIDTH - 80, 400), fill=PANEL)
    text(draw, (124, 226), "uv run python examples/make_demo_video.py", 30, INK)
    text(draw, (124, 296), "uvx analysis-video analyze docs/media/demo-pipeline.mp4",
         30, ACCENT)
    text(draw, (80, 452), "no network, no account, nothing but the file on your disk",
         32, INK)
    text(draw, (80, 506), "every pixel in this clip was drawn by the script above",
         27, MUTED)


def state_at(t: float) -> tuple:
    """이 시각의 화면 상태를 나타내는 열쇠 — 같은 열쇠면 같은 그림이다.

    500장 넘는 프레임 대부분이 앞 프레임과 똑같으므로, 열쇠로 캐시해 두면 그리기가
    글자 수만큼만 일어난다."""
    idx = max(i for i, c in enumerate(CUTS[:-1]) if t >= c)
    if idx != 2:
        return (idx, 0)
    written = int(max(0.0, t - BOARD_START) * FPS) * BOARD_CPF
    return (idx, min(BOARD_CHARS, written))


# 슬라이드 순서. 판서 슬라이드(인덱스 2)만 인자가 하나 더 필요해 render 가 따로 부른다.
STATIC_SLIDES = {0: _slide_title, 1: _slide_problem, 3: _slide_output, 4: _slide_repro}


def render(state: tuple) -> Image.Image:
    idx, shown = state
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, HEIGHT - 72, WIDTH, HEIGHT - 71), fill=RULE)
    if idx in STATIC_SLIDES:
        STATIC_SLIDES[idx](draw)
    else:
        _slide_board(draw, shown)
    return img


# ─── 자막 ────────────────────────────────────────────────────────────────────
# (시작, 끝, 텍스트). 화면에 떠 있는 것을 말로 풀어 주는 강의 대사 형태다 —
# 자막 사다리(stt.subtitles)가 이것을 그대로 전사로 채택하고 whisper 는 돌지 않는다.
CUES = [
    (0.4, 2.7, "This clip was drawn by a script, so it is free to share."),
    (2.9, 4.8, "It shows what analysis-video pulls out of a lecture."),
    (5.2, 7.6, "A recording is thousands of frames that are nearly all the same."),
    (7.8, 9.8, "And a transcript that never says what was on screen."),
    (10.2, 12.8, "So the tool works in four moves, and I will write them out."),
    (13.0, 15.6, "Watch the board. Nothing here is a cut, the picture only grows."),
    (15.8, 18.4, "Every frame is almost identical to the one before it."),
    (18.6, 21.4, "A detector that only hunts for cuts would keep this empty board."),
    (21.6, 24.6, "So a second signal measures the drift away from where it started."),
    (24.8, 28.4, "And when the screen finally leaves, it is shot again, finished."),
    (29.2, 31.6, "Each screen becomes one section of a Markdown file."),
    (31.8, 34.6, "The seconds it was up, its images, and the words spoken over it."),
    (35.2, 37.6, "You can rebuild this clip and rerun the whole pipeline yourself."),
    (37.8, 40.6, "One command, no network, nothing but the file on your disk."),
]


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path) -> None:
    blocks = [f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{s}\n"
              for i, (a, b, s) in enumerate(CUES, start=1)]
    # 줄바꿈을 LF 로 고정한다 — 윈도우에서 만들면 CRLF 가 섞여 같은 스크립트가
    # 다른 파일을 내놓는다(파서는 둘 다 읽지만 결정성이 깨진다).
    path.write_text("\n".join(blocks), encoding="utf-8", newline="\n")


# ─── 인코딩 ──────────────────────────────────────────────────────────────────
def encode(path: Path) -> None:
    duration = CUTS[-1]
    n_frames = round(duration * FPS)
    samples_per_frame = SAMPLE_RATE // FPS

    out = av.open(str(path), "w")
    # 스트림은 첫 mux(=헤더 기록) 전에 모두 선언해야 한다.
    vs = out.add_stream("libx264", rate=FPS)
    vs.width, vs.height, vs.pix_fmt = WIDTH, HEIGHT, "yuv420p"
    # 키프레임 간격이 파일 크기를 지배한다 — 정지 슬라이드는 키프레임 한 장이
    # 나머지 1초치보다 비싸다. 실측(이 클립의 34초 판, 720p, crf 20): 1초 간격
    # 1,173KB / 8초 간격 332KB. 장면 전환 검출(scenecut, x264 기본값)은 켜 둔다: 그래야
    # 슬라이드가 바뀌는 자리에 키프레임이 놓여 그 시각을 찍을 때 탐색이 짧다.
    # tune=stillimage 는 정지 화면용 양자화 — 글자 획이 뭉개지지 않게 한다.
    vs.options = {"crf": "20", "preset": "veryslow", "tune": "stillimage",
                  "x264-params": f"keyint={FPS * 8}:min-keyint={FPS}"}
    audio = out.add_stream("aac", rate=SAMPLE_RATE)
    audio.layout = "mono"
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)

    cache: dict[tuple, np.ndarray] = {}
    silence = np.zeros((1, samples_per_frame), dtype=np.float32)

    for i in range(n_frames):
        state = state_at(i / FPS)
        if state not in cache:
            cache.clear()  # 상태는 단조 진행이라 직전 것만 남기면 된다
            cache[state] = np.asarray(render(state))
        vf = av.VideoFrame.from_ndarray(cache[state], format="rgb24")
        vf.pts = i
        for packet in vs.encode(vf):
            out.mux(packet)

        # 오디오는 비디오 프레임마다 같은 길이로 끼워 넣는다 — 뒤에 몰아서 넣으면
        # 재생기가 파일 전체를 버퍼링해야 소리가 시작된다.
        af = av.AudioFrame.from_ndarray(silence, format="flt", layout="mono")
        af.sample_rate = SAMPLE_RATE
        af.pts = i * samples_per_frame
        af.time_base = Fraction(1, SAMPLE_RATE)
        for resampled in resampler.resample(af):
            for packet in audio.encode(resampled):
                out.mux(packet)

    for packet in vs.encode(None):
        out.mux(packet)
    for packet in audio.encode(None):
        out.mux(packet)
    out.close()


def main() -> int:
    default_out = Path(__file__).resolve().parent.parent / "docs" / "media"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=default_out,
                    help=f"산출물을 둘 디렉터리 (기본: {default_out})")
    ap.add_argument("--name", default="demo-pipeline", help="파일 이름(확장자 제외)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    video = args.out / f"{args.name}.mp4"
    # 자막은 영상 **바로 옆에** 같은 어간으로 둔다 — 그 자리에 있어야 자막 사다리가
    # 사이드카 후보로 집어 whisper 없이 전사가 끝난다(stt.subtitles.sidecar_candidates).
    srt = args.out / f"{args.name}.en.srt"

    encode(video)
    write_srt(srt)
    print(f"{video} ({video.stat().st_size / 1024:.0f} KB, {CUTS[-1]:.0f}s @ {FPS}fps)")
    print(f"{srt} ({len(CUES)} cues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
