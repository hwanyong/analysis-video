"""출처 해석(origin.resolve) — 원본 URL을 어디서 읽고, 무엇을 URL로 인정하는가.

이 함수의 반환값은 GUI가 **브라우저로 여는 데** 쓴다. 그래서 여기서 지키는 성질은
"URL을 잘 찾는다"보다 두 가지가 먼저다:

- **아무 문자열이나 URL로 인정하지 않는다.** 컨테이너의 comment 칸에는 제작 메모가
  들어오고, `file://`·`javascript:`·`data:`는 스킴만 붙이면 그대로 실행 경로를 탄다.
- **어떤 입력에도 예외를 던지지 않는다.** 깨진 info.json·영상이 아닌 파일 앞에서
  예외가 나면 URL 한 줄이 아니라 허브 창 전체가 뜨지 않는다.

컨테이너 픽스처는 **PyAV만으로** 만든다. ffmpeg 실행파일에 기대지 않는 것은
test_split._make_video_with_subtitles와 같은 이유다(코어 CI는 ubuntu·macOS·
Windows 셋에서 도는데 ffmpeg 실행파일이 있는 건 ubuntu뿐이다). 컨테이너 레벨
메타데이터는 출력 컨테이너의 `metadata`에 쓰면 그대로 실린다 — 실측으로 mkv는
키를 대문자로(`comment` → `COMMENT`), mp4는 소문자로 저장하고 mp4 먹서는
PURL·WWW를 아예 버린다. 그래서 픽스처는 mkv로 만들고, 그 대소문자 차이가
_url_from_container의 소문자 대조를 정당화한다.
"""
import json
from pathlib import Path

import av
import numpy as np
import pytest

from analysis_video import origin

WEBPAGE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
ORIGINAL = "https://youtu.be/dQw4w9WgXcQ"
DIRECT = "https://rr3---sn-abc.googlevideo.com/videoplayback?expire=1"


def _make_video(path: Path, metadata: dict[str, str] | None = None) -> None:
    """메타데이터를 심은 짧은 mkv. 프레임 3장이면 컨테이너로 성립한다 —
    이 테스트가 보는 것은 화소가 아니라 헤더의 태그다."""
    with av.open(str(path), "w") as out:
        out.metadata.update(metadata or {})
        stream = out.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 36, "yuv420p"
        for i in range(3):
            frame = av.VideoFrame.from_ndarray(
                np.zeros((36, 64, 3), dtype=np.uint8), format="rgb24")
            frame.pts = i
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


def _write_info(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def video(tmp_path) -> Path:
    """URL을 아무 데도 담지 않은 영상 — 각 테스트가 자기 출처만 얹는다."""
    path = tmp_path / "강의.mkv"
    _make_video(path)
    return path


# ─── info.json ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", origin.INFO_JSON_KEYS)
def test_info_json_url_keys(video, key):
    """세 키를 모두 읽는다 — yt-dlp 버전·추출기에 따라 채워지는 칸이 다르다."""
    _write_info(video.with_suffix(".info.json"), {key: WEBPAGE})

    assert origin.resolve(video) == {
        "path": str(video.resolve()), "url": WEBPAGE,
        "url_from": origin.FROM_INFO_JSON}


def test_info_json_key_priority(video):
    """webpage_url > original_url > url. 마지막 url에는 만료되는 미디어 직링크가
    들어오므로, 사람이 보던 페이지가 있으면 그것이 이겨야 한다."""
    _write_info(video.with_suffix(".info.json"),
                {"url": DIRECT, "original_url": ORIGINAL, "webpage_url": WEBPAGE})

    assert origin.resolve(video)["url"] == WEBPAGE

    _write_info(video.with_suffix(".info.json"), {"url": DIRECT, "original_url": ORIGINAL})

    assert origin.resolve(video)["url"] == ORIGINAL


def test_info_json_beside_full_filename(video):
    """`강의.mkv.info.json`(전체 파일명 형태)도 받는다 — 자막 사이드카와 같은 어간 규칙."""
    _write_info(video.parent / (video.name + ".info.json"), {"webpage_url": WEBPAGE})

    assert origin.resolve(video)["url"] == WEBPAGE


def test_full_filename_form_wins_over_stem_form(video):
    """둘이 함께 있으면 전체 파일명 쪽이다. `강의.info.json`은 옆에 있는
    `강의.mp4`의 것일 수도 있지만 `강의.mkv.info.json`은 이 파일 하나를 지목한다."""
    _write_info(video.with_suffix(".info.json"), {"webpage_url": ORIGINAL})
    _write_info(video.parent / (video.name + ".info.json"), {"webpage_url": WEBPAGE})

    assert origin.resolve(video)["url"] == WEBPAGE


def test_broken_info_json_falls_back_to_no_url(video):
    """깨진 JSON은 예외가 아니라 'URL 없음'이다 — 창을 그리는 중에 불린다."""
    video.with_suffix(".info.json").write_text("{ 이건 JSON이 아니다", encoding="utf-8")

    assert origin.resolve(video) == {
        "path": str(video.resolve()), "url": None, "url_from": None}


def test_info_json_that_is_not_an_object(video):
    """최상위가 배열인 파일은 yt-dlp의 것이 아니다 — .get을 부르면 죽는다."""
    video.with_suffix(".info.json").write_text("[1, 2, 3]", encoding="utf-8")

    assert origin.resolve(video)["url"] is None


def test_info_json_with_non_string_url(video):
    """URL 칸에 숫자·null이 들어와도 문자열 취급하지 않는다."""
    _write_info(video.with_suffix(".info.json"), {"webpage_url": None, "url": 42})

    assert origin.resolve(video)["url"] is None


def test_unreadable_info_json_is_skipped(video):
    """디렉터리가 그 이름을 차지한 경우(읽기 실패) — OSError를 밖으로 내지 않는다."""
    (video.parent / (video.stem + ".info.json")).mkdir()
    _write_info(video.parent / (video.name + ".info.json"), {"webpage_url": WEBPAGE})

    assert origin.resolve(video)["url"] == WEBPAGE


# ─── 컨테이너 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", origin.CONTAINER_KEYS)
def test_container_metadata_keys(tmp_path, key):
    """PURL·comment·WWW 셋 다 읽는다. 대소문자는 먹서가 바꾸므로 대조는 소문자로."""
    path = tmp_path / "강의.mkv"
    _make_video(path, {key: WEBPAGE})

    assert origin.resolve(path) == {
        "path": str(path.resolve()), "url": WEBPAGE,
        "url_from": origin.FROM_CONTAINER}


def test_container_key_priority(tmp_path):
    """PURL > comment. PURL은 yt-dlp 전용 키라 뜻이 하나뿐이고, comment는
    아무 글이나 들어오는 자유 문장 칸이다."""
    path = tmp_path / "강의.mkv"
    _make_video(path, {"PURL": WEBPAGE, "comment": ORIGINAL})

    assert origin.resolve(path)["url"] == WEBPAGE


def test_comment_that_is_not_a_url(tmp_path):
    """comment에는 제작 메모가 들어온다 — URL처럼 생긴 값만 인정한다."""
    path = tmp_path / "강의.mkv"
    _make_video(path, {"comment": "2026 봄학기 3주차 녹화본"})

    assert origin.resolve(path)["url"] is None


def test_comment_with_url_inside_a_sentence(tmp_path):
    """문장 안에 URL이 섞인 것은 URL이 아니다. 통째로 넘기면 뒷말까지 주소에
    실려 브라우저가 엉뚱한 곳을 연다."""
    path = tmp_path / "강의.mkv"
    _make_video(path, {"comment": f"받은 곳: {WEBPAGE} 참고"})

    assert origin.resolve(path)["url"] is None


def test_no_url_anywhere(video):
    """둘 다 없으면 경로만 남는다 — 지어내지 않는다."""
    assert origin.resolve(video) == {
        "path": str(video.resolve()), "url": None, "url_from": None}


def test_info_json_wins_and_container_is_never_opened(video, monkeypatch):
    """info.json에서 찾으면 컨테이너를 열지 않는다 — 디먹서를 돌리는 비용이
    사이드카 하나를 읽는 것과 다르고, 이 함수는 창을 그리는 도중에 불린다."""
    _make_video(video, {"PURL": ORIGINAL})     # 컨테이너에도 URL이 있다
    _write_info(video.with_suffix(".info.json"), {"webpage_url": WEBPAGE})

    def boom(*args, **kwargs):
        raise AssertionError("info.json에서 찾았는데 컨테이너를 열었다")

    monkeypatch.setattr(av, "open", boom)

    assert origin.resolve(video)["url"] == WEBPAGE


# ─── 위험한 값 ────────────────────────────────────────────────────────────
DANGEROUS = [
    "file:///etc/passwd",                       # 로컬 파일이 브라우저에 열린다
    "javascript:alert(document.cookie)",         # 스크립트가 그대로 실행 경로를 탄다
    "data:text/html,<script>alert(1)</script>",  # 인라인 문서 주입
    "vbscript:msgbox(1)",
    "ftp://example.com/x",                      # 스킴 화이트리스트에 없다
    "www.example.com/watch",                    # 스킴이 없다 — 붙여 주지 않는다
    "http://",                                  # 여는 곳(호스트)이 없다
    "https:///path",
    "그냥 글자",
    "",
    "   ",
]


@pytest.mark.parametrize("value", DANGEROUS)
def test_dangerous_or_malformed_values_are_rejected(tmp_path, value):
    """info.json과 컨테이너 **양쪽**에서 같은 잣대로 걸러야 한다 — 한쪽만 막으면
    다른 쪽이 그대로 통로가 된다."""
    path = tmp_path / "강의.mkv"
    _make_video(path, {"comment": value})
    _write_info(path.with_suffix(".info.json"), {"webpage_url": value})

    assert origin.resolve(path) == {
        "path": str(path.resolve()), "url": None, "url_from": None}


def test_scheme_case_does_not_matter(tmp_path):
    """스킴 대소문자로 검사를 피해 갈 수 없고, 정상 URL이 대문자라고 버려지지도 않는다."""
    path = tmp_path / "강의.mkv"
    _write_info(path.with_suffix(".info.json"), {"webpage_url": "HTTPS://EXAMPLE.COM/a"})
    _make_video(path)

    assert origin.resolve(path)["url"] == "HTTPS://EXAMPLE.COM/a"

    _write_info(path.with_suffix(".info.json"), {"webpage_url": "JavaScript:alert(1)"})

    assert origin.resolve(path)["url"] is None


def test_surrounding_whitespace_is_trimmed(tmp_path):
    """앞뒤 공백·줄바꿈은 값의 일부가 아니다(info.json을 손으로 고친 경우)."""
    path = tmp_path / "강의.mkv"
    _make_video(path)
    _write_info(path.with_suffix(".info.json"), {"webpage_url": f"  {WEBPAGE}\n"})

    assert origin.resolve(path)["url"] == WEBPAGE


# ─── 죽지 않는다 ──────────────────────────────────────────────────────────
def test_non_media_file_does_not_raise(tmp_path):
    """영상이 아닌 파일 — 성한 영상인지 판정하는 것은 이 모듈의 일이 아니다."""
    path = tmp_path / "깨진.mkv"
    path.write_bytes(b"not a container")

    assert origin.resolve(path) == {
        "path": str(path.resolve()), "url": None, "url_from": None}


def test_missing_file_still_reports_a_path(tmp_path):
    """파일이 없어도 경로는 항상 채운다 — GUI는 그 경로를 보여 주고 Finder로 연다."""
    path = tmp_path / "없는영상.mkv"

    result = origin.resolve(path)

    assert Path(result["path"]).is_absolute()
    assert Path(result["path"]).name == path.name
    assert (result["url"], result["url_from"]) == (None, None)


def test_relative_path_becomes_absolute(video, monkeypatch):
    """상대경로로 물어도 절대경로로 답한다 — manifest가 state.json·metadata.json에
    적는 경로(resolve)와 같은 규칙이어야 소비자가 둘을 나란히 놓을 수 있다."""
    monkeypatch.chdir(video.parent)

    result = origin.resolve(Path(video.name))

    assert Path(result["path"]).is_absolute()
    assert result["path"] == str(video.resolve())
