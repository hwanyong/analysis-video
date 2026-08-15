"""GUI 창 스크린샷 — 실제 분석 결과를 띄운 창을 오프스크린으로 캡처한다.

**왜 오프스크린인가.** 화면을 띄우고 손으로 찍으면 창 장식·바탕화면·커서·개인
파일 이름이 함께 찍히고, 무엇보다 다음 사람이 같은 그림을 다시 만들 수 없다.
Qt 의 offscreen 플랫폼 플러그인(`QT_QPA_PLATFORM=offscreen`)으로 띄우면 화면
없이도 위젯이 그려지고 `QWidget.grab()` 이 그 결과를 그대로 준다 — GUI 테스트가
쓰는 것과 같은 방식이다(packages/gui/tests/conftest.py).

**설정을 격리한다.** GUI 는 언어와 창 위치를 QSettings 에 저장하고 다음 실행에
그대로 복원한다. 격리하지 않으면 두 가지가 깨진다 — ① 찍는 사람이 마지막으로
쓰던 언어·창 크기가 그림에 나와 기계마다 다른 스크린샷이 나오고, ② 이 스크립트가
찍는 사람의 실제 설정을 덮어쓴다. 그래서 저장 형식을 IniFormat 으로 바꿔 임시
디렉터리로 보내고(NativeFormat 은 macOS 에서 경로 지정을 무시한다), 언어는
인자로 못박는다.

**결정성의 한계.** 글자는 OS 의 시스템 글꼴로 그려지므로 기계가 다르면 자간이
달라진다. 창 구성·데이터·크기는 같다.

사용:
    uv run python examples/make_demo_video.py
    uv run analysis-video analyze docs/media/demo-pipeline.mp4
    uv run python examples/make_gui_screenshot.py
"""
import argparse
import contextlib
import io
import os
import shutil
import tempfile
import time
from pathlib import Path

# PySide6 를 들이기 **전에** 걸어야 한다 — 플랫폼 플러그인은 QApplication 이
# 만들어질 때 한 번 정해지고, 그 뒤에 바꿔도 늦다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analysis_video_gui import app as gui_app, i18n
from analysis_video_gui.session import REGISTRY, Session

WINDOWS = [wid for wid, _key in REGISTRY]

# 워크벤치 합성의 배치. 창 하나를 찍는 것과 달리 "이 도구가 어떤 화면들로 이루어져
# 있는가"를 한 장으로 보여 주는 것이 목적이라, 크기는 각 창이 **자기 내용을 다 보여 줄
# 만큼**으로 고정한다(허브는 좁고 길게, 타임라인은 폭 전체).
HUB = "__hub__"
WORKBENCH = [
    [("player", 956, 660), ("gallery", 956, 660)],
    [("frame_sync", 440, 480), ("dialogue", 440, 480), ("compare", 620, 480), (HUB, 380, 480)],
    [("timeline", 1928, 520)],
]
PAD, GAP, TITLE_H = 16, 14, 26


def ascii_title(s: str) -> str:
    """창 제목을 내장 글꼴이 그릴 수 있는 글자로 — 뜻은 남기고 글리프만 바꾼다.

    제목에는 단축키 번호가 동그라미 숫자(①)로, 구분자가 em dash 로 들어 있다.
    demo_style.text 는 글리프가 없는 글자를 빈 네모로 그리는 대신 멈추므로(그게 옳다),
    여기서 뜻이 같은 ASCII 로 바꿔 넘긴다. 번호를 그냥 버리면 허브의 Windows 목록과
    그림의 칸을 맞춰 볼 수 없다.
    """
    out = []
    for ch in s:
        o = ord(ch)
        if 0x2460 <= o <= 0x2473:        # ① .. ⑳
            out.append(f"{o - 0x2460 + 1}.")
        elif ch in "—–":
            out.append("-")
        elif ch == "·":
            out.append("/")
        else:
            out.append(ch)
    return "".join(out)


def stage(path: Path) -> Path:
    """입력만 **중립 경로**로 옮기고 거기서 다시 분석한 뒤 그 사본을 가리킨다.

    허브 창은 Source·Subtitle 의 절대 경로를 그대로 띄운다. 저장소 자리에서 찍으면
    찍은 사람의 홈 디렉터리(= 계정 이름)가 문서 그림에 실려 나가고, 경로 길이가
    기계마다 달라 생략 위치까지 달라진다.

    **분석 디렉터리를 통째로 복사하는 것으로는 안 된다** — `state.json` 이 원본의
    절대 경로를 안고 있어 옮긴 자리에서도 그 값이 그대로 표시된다(허브가 읽는 것이
    그 값이다). 영상과 자막만 옮겨 새로 분석해야 기록되는 경로도 옮긴 자리가 된다.
    """
    # /tmp 를 먼저 쓴다. macOS 의 gettempdir() 은 /var/folders/…/T 로 길어서, 짧게
    # 만들려던 경로가 다시 생략 표시되고 만다.
    base = Path("/tmp") if Path("/tmp").is_dir() else Path(tempfile.gettempdir())
    dst_dir = base / "analysis-video-demo"
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    for item in path.parent.iterdir():
        if item.is_file() and item.name.startswith(path.stem):
            shutil.copy2(item, dst_dir / item.name)

    staged = dst_dir / path.name
    from analysis_video.cli import main as cli_main
    with contextlib.redirect_stdout(io.StringIO()):   # 결과 JSON 은 이 스크립트의 출력이 아니다
        rc = cli_main(["analyze", str(staged)])
    if rc != 0:
        raise SystemExit(f"옮긴 사본을 분석하지 못했습니다 (exit {rc}): {staged}")
    return staged


def isolate_settings() -> None:
    """QSettings 를 임시 디렉터리로 보낸다. 첫 QSettings 생성 전에 불려야 한다."""
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      tempfile.mkdtemp(prefix="analysis-video-shot-"))


def capture(path: Path, wid: str, lang: str, at: float, size: tuple[int, int],
            out: Path) -> None:
    isolate_settings()
    i18n.set_language(lang)
    qapp = QApplication([])
    # 경로 해석은 GUI 엔트리와 **같은 함수**로 한다 — 여기서 `.analysis` 를 다시
    # 조립하면 레이아웃 규칙이 바뀔 때 이 스크립트만 조용히 옛 경로를 짚는다.
    video, out_dir = gui_app._resolve(path)
    session = Session(video, out_dir)
    if not session.store.metadata:
        raise SystemExit(f"분석 결과가 없습니다: {out_dir}\n"
                         f"먼저 `analysis-video analyze {path}` 를 돌려 주세요.")

    session.engine.seek(at)
    window = session.open_window(wid)
    window.resize(*size)

    # 창을 띄운 직후에는 그래프·썸네일이 아직 안 그려져 있다. 갤러리는 썸네일을
    # 타이머로 나눠 넣고(windows/gallery.py), pyqtgraph 는 첫 레이아웃을 다음
    # 이벤트 루프 차례에 한다 — 이벤트를 충분히 돌려 준 뒤에 찍는다.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    out.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(out)):
        raise SystemExit(f"스크린샷을 저장하지 못했습니다: {out}")


def capture_workbench(path: Path, lang: str, at: float, out: Path,
                      max_width: int = 0, colors: int = 0) -> None:
    """창 일곱 개를 한 장으로 — 이 도구가 어떤 화면들로 이루어져 있는지.

    창마다 따로 찍어 Pillow 로 붙인다. 한 화면에 다 띄워 놓고 통째로 찍으면 그것이
    바로 이 스크립트가 존재하는 이유(바탕화면·커서·개인 경로·재현 불가)를 되살린다.
    `grab()` 은 창 내용만 주고 제목 표시줄은 주지 않으므로 제목 띠는 여기서 그린다 —
    어느 칸이 무슨 창인지가 이 그림의 절반이다.
    """
    from PIL import Image, ImageDraw

    from demo_style import BG, INK, MUTED, PANEL, RULE, text

    isolate_settings()
    i18n.set_language(lang)
    qapp = QApplication([])
    video, out_dir = gui_app._resolve(path)
    session = Session(video, out_dir)
    if not session.store.metadata:
        raise SystemExit(f"분석 결과가 없습니다: {out_dir}\n"
                         f"먼저 `analysis-video analyze {path}` 를 돌려 주세요.")
    session.engine.seek(at)

    from analysis_video_gui.windows.hub import HubWindow

    # 먼저 전부 만들고 크기를 준 뒤에 이벤트를 돌린다. 하나씩 찍으면 뒤엣것이 그려지는
    # 동안 앞엣것이 이미 캡처된 뒤라, 타이머로 채우는 갤러리 썸네일이 빈 채로 남는다.
    widgets: dict[str, object] = {}
    for row in WORKBENCH:
        for wid, w, h in row:
            win = HubWindow(session) if wid == HUB else session.open_window(wid)
            win.resize(w, h)
            widgets[wid] = win

    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    inner = max(sum(w for _, w, _ in row) + GAP * (len(row) - 1) for row in WORKBENCH)
    height = PAD * 2 + sum(TITLE_H + row[0][2] for row in WORKBENCH) + GAP * (len(WORKBENCH) - 1)
    canvas = Image.new("RGB", (inner + PAD * 2, height), BG)
    draw = ImageDraw.Draw(canvas)

    tmp = Path(tempfile.mkdtemp(prefix="analysis-video-wb-"))
    y = PAD
    for row in WORKBENCH:
        x = PAD
        for wid, w, h in row:
            shot = tmp / f"{wid}.png"
            if not widgets[wid].grab().save(str(shot)):
                raise SystemExit(f"창을 캡처하지 못했습니다: {wid}")
            title = (widgets[wid].windowTitle() if wid == HUB
                     else session.window_title(wid))
            draw.rectangle([x, y, x + w - 1, y + TITLE_H - 1], fill=PANEL, outline=RULE)
            text(draw, (x + 10, y + TITLE_H / 2), ascii_title(title), 13, fill=INK,
                 anchor="lm")
            canvas.paste(Image.open(shot).convert("RGB").resize((w, h)), (x, y + TITLE_H))
            draw.rectangle([x, y, x + w - 1, y + TITLE_H + h - 1], outline=RULE)
            x += w + GAP
        y += TITLE_H + row[0][2] + GAP

    text(draw, (canvas.width - PAD, height - PAD + 2),
         "analysis-video-gui / offscreen capture, examples/make_gui_screenshot.py",
         12, fill=MUTED, anchor="rs")

    # 창은 제 크기로 그려 놓고 **마지막에 한 번만** 줄인다. 처음부터 작게 잡으면 Qt 가
    # 그 크기에 맞춰 다시 배치하면서 범례·표가 잘리고, 줄일 때마다 어디가 잘렸는지
    # 확인해야 한다. 한 번의 리샘플이면 글자만 조금 무뎌지고 구성은 그대로다.
    if max_width and canvas.width > max_width:
        canvas = canvas.resize(
            (max_width, round(canvas.height * max_width / canvas.width)),
            Image.LANCZOS)

    # 팔레트로 줄인다. 이 그림이 무거운 이유는 크기가 아니라 **색 수**다 — UI 는 평평한
    # 색 몇 가지로 되어 있어 원래 잘 압축되는데, 축소 리샘플이 그 경계마다 중간색을
    # 만들어 17,000색짜리 사진처럼 만들어 버린다(줄여도 파일이 안 줄어드는 이유다).
    # dither 를 끄는 것이 중요하다 — 디더 점무늬는 눈에 띄지도 않으면서 압축만 망친다.
    if colors:
        canvas = canvas.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                                 dither=Image.Dither.NONE)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "PNG", optimize=True)
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", type=Path, default=root / "docs/media/demo-pipeline.mp4",
                    help="영상 파일 또는 .analysis 디렉터리")
    ap.add_argument("--window", choices=[*WINDOWS, "workbench"], default="timeline",
                    help="찍을 창 (기본: timeline — 세 신호와 판정선이 함께 보인다). "
                         "workbench 는 창 일곱 개를 한 장으로 합성한다")
    ap.add_argument("--stage", action="store_true",
                    help="영상과 분석 결과를 임시 경로로 복사해 그쪽을 찍는다 — "
                         "허브 창에 뜨는 절대 경로에서 홈 디렉터리(계정 이름)를 없앤다. "
                         "workbench 에서는 기본으로 켜진다")
    ap.add_argument("--no-stage", dest="stage", action="store_false")
    ap.set_defaults(stage=None)
    # 1400px: 랜딩의 본문 폭이 1040 CSS px 이라 브라우저가 어차피 줄여서 그린다.
    # 원본 1960 을 그대로 실어 봐야 그 축소를 브라우저가 대신할 뿐이고 전송량만 두 배다.
    # 0 을 주면 줄이지 않는다.
    ap.add_argument("--max-width", type=int, default=1400,
                    help="workbench 합성본의 최대 가로 픽셀 (기본 1400, 0 = 줄이지 않음)")
    ap.add_argument("--colors", type=int, default=256,
                    help="팔레트 색 수 (기본 256, 0 = 트루컬러). 용량을 실제로 가르는 값이다")
    ap.add_argument("--lang", choices=i18n.CODES, default="en", help="UI 언어")
    ap.add_argument("--at", type=float, default=20.0,
                    help="재생 위치(초). 기본값은 판서 화면 한복판이다")
    ap.add_argument("--size", default="1400x760", help="창 크기 (가로x세로)")
    ap.add_argument("--out", type=Path, default=None,
                    help="기본: docs/media/gui-<창>.png")
    args = ap.parse_args()

    out = args.out or root / f"docs/media/gui-{args.window}.png"
    path = args.path
    if args.stage or (args.stage is None and args.window == "workbench"):
        path = stage(path)

    if args.window == "workbench":
        capture_workbench(path, args.lang, args.at, out, args.max_width, args.colors)
    else:
        w, _, h = args.size.partition("x")
        capture(path, args.window, args.lang, args.at, (int(w), int(h)), out)
    print(f"{out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
