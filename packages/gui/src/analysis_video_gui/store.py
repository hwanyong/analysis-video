"""`.analysis/` 산출물 로더 — 코어가 만든 파일을 읽기만 한다(재구현 0).

GUI에 보이는 것 = 실제 파이프라인 산출물이 되도록 metadata.json / frames.json /
transcript.json / detect_anchor.npz 를 그대로 노출하고, 파일 변경을 감시해
CLI가 재분석하면 자동으로 갱신 신호를 낸다.
"""
import bisect
import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from analysis_video import media


class Store(QObject):
    reloaded = Signal()

    def __init__(self, video_path: Path, out_dir: Path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.out_dir = out_dir

        self.metadata: dict = {}
        self.frames: list[dict] = []       # 채택 프레임 (시간순)
        self.rejected: list[dict] = []
        self.requested: list[dict] = []
        self.segments: list[dict] = []
        self.series: dict | None = None    # times/cum/rate/cum_threshold/rate_threshold
        self.duration: float = 0.0
        self.point_times: list[float] = []

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self.reload)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.addPath(str(out_dir))
        for name in ("metadata.json", "transcript.json"):
            p = out_dir / name
            if p.exists():
                self._watcher.addPath(str(p))
        self._watcher.directoryChanged.connect(lambda _: self._debounce.start())
        self._watcher.fileChanged.connect(lambda _: self._debounce.start())

        self.reload()

    # ---------- 로드 ----------

    def reload(self) -> None:
        self.metadata = self._read_json("metadata.json") or {}
        self.frames = self.metadata.get("frames", [])
        self.rejected = self.metadata.get("rejected", [])
        self.requested = self.metadata.get("requested", [])
        transcript = self._read_json("transcript.json") or {}
        self.segments = transcript.get("segments",
                                       self.metadata.get("transcript", {}).get("segments", []))
        self.duration = float(self.metadata.get("source", {}).get("duration", 0.0))
        if not self.duration:
            try:
                self.duration = media.get_duration(self.video_path)
            except Exception:
                self.duration = 0.0

        npz = self.out_dir / "detect_anchor.npz"
        self.series = None
        if npz.exists():
            try:
                d = np.load(npz)
                fps = float(d["fps"])
                n = len(d["cum_series"])
                times = d["time_series"] if "time_series" in d else np.arange(n) / fps
                self.series = {
                    "times": times, "cum": d["cum_series"], "rate": d["rate_series"],
                    "cum_threshold": float(d["cum_threshold"]),
                    "rate_threshold": float(d["rate_threshold"]),
                }
            except Exception:
                self.series = None

        self._frame_starts = [f["time"] for f in self.frames]
        self._seg_starts = [s["start"] for s in self.segments]
        self.point_times = sorted(
            t for f in self.frames + self.rejected for t in f.get("point_times", []))
        self.reloaded.emit()

    def _read_json(self, name: str):
        p = self.out_dir / name
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # CLI가 쓰는 도중일 수 있음 — 다음 감시 이벤트에서 재시도

    # ---------- 시간 조회 (동기 패널들의 공용 프리미티브) ----------

    def frame_index_at(self, t: float) -> int | None:
        """t가 속한 채택 프레임 인덱스 — 프레임 i의 구간은 [time_i, time_{i+1}).
        metadata 시각은 2자리 반올림이라 실제 PTS와 최대 수십 ms 어긋난다 —
        경계에서 한 칸 이전 구간을 가리키지 않게 엡실론을 둔다."""
        i = bisect.bisect_right(self._frame_starts, t + 0.05) - 1
        return i if i >= 0 else None

    def segment_index_at(self, t: float) -> int | None:
        i = bisect.bisect_right(self._seg_starts, t) - 1
        if i >= 0 and self.segments[i]["end"] >= t:
            return i
        return None

    def rejected_in(self, start: float, end: float) -> list[dict]:
        return [r for r in self.rejected if start <= r["time"] < end]

    @staticmethod
    def _jump(sorted_times: list[float], t: float, forward: bool) -> float | None:
        eps = 0.05
        if forward:
            i = bisect.bisect_right(sorted_times, t + eps)
            return sorted_times[i] if i < len(sorted_times) else None
        i = bisect.bisect_left(sorted_times, t - eps) - 1
        return sorted_times[i] if i >= 0 else None

    def next_frame_time(self, t: float, forward: bool = True) -> float | None:
        return self._jump(self._frame_starts, t, forward)

    def next_point_time(self, t: float, forward: bool = True) -> float | None:
        return self._jump(self.point_times, t, forward)
