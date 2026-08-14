"""원본 위치 — 이 분석이 무엇에서 나왔는지, 그리고 그 자리로 가는 길.

"어디인가"(원본 URL / 로컬 파일)와 "그리로 가기"(브라우저 / 파일 관리자에서
드러내기)를 한 모듈에 둔다. 둘은 같은 판정 — 웹이냐 파일이냐 — 의 표시와 실행이라
갈라 두면 규칙이 두 곳에서 따로 늙는다.

원본 URL은 산출물에 적혀 있지 않다. 적으려면 metadata.json 스키마를 올려야 하는데
이 저장소는 하위 호환을 두지 않아(옛 디렉터리는 exit 2로 거부) 이미 끝난 분석이
통째로 무효가 된다. URL은 파이프라인이 *한 일*이 아니라 영상 파일 주변의 정황이고
언제든 다시 읽어낼 수 있으므로, 기록하는 대신 볼 때마다 코어의 순수 해석기에
물어본다 — GUI가 해석을 재구현하지는 않는다.
"""
import subprocess
import sys
from pathlib import Path

from analysis_video import manifest
from analysis_video.errors import CliError
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

# 파일 관리자는 플랫폼마다 이름도 동작도 다르다. 리눅스에서 "Finder에서 보기"라고
# 적힌 버튼이 폴더만 열면 사용자는 버튼 문구를 더 이상 믿지 않는다 — 문구 키를
# reveal 구현 바로 옆에서 고른다.
REVEAL_LABEL_KEY = ("hub.loc.reveal_macos" if sys.platform == "darwin"
                    else "hub.loc.reveal_windows" if sys.platform == "win32"
                    else "hub.loc.reveal_other")


def source_files(root: Path, video_path: Path) -> tuple[Path, Path | None]:
    """이 분석의 입력 — (영상, 자막). 자막은 없을 수 있다.

    state.json이 유일한 원천이고, 읽기는 기동 경로(app.py)와 같은 통로인
    manifest.load_state를 쓴다 — GUI가 json을 직접 읽으면 코어가 거부하는 형식을
    GUI만 통과시켜, 같은 디렉터리에 대해 두 도구의 판단이 갈린다.
    분석 전이라 source 칸이 비어 있으면 GUI를 연 그 파일이 곧 원본이다.

    형식이 어긋난 state.json은 기동 시 app._state가 이미 막는다. 여기 걸리는 경우는
    세션 도중 CLI가 새 형식으로 다시 쓴 때뿐인데, 그때 허브를 죽이는 것보다 이 줄을
    접는 편이 낫다 — 산출물을 못 읽으면 조용히 다음 감시 이벤트를 기다리는
    Store._read_json과 같은 정책이다.
    """
    try:
        source = manifest.load_state(root).get("source", {})
    except (CliError, OSError):
        source = {}
    video = Path(source["path"]) if source.get("path") else video_path
    subtitle = source.get("subtitle") or {}
    return video, (Path(subtitle["path"]) if subtitle.get("path") else None)


def source_url(video_path: Path) -> str | None:
    """원본 URL — 없으면 None. 해석은 코어 몫이고 여기서는 부르기만 한다.

    코어 계약: `analysis_video.origin.resolve(Path) -> dict | None`, URL은 "url" 키
    (yt-dlp가 남긴 `<어간>.info.json`의 webpage_url, 또는 `--embed-metadata`로 받은
    컨테이너의 PURL/comment).

    지연 import이고 ImportError를 삼키지 않는다. GUI의 코어 의존은 하한만 걸려 있어
    (analysis-video>=0.1,<0.2) 해석기가 없는 코어와 조합될 수 있는데, ① 기동 자체가
    죽으면 나머지 검토 기능까지 못 쓰고 ② 여기서 None으로 뭉개면 "URL이 없다"와
    "해석기를 못 불렀다"가 같은 화면이 되어 사용자가 영상 파일을 의심하게 된다.
    둘을 갈라 보여주는 판단은 호출자(허브)의 몫이므로 예외를 그대로 올린다.

    http/https만 통과시킨다. 이 값의 유일한 쓰임은 `QDesktopServices.openUrl`인데
    그것은 스킴에 따라 임의의 핸들러를 실행하므로, 다운로더가 파일에 남긴 문자열을
    그대로 넘기지 않는다.
    """
    from analysis_video.origin import resolve

    info = resolve(video_path)
    url = info.get("url") if info else None
    return url if url and QUrl(url).scheme().lower() in ("http", "https") else None


def open_url(url: str) -> None:
    """웹 원본을 기본 브라우저로 연다."""
    QDesktopServices.openUrl(QUrl(url))


def reveal(path: Path) -> None:
    """파일 관리자에서 이 파일을 **드러낸다**(여는 것이 아니다).

    `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`를 쓰면 안 된다 — 그것은
    파일을 연결 프로그램으로 **연다**. 영상이면 플레이어가 뜨는데, 요구는 "그 파일이
    어디에 있는지 보여 달라"이다. 그래서 플랫폼별 reveal 명령을 직접 부른다.

    인자는 리스트로 넘기고 셸을 거치지 않는다 — 경로에는 공백·따옴표·`$`가 들어갈 수
    있고 shell=True면 셸이 그것을 문법으로 읽는다.
    실패해도 예외로 올리지 않는다(check=False): 파일 관리자를 못 띄운 것은 검토를
    중단시킬 일이 아니고, 사용자에게는 경로를 복사해 가는 길이 남아 있다.
    """
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(path)], check=False)
    elif sys.platform == "win32":
        # explorer는 `/select,<경로>`를 **한 인자**로 받는다(쉼표 뒤에 공백을 두면
        # 경로를 인식하지 못한다). 파일을 선택해 준 뒤 종료 코드 1을 내는 것이 정상
        # 동작이라 반환값을 보지 않는다.
        subprocess.run(["explorer", f"/select,{path}"], check=False)
    else:
        # X/Wayland에는 "파일을 선택한 채 폴더 열기"의 표준이 없다(파일 관리자마다
        # D-Bus 인터페이스가 다르다). 부모 폴더를 여는 것이 최선이고, 어떤 파일
        # 관리자를 부를지는 Qt가 데스크톱 환경별로 이미 처리한다.
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
