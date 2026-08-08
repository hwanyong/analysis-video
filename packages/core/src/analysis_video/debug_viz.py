"""디버그 그래프 — frames 스테이지가 남긴 산출물만 읽어서 그린다.

분석을 재계산하지 않는다: detect_signals.npz(시계열 캐시) + frames.json(판정 레코드)
+ transcript.json을 그대로 시각화하므로 "그래프에 보이는 것 = 실제 파이프라인
산출"이 구조적으로 보장된다. x축은 저장된 PTS(time_series)를 사용한다.
matplotlib은 [viz] extra — 지연 임포트하고 없으면 EXIT_DEPS로 안내한다.
"""
import json
import sys
from pathlib import Path

import numpy as np

from .errors import EXIT_DEPS, CliError, log

STATUS_COLOR = {"accepted": "green", "rejected": "gray"}

# 플랫폼별 한글 폰트 후보 — 설치 확인 후 선택 (없는 폰트를 지정하면 전부 tofu)
_FONT_CANDIDATES = {
    "darwin": ["AppleGothic", "Apple SD Gothic Neo"],
    "win32": ["Malgun Gothic"],
}
_FONT_FALLBACK = ["Noto Sans CJK KR", "NanumGothic", "NanumBarunGothic", "UnDotum"]


def _load_matplotlib():
    try:
        import matplotlib
    except ImportError:
        raise CliError(EXIT_DEPS, "viz-missing",
                       "matplotlib이 설치되어 있지 않습니다 (debug-report는 [viz] extra)",
                       hint="uv tool install 'analysis-video[viz]' 또는 pip install 'analysis-video[viz]'")
    matplotlib.use("Agg")
    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in _FONT_CANDIDATES.get(sys.platform, []) + _FONT_FALLBACK:
        if name in installed:
            matplotlib.rcParams["font.family"] = name
            break
    else:
        log("[debug-report] 경고: 한글 폰트를 찾지 못했습니다 — 라벨이 깨질 수 있습니다")
    matplotlib.rcParams["axes.unicode_minus"] = False
    return matplotlib


def render(out_dir: Path, title: str, unit_dir: Path | None = None) -> Path:
    """out_dir = 영상 단위(검출 캐시·전사가 있는 곳), unit_dir = 분석 단위."""
    _load_matplotlib()
    import matplotlib.pyplot as plt

    unit = unit_dir if unit_dir is not None else out_dir
    data = np.load(out_dir / "detect_signals.npz")
    anchor_s, rate, area = data["anchor_series"], data["rate_series"], data["area_series"]
    fps = float(data["fps"])
    params = json.loads((unit / "frames.json").read_text(encoding="utf-8"))["params"]
    anchor_threshold = float(params["anchor_threshold"])
    rate_threshold = float(params["rate_threshold"])
    cut_area_threshold = float(params["cut_area_threshold"])

    frames_info = json.loads((unit / "frames.json").read_text(encoding="utf-8"))
    transcript = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
    records = frames_info["records"]
    events = frames_info["events"]

    n = len(anchor_s)
    times = data["time_series"] if "time_series" in data else np.arange(n) / fps
    duration = float(times[-1]) if n else 0.0

    width = max(12, duration / 20)
    fig, (ax_v, ax_r, ax_c, ax_a) = plt.subplots(
        4, 1, figsize=(width, 13), sharex=True,
        gridspec_kw={"height_ratios": [3, 1, 1, 2]},
    )
    fig.suptitle(title, fontsize=14)

    # ---- 상단: anchor diff(앵커 대비) + 판정 레코드 ----
    ax_v.plot(times, anchor_s, color="#1f77b4", lw=0.6, label="anchor diff(앵커 대비)")
    ax_v.axhline(anchor_threshold, color="red", ls="--", lw=1,
                 label=f"anchor_threshold={anchor_threshold}")

    for e in events:
        start = e["time"]
        end = e["after_time"]
        ax_v.axvspan(start, end, color="orange", alpha=0.15)
        ax_v.plot(e.get("anchor_time", e["anchor_idx"] / fps), 0,
                  marker="v", color="blue", ms=7, zorder=5)

    for i, r in enumerate(records):
        idx = min(int(np.searchsorted(times, r["time"])), n - 1)
        color = STATUS_COLOR[r["status"]]
        marker = "s" if "screen-end" in r["sources"] else "^"
        ax_v.plot(r["time"], anchor_s[idx], marker=marker, color=color, ms=8, zorder=5)
        ax_v.text(r["time"], anchor_s[idx], f" {i}", fontsize=6, va="bottom", color=color)

    ax_v.plot([], [], marker="v", color="blue", ms=7, lw=0, label="앵커(기준커서)")
    ax_v.plot([], [], marker="^", color="green", ms=8, lw=0, label="채택 프레임")
    ax_v.plot([], [], marker="^", color="gray", ms=8, lw=0, label="탈락 프레임(사유는 frames.json)")
    ax_v.plot([], [], marker="s", color="green", ms=8, lw=0, label="전환 직전(완성 화면)")
    ax_v.axvspan(0, 0, color="orange", alpha=0.15, label="전환구간")
    n_acc = sum(1 for r in records if r["status"] == "accepted")
    ax_v.set_ylabel("anchor diff (앵커 대비)")
    ax_v.legend(loc="upper right", fontsize=8, ncol=3)
    ax_v.set_title(f"영상: 후보 {len(records)}건 (채택 {n_acc} / 탈락 {len(records) - n_acc})",
                   fontsize=10)

    # ---- 중단: 순간변화율 ----
    ax_r.plot(times, rate, color="#ff7f0e", lw=0.5)
    ax_r.axhline(rate_threshold, color="green", ls="--", lw=1,
                 label=f"rate_threshold={rate_threshold} (전환 진행중 판정)")
    ax_r.set_ylabel("순간변화율\n(인접프레임)")
    ax_r.legend(loc="upper right", fontsize=8)

    # ---- 컷 면적: 한 프레임 만에 확 바뀐 픽셀의 비율 ----
    ax_c.plot(times, area, color="#9467bd", lw=0.5)
    ax_c.axhline(cut_area_threshold, color="red", ls="--", lw=1,
                 label=f"cut_area_threshold={cut_area_threshold} (넘으면 컷)")
    ax_c.set_ylabel("컷 면적\n(변한 픽셀 비율)")
    ax_c.legend(loc="upper right", fontsize=8)

    # ---- 하단: STT 단어 밀도 + 채택 시각 ----
    words = transcript.get("words", [])
    if words:
        ax_a.eventplot([w["start"] for w in words], lineoffsets=0.5, linelengths=0.8,
                       color="#888888", lw=0.4, label=f"STT 단어({len(words)}개)")
    for r in records:
        if r["status"] == "accepted":
            ax_a.axvline(r["time"], color="crimson", lw=0.8, alpha=0.5)
    ax_a.plot([], [], color="crimson", lw=0.8, label="채택 프레임 시각")
    ax_a.set_ylim(0, 1)
    ax_a.set_yticks([])
    ax_a.set_ylabel("음성")
    ax_a.set_xlabel("시간(초)")
    ax_a.legend(loc="upper left", fontsize=8)

    plt.tight_layout()
    out_path = unit / "debug_graph.png"
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path
