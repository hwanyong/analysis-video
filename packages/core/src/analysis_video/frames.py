"""프레임 후보 통합 — initial ∪ anchor-diff ∪ AdaptiveDetector ∪ importance-points.

판정 기록 보존 원칙: 어떤 후보도 조용히 사라지지 않는다. 탈락 이미지는
frames/rejected/로 이동하고 레코드에 사유가 남으며, phash 중복으로 탈락해도
출처(sources)·근거(reasons)·point_times는 생존 레코드로 승계된다.
importance-point를 품고 있던 후보가 어두움/추출실패로 탈락하면 point 자체
시각에서 폴백 재캡처를 시도한다 — 문서화된 계약(reason은 metadata에 보존)의 이행.

파일명은 순번 기반(scene_003_t0012.33.jpg)이라 시각 반올림 충돌이 불가능하다.
검출기 결과는 out_dir에 캐시(detect_anchor.npz, detect_adaptive.json)되어
재실행 시 전체 디코드를 건너뛴다 — 긴 영상에서 타임아웃으로 잘린 frames를
재호출하면 검출부터가 아니라 추출부터 이어지는 효과.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from . import media
from .detect import adaptive, anchor
from .errors import log

# 프레임 번호를 실제 PTS로 옮기게 된 이후의 adaptive 캐시 (v1은 선언 fps 근사였다)
ADAPTIVE_SCHEMA = "adaptive/2"


def _gray_for_compare(img_path: Path, w: int = 400, h: int = 225) -> np.ndarray:
    return np.asarray(Image.open(img_path).convert("L").resize((w, h)))


def _cached_anchor(video_path: Path, out_dir: Path,
                   cum_threshold: float, rate_threshold: float) -> dict:
    cache = out_dir / "detect_anchor.npz"
    if cache.exists():
        # 캐시는 수치 배열 + JSON 문자열(유니코드 배열)만 담는다 — pickle 불필요/금지
        data = np.load(cache)
        if (float(data["cum_threshold"]) == cum_threshold
                and float(data["rate_threshold"]) == rate_threshold
                and "events_json" in data):
            log("[frames] anchor-diff 캐시 재사용 (detect_anchor.npz)")
            return {
                "fps": float(data["fps"]), "n_frames": int(data["cum_series"].shape[0]),
                "cum_series": data["cum_series"], "rate_series": data["rate_series"],
                "time_series": data["time_series"],
                "events": json.loads(str(data["events_json"])),
                "cum_threshold": cum_threshold, "rate_threshold": rate_threshold,
            }

    log("[frames] anchor-diff 전환추적 실행 중...")
    result = anchor.transition_aware_anchor_diff(
        video_path, cum_threshold=cum_threshold, rate_threshold=rate_threshold)
    np.savez_compressed(
        cache,
        cum_series=result["cum_series"], rate_series=result["rate_series"],
        time_series=result["time_series"], fps=result["fps"],
        cum_threshold=cum_threshold, rate_threshold=rate_threshold,
        events_json=json.dumps(result["events"]))
    return result


def _cached_adaptive(video_path: Path, out_dir: Path, duration: float,
                     frame_times) -> list[dict]:
    cache = out_dir / "detect_adaptive.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        # v1은 선언 fps로 시각을 계산해 컨테이너 헤더가 틀리면 통째로 밀려 있었다.
        # 버전이 없으면 그 산출물이므로 버리고 다시 검출한다 — 조용히 재사용하면
        # 수정이 기존 분석에는 영원히 적용되지 않는다.
        if isinstance(cached, dict) and cached.get("schema") == ADAPTIVE_SCHEMA:
            log("[frames] AdaptiveDetector 캐시 재사용 (detect_adaptive.json)")
            return cached["entries"]
        log("[frames] AdaptiveDetector 캐시가 구버전 — 재검출합니다")

    log("[frames] AdaptiveDetector 실행 중...")
    entries = []
    # 프레임 번호 → 실제 PTS 변환에 anchor-diff가 이미 만든 time_series를 넘긴다.
    # 선언 fps 근사를 쓰면 컨테이너 헤더가 틀렸을 때 시각이 통째로 밀린다.
    for t in adaptive.adaptive_detector_candidates(video_path, frame_times=frame_times):
        # AdaptiveDetector는 자체 전환추적이 없어 사후 안정화가 필요
        stable = adaptive.pick_stable_time(video_path, t, duration)
        entries.append({"detected_at": t, "time": stable})
    cache.write_text(json.dumps({"schema": ADAPTIVE_SCHEMA, "entries": entries}),
                     encoding="utf-8")
    return entries


def build_frames(video_path: Path, out_dir: Path, points: list[dict], *,
                 cum_threshold: float = 0.02, rate_threshold: float = 0.0015,
                 yavg_floor: float = 5.0, phash_dup_distance: int = 4,
                 ssim_dup_threshold: float = 0.9,
                 near_distance: float = 2.0) -> dict:
    frames_dir = out_dir / "frames"
    rejected_dir = frames_dir / "rejected"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    duration = media.get_duration(video_path)

    anchor_result = _cached_anchor(video_path, out_dir, cum_threshold, rate_threshold)
    fps = anchor_result["fps"]

    def new_candidate(time: float, detected_at: float, source: str) -> dict:
        return {"time": time, "detected_at": detected_at,
                "sources": [source], "reasons": [], "point_times": []}

    # 첫 슬라이드(t≈0)는 어떤 검출기도 방출하지 않는다 — 명시적 시드.
    # 오프닝 페이드 대비로 안정화를 거친다; 어두우면 게이트가 사유와 함께 걸러준다.
    initial_t = adaptive.pick_stable_time(video_path, 0.0, duration, offset=0.5)
    candidates = [new_candidate(initial_t, 0.0, "initial")]

    for e in anchor_result["events"]:
        # 전환추적된 트리거는 이미 안정 상태에서 잡힌 것 — 추가 안정화 불필요
        t = e.get("trigger_time", e["trigger_idx"] / fps)
        candidates.append(new_candidate(t, t, "anchor-diff"))

    for entry in _cached_adaptive(video_path, out_dir, duration,
                                  anchor_result["time_series"]):
        candidates.append(new_candidate(entry["time"], entry["detected_at"], "adaptive"))

    # importance-points 병합: 기존 후보와 가까우면 태그만 붙이고, 멀면 새로 캡처
    for p in points:
        near = min(candidates, key=lambda c: abs(c["time"] - p["time"]), default=None)
        if near is not None and abs(near["time"] - p["time"]) <= near_distance:
            if "importance-point" not in near["sources"]:
                near["sources"].append("importance-point")
            near["reasons"].append(p["reason"])
            near["point_times"].append(p["time"])
        else:
            t = min(p["time"] + 0.3, duration - 0.05)
            c = new_candidate(t, p["time"], "importance-point")
            c["reasons"] = [p["reason"]]
            c["point_times"] = [p["time"]]
            candidates.append(c)

    log(f"[frames] 후보 {len(candidates)}건 추출·게이트 판정 중...")
    records: list[dict] = []
    accepted: list[dict] = []

    def gate(c: dict, img: Path) -> None:
        """추출→YAVG→phash 게이트. 판정을 c에 기록하고 records/accepted를 갱신한다."""
        c["image"] = img.relative_to(out_dir).as_posix()
        if not media.extract_frame(video_path, c["time"], img):
            c.update(status="rejected", reject_reason="extract-failed", image=None)
            records.append(c)
            return
        y = media.yavg(img)
        c["yavg"] = round(y, 2)
        if y < yavg_floor:
            dst = rejected_dir / img.name
            img.rename(dst)
            c.update(status="rejected", reject_reason=f"yavg-dark(<{yavg_floor})",
                     image=dst.relative_to(out_dir).as_posix())
            records.append(c)
            return
        h = media.phash(img)
        # 2단 중복 게이트: pHash는 저주파 구조만 봐서 "같은 레이아웃, 다른 내용"
        # (필기 추가·어두운 애니메이션)을 중복으로 오판한다 — 실측 29건 중 8건 오병합.
        # pHash를 싼 사전 필터로만 쓰고 SSIM(≥ssim_dup_threshold)으로 확증한다.
        dup = next(
            (a for a in accepted
             if h - a["_hash"] <= phash_dup_distance
             and ssim(_gray_for_compare(img),
                      _gray_for_compare(out_dir / a["image"])) >= ssim_dup_threshold),
            None)
        if dup is not None:
            dst = rejected_dir / img.name
            img.rename(dst)
            # 중복 탈락이라도 출처·근거는 생존 레코드로 승계 — provenance 소실 금지
            for s in c["sources"]:
                if s not in dup["sources"]:
                    dup["sources"].append(s)
            dup["reasons"].extend(r for r in c["reasons"] if r not in dup["reasons"])
            dup["point_times"].extend(t for t in c["point_times"] if t not in dup["point_times"])
            # dup_of는 사유 문자열과 별개의 기계 판독용 필드다. 소비자가 "of=…"를
            # 정규식으로 되파싱하게 두면 표현이 바뀔 때마다 조용히 끊긴다.
            c.update(status="rejected", reject_reason=f"phash-dup(of={dup['time']:.2f})",
                     dup_of=round(dup["time"], 2),
                     image=dst.relative_to(out_dir).as_posix())
            records.append(c)
            return
        c["_hash"] = h
        c["status"] = "accepted"
        accepted.append(c)
        records.append(c)

    # 순번 기반 파일명 — 시각 반올림 충돌로 채택 이미지가 덮어써지는 사고를 차단
    for seq, c in enumerate(sorted(candidates, key=lambda c: c["time"])):
        prefix = "point" if c["sources"] == ["importance-point"] else "scene"
        gate(c, frames_dir / f"{prefix}_{seq:03d}_t{c['time']:07.2f}.jpg")

    # importance-point 폴백: 병합 호스트가 어두움/추출실패로 탈락하면 point 자체
    # 시각에서 재캡처를 시도한다 (phash-dup 탈락은 승계가 끝났으므로 제외)
    lost_points = []
    for r in records:
        if r["status"] == "rejected" and r["point_times"] \
                and not r["reject_reason"].startswith("phash-dup"):
            for pt, reason in zip(r["point_times"], r["reasons"]):
                lost_points.append((pt, reason))
    for seq, (pt, reason) in enumerate(lost_points):
        t = min(pt + 0.3, duration - 0.05)
        c = new_candidate(t, pt, "importance-point")
        c["reasons"] = [reason]
        c["point_times"] = [pt]
        c["fallback"] = True
        log(f"[frames] importance-point 폴백 재캡처: t={pt:.2f}")
        gate(c, frames_dir / f"point_fb{seq:02d}_t{t:07.2f}.jpg")

    records.sort(key=lambda r: r["time"])
    for r in accepted:
        r["hash"] = str(r.pop("_hash"))

    log(f"[frames] 완료: 채택 {len(accepted)}건 / 탈락 {len(records) - len(accepted)}건")
    return {
        "records": records, "duration": duration, "fps": fps,
        "anchor_events": anchor_result["events"],
        "params": {
            "cum_threshold": cum_threshold, "rate_threshold": rate_threshold,
            "yavg_floor": yavg_floor, "phash_dup_distance": phash_dup_distance,
            "ssim_dup_threshold": ssim_dup_threshold,
            "near_distance": near_distance,
        },
    }
