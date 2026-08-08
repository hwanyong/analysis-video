"""프레임 ↔ 대사 정렬 — 메타데이터 3요소(이미지 + 시간 + 대사)의 '대사'를 채운다.

**단위는 프레임이 아니라 화면(screen)이다.** 화면 하나가 떠 있던 구간에
이미지가 여러 장(등장 직후의 신선한 상태, 사라지기 직전의 완성된 상태) 붙고,
그 구간의 대사 전체가 그 화면의 대사다. 즉 `화면 1 : 이미지 M : 대사 N`.

프레임을 단위로 삼으면(구 방식: interval = [time_i, time_{i+1})) 깨진다.
전환 직전 프레임은 구간의 **끝**인데 구 방식은 모든 프레임을 구간의 **시작**으로
가정하기 때문이다. 실측 피해: video3 t=87.70의 완성 판서 이미지가 구간
[87.70, 114.44]와 대사 7건을 받았는데, 그 구간에 실제로 떠 있던 것은 컷 이후의
전혀 다른(거의 빈) 페이지였다 — 이미지와 대사가 서로 다른 화면을 가리켰다.
채택 74건 중 28건이 이 상태였다. 짝인 트리거가 살아남은 경우엔 반대로 구간이
0.07초로 퇴화해 같은 대사가 두 이미지에 중복으로 붙었다.

화면 경계는 anchor-diff 전환 이벤트에서 온다(AdaptiveDetector는 보조 검출기라
경계 정의에 섞지 않는다 — 구간의 정의를 검출기 하나에 고정해 SSOT를 지킨다):
화면 k = [직전 트리거 시각, 이번 전환이 시작된 시각].
"""
from bisect import bisect_right


def screen_periods(anchor_events: list[dict], duration: float,
                   window: tuple[float, float] | None = None) -> list[tuple[float, float]]:
    """화면이 떠 있던 구간들. 전환 자체(시작~트리거, 실측 중앙값 1프레임)는
    어느 화면에도 속하지 않는 '바뀌는 중'이므로 다음 화면 쪽에 흡수된다.

    window를 주면 그 구간으로 잘라낸다 — 부분 분석에서 첫 화면은 구간 시작에서
    시작하고(그 화면의 진짜 등장은 구간 이전이다) 마지막은 구간 끝에서 닫힌다."""
    lo, hi = window if window is not None else (0.0, duration)
    periods = []
    start = lo
    for e in anchor_events:
        end = e.get("transition_start_time")
        trigger = e.get("trigger_time")
        if end is None or trigger is None or not lo <= trigger <= hi:
            continue
        if end > start:
            periods.append((start, min(end, hi)))
        start = trigger
    if hi > start:
        periods.append((start, hi))
    return periods or [(lo, hi)]


def assign_segments(segments: list[dict],
                    periods: list[tuple[float, float]]) -> dict[int, list[dict]]:
    """대사를 화면에 **하나씩만** 배정한다 — 가장 많이 걸친 화면으로.

    겹치는 화면 전부에 붙이면(단순 overlap) 경계를 걸친 문장이 두 번 실려
    전사 원문의 106~142%가 된다. 한 문장은 한 번만 읽혀야 하고, 동시에 한
    문장도 사라지면 안 된다 — 최대 겹침 배정이 그 둘을 동시에 만족한다.
    (구간 조회 자체가 필요한 곳은 segments_in을 그대로 쓴다)"""
    out: dict[int, list[dict]] = {}
    for s in segments:
        best, best_ov = None, 0.0
        for k, (a, b) in enumerate(periods):
            ov = min(s["end"], b) - max(s["start"], a)
            if ov > best_ov:
                best, best_ov = k, ov
        if best is None:  # 어느 화면과도 겹치지 않는다(전환 틈새) — 가장 가까운 화면
            best = min(range(len(periods)),
                       key=lambda k: min(abs(periods[k][0] - s["start"]),
                                         abs(periods[k][1] - s["end"])))
        out.setdefault(best, []).append(s)
    return out


def attach_dialogue(records: list[dict], segments: list[dict], duration: float,
                    anchor_events: list[dict] | None = None,
                    window: tuple[float, float] | None = None
                    ) -> list[tuple[float, float]]:
    """모든 레코드에 소속 화면을 매긴다 — 탈락한 것도 포함.

    탈락 레코드에도 화면을 매기는 이유: 어떤 화면은 후보가 **전부** 탈락한다
    (그림이 비어서). 그 화면을 기록에서 지우면 그동안의 대사가 통째로 사라진다
    — 실측 유실 video1 64%, video2 33%, video3 14%."""
    periods = screen_periods(anchor_events or [], duration, window)
    starts = [p[0] for p in periods]
    # 구간 밖의 대사는 이 분석의 것이 아니다 — 배정 대상에서 제외한다
    lo, hi = periods[0][0], periods[-1][1]
    scoped = [s for s in segments if s["end"] > lo and s["start"] < hi]
    said = assign_segments(scoped, periods)

    for r in records:
        # 프레임이 속한 화면 = 시작 시각이 프레임 시각을 넘지 않는 마지막 화면
        k = max(bisect_right(starts, r["time"]) - 1, 0)
        start, end = periods[k]
        r["screen"] = k
        r["interval"] = [round(start, 2), round(end, 2)]
        if r["status"] != "accepted":
            continue  # 대사는 채택본에만 — 탈락 레코드까지 실으면 metadata가 배로 커진다
        r["dialogue"] = said.get(k, [])
    return periods


def segments_in(segments: list[dict], start: float, end: float) -> list[dict]:
    return [s for s in segments if s["end"] > start and s["start"] < end]


def find_segment_at(segments: list[dict], t: float) -> dict | None:
    for s in segments:
        if s["start"] <= t <= s["end"]:
            return s
    if not segments:
        return None
    return min(segments, key=lambda s: min(abs(s["start"] - t), abs(s["end"] - t)))
