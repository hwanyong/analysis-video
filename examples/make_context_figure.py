"""산출물 예시 그림 — context.md 한 조각과 그것이 가리키는 프레임을 나란히 놓는다.

**왜 필요한가.** 이 도구의 산출물은 마크다운 파일 하나(context.md)인데, 글로만
설명하면 "그래서 무엇이 나오나"가 끝까지 손에 잡히지 않는다. 마크다운 원문과 그
원문의 `![](...)` 가 실제로 가리키는 이미지를 한 화면에 두면 그 한 장으로 끝난다.

**입력은 실제 분석 결과다.** 그림에 적히는 문장·경로·시각은 전부 analyze 가 만든
context.md 에서 그대로 읽어 온다 — 손으로 옮겨 적으면 도구가 바뀌었을 때 그림만
옛말을 하게 된다. 보여 줄 항목은 **이미지가 두 장 붙은 화면**을 고른다: 한 화면에서
첫 등장과 완성 상태를 함께 남기는 것이 이 도구의 핵심이고, 그림의 주제도 그것이다.

**한계 하나.** context.md 의 머리말(읽는 법 안내)은 한국어인데 Pillow 내장 글꼴에는
한글 글리프가 없어 그릴 수 없다(demo_style 참조). 그래서 이 그림은 **한 화면 항목만**
발췌한다 — 그 부분은 시각·경로·대사뿐이라 원문 그대로 실린다.

사용:
    uv run python examples/make_demo_video.py
    uv run analysis-video analyze docs/media/demo-pipeline.mp4
    uv run python examples/make_context_figure.py
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw

from demo_style import (ACCENT, BG, INK, MUTED, PANEL, RULE, WARM, text,
                        text_width)

W = 1440                        # 높이는 내용에 맞춰 계산한다 (build 참조)
PANEL_L, PANEL_R = 48, 680      # 왼쪽(마크다운 원문) 패널
SHOT_X, SHOT_W = 800, 600       # 오른쪽(이미지) 칸
TOP = 228                       # 두 칸이 함께 시작하는 높이
CAP_H = 48                      # 이미지 아래 설명 한 줄이 차지하는 높이
SHOT_GAP = 26


def sections(md: str) -> list[list[str]]:
    """context.md 를 '## ' 항목 단위로 자른다. 머리말은 버린다."""
    out: list[list[str]] = []
    for line in md.splitlines():
        if line.startswith("## "):
            out.append([line])
        elif out:
            out[-1].append(line)
    return [[ln for ln in sec if ln.strip()] for sec in out]


def pick(secs: list[list[str]]) -> list[str]:
    """이미지가 둘 이상 붙은 첫 항목. 없으면 첫 항목.

    없을 수도 있다는 것을 예외로 만들지 않는 이유: 이 스크립트는 분석 결과를 그리는
    도구이지 결과를 검사하는 도구가 아니다. 두 장짜리 화면이 없으면 그 사실이
    그림에 그대로 드러나는 편이 낫다(만든 사람이 바로 알아본다)."""
    for sec in secs:
        if sum(ln.startswith("![](") for ln in sec) >= 2:
            return sec
    return secs[0]


def wrap(s: str, size: int, width: float) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        trial = f"{cur} {word}".strip()
        if cur and text_width(trial, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur] if cur else lines


def arrow(draw: ImageDraw.ImageDraw, x0: float, y0: float, gutter: float,
          x1: float, y1: float) -> None:
    """원문의 한 줄에서 그 줄이 가리키는 이미지까지. 사선이 아니라 꺾어서 간다 —
    사선은 두 칸의 글줄을 가로질러 읽기를 방해한다. 세로로 내려가는 자리(gutter)를
    화살표마다 다르게 받는 이유는 겹침 방지다: 아래 이미지로 가는 화살표가 위
    화살표의 세로줄을 타고 넘으면 어느 줄이 어느 그림으로 가는지 알 수 없다."""
    draw.line([(x0, y0), (gutter, y0), (gutter, y1), (x1 - 12, y1)], fill=ACCENT,
              width=3)
    draw.polygon([(x1, y1), (x1 - 14, y1 - 8), (x1 - 14, y1 + 8)], fill=ACCENT)


def build(run_dir: Path) -> Image.Image:
    md = (run_dir / "context.md").read_text(encoding="utf-8")
    section = pick(sections(md))
    heading = section[0]
    img_lines = [ln for ln in section if ln.startswith("![](")]
    said = " ".join(ln for ln in section[1:] if not ln.startswith("![]("))

    # 캔버스 높이는 두 칸 중 긴 쪽에 맞춘다. 상수로 박아 두면 대사 길이나 이미지
    # 장수가 조금만 달라져도 아래 캡션과 그림이 겹친 채로 저장된다(실제로 겪었다).
    shots = []
    for line in img_lines:
        shot = Image.open(run_dir / line[len("![]("):-1])
        shots.append(shot.resize((SHOT_W, round(SHOT_W * shot.height / shot.width)),
                                 Image.LANCZOS))
    body = wrap(said, 22, PANEL_R - PANEL_L - 64)
    panel_bottom = TOP + 28 + 34 + 54 + 42 * len(img_lines) + 14 + 34 * len(body) + 34
    right_bottom = TOP + sum(s.height + CAP_H for s in shots) + SHOT_GAP * (len(shots) - 1)
    H = int(max(panel_bottom + 96, right_bottom)) + 100

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    text(draw, (48, 44), "context.md - what the agent reads", 44, INK)
    draw.rectangle((48, 104, 144, 108), fill=ACCENT)
    text(draw, (48, 132),
         "one section per screen: how long it was up, its images, and what was said",
         26, MUTED)

    # ── 오른쪽: 실제 이미지 (먼저 배치해 화살표의 도착점을 확정한다) ──────────
    text(draw, (SHOT_X, 196), "the frames those two lines point to", 22, MUTED)
    labels = ["the screen when it appeared", "the same screen, finished"]
    centers: list[float] = []
    y = TOP
    for i, shot in enumerate(shots):
        img.paste(shot, (SHOT_X, int(y)))
        draw.rectangle((SHOT_X, y, SHOT_X + SHOT_W, y + shot.height), outline=RULE,
                       width=1)
        centers.append(y + shot.height / 2)
        draw.rectangle((SHOT_X, y + shot.height + 20, SHOT_X + 12,
                        y + shot.height + 32), fill=WARM if i == 0 else ACCENT)
        text(draw, (SHOT_X + 26, y + shot.height + 14),
             labels[i] if i < len(labels) else img_lines[i], 24, INK)
        y += shot.height + CAP_H + SHOT_GAP

    # ── 왼쪽: 마크다운 원문 그대로 ────────────────────────────────────────────
    text(draw, (PANEL_L, 196), "runs/full/context.md   (one section, verbatim)",
         22, MUTED)
    draw.rectangle((PANEL_L, TOP, PANEL_R, panel_bottom), fill=PANEL)
    draw.rectangle((PANEL_L, TOP, PANEL_L + 6, panel_bottom), fill=ACCENT)

    y = TOP + 22
    text(draw, (PANEL_L + 32, y), "...", 22, MUTED)   # 발췌임을 드러낸다
    y += 34
    text(draw, (PANEL_L + 32, y), heading, 28, ACCENT)
    y += 54
    anchors: list[tuple[float, float]] = []
    for line in img_lines:
        text(draw, (PANEL_L + 32, y), line, 21, INK)
        anchors.append((PANEL_L + 32 + text_width(line, 21) + 14, y + 12))
        y += 42
    y += 14
    for line in body:
        text(draw, (PANEL_L + 32, y), line, 22, MUTED)
        y += 34
    text(draw, (PANEL_L + 32, y), "...", 22, MUTED)

    # 화살표는 아래로 갈수록 왼쪽 통로를 쓴다 — 위 화살표의 세로줄과 겹치지 않는다.
    for i, ((ax, ay), by) in enumerate(zip(anchors, centers)):
        arrow(draw, ax, ay, SHOT_X - 44 - i * 50, SHOT_X - 4, by)

    text(draw, (PANEL_L, panel_bottom + 34),
         "every number, path and sentence above is copied", 22, MUTED)
    text(draw, (PANEL_L, panel_bottom + 66),
         "straight out of the generated file", 22, MUTED)

    draw.rectangle((48, H - 76, W - 48, H - 75), fill=RULE)
    text(draw, (48, H - 56),
         "the same screen, shot twice - a cut detector alone would have kept "
         "the empty board and nothing else", 24, INK)
    return img


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path,
                    default=root / "docs/media/demo-pipeline.mp4.analysis/runs/full",
                    help="분석 단위 디렉터리 (context.md 와 read/ 가 있는 곳)")
    ap.add_argument("--out", type=Path, default=root / "docs/media/context-example.png")
    args = ap.parse_args()

    if not (args.run / "context.md").is_file():
        raise SystemExit(f"context.md 가 없습니다: {args.run}\n"
                         "먼저 `analysis-video analyze docs/media/demo-pipeline.mp4` 를 "
                         "돌려 주세요.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # optimize=True 는 압축을 한 번 더 시도한다. 이 그림은 저장소에 영구히 남으므로
    # 몇십 KB 라도 줄여 두는 편이 맞다.
    build(args.run).save(args.out, optimize=True)
    print(f"{args.out} ({args.out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
