"""사용자 GT(ground truth) 플래그 — "여기서 이미지가 추출됐어야 한다"는 사람의 기준.

user_flags.json에 저장하고, 로직 검출(채택 프레임)과 허용오차 내 매칭해
precision/recall을 산출한다. 초기 기획의 "사용자 플래그 vs 로직 추출 비교" 요건.
"""
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from analysis_video.manifest import write_json_atomic


class FlagStore(QObject):
    changed = Signal()

    def __init__(self, out_dir: Path, parent=None):
        super().__init__(parent)
        self.path = out_dir / "user_flags.json"
        self.flags: list[dict] = []  # [{"time": float, "note": str}]
        if self.path.exists():
            try:
                self.flags = json.loads(self.path.read_text(encoding="utf-8"))["flags"]
            except Exception:
                self.flags = []

    def _save(self) -> None:
        write_json_atomic(self.path, {"flags": self.flags})
        self.changed.emit()

    def add(self, time: float, note: str = "") -> None:
        self.flags.append({"time": round(time, 2), "note": note})
        self.flags.sort(key=lambda f: f["time"])
        self._save()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.flags):
            del self.flags[index]
            self._save()

    def times(self) -> list[float]:
        return [f["time"] for f in self.flags]


def compare_metrics(flag_times: list[float], detected_times: list[float],
                    tolerance: float) -> dict:
    """GT 플래그 ↔ 검출 프레임 매칭 지표. 각 플래그는 허용오차 내 최근접 검출과 매칭."""
    matched_flags = []
    unmatched_flags = []
    for ft in flag_times:
        best = min(detected_times, key=lambda d: abs(d - ft), default=None)
        if best is not None and abs(best - ft) <= tolerance:
            matched_flags.append({"flag": ft, "detected": best, "gap": round(best - ft, 2)})
        else:
            unmatched_flags.append(ft)

    matched_det = {m["detected"] for m in matched_flags}
    false_positives = [d for d in detected_times
                       if not any(abs(d - ft) <= tolerance for ft in flag_times)]

    n_f, n_d = len(flag_times), len(detected_times)
    recall = len(matched_flags) / n_f if n_f else None
    precision = (n_d - len(false_positives)) / n_d if n_d else None
    return {
        "tolerance": tolerance,
        "n_flags": n_f, "n_detected": n_d,
        "matched": matched_flags,
        "missed_flags": unmatched_flags,          # FN: 사람은 원했는데 로직이 못 뽑음
        "extra_detected": false_positives,        # FP: 로직이 뽑았지만 사람 기준엔 없음
        "precision": None if precision is None else round(precision, 3),
        "recall": None if recall is None else round(recall, 3),
    }
