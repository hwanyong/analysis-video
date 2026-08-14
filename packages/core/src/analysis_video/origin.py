"""영상 파일 하나가 **어디서 왔는가**를 그때그때 해석한다 — 원본 웹 주소와 절대경로.

**기록하지 않고 해석한다.** 이 값을 metadata.json에 실으면 METADATA_SCHEMA를 올려야
하고, 이 저장소는 하위 호환을 두지 않으므로(manifest._require_schema) 그 순간 이미
끝난 분석 디렉터리가 전부 exit 2로 거부된다. URL은 파이프라인이 **한 일**이 아니라
영상 파일 주변에 남아 있는 정황이고, 파일이 그대로 있는 한 언제든 같은 답이 다시
나온다 — 산출물에 못 박을 이유가 없다. "코어는 다운로드하지 않는다"는 경계와도
맞는다: 받아 온 사람이 남긴 흔적을 읽을 뿐, 이 모듈은 네트워크를 건드리지 않는다.

이름을 `source`로 하지 않은 이유: 그 낱말은 이 저장소에서 이미 두 뜻으로 쓰인다
(transcript.json의 `source` = 대사가 어느 전사 출처에서 왔는가, metadata.json의
`source.file` = 원본 영상 경로). 세 번째 뜻을 얹으면 grep 한 번으로 무엇을 보는지
갈리지 않는다.

찾는 자리는 둘이고, 순서에 근거가 있다:

1. **`<어간>.info.json`** — yt-dlp `--write-info-json`이 영상 옆에 남기는 파일.
   받아 온 그 순간의 `webpage_url`이 그대로 들어 있어 가장 확실하고, 여는 비용이
   컨테이너 디먹싱보다 훨씬 싸다.
2. **컨테이너 메타데이터** — `--embed-metadata`로 받은 파일에만 있다. info.json을
   지운 뒤에도 영상 파일 안에 남아 있다는 것이 이 경로의 값어치다.

둘 다 없으면 URL은 없는 것이다. 그때는 지어내지 않고 None을 돌려준다 —
이 값은 GUI가 **브라우저로 여는** 데 쓰이므로 추측이 섞이면 안 된다.

**어떤 입력에도 예외를 던지지 않는다.** 호출자(GUI 허브 창)는 창을 그리는 도중에
이 함수를 부른다. 깨진 info.json이나 영상이 아닌 파일 앞에서 예외가 나면 URL 한 줄이
아니라 창 전체가 뜨지 않는다.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

import av

# yt-dlp `--write-info-json`의 확장자. 영상 파일명 뒤에 통째로 붙는다.
INFO_JSON_SUFFIX = ".info.json"
# info.json에서 URL을 읽는 순서. webpage_url이 사람이 보던 그 페이지이고,
# original_url은 사용자가 명령줄에 적은 주소(재생목록·단축 주소일 수 있다),
# url은 포맷에 따라 **미디어 직링크**(만료되는 CDN 주소)가 들어오는 자리라 마지막이다.
INFO_JSON_KEYS = ("webpage_url", "original_url", "url")
# 컨테이너 메타데이터에서 URL을 읽는 순서. PURL은 yt-dlp `--embed-metadata`가
# 쓰는 전용 키라 뜻이 하나뿐이고, comment는 URL이 들어오기도 하는 자유 문장 칸이며
# (실측: mp4 먹서는 PURL·WWW를 버리고 comment만 남긴다), WWW는 일부 태거의 관례다.
CONTAINER_KEYS = ("PURL", "comment", "WWW")
# 브라우저로 열어도 되는 스킴. 화이트리스트인 이유는 아래 _as_url 참조.
SAFE_SCHEMES = ("http", "https")

# url_from에 실리는 값. 문자열을 여기 한 번만 적어 둔다 — 소비자(GUI)가 어느 경로로
# 찾았는지 분기하므로, 양쪽에 리터럴을 따로 적으면 조용히 갈린다.
FROM_INFO_JSON = "info-json"
FROM_CONTAINER = "container"


def _as_url(value: object) -> str | None:
    """값 하나 → 브라우저에 넘겨도 되는 URL, 아니면 None.

    **이 함수가 이 모듈의 방어선 전부다.** 돌려준 문자열은 GUI가 그대로 브라우저로
    여는 데 쓰이므로, 검증을 무르게 하면 `file:///etc/passwd`나 `javascript:...`가
    실행 경로를 탄다. 그래서 "위험한 스킴을 뺀다"(블랙리스트)가 아니라 http·https만
    받는다 — 블랙리스트는 새 스킴이 생길 때마다 조용히 낡는다.

    호스트(netloc)까지 요구하는 이유: `http:...`는 스킴만 맞고 여는 곳이 없다.

    공백이 하나라도 섞이면 거부한다. comment는 아무 글이나 들어오는 칸이라
    "받은 곳: https://example.com/a 참고"처럼 URL이 **문장 안에** 있을 수 있는데,
    그때 urlsplit은 뒷말까지 경로에 담아 통째로 URL이라고 답한다. 문장에서 URL을
    골라내는 것은 추측이고, 여기서 필요한 판정은 "이 값 자체가 URL인가"다.
    실제로 yt-dlp가 comment에 넣는 값은 webpage_url 하나뿐이라 이 규칙에 걸리지 않는다.

    스킴이 없는 값(`www.example.com/a`)에 http를 붙여 주지도 않는다 — 여는 주소를
    이 함수가 지어내면 안 된다."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7f for ch in text):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        # urlsplit도 던진다(대괄호가 깨진 IPv6 리터럴 등). 창이 안 뜨는 것보다
        # URL이 없는 편이 낫다.
        return None
    if parts.scheme.lower() not in SAFE_SCHEMES or not parts.netloc:
        return None
    return text


def _info_json_paths(video: Path) -> list[Path]:
    """영상 옆의 info.json 후보 — **자막 사이드카와 같은 어간 해석**이다.

    yt-dlp의 기본 출력이 `영상.mkv` + `영상.info.json`이고, 도구에 따라 전체 파일명
    뒤에 붙인 `영상.mkv.info.json`도 나온다. 두 형태를 다 받는 것,
    그리고 **긴 접두사를 먼저 보는 것**까지 subtitles.sidecar_candidates와 같다:
    `영상.mkv.info.json`은 이 파일 하나를 지목하지만 `영상.info.json`은 옆에 있는
    `영상.mp4`의 것일 수도 있어, 둘이 함께 있으면 지목이 분명한 쪽이 맞다.

    같은 규칙인데 subtitles의 함수를 부르지 않는 이유: 그 함수가 돌려주는 것은
    **자막 선택 정책**이 붙은 Candidate다(언어 태그 해석·포맷 순위·forced 판정).
    출처 해석에는 그 정책이 필요 없고, 애초에 sidecar_candidates는 FORMATS에 든
    자막 확장자만 후보로 세우므로 info.json은 걸리지도 않는다. 공유하는 것은 어간
    규칙 한 줄뿐이라 그 한 줄만 같은 순서로 다시 적는다 — 함수를 끌어오면 자막
    선택 정책이 딸려 와 두 관심사가 한 곳에서 얽힌다.

    `video.parent / 이름`으로 만드는 것은 Path.with_name이 이름 없는 경로에서
    ValueError를 던지기 때문이다(이 모듈은 어떤 입력에도 예외를 내지 않는다)."""
    names = dict.fromkeys((video.name + INFO_JSON_SUFFIX,
                           video.stem + INFO_JSON_SUFFIX))
    return [video.parent / name for name in names]


def _url_from_info_json(video: Path) -> str | None:
    """info.json에서 URL을 읽는다. 없거나 깨졌으면 None."""
    for path in _info_json_paths(video):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 파일 없음·권한·깨진 JSON·UTF-8이 아닌 바이트를 한자리에서 받는다
            # (JSONDecodeError·UnicodeDecodeError는 둘 다 ValueError의 하위).
            # 어느 쪽이든 답은 같다: 이 파일에서는 URL을 못 얻는다.
            continue
        if not isinstance(data, dict):
            continue          # 최상위가 배열·숫자인 파일 — yt-dlp의 것이 아니다
        for key in INFO_JSON_KEYS:
            url = _as_url(data.get(key))
            if url is not None:
                return url
    return None


def _url_from_container(video: Path) -> str | None:
    """컨테이너 메타데이터에서 URL을 읽는다. 열 수 없는 파일이면 None.

    키를 소문자로 접어 맞추는 이유는 먹서가 표기를 바꾸기 때문이다 — 실측으로
    같은 `comment`가 mkv에서는 `COMMENT`로, mp4에서는 `comment`로 저장된다.
    적은 대로 찾으면 컨테이너 종류에 따라 있는 값을 못 본다."""
    try:
        with av.open(str(video)) as container:
            meta = dict(container.metadata or {})
    except (OSError, ValueError, av.FFmpegError):
        # 파일 없음(OSError)·미디어가 아님(InvalidDataError)·디먹서 실패를 모두
        # '출처를 알 수 없음'으로 떨어뜨린다. 영상이 성한지 판정하는 것은 이
        # 모듈의 일이 아니다 — 파이프라인 스테이지가 제 자리에서 제대로 죽는다.
        return None
    lowered = {str(key).lower(): value for key, value in meta.items()}
    for key in CONTAINER_KEYS:
        url = _as_url(lowered.get(key.lower()))
        if url is not None:
            return url
    return None


def _absolute(video: Path) -> str:
    """표시용 절대경로 — **manifest와 같은 규칙(resolve)으로 만든다.**

    manifest는 state.json의 `source.path`와 metadata.json의 `source.file`을 전부
    `video_path.resolve()`로 적는다. 소비자는 이 함수가 낸 경로와 그 기록을 나란히
    놓게 되므로(둘 다 "그 영상 파일"을 가리킨다), 여기만 규칙이 다르면 심링크로
    가리킨 영상에서 두 값이 서로 다른 문자열로 갈린다. 분석 디렉터리 **위치**를
    정할 때 resolve를 금지한 것(cli.resolve_out)은 이것과 다른 문제다 — 그쪽은
    사용자가 준 경로 옆에 결과가 남아야 이어하기가 성립한다는 이야기다.

    resolve()는 링크를 따라가며 파일시스템을 만지므로 끊긴 네트워크 마운트에서
    OSError가 난다. 경로 한 줄 때문에 창이 안 뜨는 일은 없어야 해서, 그때는
    파일시스템을 건드리지 않는 absolute()로 내려간다."""
    try:
        return str(video.resolve())
    except OSError:
        return str(video.absolute())


def resolve(video: Path) -> dict:
    """영상 파일 하나 → 그것이 어디서 왔는가.

        {"path": str,             # 영상 절대경로. 파일이 없어도 항상 채운다
         "url": str | None,       # 원본 웹 주소. 못 찾으면 None
         "url_from": str | None}  # FROM_INFO_JSON | FROM_CONTAINER | None

    info.json에서 찾으면 컨테이너는 **열지 않는다**. 컨테이너를 여는 것은 디먹서를
    돌리는 일이라 사이드카 하나를 읽는 것과 비용이 다르고, 이 함수는 GUI가 창을
    그리는 도중에 불린다."""
    url = _url_from_info_json(video)
    if url is not None:
        return {"path": _absolute(video), "url": url, "url_from": FROM_INFO_JSON}
    url = _url_from_container(video)
    return {"path": _absolute(video), "url": url,
            "url_from": FROM_CONTAINER if url is not None else None}
