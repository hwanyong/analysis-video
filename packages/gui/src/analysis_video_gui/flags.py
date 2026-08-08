"""사용자 GT(ground truth) 플래그 — "여기서 이미지가 추출됐어야 한다"는 사람의 기준.

로직(anchor-diff·adaptive)이 뽑은 프레임이 옳은지는 로직 자신이
판정할 수 없다. 사람이 영상을 보며 "이 장면은 반드시 필요하다"를 찍어 두면,
그것이 정답지(ground truth)가 되어 검출 결과와 허용오차 내 매칭된다 —
놓친 것은 recall, 쓸데없이 뽑은 것은 precision으로 나온다. 임계값 튜닝을
감이 아니라 수치로 하기 위한 장치다. user_flags.json에 저장된다.
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
        self.path.parent.mkdir(parents=True, exist_ok=True)  # 미분석 세션에서도 기입 가능
        write_json_atomic(self.path, {"flags": self.flags})
        self.changed.emit()

    def add(self, time: float, note: str = "", dedupe_within: float = 0.25) -> None:
        t = round(time, 2)
        # F 연타(특히 일시정지 중)로 사실상 같은 시각이 중복 기입되는 것을 막는다
        if any(abs(f["time"] - t) <= dedupe_within for f in self.flags):
            return
        self.flags.append({"time": t, "note": note})
        self.flags.sort(key=lambda f: f["time"])
        self._save()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.flags):
            del self.flags[index]
            self._save()

    def index_at(self, time: float, within: float = 0.6) -> int | None:
        """time에서 within 안의 최근접 플래그 — 없으면 None."""
        if not self.flags:
            return None
        i = min(range(len(self.flags)), key=lambda i: abs(self.flags[i]["time"] - time))
        return i if abs(self.flags[i]["time"] - time) <= within else None

    def toggle(self, time: float, note: str = "", within: float = 0.6) -> bool:
        """근처에 이미 있으면 제거, 없으면 추가 — 만든 자리에서 바로 취소된다.

        기입 수단(F키·타임라인)과 취소 수단이 다른 창에 있으면 되돌릴 길이
        없는 것과 같다. 반환값은 '추가되었는가'."""
        i = self.index_at(time, within)
        if i is not None:
            self.remove(i)
            return False
        self.add(time, note)
        return True

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
