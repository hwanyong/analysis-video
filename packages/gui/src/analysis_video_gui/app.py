"""analysis-video-gui 엔트리 — `analysis-video-gui <video 또는 .analysis 디렉토리>`."""
import argparse
import sys
from pathlib import Path

from analysis_video import manifest
from analysis_video.errors import CliError
from PySide6.QtWidgets import QApplication

from . import i18n
from .i18n import tr


def _state(out_dir: Path) -> dict:
    """분석 디렉토리의 state.json — 읽기도 형식 대조도 코어(manifest)에 맡긴다.

    여기서 json으로 직접 읽으면 코어가 거부하는 옛 디렉토리를 GUI만 열게 되어,
    같은 디렉토리에 대해 두 도구의 판단이 갈린다. 대조 지점이 하나면 형식이
    올라갈 때 고칠 자리도 하나다.

    코어와 같은 자리에서 막는 것이 중요하다 — 통과시키면 아래 창들이 없는 칸을
    짚는 순간에야, 사용자가 손쓸 수 없는 모양으로 드러난다."""
    try:
        return manifest.load_state(out_dir)
    except CliError as e:
        # load_state가 내는 CliError는 형식 불일치 하나뿐이고 그 details는 두 칸을
        # 항상 채운다. 코어 메시지는 한국어 전용이라 그대로 쓰지 않고, 값만 받아
        # GUI 카탈로그의 문장에 끼운다.
        raise SystemExit(tr("app.err.schema", out_dir=out_dir,
                            expected=e.details["expected"],
                            found=e.details["found"])) from e


def _resolve(path: Path) -> tuple[Path, Path]:
    """비디오 파일 또는 .analysis 디렉토리 어느 쪽을 받아도 (video, out_dir)로 푼다."""
    if path.is_dir():
        out_dir = path
        # load_state는 없는 state.json을 빈 상태로 돌려준다(정상적인 첫 실행) —
        # 디렉토리를 지목한 경우엔 그게 곧 "분석한 적 없는 디렉토리"라 여기서 가른다.
        if not manifest.state_path(out_dir).exists():
            raise SystemExit(tr("app.err.no_state", out_dir=out_dir))
        src = _state(out_dir)["source"]["path"]
        video = Path(src)
        if not video.exists():
            raise SystemExit(tr("app.err.source_missing", src=src))
        return video, out_dir
    if not path.exists():
        raise SystemExit(tr("app.err.no_file", path=path))
    # 비디오로 열어도 결국 같은 디렉토리를 읽는다 — 형식 대조를 이쪽만 빼면
    # 거부되는 디렉토리를 여는 우회로가 하나 남는다. 아직 분석하지 않았으면
    # state.json이 없어 그대로 통과한다.
    out_dir = path.parent / f"{path.name}.analysis"
    _state(out_dir)
    return path, out_dir


def main(argv: list[str] | None = None) -> int:
    # 도움말과 기동 실패 메시지도 현지화 대상이라 argparse보다 먼저 언어를 정한다
    # (이 시점엔 QApplication이 아직 없다 — i18n.init이 그것을 전제하지 않는 이유).
    i18n.init()

    parser = argparse.ArgumentParser(
        prog="analysis-video-gui", description=tr("app.description"))
    parser.add_argument("path", type=Path, help=tr("app.arg.path"))
    args = parser.parse_args(argv)

    video, out_dir = _resolve(args.path)

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setApplicationName("analysis-video-gui")

    from .session import Session
    from .windows.hub import HubWindow

    session = Session(video, out_dir)
    # 산출물이 있는지는 Store가 분석 단위를 고른 뒤에야 알 수 있다 — 여기서 경로를
    # 다시 조립하면 단위 레이아웃이 바뀔 때마다 이 경고가 거짓말을 한다
    if not session.store.metadata:
        print(tr("app.warn.no_outputs", out_dir=out_dir), file=sys.stderr)

    hub = HubWindow(session)
    hub.show()
    session.restore_layout()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
