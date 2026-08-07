from pathlib import Path

from . import ffutil


def merge_impact_frames(video_path: Path, out_dir: Path, scene_candidates: list[dict],
                         emphasis_points: list[dict], duration: float,
                         near_distance: float = 2.0, yavg_floor: float = 5.0) -> list[dict]:
    """오디오 임팩트 시점을 영상 후보에 합친다.
    기존 후보와 가까우면(near_distance 이내) 새 프레임을 만들지 않고 태그만 붙인다."""
    result = [dict(c) for c in scene_candidates]

    for e in emphasis_points:
        t = e["time"]
        near = next((c for c in result if abs(c["time"] - t) <= near_distance), None)
        if near is not None:
            near["impact"] = True
            near["impact_score"] = max(near.get("impact_score", 0.0), e["score"])
            continue

        stable_t = min(t + 0.3, duration - 0.05)
        img_path = out_dir / f"impact_{stable_t:07.2f}.jpg"
        if not ffutil.extract_frame(video_path, stable_t, img_path):
            continue
        y = ffutil.yavg(img_path)
        if y < yavg_floor:
            img_path.unlink()
            continue
        result.append({
            "time": stable_t, "detected_at": t, "path": str(img_path), "yavg": y,
            "hash": str(ffutil.phash(img_path)), "impact": True, "impact_score": e["score"],
        })

    return sorted(result, key=lambda c: c["time"])


def build_alignment_table(candidates: list[dict], words: list[dict]) -> list[dict]:
    table = []
    for c in candidates:
        nearest = min(words, key=lambda w: abs(w["start"] - c["time"])) if words else None
        table.append({
            "frame_time": c["time"],
            "nearest_word": nearest["word"] if nearest else None,
            "nearest_word_time": nearest["start"] if nearest else None,
            "gap_seconds": abs(nearest["start"] - c["time"]) if nearest else None,
        })
    return table
