"""context.md — 호출 AI 에이전트에게 건네는 전용 산출물.

metadata.json은 전체 기록(탈락 사유·yavg·해시·검출 파라미터·전사 원문)을 담는
그릇이고 GUI가 그걸 읽는다. 그대로 AI에게 주면 video3 기준 **85,411 토큰**인데,
그중 84%가 구조·중복·진단이다: 전사 원문과 세그먼트 배열이 통째로 한 번 더 실리고
(29%), 탈락 레코드가 실리고, 프레임마다 yavg·hash·sources가 붙는다.

AI에게 필요한 것은 셋뿐이다 — **이미지, 그 화면이 떠 있던 시간, 그동안의 대사**.
이 파일은 그것만 담는다. 실측 14,558 토큰(현행의 17%)이고, 대사 본문 자체가
12,575 토큰이므로 구조 오버헤드는 5.5%다.

형식은 마크다운이다. 토큰이 가장 적고(YAML 대비 5%, JSON 대비 12% 작다 — YAML은
화면마다 키를 반복하고 블록 스칼라 지시자·들여쓰기가 붙는 반면 마크다운은 키가
아예 없다), LLM이 파서 없이 읽으며, `![](경로)`가 이미지 참조로 해석되고,
사람이 눈으로 검증할 수 있다. 기계가 읽어야 하면 metadata.json이 그대로 있다.

단위는 프레임이 아니라 **화면**이다 — 한 화면에 이미지가 여러 장(등장 직후의
신선한 상태, 사라지기 직전의 완성된 상태) 붙고 대사는 그 화면에 한 번만 실린다.
프레임 단위로 쓰면 같은 대사가 두 번 실려 실측 전사 원문의 109~154%가 됐다.
화면 단위로 묶으면 정확히 100% — 한 마디도 중복되지 않고 한 마디도 빠지지 않는다.
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
    said: dict[int, list[dict]] = {}
    for f in frames:
        k = screen_of(f)
        if k is not None:
            images.setdefault(k, []).append(f["image"])
            said.setdefault(k, f.get("dialogue", []))
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

    n_img = sum(len(v) for k, v in images.items() if k not in borrowed)
    out = [f"# {video_name}", "",
           f"화면 {len(periods)}개 · 이미지 {n_img}장 · {duration:.0f}초", "",
           "각 항목은 화면 하나다 — 그 화면이 떠 있던 구간, 그 구간에 촬영된"
           " 이미지(여럿이면 등장 직후→사라지기 직전 순), 그동안의 대사.", ""]
    # 이미지가 하나도 없는 화면은 대사를 붙일 자리가 없었다 — 같은 배정 규칙으로
    # 다시 구한다(규칙을 여기서 다시 구현하지 않고 align에 위임한다).
    orphan = align.assign_segments(segments, periods) if segments else {}

    for k, (a, b) in enumerate(periods):
        segs = said.get(k) if k in said else orphan.get(k, [])
        text = " ".join(seg["text"].strip() for seg in segs).strip()
        imgs = images.get(k, [])
        if not imgs and not text:
            continue  # 이미지도 대사도 없는 화면은 실을 것이 없다
        out.append(f"## {a}-{b}s")
        out += [f"![]({p})" for p in imgs]
        if k in borrowed:
            out.append("(앞 화면과 같은 그림 — 위 이미지가 이 구간의 모습이다)")
        elif not imgs:
            out.append("(그림 없음 — 화면이 너무 어두워 추출하지 못했다)")
        out.append(text or "(무음)")
        out.append("")
    return "\n".join(out)


def write(out_dir: Path, metadata: dict, video_name: str) -> Path:
    path = out_dir / "context.md"
    path.write_text(render(metadata, video_name), encoding="utf-8")
    return path
