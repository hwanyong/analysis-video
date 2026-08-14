"""데모 자산의 공통 표기 — 화면 크기·팔레트·글꼴.

영상(make_demo_video.py)과 산출물 예시 그림(make_context_figure.py)이 같은 색과
같은 글꼴을 쓰게 하려고 한 군데 모았다. 두 스크립트가 각자 색을 적어 두면 한쪽만
고쳤을 때 같은 문서에 실린 두 그림의 계열이 갈린다.

**글꼴은 Pillow가 안고 다니는 Aileron 하나만 쓴다**(`ImageFont.load_default(size=)`).
시스템 글꼴(macOS의 SF, 리눅스의 DejaVu …)을 쓰면 만드는 사람의 기계마다 글자
모양·너비가 달라져 "같은 스크립트 → 같은 그림"이 깨지고, 저장소에 글꼴 파일을
넣으면 그 파일의 라이선스를 따로 져야 한다. 대신 이 글꼴에는 한글 글리프가 없어
데모 영상의 슬라이드와 자막은 영어로 적는다.
"""
from functools import cache

from PIL import ImageFont

# 데모 영상의 화면 크기. 720p인 이유는 두 가지다 — 추출된 프레임을 그대로 문서에
# 실어도 읽히고, 정지 화면 위주라 이 해상도에서도 파일이 수백 KB에 머문다.
WIDTH, HEIGHT = 1280, 720

# 밝은 계열로 고정한다. 검출기의 내용량 게이트(overlay.content_area)는 배경
# 중앙값에서 떨어진 픽셀의 **면적**을 보므로 밝기 자체가 조건은 아니지만,
# 문서에 실릴 그림이라 인쇄·라이트 테마에서 그대로 읽히는 쪽이 낫다.
BG = (250, 250, 248)        # 종이색 배경
PANEL = (240, 241, 237)     # 본문 안의 얕은 패널
INK = (28, 34, 46)          # 본문 글자
MUTED = (108, 116, 130)     # 보조 설명
ACCENT = (15, 110, 110)     # 제목 밑줄·강조 (청록)
WARM = (176, 84, 20)        # 두 번째 강조 (주황)
RULE = (214, 217, 211)      # 얇은 구분선


@cache
def font(size: int) -> ImageFont.FreeTypeFont:
    """Pillow 내장 글꼴을 지정 크기로.

    `load_default(size=...)`는 Pillow 10.1 부터다. 그 아래에서는 크기 인자를 받지
    않는 비트맵 글꼴이 돌아오는데, 조용히 그걸 쓰면 글자만 개미만 하게 나온 그림이
    산출물로 남는다. 폴백하지 않고 멈춘다.
    """
    try:
        return ImageFont.load_default(size=size)
    except TypeError as exc:  # pragma: no cover - 옛 Pillow에서만
        raise SystemExit(
            "Pillow 10.1 이상이 필요합니다 (ImageFont.load_default(size=...)). "
            "`uv sync` 로 워크스페이스 환경을 맞춰 주세요."
        ) from exc


def text(draw, xy, s: str, size: int, fill=INK, anchor: str = "la") -> None:
    """글자 한 줄. anchor는 Pillow 표기 그대로다 (la=왼쪽 위, ls=왼쪽 baseline).

    ASCII 밖의 글자는 **그리지 않고 멈춘다.** Aileron 에 없는 글리프는 예외 없이
    빈 네모(두부)로 그려지는데, 그림은 정상적으로 만들어지고 산출물이 된 뒤에야
    눈으로 발견된다 — 실제로 푸터의 em dash(—)가 그렇게 한 번 실려 나갔다.
    """
    bad = [c for c in s if not c.isascii()]
    if bad:
        raise ValueError(
            f"내장 글꼴에 없는 글자라 빈 네모로 그려집니다: {bad!r} (문장: {s!r}). "
            "ASCII 로 바꿔 주세요 — em dash 는 '-', 가운뎃점은 '/' 등."
        )
    draw.text(xy, s, font=font(size), fill=fill, anchor=anchor)


def text_width(s: str, size: int) -> float:
    """그려질 너비 — 판서 슬라이드의 커서 위치와 그림의 연결선이 이 값을 쓴다."""
    return font(size).getlength(s)
