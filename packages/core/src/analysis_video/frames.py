"""프레임 후보 통합 — anchor-diff ∪ AdaptiveDetector ∪ importance-points.

판정 기록 보존 원칙: 어떤 후보도 조용히 사라지지 않는다(프로토타입의 unlink 폐기
리팩터). 탈락 이미지는 frames/rejected/로 이동하고 레코드에 사유가 남으며,
phash 중복으로 탈락해도 출처(sources)·근거(reasons)는 생존 레코드로 승계된다.
검출 시계열은 detect_anchor.npz로 캐시해 debug-report/GUI가 재계산 없이 쓴다.
"""
from pathlib import Path

import numpy as np

from . import media
from .detect import adaptive, anchor
from .errors import log


def build_frames(video_path: Path, out_dir: Path, points: list[dict], *,
                 cum_threshold: float = 0.02, rate_threshold: float = 0.0015,
                 yavg_floor: float = 5.0, phash_dup_distance: int = 4,
                 near_distance: float = 2.0) -> dict:
    frames_dir = out_dir / "frames"
    rejected_dir = frames_dir / "rejected"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    duration = media.get_duration(video_path)

    log("[frames] anchor-diff 전환추적 실행 중...")
    anchor_result = anchor.transition_aware_anchor_diff(
        video_path, cum_threshold=cum_threshold, rate_threshold=rate_threshold)
    fps = anchor_result["fps"]
    np.savez_compressed(
        out_dir / "detect_anchor.npz",
        cum_series=anchor_result["cum_series"], rate_series=anchor_result["rate_series"],
        fps=fps, cum_threshold=cum_threshold, rate_threshold=rate_threshold)

    candidates = []
    for e in anchor_result["events"]:
        t = e["trigger_idx"] / fps
        # 전환추적된 트리거는 이미 안정 상태에서 잡힌 것 — 추가 안정화 불필요
        candidates.append({"time": t, "detected_at": t,
                          "sources": ["anchor-diff"], "reasons": [], "point_times": []})

    log("[frames] AdaptiveDetector 실행 중...")
    for t in adaptive.adaptive_detector_candidates(video_path):
        # AdaptiveDetector는 자체 전환추적이 없어 사후 안정화가 필요
        stable = adaptive.pick_stable_time(video_path, t, duration)
        candidates.append({"time": stable, "detected_at": t,
                          "sources": ["adaptive"], "reasons": [], "point_times": []})

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
            candidates.append({"time": t, "detected_at": p["time"],
                              "sources": ["importance-point"], "reasons": [p["reason"]],
                              "point_times": [p["time"]]})

    log(f"[frames] 후보 {len(candidates)}건 추출·게이트 판정 중...")
    records: list[dict] = []
    accepted: list[dict] = []
    for c in sorted(candidates, key=lambda c: c["time"]):
        prefix = "point" if c["sources"] == ["importance-point"] else "scene"
        img = frames_dir / f"{prefix}_{c['time']:07.2f}.jpg"
        rec = dict(c)
        rec["image"] = str(img.relative_to(out_dir))

        if not media.extract_frame(video_path, c["time"], img):
            rec.update(status="rejected", reject_reason="extract-failed", image=None)
            records.append(rec)
            continue

        y = media.yavg(img)
        rec["yavg"] = round(y, 2)
        if y < yavg_floor:
            dst = rejected_dir / img.name
            img.rename(dst)
            rec.update(status="rejected", reject_reason=f"yavg-dark(<{yavg_floor})",
                       image=str(dst.relative_to(out_dir)))
            records.append(rec)
            continue

        h = media.phash(img)
        dup = next((a for a in accepted if h - a["_hash"] <= phash_dup_distance), None)
        if dup is not None:
            dst = rejected_dir / img.name
            img.rename(dst)
            # 중복 탈락이라도 출처·근거는 생존 레코드로 승계 — provenance 소실 금지
            for s in rec["sources"]:
                if s not in dup["sources"]:
                    dup["sources"].append(s)
            dup["reasons"].extend(r for r in rec["reasons"] if r not in dup["reasons"])
            dup["point_times"].extend(t for t in rec["point_times"] if t not in dup["point_times"])
            rec.update(status="rejected", reject_reason=f"phash-dup(of={dup['time']:.2f})",
                       image=str(dst.relative_to(out_dir)))
            records.append(rec)
            continue

        rec["_hash"] = h
        rec["status"] = "accepted"
        accepted.append(rec)
        records.append(rec)

    for r in accepted:
        r["hash"] = str(r.pop("_hash"))

    log(f"[frames] 완료: 채택 {len(accepted)}건 / 탈락 {len(records) - len(accepted)}건")
    return {
        "records": records, "duration": duration, "fps": fps,
        "anchor_events": anchor_result["events"],
        "params": {
            "cum_threshold": cum_threshold, "rate_threshold": rate_threshold,
            "yavg_floor": yavg_floor, "phash_dup_distance": phash_dup_distance,
            "near_distance": near_distance,
        },
    }
