"""문서용 다이어그램 — 루프와 파이프라인을 SVG 로 그린다.

**왜 SVG 인가.** 이 그림들은 README(GitHub)와 랜딩(브라우저) 양쪽에 실린다.
- PNG(Pillow)로는 **한국어판을 만들 수 없다.** 내장 글꼴 Aileron 에 한글 글리프가 없고,
  글꼴 파일을 저장소에 넣으면 그 라이선스를 따로 져야 한다(examples/demo_style.py 참조).
  SVG 의 글자는 **보는 쪽의 글꼴**로 그려지므로 이 문제가 통째로 사라진다.
- 확대해도 깨지지 않고, 파일이 수 KB 이며, 글자가 진짜 글자라 선택·검색·스크린리더가 된다.

**레이아웃은 글자 폭에 의존하지 않는다.** 생성기에 글꼴 엔진이 없어 문자열의 실제 폭을 잴 수
없다. 그래서 모든 글자는 고정 좌표에 **가운데/끝 정렬**로 놓고, 상자 크기는 미리 정한 값을
쓴다 — 폭을 재야만 맞는 배치(글자에 딱 맞는 테두리 등)는 만들지 않는다.

**스타일 블록 대신 표현 속성을 쓴다.** GitHub 은 README 안의 SVG 를 정화해 내보내는데,
`<style>` 안의 규칙이 항상 살아남는다는 보장이 없다. fill·font-size 를 요소에 직접 달면
정화기를 타도 그대로 그려진다.

색은 site/style.css 의 :root 에서 읽는다 — 랜딩 테마를 바꾸면 그림도 따라온다.
그림이 스스로 어두운 패널을 그리므로 GitHub 라이트 테마에서도 터미널 스크린샷처럼 읽힌다.

사용:
    python3 site/make_diagrams.py      # → docs/media/{loop,pipeline}-{en,ko}.svg
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
OUT = ROOT / "docs" / "media"

MONO = ("ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', "
        "'Apple SD Gothic Neo', 'Malgun Gothic', monospace")
SANS = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif")


def palette() -> dict[str, str]:
    css = (SITE / "style.css").read_text("utf-8")
    found = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", css))
    want = ("bg", "bg-soft", "bg-code", "fg", "muted", "accent", "warm", "line")
    missing = [n for n in want if n not in found]
    if missing:
        raise SystemExit(f"site/style.css 의 :root 에서 색을 찾지 못했습니다: {missing}")
    return {n: found[n] for n in want}


class Svg:
    """좌표 기반 SVG 조립기 — 글자 폭을 재지 않는 것만 제공한다."""

    def __init__(self, w: int, h: int, title: str, desc: str, c: dict[str, str]):
        self.w, self.h, self.c = w, h, c
        self.parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" '
            f'aria-labelledby="t d" font-family="{escape(SANS)}">',
            f'<title id="t">{escape(title)}</title>',
            f'<desc id="d">{escape(desc)}</desc>',
            f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" '
            f'fill="{c["bg"]}" stroke="{c["line"]}"/>',
        ]

    def text(self, x, y, s, size=14, fill=None, anchor="middle", mono=False,
             weight="normal", style="normal"):
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill or self.c["fg"]}" '
            f'text-anchor="{anchor}" font-family="{escape(MONO if mono else SANS)}" '
            f'font-weight="{weight}" font-style="{style}">{escape(s)}</text>')

    def box(self, x, y, w, h, fill=None, stroke=None, rx=8, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill or self.c["bg-soft"]}" stroke="{stroke or self.c["line"]}"{d}/>')

    def line(self, x1, y1, x2, y2, stroke=None, dash=None, width=1):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke or self.c["line"]}" stroke-width="{width}"{d}/>')

    def arrow(self, x1, y, x2, stroke=None):
        """수평 화살표. 머리는 path 로 그린다 — marker 는 정화기에 걸릴 수 있다."""
        s = stroke or self.c["accent"]
        sign = 1 if x2 > x1 else -1
        tip = x2 - sign * 1
        self.parts.append(
            f'<line x1="{x1}" y1="{y}" x2="{tip - sign * 7}" y2="{y}" '
            f'stroke="{s}" stroke-width="1.6"/>')
        self.parts.append(
            f'<path d="M {tip} {y} L {tip - sign * 9} {y - 4.5} '
            f'L {tip - sign * 9} {y + 4.5} Z" fill="{s}"/>')

    def render(self) -> str:
        return "\n".join(self.parts) + "\n</svg>\n"


# ── 루프 다이어그램 ────────────────────────────────────────────────────────

LOOP = {
    "en": {
        "title": "The loop your AI agent runs with analysis-video",
        "desc": ("Three lanes: you, your AI agent, and analysis-video. You ask a question; "
                 "the agent runs analyze, receives context.md plus a next object carrying "
                 "the image cost, reads and writes the analysis itself, then stores it with "
                 "review. The tool never calls a model."),
        "lanes": ("YOU", "YOUR AGENT", "analysis-video"),
        "ask": "“summarise lecture.mp4 — include the slides”",
        "run": "analysis-video analyze lecture.mp4",
        "work": ("split", "transcribe", "detect screens"),
        "back": "context.md",
        "back_sub": "next: do=read · 6 images · 2,652 tokens",
        "think": ("reads", "thinks", "writes"),
        "think_cap": "the only step that needs a model — the tool has none",
        "store": "analysis-video review … --write -",
        "stored": "reviews/full.md · next: do=done",
        "answer": ("an answer that cites the screen —", "and a file that outlives the session"),
        "legend": "no LLM call anywhere inside the tool · nothing leaves your machine",
    },
    "ko": {
        "title": "analysis-video 를 쓰는 AI 에이전트의 루프",
        "desc": ("세 갈래: 당신, AI 에이전트, analysis-video. 당신이 묻고, 에이전트가 analyze 를 "
                 "실행하고, context.md 와 이미지 비용이 담긴 next 객체를 받고, 스스로 읽고 분석을 "
                 "쓴 뒤 review 로 저장한다. 도구는 모델을 호출하지 않는다."),
        "lanes": ("당신", "AI 에이전트", "analysis-video"),
        "ask": "“lecture.mp4 요약해줘 — 슬라이드에 있던 것도”",
        "run": "analysis-video analyze lecture.mp4",
        "work": ("split", "transcribe", "화면 변화 검출"),
        "back": "context.md",
        "back_sub": "next: do=read · 이미지 6장 · 2,652 토큰",
        "think": ("읽고", "판단하고", "쓴다"),
        "think_cap": "모델이 필요한 유일한 단계 — 도구 안에는 모델이 없다",
        "store": "analysis-video review … --write -",
        "stored": "reviews/full.md · next: do=done",
        "answer": ("화면을 근거로 든 답변 —", "그리고 세션보다 오래 남는 파일"),
        "legend": "파이프라인 어디에도 LLM 호출이 없다 · 기기 밖으로 나가는 것이 없다",
    },
}

W, H = 900, 638
LX = (128, 450, 772)          # 세 갈래의 x
BOX_W, BOX_H = 196, 40


def loop_svg(t: dict, c: dict[str, str]) -> str:
    s = Svg(W, H, t["title"], t["desc"], c)

    # 갈래 머리
    for x, name, is_tool in zip(LX, t["lanes"], (False, False, True)):
        s.box(x - BOX_W // 2, 24, BOX_W, BOX_H, fill=c["bg-code"])
        s.text(x, 49, name, 15, c["accent"] if is_tool else c["fg"], mono=is_tool,
               weight="600")
        s.line(x, 64, x, H - 52, dash="3 5")

    def step(y, a, b, label, sub=None, mono=False):
        """라벨(문자열 또는 여러 줄) → 화살표 → 부제.

        시작·끝 x 는 진행 방향을 따른다. 방향과 무관하게 +offset 을 더하면 왼쪽으로
        가는 화살표가 출발선 오른쪽에서 시작해 갈고리처럼 보인다.
        """
        mid = (LX[a] + LX[b]) / 2
        lines = (label,) if isinstance(label, str) else label
        for i, ln in enumerate(lines):
            s.text(mid, y - 12 - (len(lines) - 1 - i) * 17, ln, 13, c["fg"], mono=mono)
        if sub:
            s.text(mid, y + 22, sub, 12, c["muted"], mono=True)
        d = 1 if b > a else -1
        s.arrow(LX[a] + 16 * d, y, LX[b] - 16 * d)

    # ① 묻는다
    step(104, 0, 1, t["ask"])
    # ② 실행
    step(160, 1, 2, t["run"], mono=True)

    # ③ 도구가 하는 일
    s.box(LX[2] - 104, 186, 208, 76, fill=c["bg-code"])
    for i, w in enumerate(t["work"]):
        s.text(LX[2], 208 + i * 20, w, 13, c["muted"], mono=True)

    # ④ 돌려준다
    step(302, 2, 1, t["back"], t["back_sub"], mono=True)

    # ⑤ 모델이 필요한 단 한 단계
    s.box(LX[1] - 118, 348, 236, 92, fill=c["bg-soft"], stroke=c["accent"])
    for i, w in enumerate(t["think"]):
        s.text(LX[1], 374 + i * 24, w, 16, c["accent"], mono=True, weight="600")
        s.text(LX[1], 462, t["think_cap"], 12.5, c["muted"], style="italic")

    # ⑥ 저장
    step(506, 1, 2, t["store"], mono=True)
    # ⑦ 저장 확인
    step(552, 2, 1, t["stored"], mono=True)
    # ⑧ 답변 — 두 줄이다. 한 줄로 두면 YOU 갈래 왼쪽으로 넘쳐 패널 밖에 걸린다.
    step(600, 1, 0, t["answer"])

    s.line(28, H - 40, W - 28, H - 40)
    s.text(W / 2, H - 18, t["legend"], 12, c["muted"])
    return s.render()


# ── 파이프라인 다이어그램 ──────────────────────────────────────────────────

PIPE = {
    "en": {
        "title": "The analysis-video pipeline: split, transcribe, frames, context.md, review",
        "desc": ("Five stages in order. split writes a video resource and demuxes subtitle "
                 "tracks; transcribe prefers subtitles and falls back to Whisper; frames "
                 "detects screen changes and extracts them; context.md aligns screens with "
                 "time and dialogue; review is where the agent's analysis is kept."),
        "stages": [
            ("split", "video resource", "+ subtitle tracks"),
            ("transcribe", "subtitles first,", "Whisper as fallback"),
            ("frames", "scene change", "(image ops)"),
            ("context.md", "screens + time", "+ dialogue"),
            ("review", "what your agent", "read and wrote"),
        ],
        "head": "video",
        "tool_note": "image processing and file I/O — no model",
        "model_note": "your agent",
    },
    "ko": {
        "title": "analysis-video 파이프라인: split, transcribe, frames, context.md, review",
        "desc": ("순서대로 도는 다섯 단계. split 은 비디오 리소스를 쓰고 자막 트랙을 분리한다. "
                 "transcribe 는 자막을 우선하고 없으면 Whisper 로 넘어간다. frames 는 화면 변화를 "
                 "검출해 뽑는다. context.md 는 화면과 시각과 대사를 정렬한다. review 는 에이전트의 "
                 "분석이 보관되는 자리다."),
        "stages": [
            ("split", "비디오 리소스", "+ 자막 트랙"),
            ("transcribe", "자막 우선,", "없으면 Whisper"),
            ("frames", "화면 변화 검출", "(이미지 연산)"),
            ("context.md", "화면 + 시간", "+ 대사"),
            ("review", "에이전트가", "읽고 쓴 것"),
        ],
        "head": "영상",
        "tool_note": "이미지 연산과 파일 입출력 — 모델 없음",
        "model_note": "당신의 에이전트",
    },
}

PW, PH = 980, 268
SW, SH = 158, 96


def pipe_svg(t: dict, c: dict[str, str]) -> str:
    s = Svg(PW, PH, t["title"], t["desc"], c)
    left = 34
    s.text(left + 22, 96, t["head"], 14, c["muted"], mono=True)

    x0 = left + 62
    gap = 22
    for i, (name, l1, l2) in enumerate(t["stages"]):
        x = x0 + i * (SW + gap)
        last = i == len(t["stages"]) - 1
        s.box(x, 52, SW, SH, fill=c["bg-code"],
              stroke=c["accent"] if last else c["line"])
        s.text(x + SW / 2, 80, name, 15, c["accent"] if last else c["fg"], mono=True,
               weight="600")
        s.text(x + SW / 2, 106, l1, 11.5, c["muted"])
        s.text(x + SW / 2, 122, l2, 11.5, c["muted"])
        s.arrow(x - gap + 4, 100, x - 4, c["line"] if i else c["line"])

    # 아래 띠 — 도구의 몫과 모델의 몫을 갈라 보여준다
    span_end = x0 + 4 * (SW + gap) - gap
    s.line(x0, 176, span_end, 176, stroke=c["line"])
    s.text((x0 + span_end) / 2, 198, t["tool_note"], 12.5, c["muted"])

    lastx = x0 + 4 * (SW + gap)
    s.line(lastx, 176, lastx + SW, 176, stroke=c["accent"])
    s.text(lastx + SW / 2, 198, t["model_note"], 12.5, c["accent"])
    return s.render()


def main() -> int:
    c = palette()
    written = []
    for lang in ("en", "ko"):
        for name, svg in (("loop", loop_svg(LOOP[lang], c)),
                          ("pipeline", pipe_svg(PIPE[lang], c))):
            p = OUT / f"{name}-{lang}.svg"
            p.write_text(svg, "utf-8")
            written.append((p, len(svg.encode())))
    for p, n in written:
        print(f"→ {p.relative_to(ROOT)}  ({n:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
