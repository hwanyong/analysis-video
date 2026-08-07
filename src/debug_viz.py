import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams["font.family"] = "AppleGothic"
matplotlib.rcParams["axes.unicode_minus"] = False

from . import ffutil
from .audio_timeline import emphasis_candidates, transcribe
from .frame_candidates import transition_aware_anchor_diff


def analyze_video(video_path: Path, out_dir: Path, yavg_floor: float = 5.0) -> dict:
    """transition_aware_anchor_diff를 돌리고, 각 트리거마다 프레임을 뽑아 YAVG로 accept/reject 판정."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = transition_aware_anchor_diff(video_path)
    fps = result["fps"]

    for i, e in enumerate(result["events"]):
        t = e["trigger_idx"] / fps
        img_path = out_dir / f"event{i:03d}_t{t:07.2f}.jpg"
        ok = ffutil.extract_frame(video_path, t, img_path)
        y = ffutil.yavg(img_path) if ok else 0.0
        e["time"] = t
        e["anchor_time"] = e["anchor_idx"] / fps
        e["transition_start_time"] = e["transition_start_idx"] / fps
        e["yavg"] = y
        e["accepted"] = y >= yavg_floor
        e["path"] = str(img_path)

    result["yavg_floor"] = yavg_floor
    return result


def analyze_audio(audio_path: Path, z_threshold: float = 1.5) -> dict:
    stt = transcribe(audio_path)
    emphasis = emphasis_candidates(audio_path, z_threshold=z_threshold)
    return {"stt": stt, "emphasis": emphasis, "z_threshold": z_threshold}


def plot_debug_report(video_result: dict, audio_result: dict, out_path: Path, title: str) -> Path:
    fps = video_result["fps"]
    n = video_result["n_frames"]
    times = np.arange(n) / fps
    duration = n / fps

    width = max(12, duration / 20)
    fig, (ax_v, ax_r, ax_a) = plt.subplots(
        3, 1, figsize=(width, 11), sharex=True,
        gridspec_kw={"height_ratios": [3, 1, 2]},
    )
    fig.suptitle(title, fontsize=14)

    # ---- 상단: 누적(anchor 대비) diff + 이벤트 ----
    ax_v.plot(times, video_result["cum_series"], color="#1f77b4", lw=0.6, label="누적diff(anchor 대비)")
    ax_v.axhline(video_result["cum_threshold"], color="red", ls="--", lw=1,
                 label=f"cum_threshold={video_result['cum_threshold']}")

    for i, e in enumerate(video_result["events"]):
        color = "green" if e["accepted"] else "gray"
        ax_v.axvspan(e["transition_start_time"], e["time"], color="orange", alpha=0.15)
        ax_v.plot(e["anchor_time"], 0, marker="v", color="blue", ms=7, zorder=5)
        ax_v.plot(e["time"], video_result["cum_series"][e["trigger_idx"]], marker="^",
                   color=color, ms=8, zorder=5)
        ax_v.annotate("", xy=(e["time"], -0.04), xytext=(e["anchor_time"], -0.04),
                      xycoords=("data", "axes fraction"), textcoords=("data", "axes fraction"),
                      arrowprops=dict(arrowstyle="-", color="purple", lw=0.8, alpha=0.5))
        ax_v.text(e["time"], video_result["cum_series"][e["trigger_idx"]], f" {i}",
                  fontsize=6, va="bottom", color=color)

    ax_v.plot([], [], marker="v", color="blue", ms=7, lw=0, label="앵커(기준커서)")
    ax_v.plot([], [], marker="^", color="green", ms=8, lw=0, label="커서(트리거, YAVG 통과)")
    ax_v.plot([], [], marker="^", color="gray", ms=8, lw=0, label="커서(트리거, YAVG 폐기=빈화면)")
    ax_v.axvspan(0, 0, color="orange", alpha=0.15, label="전환구간(transition)")
    ax_v.set_ylabel("누적 diff (anchor 대비)")
    ax_v.legend(loc="upper right", fontsize=8, ncol=3)
    ax_v.set_title(f"영상: anchor-diff 전환추적 — {len(video_result['events'])}건 트리거 "
                    f"({sum(1 for e in video_result['events'] if e['accepted'])}건 YAVG 통과)", fontsize=10)

    # ---- 중단: 순간변화율(rate) ----
    ax_r.plot(times, video_result["rate_series"], color="#ff7f0e", lw=0.5)
    ax_r.axhline(video_result["rate_threshold"], color="green", ls="--", lw=1,
                 label=f"rate_threshold={video_result['rate_threshold']} (전환 진행중 판정 기준)")
    ax_r.set_ylabel("순간변화율\n(인접프레임)")
    ax_r.legend(loc="upper right", fontsize=8)

    # ---- 하단: 오디오 STT 단어밀도 + 임팩트 후보 ----
    words = audio_result["stt"]["words"]
    if words:
        word_times = [w["start"] for w in words]
        ax_a.eventplot(word_times, lineoffsets=0.5, linelengths=0.8, color="#888888", lw=0.4,
                       label=f"STT 단어({len(words)}개)")
    emph = audio_result["emphasis"]
    if emph:
        et = [c["time"] for c in emph]
        es = [c["score"] for c in emph]
        ax_a2 = ax_a.twinx()
        ax_a2.scatter(et, es, color="crimson", s=6, zorder=5, label=f"임팩트 후보({len(emph)}개)")
        ax_a2.axhline(audio_result["z_threshold"], color="crimson", ls=":", lw=1,
                      label=f"z_threshold={audio_result['z_threshold']}")
        ax_a2.set_ylabel("임팩트 스코어(z)", color="crimson")
        ax_a2.legend(loc="upper right", fontsize=8)
    ax_a.set_ylim(0, 1)
    ax_a.set_yticks([])
    ax_a.set_ylabel("음성")
    ax_a.set_xlabel("시간(초)")
    ax_a.legend(loc="upper left", fontsize=8)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def generate_debug_report(video_path: Path, audio_path: Path, out_dir: Path, label: str) -> dict:
    video_result = analyze_video(video_path, out_dir / "frames")
    audio_result = analyze_audio(audio_path)
    png_path = plot_debug_report(video_result, audio_result, out_dir / "debug_graph.png", label)
    return {"png": str(png_path), "n_events": len(video_result["events"]),
            "n_accepted": sum(1 for e in video_result["events"] if e["accepted"]),
            "n_words": len(audio_result["stt"]["words"]),
            "n_emphasis": len(audio_result["emphasis"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--out", type=Path, default=Path("debug_out"))
    parser.add_argument("--label", default="debug")
    args = parser.parse_args()
    summary = generate_debug_report(args.video, args.audio, args.out, args.label)
    print(summary)
