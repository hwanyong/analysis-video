"""화면 구간 정렬 + AI용 context.md.

구 방식(interval = [time_i, time_{i+1}))은 모든 프레임을 구간의 '시작'으로
가정했는데, 전환 직전 프레임은 구간의 '끝'이다. 그래서 완성된 판서 이미지가
컷 이후 전혀 다른 화면의 대사를 물려받았다(video3 채택 74건 중 28건 실측).
"""
import json

import pytest

from analysis_video import align, budget, context


def _seg(a, b, text):
    return {"start": a, "end": b, "text": text}


def _images(n: int) -> dict:
    """metadata의 `images` 블록 — frames가 실제로 만든 **읽기용 사본들의 크기**에서
    나온다. 그래서 count는 프레임 수와 같아야 한다: context.md의 비용 문단이 이
    숫자를 그대로 적으므로, 어긋나게 지으면 픽스처가 거짓을 렌더하게 된다.

    원본 1920x1080을 긴 변 768px로 줄인 크기(768x432)를 쓴다."""
    return budget.summary([(768, 432)] * n)


EVENTS = [
    {"time": 10.0, "after_time": 10.1},
    {"time": 30.0, "after_time": 30.1},
]


def test_screen_periods_span_between_transitions():
    p = align.screen_periods(EVENTS, 50.0)
    assert p == [(0.0, 10.0), (10.1, 30.0), (30.1, 50.0)]


def test_screen_periods_without_events_is_whole_video():
    assert align.screen_periods([], 50.0) == [(0.0, 50.0)]


def test_pre_frame_keeps_its_own_screen_not_the_next():
    """전환 직전(9.97) 프레임은 첫 화면에 속해야 한다. 구 방식은 이 프레임에
    [9.97, 다음프레임] 구간을 줘서 컷 이후의 대사를 붙였다."""
    records = [
        {"time": 0.5, "status": "accepted", "point_times": []},
        {"time": 9.97, "status": "accepted", "point_times": []},   # 전환 직전
        {"time": 10.1, "status": "accepted", "point_times": []},   # 트리거
        {"time": 35.0, "status": "accepted", "point_times": []},
    ]
    segments = [_seg(0.0, 8.0, "첫 화면 설명"), _seg(11.0, 25.0, "둘째 화면 설명"),
                _seg(31.0, 45.0, "셋째 화면 설명")]
    align.attach_dialogue(records, segments, 50.0, EVENTS)

    assert records[0]["interval"] == [0.0, 10.0]
    assert records[1]["interval"] == [0.0, 10.0], "직전 프레임은 자기 화면에 남는다"
    assert records[0]["screen"] == records[1]["screen"] == 0
    assert records[2]["interval"] == [10.1, 30.0] and records[2]["screen"] == 1
    assert records[3]["interval"] == [30.1, 50.0]

    texts = lambda r: [s["text"] for s in r["dialogue"]]
    assert texts(records[1]) == ["첫 화면 설명"], "컷 이후 대사를 물려받으면 안 된다"
    assert texts(records[2]) == ["둘째 화면 설명"]


def test_every_segment_lands_on_exactly_one_screen():
    """한 문장은 정확히 한 번 — 빠져도(유실) 두 번 실려도(토큰 낭비) 안 된다.

    단순 overlap으로 붙이면 경계를 걸친 문장이 양쪽에 실려 실측 전사 원문의
    106~142%가 됐다. 반대로 화면을 지우면 64%까지 빠졌다."""
    periods = align.screen_periods(EVENTS, 50.0)
    # 경계(10.0/10.1, 30.0/30.1)를 일부러 걸치는 문장들을 섞는다
    segments = [_seg(8.0, 12.0, "경계1"), _seg(9.0, 10.05, "경계2"),
                _seg(29.0, 31.5, "경계3"), _seg(1.0, 2.0, "안쪽1"),
                _seg(20.0, 21.0, "안쪽2"), _seg(40.0, 41.0, "안쪽3")]
    assigned = align.assign_segments(segments, periods)
    landed = [s for segs in assigned.values() for s in segs]
    assert len(landed) == len(segments), "빠진 문장이 없어야 한다"
    assert len({id(s) for s in landed}) == len(segments), "두 번 실린 문장이 없어야 한다"
    # 8.0~12.0은 화면0에 2.0초, 화면1에 1.9초 걸친다 → 더 많이 걸친 화면0
    assert segments[0] in assigned[0]
    assert segments[2] in assigned[2], "29.0~31.5는 화면2에 1.4초로 더 많이 걸친다"


def test_same_screen_frames_share_one_dialogue_block():
    records = [{"time": t, "status": "accepted", "point_times": []}
               for t in (0.5, 9.97, 10.1)]
    segments = [_seg(1.0, 2.0, "가"), _seg(12.0, 13.0, "나")]
    align.attach_dialogue(records, segments, 50.0, EVENTS)
    assert records[0]["dialogue"] == records[1]["dialogue"], "같은 화면이면 같은 대사"
    assert records[2]["dialogue"] != records[0]["dialogue"]


def test_context_keeps_screens_whose_images_all_dropped():
    """후보가 전부 탈락한 화면도 남아야 한다 — 지우면 그동안의 대사가 통째로
    사라진다(실측 유실 video1 64%)."""
    metadata = {
        "source": {"duration": 50.0},
        "screens": [[0.0, 10.0], [10.1, 30.0], [30.1, 50.0]],
        "frames": [{"time": 0.5, "image": "frames/a.jpg", "screen": 0,
                    "interval": [0.0, 10.0], "dialogue": [_seg(1.0, 5.0, "첫 화면")]}],
        "rejected": [
            {"time": 11.0, "screen": 1, "reject_reason": "blank(<=0.001)"},
            {"time": 31.0, "screen": 2, "reject_reason": "blank(<=0.001)"},
        ],
        "transcript": {"segments": [_seg(1.0, 5.0, "첫 화면"),
                                    _seg(12.0, 20.0, "둘째 화면 설명"),
                                    _seg(32.0, 40.0, "셋째 화면 설명")]},
        "images": _images(1),
    }
    doc = context.render(metadata, "v.mkv")
    assert doc.count("## ") == 3, "이미지 없는 화면도 자리를 지킨다"
    assert "둘째 화면 설명" in doc and "셋째 화면 설명" in doc, "대사가 사라지면 안 된다"
    # 이미지는 자기 화면에만 붙는다 — 남의 그림을 빌려 오지 않는다.
    # 가리키는 것은 읽기용 사본(read/)이고 파일명은 원본과 같다.
    assert doc.count("![](read/a.jpg)") == 1
    assert doc.count("(그림 없음") == 2
    # 어두워서 못 뽑은 화면은 그림 없이 대사만
    assert "그림 없음" in doc


def test_context_groups_images_by_screen():
    metadata = {
        "source": {"duration": 50.0},
        "screens": [[0.0, 10.0], [10.1, 30.0]],
        "frames": [
            {"time": 0.5, "image": "frames/a.jpg", "screen": 0,
             "interval": [0.0, 10.0], "dialogue": [_seg(0.0, 8.0, "첫 화면")]},
            {"time": 9.97, "image": "frames/b.jpg", "screen": 0,
             "interval": [0.0, 10.0], "dialogue": [_seg(0.0, 8.0, "첫 화면")]},
            {"time": 10.1, "image": "frames/c.jpg", "screen": 1,
             "interval": [10.1, 30.0], "dialogue": []},
        ],
        "transcript": {"segments": [_seg(0.0, 8.0, "첫 화면")]},
        "images": _images(3),
    }
    doc = context.render(metadata, "lecture.mkv")
    assert doc.count("## ") == 2, "화면 단위여야 한다 — 프레임 3장에 화면 2개"
    assert doc.count("![](") == 3, "이미지는 전부 실린다"
    assert doc.count("첫 화면") == 1, "같은 대사가 두 번 실리면 안 된다"
    assert "(무음)" in doc, "대사 없는 화면도 자리를 지킨다"
    assert "read/b.jpg" in doc

    # 참조는 **읽기용 사본만** 가리킨다. 원본(frames/)을 가리키면 읽는 쪽이
    # 4.17배 비싼 것을 열게 되고, 축소 사본을 만든 이유가 사라진다.
    assert doc.count("![](read/") == 3 and "![](frames/" not in doc
    # 비용 문단 — 몇 장인지만 적고 얼마인지 안 적으면 "골라 열어라"는 안내에
    # 근거가 없다. 768x432 세 장 = 442*3토큰.
    assert "768px" in doc and "1,326" in doc, "장수와 토큰이 함께 있어야 한다"
    # 진단 데이터는 들어가지 않는다
    for noise in ("yavg", "content_area", "reject", "blank", "anchor_threshold"):
        assert noise not in doc, f"AI용 파일에 {noise}가 새어 들어갔다"


def test_context_stops_instead_of_regrouping_without_screen_keys():
    """screens[]·frames[].screen·transcript·images가 없으면 그 자리에서 멈춘다.

    구간·시각 같은 대체 키로 되짚으면 묶기가 조용히 무력화된다(실측 사고).
    옛 산출물은 load_metadata가 exit 2로 거부하므로, 여기까지 온 metadata에
    키가 없다는 것은 코드의 버그다 — 조용히 렌더하지 말고 터져야 한다."""
    metadata = {
        "source": {"duration": 30.0},
        "screens": [[0.0, 10.0], [10.1, 30.0]],
        "frames": [{"time": 0.5, "image": "frames/a.jpg", "screen": 0,
                    "interval": [0.0, 10.0], "dialogue": []}],
        "transcript": {"segments": [_seg(0.0, 8.0, "첫 화면"),
                                    _seg(12.0, 20.0, "둘째 화면")]},
        "images": _images(1),
    }
    assert context.render(metadata, "v.mkv").count("## ") == 2  # 온전하면 렌더된다

    with pytest.raises(KeyError):
        context.render({k: v for k, v in metadata.items() if k != "screens"}, "v.mkv")
    with pytest.raises(KeyError):
        context.render({**metadata, "frames": [
            {k: v for k, v in f.items() if k != "screen"}
            for f in metadata["frames"]]}, "v.mkv")
    # 키만 있고 비어 있어도 마찬가지 — 프레임을 들고 섹션이 0개면 유실이다
    with pytest.raises(IndexError):
        context.render({**metadata, "screens": []}, "v.mkv")
    # 전사도 같다. 없는 셈 치고 넘어가면 대사 0줄짜리 문서가 정상 종료로 나가고,
    # 그것을 읽는 에이전트는 말이 없는 강의였다고 믿는다.
    with pytest.raises(KeyError):
        context.render({k: v for k, v in metadata.items() if k != "transcript"}, "v.mkv")
    # 읽기 예산도 폴백을 두지 않는다. 기본값으로 때우면 다른 --read-long-edge로
    # 만든 산출물이 남의 숫자를 자기 비용이라고 적는다 — 틀린 비용은 없는 비용보다
    # 나쁘다(읽는 쪽이 그 값을 믿고 예산을 짠다).
    with pytest.raises(KeyError):
        context.render({k: v for k, v in metadata.items() if k != "images"}, "v.mkv")


def test_context_write_creates_file(tmp_path):
    metadata = {"source": {"duration": 5.0},
                "screens": [[0.0, 5.0]],
                "frames": [{"time": 1.0, "image": "frames/a.jpg", "screen": 0,
                            "interval": [0.0, 5.0], "dialogue": []}],
                "transcript": {"segments": []},
                "images": _images(1)}
    p = context.write(tmp_path, metadata, "v.mkv")
    assert p.name == "context.md" and p.read_text(encoding="utf-8").startswith("# v.mkv")


def test_context_is_far_smaller_than_metadata():
    """AI용 파일이 전체 기록보다 작지 않으면 존재 이유가 없다."""
    segs = [_seg(i, i + 1, "가나다라마바사아자차카타파하" * 3) for i in range(200)]
    metadata = {
        "source": {"duration": 200.0},
        "screens": [[float(i), i + 1.0] for i in range(200)],
        "frames": [{"time": float(i), "image": f"frames/{i}.jpg", "screen": i,
                    "interval": [float(i), i + 1.0], "dialogue": [segs[i]],
                    "yavg": 123.45, "hash": "0" * 16, "sources": ["anchor-diff"]}
                   for i in range(200)],
        "rejected": [{"time": float(i), "reject_reason": "blank(<=0.001)"}
                     for i in range(200)],
        "transcript": {"backend": "mlx", "model": "tiny", "text": " ".join(
            s["text"] for s in segs), "segments": segs},
        "params": {"anchor_threshold": 0.02},
        "images": _images(200),
    }
    doc = context.render(metadata, "v.mkv")
    full = json.dumps(metadata, ensure_ascii=False)
    assert len(doc) < len(full) * 0.5, (
        f"context.md {len(doc)}자 vs metadata {len(full)}자 — 절반 미만이어야 한다")
