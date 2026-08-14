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
import os
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


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", type=Path, default=root / "docs/media/demo-pipeline.mp4",
                    help="영상 파일 또는 .analysis 디렉터리")
    ap.add_argument("--window", choices=WINDOWS, default="timeline",
                    help="찍을 창 (기본: timeline — 세 신호와 판정선이 함께 보인다)")
    ap.add_argument("--lang", choices=i18n.CODES, default="en", help="UI 언어")
    ap.add_argument("--at", type=float, default=20.0,
                    help="재생 위치(초). 기본값은 판서 화면 한복판이다")
    ap.add_argument("--size", default="1400x760", help="창 크기 (가로x세로)")
    ap.add_argument("--out", type=Path, default=None,
                    help="기본: docs/media/gui-<창>.png")
    args = ap.parse_args()

    w, _, h = args.size.partition("x")
    out = args.out or root / f"docs/media/gui-{args.window}.png"
    capture(args.path, args.window, args.lang, args.at, (int(w), int(h)), out)
    print(f"{out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
