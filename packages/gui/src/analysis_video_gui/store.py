"""`.analysis/` 산출물 로더 — 코어가 만든 파일을 읽기만 한다(재구현 0).

GUI에 보이는 것 = 실제 파이프라인 산출물이 되도록 metadata.json / frames.json /
transcript.json / detect_anchor.npz 를 그대로 노출하고, 파일 변경을 감시해
CLI가 재분석하면 자동으로 갱신 신호를 낸다.
"""
import bisect
import json
from collections import Counter
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
        self.transitions: list[tuple[float, float]] = []  # (전환 시작, 트리거) 구간
        self.duration: float = 0.0
        self.point_times: list[float] = []        # 원시 point 시각 (★를 찍는 자리)
        self.point_landings: list[float] = []     # 그 point들이 만든 프레임 시각
        self.point_owner: dict[float, float] = {}

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self.reload)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_fs_event)
        self._watcher.fileChanged.connect(self._on_fs_event)
        self._rearm_watcher()

        self.reload()

    def _on_fs_event(self, _path: str) -> None:
        self._rearm_watcher()
        self._debounce.start()

    def _rearm_watcher(self) -> None:
        """감시 경로를 매번 다시 건다 — out_dir가 아직 없을 수도 있고(첫 분석 전),
        frames 재실행이 디렉토리를 지웠다 다시 만들면 기존 감시가 끊기기 때문."""
        watched = set(self._watcher.directories()) | set(self._watcher.files())
        targets = [self.out_dir.parent, self.out_dir,
                   self.out_dir / "metadata.json", self.out_dir / "transcript.json"]
        for p in targets:
            if p.exists() and str(p) not in watched:
                self._watcher.addPath(str(p))

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
        self.transitions = []
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
                # 앵커가 흔들리기 시작해(transition_start) 안정 판정으로 트리거되기까지의
                # 구간 — 검출기가 "왜 여기서 끊었는가"를 설명하는 유일한 증거다
                self.transitions = [
                    (float(e["transition_start_time"]), float(e["trigger_time"]))
                    for e in json.loads(str(d["events_json"]))]
            except Exception:
                self.series = None

        self._frame_starts = [f["time"] for f in self.frames]
        self._seg_starts = [s["start"] for s in self.segments]
        # 같은 importance-point가 탈락 후보와 그것이 병합된 채택 프레임 양쪽에 붙는다
        # (예: point 1069.0 → 채택 963.13 + 탈락 1069.3 phash-dup). 중복을 남기면
        # ★가 겹쳐 그려지고 P 내비게이션이 같은 지점에 두 번 멈춘다.
        self.point_times = sorted({
            round(t, 2) for f in self.frames + self.rejected
            for t in f.get("point_times", [])})
        self._build_point_owners()
        self.reloaded.emit()

    def _build_point_owners(self) -> None:
        """point 원시 시각 → 그 point가 실제로 만들어낸 채택 프레임의 시각.

        point는 안정화 때문에 +0.3초 뒤에서 캡처되고(frames.py), 중복 병합되면
        수십 초 떨어진 프레임으로 승계된다. 그래서 point 원시 시각으로 이동하면
        화면에는 **직전 구간의 이미지**가 뜬다 — video3 실측 5/5 전부 빗나갔다.
        착지는 담당 프레임으로 해야 "이 대사 때문에 이 장면"이 확인된다.
        """
        owner: dict[float, float] = {}
        for f in self.frames:
            for t in f.get("point_times", []):
                owner.setdefault(round(t, 2), f["time"])
        for r in self.rejected:
            for t in r.get("point_times", []):
                # 탈락에만 붙은 point는 병합 대상으로, 그것도 없으면 제자리
                owner.setdefault(round(t, 2), r.get("dup_of", r["time"]))
        self.point_owner = owner
        # 순회는 착지 시각 위에서 해야 한다 — 원시 시각으로 순회하면 착지 후
        # 뒤로 가기가 방금 온 자리를 다시 가리켜 제자리에 갇힌다
        self.point_landings = sorted(set(owner.values()))

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

    def source_counts(self) -> Counter:
        """검출 근거별 채택 프레임 수 — 복합 근거는 각 근거에 모두 계상한다."""
        return Counter(s for f in self.frames for s in f["sources"])

    def series_at(self, t: float) -> tuple[float, float] | None:
        """t 시점의 (누적 diff, 순간 변화율) 원값 — 정규화 전이라 그대로 읽힌다."""
        if self.series is None:
            return None
        i = int(np.searchsorted(self.series["times"], t))
        i = min(max(i, 0), len(self.series["times"]) - 1)
        return float(self.series["cum"][i]), float(self.series["rate"][i])

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
        return self._jump(self.point_landings, t, forward)

    def mark_times(self, kind: str) -> list[float]:
        """마크 종류별 착지 시각 목록 (시간 오름차순). 순회의 단일 원천."""
        return {
            "frame": self._frame_starts,
            "rejected": sorted(r["time"] for r in self.rejected),
            "point": self.point_landings,
            "requested": sorted(r["time"] for r in self.requested),
            "transition": sorted(a for a, _ in self.transitions),
            "segment": self._seg_starts,
        }.get(kind, [])

    def dup_target(self, time: float, within: float = 0.3) -> float | None:
        """time 근처 탈락 후보가 '무엇의 중복'으로 판정됐는지 — 그 원본의 시각."""
        near = [r for r in self.rejected if abs(r["time"] - time) <= within
                and r.get("dup_of") is not None]
        if not near:
            return None
        return min(near, key=lambda r: abs(r["time"] - time))["dup_of"]
