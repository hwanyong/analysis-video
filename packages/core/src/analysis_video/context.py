"""context.md — 호출 AI 에이전트에게 건네는 전용 산출물.

metadata.json은 전체 기록(탈락 사유·yavg·해시·검출 파라미터·전사 원문)을 담는
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

from . import align


def render(metadata: dict, video_name: str) -> str:
    duration = metadata["source"]["duration"]
    frames = sorted(metadata["frames"], key=lambda f: f["time"])
    rejected = metadata.get("rejected", [])
    segments = metadata.get("transcript", {}).get("segments", [])
    by_time = {round(f["time"], 2): f["image"] for f in frames}

    periods = [tuple(p) for p in metadata.get("screens", [])]
    if not periods:  # screens가 없는 구산출물 — 프레임의 구간에서 되짚는다
        seen: list[tuple] = []
        for f in frames:
            if tuple(f["interval"]) not in seen:
                seen.append(tuple(f["interval"]))
        periods = seen
    index = {p: k for k, p in enumerate(periods)}

    def screen_of(rec: dict):
        # screen이 있으면 그것이 정본. 없는 구산출물은 구간으로 되짚는다 —
        # 시각 같은 대체 키로 폴백하면 묶기가 조용히 무력화된다(실측 사고).
        k = rec.get("screen")
        return k if k is not None else index.get(tuple(rec.get("interval", ())))

    images: dict[int, list[str]] = {}
    for f in frames:
        k = screen_of(f)
        if k is not None:
            images.setdefault(k, []).append(f["image"])
    # 후보가 전부 탈락한 화면: 앞선 동일 화면에 병합된 것이면 그 이미지가
    # 이 화면의 모습이기도 하다 — 되찾아 붙인다(같은 파일을 다시 참조할 뿐이다).
    borrowed: set[int] = set()
    for r in rejected:
        k = screen_of(r)
        if k is None or k in images or r.get("dup_of") is None:
            continue
        img = by_time.get(round(r["dup_of"], 2))
        if img:
            images.setdefault(k, []).append(img)
            borrowed.add(k)

    # 대사 배정은 align과 **같은 함수**로 한다 — 이미지가 하나도 없는 화면에는
    # 붙을 프레임이 없어 frames[].dialogue로는 닿지 못하기 때문이다.
    scoped = align.segments_in(segments, periods[0][0], periods[-1][1]) if periods else []
    said = align.assign_segments(scoped, periods) if periods else {}
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

    lines = [f"# {video_name}", ""]
    n_img = sum(len(v) for k, v in images.items() if k not in borrowed)
    lines.append(f"화면 {len(periods)}개 · 이미지 {n_img}장 · {duration:.0f}초")
    lines += ["", "각 항목은 한 화면(또는 한 문장이 말해지는 동안 지나간 화면들)이다"
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
        lines += [f"![]({p})" for p in pics]
        if k in borrowed:
            lines.append("(앞 화면과 같은 그림 — 위 이미지가 이 구간의 모습이다)")
        elif not pics:
            lines.append("(그림 없음 — 화면이 너무 어두워 추출하지 못했다)")
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
        lines.append(f"| {e['name']} | {span} | {e.get('n_screens', '?')} | "
                     f"{e.get('n_frames', '?')} | `runs/{e['name']}/context.md` |")
    lines.append("")
    return "\n".join(lines)


def write_index(out_dir: Path, video_name: str, duration: float,
                entries: list[dict]) -> Path:
    path = out_dir / "context.md"
    path.write_text(render_index(video_name, duration, entries), encoding="utf-8")
    return path
