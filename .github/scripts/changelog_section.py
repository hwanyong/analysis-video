#!/usr/bin/env python3
"""CHANGELOG.md 에서 "이 패키지의 이 버전" 절만 뽑아 표준출력으로 낸다.

CHANGELOG.md 는 패키지 두 개를 한 파일에 담고(H1 = 패키지, H2 = 버전) 버전은 서로
독립이다. 릴리스 노트를 만들려면 그 둘을 함께 짚어야 한다.

release.yml 이 **두 자리에서** 쓴다:
  1) verify 잡 — 되돌릴 수 없는 PyPI 업로드 **전에** 절이 있는지만 확인(종료코드로 게이트)
  2) github-release 잡 — 업로드 뒤 릴리스 본문으로 사용
같은 규칙을 두 잡에 각각 적으면 한쪽만 낡으므로 파일 하나로 둔다.

GitHub Actions 로그에서 읽히도록 경고는 `::warning::` 접두사로 stderr 에 낸다 —
이 스크립트는 워크플로 전용이다.

사용법:
    changelog_section.py <배포물 이름> <버전> [--changelog 경로]
예:
    changelog_section.py analysis-video 0.1.0
종료코드: 0 = 찾음(본문 출력) / 1 = 못 찾음(사유는 stderr)
"""
import argparse
import re
import sys
from pathlib import Path

# 저장소 루트의 CHANGELOG.md — 이 파일은 .github/scripts/ 에 있다.
DEFAULT_CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def find_section(text: str, dist: str, version: str) -> tuple[str, str]:
    """(제목 줄, 본문)을 돌려준다. 없으면 SystemExit(1).

    H1(`# <배포물 이름> (…)`)로 패키지 구역을 좁힌 뒤 그 안에서
    H2(`## [<버전>]`)를 찾는다. 배포물 이름 뒤에 경계를 요구하는 이유는
    `# analysis-video-gui …` 가 `analysis-video` 의 접두사이기 때문이다.
    """
    lines = text.splitlines()
    name = re.escape(dist)
    h1 = re.compile(rf"^#\s+{name}(?![\w-])")
    any_h1 = re.compile(r"^#\s+\S")
    h2 = re.compile(rf"^##\s+\[{re.escape(version)}\]")
    any_h2 = re.compile(r"^##\s+\S")

    start = next((i for i, ln in enumerate(lines) if h1.match(ln)), None)
    if start is None:
        sys.exit(f"CHANGELOG 에 '# {dist} …' 절이 없습니다")
    end = next((i for i in range(start + 1, len(lines)) if any_h1.match(lines[i])),
               len(lines))

    body_start = next((i for i in range(start + 1, end) if h2.match(lines[i])), None)
    if body_start is None:
        sys.exit(f"CHANGELOG 의 '{dist}' 절에 '## [{version}]' 이 없습니다 — "
                 f"[Unreleased] 를 [{version}] 으로 확정했는지 확인하세요")
    body_end = next((i for i in range(body_start + 1, end) if any_h2.match(lines[i])),
                    end)
    body = lines[body_start + 1:body_end]
    # 패키지 구역을 가르는 수평선(`---`)은 그 앞 절의 본문이 아니다 —
    # H1/H2 가 아니라 경계 판정에 걸리지 않으므로 여기서 떼어낸다.
    rule = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
    while body and (not body[-1].strip() or rule.match(body[-1])):
        body.pop()
    return lines[body_start], "\n".join(body).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dist", help="배포물 이름 (analysis-video 또는 analysis-video-gui)")
    ap.add_argument("version", help="버전 (예: 0.1.0)")
    ap.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    args = ap.parse_args()

    if not args.changelog.exists():
        sys.exit(f"{args.changelog} 가 없습니다")

    heading, body = find_section(args.changelog.read_text(encoding="utf-8"),
                                 args.dist, args.version)
    # 올리는 중인 버전이 아직 "미발행"이라고 적혀 있으면 문서가 낡은 것이다.
    # 업로드를 막을 일은 아니므로 경고만 남긴다.
    if "미발행" in heading:
        print(f"::warning::CHANGELOG 의 '{heading.strip()}' 이 아직 미발행으로 적혀 있습니다 "
              f"— 발행일로 고치세요", file=sys.stderr)
    if not body:
        sys.exit(f"CHANGELOG 의 '{args.dist}' / '{args.version}' 절이 비어 있습니다")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
