"""analysis-video-gui 엔트리 — `analysis-video-gui <video 또는 .analysis 디렉토리>`."""
import argparse
import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def _resolve(path: Path) -> tuple[Path, Path]:
    """비디오 파일 또는 .analysis 디렉토리 어느 쪽을 받아도 (video, out_dir)로 푼다."""
    if path.is_dir():
        out_dir = path
        state = out_dir / "state.json"
        if not state.exists():
            raise SystemExit(f"오류: {out_dir}에 state.json이 없습니다 — "
                             "analysis-video로 먼저 분석하세요")
        src = json.loads(state.read_text(encoding="utf-8")).get("source", {}).get("path")
        video = Path(src) if src else None
        if video is None or not video.exists():
            raise SystemExit(f"오류: state.json의 원본 비디오를 찾을 수 없습니다: {src}")
        return video, out_dir
    if not path.exists():
        raise SystemExit(f"오류: 파일이 없습니다: {path}")
    return path, path.parent / f"{path.name}.analysis"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="analysis-video-gui",
        description="analysis-video 산출물 검토·교정 GUI (허브 + 독립 멀티 윈도우)")
    parser.add_argument("path", type=Path, help="원본 비디오 파일 또는 .analysis 디렉토리")
    args = parser.parse_args(argv)

    video, out_dir = _resolve(args.path)
    if not (out_dir / "metadata.json").exists():
        print(f"경고: {out_dir}/metadata.json 없음 — 플레이어만 유효합니다 "
              "(frames 스테이지를 먼저 실행하세요)", file=sys.stderr)

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setApplicationName("analysis-video-gui")

    from .session import Session
    from .windows.hub import HubWindow

    session = Session(video, out_dir)
    hub = HubWindow(session)
    hub.show()
    session.restore_layout()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
