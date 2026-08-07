"""프레임 ↔ 대사 정렬 — 메타데이터 3요소(이미지 + 시간 + 대사)의 '대사'를 채운다.

프레임의 대사 = 그 프레임이 화면에 떠 있던 구간의 대사 전체.
accepted 프레임 i의 구간은 [time_i, time_{i+1}) (마지막은 영상 끝까지)이고,
이 구간과 겹치는 STT 세그먼트를 전부 부착한다. 프로토타입의 최근접 단어 1개
방식은 다운스트림 AI가 해석하기에 정보량이 부족해 폐기했다.
"""


def attach_dialogue(records: list[dict], segments: list[dict], duration: float) -> None:
    accepted = [r for r in records if r["status"] == "accepted"]
    for idx, r in enumerate(accepted):
        start = r["time"]
        end = accepted[idx + 1]["time"] if idx + 1 < len(accepted) else duration
        r["interval"] = [round(start, 2), round(end, 2)]
        r["dialogue"] = segments_in(segments, start, end)
        if r.get("point_times"):
            # importance-point가 병합된 프레임: 어떤 대사가 트리거였는지 별도 기록
            triggers = [find_segment_at(segments, t) for t in r["point_times"]]
            r["trigger_dialogue"] = [t for i, t in enumerate(triggers)
                                     if t is not None and t not in triggers[:i]]


def segments_in(segments: list[dict], start: float, end: float) -> list[dict]:
    return [s for s in segments if s["end"] > start and s["start"] < end]


def find_segment_at(segments: list[dict], t: float) -> dict | None:
    for s in segments:
        if s["start"] <= t <= s["end"]:
            return s
    if not segments:
        return None
    return min(segments, key=lambda s: min(abs(s["start"] - t), abs(s["end"] - t)))
