"""context.md — 호출 AI 에이전트에게 건네는 전용 산출물.

metadata.json은 전체 기록(탈락 사유·내용량·검출 파라미터·전사 원문)을 담는
그릇이고 GUI가 그걸 읽는다. 그대로 AI에게 주면 video3 기준 **10만 토큰**인데,
그중 84%가 구조·중복·진단이다. AI에게 필요한 것은 셋뿐이다 — **이미지, 그 화면이
떠 있던 시간, 그동안의 대사**. 이 파일은 그것만 담는다(실측 현행의 14%).

형식은 마크다운이다. 같은 내용 실측 비교: 마크다운 14,129 / YAML 손수압축 14,854 /
YAML 표준덤프 15,006 / 최소 JSON 16,443 토큰. YAML이 JSON보다 작은 건 맞지만
마크다운은 항목마다 반복되는 **키가 아예 없다**(위치가 구조를 나른다). 덤으로
`![](경로)`가 이미지 참조로 해석되고 사람이 눈으로 검증할 수 있다.

단위는 프레임이 아니라 **화면**이다. 그리고 자기 대사가 없는 화면은 그 화면을
지나가던 문장의 섹션으로 흡수한다 — 한 문장이 여러 화면에 걸쳐 있을 때
(실측 최대 5개) 문장은 한 화면에만 배정되므로 나머지가 '(무음)'으로 찍히는데,
말하고 있는 중이므로 그건 거짓이다. 실측 오표기 video1 24건 중 21건, video2
12건 중 11건, video3 4건 중 4건. 흡수하면 그 거짓이 사라지고, 한 문장이
말해지는 동안 지나간 화면들이 그 문장 옆에 나란히 놓이며, 섹션 헤딩이 줄어
토큰도 함께 준다(실측 video1 −21%).
"""
from pathlib import Path

from . import align, budget


def render(metadata: dict, video_name: str) -> str:
    duration = metadata["source"]["duration"]
    frames = sorted(metadata["frames"], key=lambda f: f["time"])
    # 전사도 필수다(아래 screens[]와 같은 이유). 없는 셈 치고 빈 목록으로 넘어가면
    # 대사가 통째로 빠진 context.md가 **정상 종료로** 나가고, 그것을 읽는 에이전트는
    # 말이 없는 강의였다고 믿는다.
    segments = metadata["transcript"]["segments"]

    # screens[]와 frames[].screen은 필수다 — 빠져 있으면 KeyError로 멈춘다.
    # 프레임의 interval로 화면을 되짚는 폴백을 두지 않는 이유: 시각·구간 같은
    # 대체 키로 묶으면 묶기가 조용히 무력화된다(실측 사고). 지금은 무엇으로도
    # 되짚을 필요가 없다 — attach_dialogue가 탈락 레코드까지 screen을 매기고
    # build_metadata가 screens[]와 각 프레임의 screen을 항상 채운다.
    # 그래도 빠진 metadata가 여기까지 왔다면 그건 사용자 입력이 아니라 코드의
    # 버그다(옛 디렉터리는 load_metadata의 스키마 게이트가 exit 2로 거부한다).
    periods = [tuple(p) for p in metadata["screens"]]

    images: dict[int, list[str]] = {}
    for f in frames:
        images.setdefault(f["screen"], []).append(f["image"])
    # 대사 배정은 align과 **같은 함수**로 한다 — 이미지가 하나도 없는 화면에는
    # 붙을 프레임이 없어 frames[].dialogue로는 닿지 못하기 때문이다.
    # 빈 screens[]도 봐주지 않는다(IndexError): 프레임을 손에 들고 섹션을 하나도
    # 만들지 못하는 렌더는 유실을 조용히 삼키는 것이다.
    scoped = align.segments_in(segments, periods[0][0], periods[-1][1])
    said = align.assign_segments(scoped, periods)
    owner_of = {id(s): k for k, ss in said.items() for s in ss}

    # 자기 대사가 없는 화면 → 그 화면을 지나가던 문장의 주인 화면으로 흡수.
    # 한 문장이 여러 화면에 걸치면 문장은 한 화면에만 배정되므로 나머지가
    # '(무음)'으로 찍히는데, 말하고 있는 중이라 그건 거짓이다.
    host_of: dict[int, int] = {}
    for s in scoped:
        hit = [k for k, (a, b) in enumerate(periods) if s["end"] > a and s["start"] < b]
        if len(hit) <= 1:
            continue
        owner = owner_of[id(s)]
        for k in hit:
            if k != owner and k not in said:
                host_of[k] = owner

    # 읽기 예산. 장수만 적고 비용을 안 적으면 "필요한 것만 열어라"는 안내가
    # 근거를 주지 못한다 — 실측상 1시간 강의는 원본 해상도로 전부 열면 컨텍스트
    # 한도를 넘는다. 규칙 이름을 값과 함께 적는 이유는 budget.TOKEN_RULE 참조.
    budget_info = metadata["images"]
    lines = [f"# {video_name}", ""]
    n_img = sum(len(v) for v in images.values())
    lines.append(f"화면 {len(periods)}개 · 이미지 {n_img}장 · {duration:.0f}초")
    lines += ["",
              f"이미지는 긴 변 {budget_info['long_edge']}px 읽기용 사본이다 — "
              f"{budget_info['count']}장을 전부 열면 약 {budget_info['tokens']:,}토큰"
              f"({budget_info['rule']}). 예산이 모자라면 전부 열지 말고 골라 열면 된다:"
              " 각 항목의 구간이 그 화면이 떠 있던 시간이라, 오래 떠 있던 화면일수록"
              " 담긴 것이 많다. 원본 해상도가 필요하면 같은 파일명이 `frames/`에 있다.",
              "",
              "각 항목은 한 화면(또는 한 문장이 말해지는 동안 지나간 화면들)이다"
              " — 구간, 그때 촬영된 이미지(등장 직후→사라지기 직전 순), 그동안의 대사.", ""]

    for k, (a, b) in enumerate(periods):
        if k in host_of:
            continue  # 다른 섹션에 흡수됨
        members = [k] + sorted(j for j, h in host_of.items() if h == k)
        start = min(periods[j][0] for j in members)
        end = max(periods[j][1] for j in members)
        pics = [p for j in sorted(members) for p in images.get(j, [])]
        text = " ".join(seg["text"].strip() for seg in said.get(k, [])).strip()
        if not pics and not text:
            continue  # 이미지도 대사도 없는 화면은 실을 것이 없다
        lines.append(f"## {round(start, 2)}-{round(end, 2)}s")
        # 가리키는 것은 읽기용 사본이다. 두 경로를 metadata에 나란히 적지 않고
        # 규칙(같은 파일명, 다른 디렉터리)으로 만든다 — budget.read_path 참조.
        lines += [f"![]({budget.read_path(p, budget_info['read_dir'])})" for p in pics]
        if not pics:
            lines.append("(그림 없음 — 화면이 비어 있어 추출하지 못했다)")
        lines.append(text or "(무음)")
        lines.append("")
    return "\n".join(lines)


def write(out_dir: Path, metadata: dict, video_name: str) -> Path:
    path = out_dir / "context.md"
    path.write_text(render(metadata, video_name), encoding="utf-8")
    return path


def render_index(video_name: str, duration: float, entries: list[dict]) -> str:
    """최상위 인덱스 — 이 영상에 어떤 분석들이 있는가.

    겹치는 구간을 서로 다른 분석 단위로 낼 수 있으므로, 같은 시각에 대해 단위마다
    다른 답이 나올 수 있다는 것을 명시한다. 안 그러면 AI가 모순으로 오해한다."""
    lines = [f"# {video_name}", "",
             f"길이 {duration:.0f}초. 이 영상에는 분석 결과가 {len(entries)}개 있다.", ""]
    if len(entries) > 1:
        lines += ["분석 단위는 서로 **독립**이다. 구간이 겹치면 같은 시각에 대해 단위마다"
                  " 다른 화면 구분·다른 이미지가 나올 수 있다 — 모순이 아니라 서로 다른"
                  " 분석이다. 하나를 골라 그 안에서 일관되게 읽으면 된다.", ""]
    lines += ["| 분석 | 구간 | 화면 | 이미지 | 읽을 파일 |", "|---|---|---|---|---|"]
    for e in entries:
        rng = e["range"]
        span = "영상 전체" if rng is None else f"{rng[0]:.1f}-{rng[1]:.1f}초"
        # 숫자를 '?'로 눅이지 않는다 — 목록의 세는 값은 runs.merge_index가 단위마다
        # 남긴 것이고, 그것이 비었다면 인덱스가 아니라 단위 기록이 깨진 것이다.
        lines.append(f"| {e['name']} | {span} | {e['n_screens']} | "
                     f"{e['n_frames']} | `runs/{e['name']}/context.md` |")
    lines.append("")
    return "\n".join(lines)


def write_index(out_dir: Path, video_name: str, duration: float,
                entries: list[dict]) -> Path:
    path = out_dir / "context.md"
    path.write_text(render_index(video_name, duration, entries), encoding="utf-8")
    return path
