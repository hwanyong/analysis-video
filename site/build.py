"""랜딩 페이지 생성기 — 템플릿 하나 + 언어별 본문 → 언어별 URL.

**왜 스크립트인가.** 언어를 자바스크립트 토글로 바꾸면 URL이 하나뿐이라 크롤러는 두 언어가
섞인 문서 하나만 보게 되고, 어느 쪽 언어로도 제대로 색인되지 않는다. 검색 유입을 목적으로
삼는 순간 언어별로 **실제 URL**이 갈려야 하고(`/` 와 `/ko/`), 그러면 `<head>` 와 상단바·푸터가
두 벌 생긴다. 그 두 벌이 손으로 관리되면 반드시 어긋나므로, 레이아웃은 template.html 한 장에
두고 언어가 다른 부분만 body.{en,ko}.html 로 나눈다.

**의존성 0.** 표준 라이브러리만 쓴다. 이 저장소의 산출물은 CLI 이고, 랜딩을 만들자고 npm 이나
정적 사이트 생성기를 끌어들이면 CI 가 관리해야 할 생태계가 하나 늘어난다.

**FAQ 구조화 데이터는 본문에서 파싱해 만든다.** 손으로 JSON-LD 를 따로 적으면 화면의 문답과
검색엔진이 읽는 문답이 갈라지는데, Google 은 그 불일치를 구조화 데이터 위반으로 본다. 파싱하면
갈라질 수가 없다.

사용:
    python site/build.py                       # → _site/  (배포용, 절대 URL)
    python site/build.py --base '' --out /tmp/preview   # 로컬 미리보기
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent

ORIGIN = "https://lab.hwanyong.com"
BASE = "/analysis-video"

# Cloudflare Web Analytics. blog.hwanyong.com 전체가 이 토큰 하나로 잡힌다 —
# 호스트 단위 집계라 하위 경로인 이 랜딩도 같은 사이트의 페이지로 들어간다.
# token 은 비밀이 아니다: 모든 방문자의 HTML 에 그대로 실려 나가는 공개 식별자다.
CF_BEACON_TOKEN = "d10ef3756f0a47f48b7896721f153bfa"

# integrity 미적용: beacon.min.js 는 버전 고정 URL 이 아니라 Cloudflare 가 계속
# 갱신하는 엔드포인트다. 해시를 박으면 다음 갱신에서 무음으로 차단돼 계측이 영구
# 정지한다 — 그 편이 더 위험하다.
CF_BEACON = (
    '<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js"'
    f" data-cf-beacon='{{\"token\": \"{CF_BEACON_TOKEN}\"}}'></script>"
)

REPO = "https://github.com/hwanyong/analysis-video"
PYPI = "https://pypi.org/project/analysis-video/"

# 본문이 참조하는 그림. docs/ 가 원본이고 사이트는 복사본을 싣는다 — 그림을 두 군데
# 두면 README 의 그림과 랜딩의 그림이 갈라진다.
MEDIA = ("context-example.png", "gui-timeline.png", "gui-workbench.png", "og-card.png",
         "loop-en.svg", "loop-ko.svg", "pipeline-en.svg", "pipeline-ko.svg")

STRINGS = {
    "en": {
        "path": "",
        "og_locale": "en_US",
        "title": "analysis-video — Turn video into AI-readable context",
        "description": (
            "Convert lecture and screencast video into one Markdown file an LLM can read "
            "— keyframes, timestamps and transcript, aligned screen by screen. Local, no API key."
        ),
        "og_image_alt": (
            "analysis-video — turn video into AI-readable context. "
            "uvx analysis-video@latest analyze lecture.mp4"
        ),
        "nav_label": "Project links",
        "alt_label": "한국어",
        "footer_note": (
            "analysis-video is an open-source command-line tool. "
            "It reads local files only and never uploads your video."
        ),
        "app_description": (
            "Command-line tool that converts lecture, screencast, and slide-based video into a "
            "single Markdown file for LLMs: keyframes selected by screen change, the time range "
            "each screen was shown, and the transcript aligned screen by screen. Runs locally "
            "with no API key and no upload."
        ),
    },
    "ko": {
        "path": "ko",
        "og_locale": "ko_KR",
        "title": "analysis-video — 영상을 AI가 읽는 컨텍스트로",
        "description": (
            "강의·스크린캐스트 영상을 LLM이 읽을 수 있는 마크다운 하나로. 키프레임·시각·대사를 "
            "화면 단위로 정렬합니다. 전부 로컬 실행, API 키 불필요."
        ),
        "og_image_alt": (
            "analysis-video — 영상을 AI가 읽는 컨텍스트로. "
            "uvx analysis-video@latest analyze lecture.mp4"
        ),
        "nav_label": "프로젝트 링크",
        "alt_label": "English",
        "footer_note": (
            "analysis-video는 오픈소스 명령줄 도구입니다. 로컬 파일만 읽으며 영상을 "
            "어디에도 업로드하지 않습니다."
        ),
        "app_description": (
            "강의·스크린캐스트·슬라이드 영상을 LLM용 마크다운 하나로 바꾸는 명령줄 도구. "
            "화면 변화량으로 고른 키프레임, 각 화면이 떠 있던 시간 구간, 화면 단위로 정렬된 "
            "대사를 담는다. API 키 없이 전부 로컬에서 실행되고 영상을 업로드하지 않는다."
        ),
    },
}


class FaqParser(HTMLParser):
    """`<details><summary>질문</summary> 답 </details>` 를 (질문, 답) 목록으로.

    화면에 실제로 그려지는 문답을 그대로 읽어 FAQPage 구조화 데이터를 만들기 위한 것이다.
    태그는 버리고 글자만 모은다 — Google 이 권장하는 것은 답변의 평문이고, 여기서 굳이
    인라인 태그를 살려 봐야 화면과 대조하기만 어려워진다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pairs: list[tuple[str, str]] = []
        self._depth = 0          # <details> 안인지
        self._in_summary = False
        self._q: list[str] = []
        self._a: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "details":
            self._depth += 1
            self._q, self._a = [], []
        elif tag == "summary" and self._depth:
            self._in_summary = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "summary" and self._depth:
            self._in_summary = False
        elif tag == "details" and self._depth:
            self._depth -= 1
            q = " ".join("".join(self._q).split())
            a = " ".join("".join(self._a).split())
            if q and a:
                self.pairs.append((q, a))

    def handle_data(self, data: str) -> None:
        if not self._depth:
            return
        (self._q if self._in_summary else self._a).append(data)


def core_version() -> str:
    """PyPI 에 올라간 패키지 버전. 구조화 데이터의 softwareVersion 이 여기서 온다.

    손으로 적으면 릴리스마다 랜딩만 옛 버전을 말하게 된다.
    """
    data = tomllib.loads((ROOT / "packages" / "core" / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


def jsonld(lang: str, canonical: str, origin: str, faq: list[tuple[str, str]],
           version: str) -> str:
    """SoftwareApplication + FAQPage.

    두 개를 `@graph` 하나로 묶는다. `<script>` 를 여러 개 두는 것도 유효하지만, 한 문서가
    무엇에 대한 것인지 크롤러가 한 덩어리로 읽는 편이 낫다.
    """
    s = STRINGS[lang]
    graph: list[dict] = [
        {
            "@type": "SoftwareApplication",
            "@id": f"{canonical}#software",
            "name": "analysis-video",
            "url": canonical,
            "description": s["app_description"],
            "applicationCategory": "DeveloperApplication",
            "applicationSubCategory": "Command Line Tool",
            "operatingSystem": "macOS, Linux, Windows",
            "softwareVersion": version,
            "downloadUrl": PYPI,
            "installUrl": PYPI,
            "codeRepository": REPO,
            "programmingLanguage": "Python",
            "runtimePlatform": "Python 3.11–3.14",
            "license": "https://opensource.org/licenses/MIT",
            "isAccessibleForFree": True,
            "inLanguage": lang,
            "author": {"@type": "Person", "name": "hwanyong", "url": "https://github.com/hwanyong"},
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "image": f"{origin}/media/og-card.png",
        }
    ]
    if faq:
        graph.append({
            "@type": "FAQPage",
            "@id": f"{canonical}#faq",
            "inLanguage": lang,
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": q,
                    "acceptedAnswer": {"@type": "Answer", "text": a},
                }
                for q, a in faq
            ],
        })
    payload = {"@context": "https://schema.org", "@graph": graph}
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f'<script type="application/ld+json">\n{body}\n</script>'


def sitemap(urls: dict[str, str], lastmod: str) -> str:
    """언어별 URL 을 hreflang 대안과 함께.

    각 URL 항목이 **자기 자신을 포함한** 모든 언어를 나열해야 한다는 것이 xhtml:link 규칙이다.
    자기 자신을 빼면 Google 은 그 묶음을 무시한다.
    """
    alts = "".join(
        f'\n    <xhtml:link rel="alternate" hreflang="{code}" href="{href}"/>'
        for code, href in urls.items()
    )
    alts += f'\n    <xhtml:link rel="alternate" hreflang="x-default" href="{urls["en"]}"/>'
    entries = "".join(
        f'\n  <url>\n    <loc>{href}</loc>\n    <lastmod>{lastmod}</lastmod>'
        f"\n    <changefreq>monthly</changefreq>"
        f"\n    <priority>{'1.0' if code == 'en' else '0.9'}</priority>{alts}\n  </url>"
        for code, href in urls.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f"{entries}\n</urlset>\n"
    )


def build(out: Path, base: str, origin: str) -> int:
    template = (SITE / "template.html").read_text("utf-8")
    style = (SITE / "style.css").read_text("utf-8")
    version = core_version()

    urls = {
        code: f"{origin}{base}/{s['path']}".rstrip("/") + "/"
        for code, s in STRINGS.items()
    }

    if out.exists():
        shutil.rmtree(out)

    # 그림은 docs/media 가 원본이다. 하나라도 없으면 멈춘다 — og-card.png 가 빠진 채로
    # 배포되면 메타 태그는 그대로 남고 공유 카드만 깨진 채 돌아다닌다.
    media_out = out / "media"
    media_out.mkdir(parents=True)
    for name in MEDIA:
        src = ROOT / "docs" / "media" / name
        if not src.is_file():
            print(
                f"error: docs/media/{name} 이 없습니다."
                + (" `uv run python examples/make_og_card.py` 로 먼저 만들어 주세요."
                   if name == "og-card.png" else ""),
                file=sys.stderr,
            )
            return 1
        shutil.copy2(src, media_out / name)

    newest = max(
        (SITE / f).stat().st_mtime
        for f in ("template.html", "style.css", "body.en.html", "body.ko.html", "build.py")
    )
    lastmod = datetime.fromtimestamp(newest, timezone.utc).date().isoformat()

    for lang, s in STRINGS.items():
        body = (SITE / f"body.{lang}.html").read_text("utf-8")
        parser = FaqParser()
        parser.feed(body)

        other = "ko" if lang == "en" else "en"
        page = template
        for key, value in {
            "lang": lang,
            "title": s["title"],
            "description": s["description"],
            "og_image_alt": s["og_image_alt"],
            "og_locale": s["og_locale"],
            "og_locale_alt": STRINGS[other]["og_locale"],
            "nav_label": s["nav_label"],
            "footer_note": s["footer_note"],
            "canonical": urls[lang],
            "href_en": urls["en"],
            "href_ko": urls["ko"],
            "alt_href": urls[other],
            "alt_lang": other,
            "alt_label": s["alt_label"],
            "origin": f"{origin}{base}".rstrip("/"),
            "base": base,
            "style": style,
            # 계측은 **프로덕션 빌드에만** 싣는다. Umami 시절에는 data-domains 가
            # 호스트를 검사해 이 일을 클라이언트에서 했지만, Cloudflare 비콘에는
            # 그런 속성이 없다 — 실리면 어디서 열리든 보낸다. 그래서 게이트를
            # 빌드로 옮긴다: --origin 이 프로덕션이 아니면 태그 자체가 안 나간다.
            # 로컬 미리보기와 포크된 저장소의 Pages 배포가 통계를 오염시키지 못한다.
            "analytics": CF_BEACON if origin == ORIGIN else "",
            "jsonld": jsonld(lang, urls[lang], f"{origin}{base}".rstrip("/"),
                             parser.pairs, version),
            "body": body.replace("{{base}}", base),
        }.items():
            page = page.replace("{{" + key + "}}", value)

        if "{{" in page:
            leftover = page[page.index("{{"): page.index("{{") + 40]
            print(f"error: 치환되지 않은 자리표시자가 남았습니다: {leftover!r}", file=sys.stderr)
            return 1

        dest = out / s["path"] / "index.html" if s["path"] else out / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page, "utf-8")
        print(f"  {dest.relative_to(out)}  ({len(page):,} bytes, FAQ {len(parser.pairs)}건)")

    # robots.txt 는 만들지 않는다. 크롤러는 **도메인 루트**의 robots.txt 만 읽으므로
    # /analysis-video/robots.txt 는 아무도 가져가지 않는 죽은 파일이 된다. 사이트맵은
    # Search Console 에 직접 제출하거나, blog.hwanyong.com 루트의 robots.txt 에
    # `Sitemap:` 줄을 한 줄 더해서 알린다.
    (out / "sitemap.xml").write_text(sitemap(urls, lastmod), "utf-8")

    # .nojekyll — GitHub Pages 는 업로드된 산출물을 Jekyll 로 한 번 더 훑는데, 그 과정에서
    # 밑줄로 시작하는 디렉터리가 버려진다. 지금은 그런 경로가 없지만, 생겼을 때 조용히
    # 사라지는 쪽이 훨씬 찾기 어렵다.
    (out / ".nojekyll").write_text("", "utf-8")

    print(f"  sitemap.xml  (lastmod {lastmod})")
    print(f"→ {out}  [analysis-video {version}]")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=ROOT / "_site", help="출력 디렉터리")
    p.add_argument("--base", default=BASE,
                   help="사이트가 놓이는 경로 접두사. 로컬 미리보기는 '' 로.")
    p.add_argument("--origin", default=ORIGIN, help="정규 URL 의 오리진")
    a = p.parse_args()
    return build(a.out, a.base.rstrip("/"), a.origin.rstrip("/"))


if __name__ == "__main__":
    raise SystemExit(main())
