"""analysis-video-gui 엔트리 — `analysis-video-gui <video 또는 .analysis 디렉토리>`."""
import argparse
import sys
from pathlib import Path

from analysis_video import manifest
from analysis_video.errors import CliError
from PySide6.QtWidgets import QApplication

from . import i18n
from .i18n import tr


# 코어가 내는 CliError.kind → GUI 카탈로그의 문장과 그 문장이 쓰는 값.
# 코어 메시지는 한국어 전용이라 그대로 내보내지 않고, details의 값만 받아
# 여기서 사용자 언어로 다시 쓴다 — 메시지 문자열을 파싱하지는 않는다.
# state.json은 언제나 분석 디렉토리 바로 아래에 있으므로 그 부모가 out_dir이다.
_ERRORS = {
    "video-not-found": lambda d: tr("app.err.no_file", path=d["path"]),
    "not-analyzed": lambda d: tr("app.err.no_state", out_dir=d["path"]),
    "source-missing": lambda d: tr("app.err.source_missing", src=d["source"]),
    "schema-mismatch": lambda d: tr("app.err.schema", out_dir=Path(d["path"]).parent,
                                    expected=d["expected"], found=d["found"]),
}


def _die(e: CliError) -> SystemExit:
    """코어의 거부를 GUI의 종료 메시지로. 모르는 kind는 코어 문장을 그대로 쓴다 —
    번역이 없다고 오류를 삼키면 사용자는 창이 안 뜨는 이유를 알 수 없다."""
    render = _ERRORS.get(e.kind)
    return SystemExit(render(e.details) if render else str(e))


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
        raise _die(e) from e


def _resolve(path: Path) -> tuple[Path, Path]:
    """비디오 파일 또는 .analysis 디렉토리 어느 쪽을 받아도 (video, out_dir)로 푼다.

    **푸는 규약은 코어(manifest.resolve_target)에 있다.** 여기서 다시 구현하면
    같은 경로에 대해 CLI와 GUI의 판단이 갈린다 — 실제로 갈렸다. GUI는 처음부터
    디렉토리를 받았는데 CLI는 받지 못해, 사용자가 GUI에서 보던 그 경로를 CLI에
    그대로 붙여 넣으면 "아직 분석 안 됨"이라는 답이 돌아왔다."""
    try:
        video, out_dir = manifest.resolve_target(path)
    except CliError as e:
        raise _die(e) from e
    # 비디오로 지목했을 때도 형식을 대조한다 — resolve_target이 state.json을 읽는
    # 것은 디렉토리로 지목한 경우뿐이라, 이쪽을 빼면 코어가 거부하는 디렉토리를
    # 여는 우회로가 하나 남는다. 아직 분석하지 않았으면 state.json이 없어 그대로 통과한다.
    _state(out_dir)
    return video, out_dir


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
