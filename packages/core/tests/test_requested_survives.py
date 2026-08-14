"""주문형 추출(frame --at)은 단위 재계산에서 살아남아야 한다.

임계를 조정하며 frames를 다시 돌리는 것은 정상적인 사용 흐름이다. 그때마다
requested/가 사라지면 "context.md를 읽고 필요한 프레임을 손으로 더 뽑는다"는
설계가 무너진다 — 뽑은 이미지뿐 아니라 왜 뽑았는지(--reason)라는 근거까지
없어지기 때문이다. 반대로 검출기의 판정(frames/·frames.json·metadata.json)은
반드시 갈아엎어야 이전 임계의 흔적이 섞이지 않는다.
"""
import json
from pathlib import Path

from analysis_video import budget, manifest, runs
from analysis_video.cli import _merge_requested, _recompute_request


def _unit_with_leftovers(tmp_path):
    unit = tmp_path / "runs" / "full"
    (unit / "frames").mkdir(parents=True)
    (unit / "frames" / "scene_000.jpg").write_bytes(b"old")
    # 읽기용 사본도 검출기의 판정물이다 — 원본 프레임과 짝이므로 함께 갈아엎어야
    # 새 임계로 뽑은 것과 이전 임계의 사본이 같은 디렉터리에 섞이지 않는다.
    (unit / budget.READ_DIRNAME).mkdir()
    (unit / budget.READ_DIRNAME / "scene_000.jpg").write_bytes(b"old-copy")
    (unit / "metadata.json").write_text("{}", encoding="utf-8")
    req = unit / runs.REQUESTED
    req.mkdir()
    (req / "req_0042.10.jpg").write_bytes(b"ordered")
    (req / "requests.json").write_text("[]", encoding="utf-8")
    return unit


def test_reset_keeps_orders_and_drops_verdicts(tmp_path):
    unit = _unit_with_leftovers(tmp_path)
    runs.reset_unit(unit)

    assert (unit / runs.REQUESTED / "req_0042.10.jpg").read_bytes() == b"ordered"
    assert (unit / runs.REQUESTED / "requests.json").exists()
    assert not (unit / "frames").exists(), "이전 판정은 남으면 안 된다"
    assert not (unit / budget.READ_DIRNAME).exists(), "사본도 판정물이다"
    assert not (unit / "metadata.json").exists()


def test_reset_on_a_missing_unit_just_creates_it(tmp_path):
    unit = tmp_path / "runs" / "full"
    runs.reset_unit(unit)
    assert unit.is_dir() and not any(unit.iterdir())


def test_interrupted_reset_is_recovered_on_the_next_run(tmp_path):
    """빼놓고 죽은 보관본은 다음 실행이 되돌린다 — 타임아웃 재실행이 이력을
    삼키면 재개 가능하다는 계약이 거짓이 된다."""
    unit = tmp_path / "runs" / "full"
    unit.mkdir(parents=True)
    stash = unit.parent / f".{unit.name}.{runs.REQUESTED}"
    stash.mkdir()
    (stash / "requests.json").write_text("[1]", encoding="utf-8")

    runs.reset_unit(unit)

    assert (unit / runs.REQUESTED / "requests.json").read_text(encoding="utf-8") == "[1]"
    assert not stash.exists()


def test_stash_directory_is_not_mistaken_for_a_run(tmp_path):
    """보관본은 runs/ 안에 잠깐 생긴다 — 인덱스가 그걸 단위로 세면 안 된다."""
    unit = _unit_with_leftovers(tmp_path)
    (unit.parent / f".{unit.name}.{runs.REQUESTED}").mkdir()
    got = runs.merge_index(tmp_path, [{"name": "full", "range": None}])
    assert [e["name"] for e in got] == ["full"]


def _metadata(frames, segments):
    return {"source": {"duration": 100.0}, "frames": frames,
            "transcript": {"segments": segments}}


def test_surviving_ledger_is_recomputed_against_the_new_frames(tmp_path):
    """살려낸 장부는 그대로 쓰면 안 된다 — 프레임 집합이 바뀌었으므로 구간·대사를
    다시 계산해야 같은 시각에 두 가지 대사 묶음이 생기지 않는다."""
    unit = tmp_path / "runs" / "full"
    (unit / runs.REQUESTED).mkdir(parents=True)
    old = [{"at": 42.0, "time": 42.1, "reason": "칠판 완성",
            "image": "requested/req_0042.10.jpg",
            "interval": [40.0, 45.0], "dialogue": [], "said_at": ""}]
    (unit / runs.REQUESTED / "requests.json").write_text(
        json.dumps(old, ensure_ascii=False), encoding="utf-8")

    segments = [{"start": 41.0, "end": 43.0, "text": "이 항을 정리하면"}]
    metadata = _metadata(
        [{"time": 30.0, "image": "frames/a.jpg", "interval": [30.0, 60.0],
          "dialogue": segments}], segments)
    _merge_requested(unit, metadata)

    entry = metadata["requested"][0]
    assert entry["interval"] == [30.0, 60.0], "새 프레임의 구간을 따라야 한다"
    assert entry["dialogue"] == segments
    assert entry["said_at"] == "이 항을 정리하면", "주문 시각의 말은 따로 남는다"
    # 장부 파일 자체도 갱신된다 — 다음 재계산의 입력이므로 stale하면 안 된다
    saved = json.loads((unit / runs.REQUESTED / "requests.json").read_text(encoding="utf-8"))
    assert saved[0]["interval"] == [30.0, 60.0]


def test_request_between_screens_attaches_to_the_nearest_frame():
    """전환 구간(화면과 화면 사이)에 떨어진 주문도 구간 없이 남으면 안 된다."""
    segments = [{"start": 9.0, "end": 11.0, "text": "다음 장"}]
    metadata = _metadata(
        [{"time": 0.0, "image": "frames/a.jpg", "interval": [0.0, 9.9],
          "dialogue": segments},
         {"time": 20.0, "image": "frames/b.jpg", "interval": [20.0, 40.0],
          "dialogue": []}], segments)
    entry = {"at": 10.0, "time": 10.0, "reason": "전환 직후"}
    _recompute_request(entry, metadata)
    assert entry["interval"] == [0.0, 9.9], "가장 가까운 화면에 붙는다"


def test_metadata_always_carries_the_requested_key():
    """주문이 없어도 키는 있어야 소비자가 조건 없이 읽는다 — 주문이 생겼을 때만
    나타나는 칸이면 읽는 쪽마다 유무 검사를 달게 되고, 그 검사가 빠진 곳은
    주문이 처음 들어오는 날에야 드러난다."""
    # images는 build_frames가 만든 **읽기용 사본들의 요약**이다. 프레임이 하나도
    # 없는 실행이면 사본도 없으므로 빈 목록의 요약(count·tokens 0)이 맞다.
    build = {"records": [], "duration": 10.0, "fps": 30.0, "params": {},
             "window": [0.0, 10.0], "images": budget.summary([])}
    transcript = {"backend": "none", "model": "none", "text": "", "segments": []}
    metadata = manifest.build_metadata(Path("v.mp4"), transcript, build, [])
    assert metadata["requested"] == []
