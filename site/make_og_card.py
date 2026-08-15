"""공유 카드 — 링크를 붙였을 때 미리보기로 뜨는 1200x630 그림.

**왜 따로 만드는가.** README 의 그림들은 1440x1126 과 1400x760 이고, 소셜 미리보기가 요구하는
1.91:1 이 아니다. 그대로 og:image 로 쓰면 잘리거나 레터박스가 생기고, 무엇보다 그 그림들에는
**패키지 이름이 적혀 있지 않다** — 미리보기 카드가 하는 일의 절반은 이름을 보여 주는 것이다.

**색은 site/style.css 에서 읽어 온다.** 여기에 색을 다시 적으면 랜딩을 다크에서 바꿨을 때
공유 카드만 옛 색으로 남는다. `:root` 의 사용자 정의 속성이 두 산출물의 단일 기준이다.

**영문 한 장으로 EN/KO 를 함께 쓴다.** 글꼴이 Pillow 내장 Aileron 하나뿐이고 거기에는 한글
글리프가 없다(examples/demo_style.py 참조). 한글 카드를 만들려면 글꼴 파일을 저장소에 넣어야
하는데, 그 라이선스를 따로 지는 것은 이 저장소가 이미 거부한 선택이다. 카드에 이름과 명령만
싣고 언어별 문구는 og:title / og:description 이 맡는다 — 그쪽은 글꼴 제약이 없다.

사용:
    uv run python site/make_og_card.py      # → docs/media/og-card.png
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent

# 글꼴 machinery 는 데모 자산과 공유한다. Pillow 버전 가드와 "내장 글꼴에 없는 글자는
# 그리지 말고 멈춘다"는 검사가 거기 들어 있고, 그 검사는 실제로 두부(빈 네모)가 산출물로
# 나가는 것을 한 번 막았다.
sys.path.insert(0, str(ROOT / "examples"))
from demo_style import font, text, text_width  # noqa: E402

WIDTH, HEIGHT = 1200, 630
PAD = 84

TAGLINE = "Turn video into AI-readable context."
COMMAND = "uvx analysis-video@latest analyze lecture.mp4"
FACTS = "No API key   /   No upload   /   No ffmpeg   /   Python 3.11-3.14   /   MIT"
REPO = "github.com/hwanyong/analysis-video"


def palette() -> dict[str, tuple[int, int, int]]:
    """style.css 의 `:root` 에서 색을 읽는다. 없는 이름이 있으면 멈춘다."""
    css = (SITE / "style.css").read_text("utf-8")
    found = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", css))
    want = ("bg", "bg-soft", "bg-code", "fg", "muted", "accent", "line")
    missing = [n for n in want if n not in found]
    if missing:
        raise SystemExit(
            f"site/style.css 의 :root 에서 색을 찾지 못했습니다: {missing}. "
            "이름을 바꿨다면 이 스크립트의 want 목록도 함께 고쳐 주세요."
        )
    return {n: tuple(int(found[n][i:i + 2], 16) for i in (1, 3, 5)) for n in want}


def build() -> Image.Image:
    c = palette()
    img = Image.new("RGB", (WIDTH, HEIGHT), c["bg"])
    d = ImageDraw.Draw(img)

    # 왼쪽 세로 막대 — 랜딩의 h1 앞에 붙는 '▌' 와 같은 표식. 그 글자는 내장 글꼴에
    # 없으므로 그리지 않고 사각형으로 놓는다.
    d.rectangle([0, 0, 12, HEIGHT], fill=c["accent"])

    y = PAD + 6
    text(d, (PAD, y), "analysis-video", 76, fill=(255, 255, 255))
    y += 104
    text(d, (PAD, y), TAGLINE, 38, fill=c["accent"])

    # 명령줄 상자. 랜딩의 .cmd 와 같은 모양이라 카드에서 페이지로 넘어와도 같은 것으로 읽힌다.
    y += 92
    box_h = 84
    d.rounded_rectangle([PAD, y, WIDTH - PAD, y + box_h], radius=10,
                        fill=c["bg-code"], outline=c["line"], width=2)
    text(d, (PAD + 28, y + box_h / 2), "$", 30, fill=c["accent"], anchor="lm")
    text(d, (PAD + 28 + text_width("$ ", 30), y + box_h / 2), COMMAND, 30,
         fill=c["fg"], anchor="lm")

    # 아래쪽: 사실 나열과 저장소 주소. 구분선을 하나 두어 위쪽 문구와 성격을 나눈다.
    y += box_h + 74
    d.line([PAD, y, WIDTH - PAD, y], fill=c["line"], width=2)
    text(d, (PAD, y + 30), FACTS, 25, fill=c["muted"])
    text(d, (WIDTH - PAD, HEIGHT - PAD + 8), REPO, 25, fill=c["muted"], anchor="rs")

    return img


def main() -> int:
    out = ROOT / "docs" / "media" / "og-card.png"
    build().save(out, "PNG", optimize=True)
    print(f"→ {out.relative_to(ROOT)}  ({out.stat().st_size:,} bytes, {WIDTH}x{HEIGHT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
