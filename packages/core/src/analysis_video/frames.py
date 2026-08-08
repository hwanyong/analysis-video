"""프레임 후보 생성과 게이트 — 사건마다 screen-start·screen-end 두 지점.

추출 기준은 **프레임 변화량 하나**다. 예전에는 호출 에이전트가 전사를 읽고
지정한 "중요한 시각"(importance-point)에서도 뽑았지만, 화면을 보지 못한 채
텍스트만으로 고른 시각이 시각적 검출과 같은 자리를 놓고 경쟁해 기준이 흐려졌다.
사후 정밀 추출은 `frame --at`이 맡는다.

사건 하나가 후보를 **둘** 낸다: 새 화면의 시작(screen-start)과 그 화면의 끝
상태(screen-end). 어느 한쪽만 잡으면 반드시 잃는다 — 시작만 잡으면 판서가
채워지기 전의 빈 페이지만 남고, 끝만 잡으면 "무엇에서 무엇으로 갔는가"가
사라진다. 끝 상태를 남길지는 **그 화면의 시작과 견줘** 정한다(_pair_changed):
슬라이드처럼 뜬 뒤 그대로인 화면은 두 장이 될 이유가 없다.

판정 기록 보존 원칙: 어떤 후보도 조용히 사라지지 않는다. 탈락 이미지는
frames/rejected/로 이동하고 레코드에 사유가 남으며, 중복으로 탈락해도
출처(sources)는 생존 레코드로 승계된다.

파일명은 순번 기반(scene_003_t0012.33.jpg)이라 시각 반올림 충돌이 불가능하다.
추출은 **2단계**다. 1단계(events)가 세 신호의 봉우리에서 "언제 화면이 바뀌었나"를
정하고, 2단계가 사건마다 촬영 지점 둘을 고른다 — 사라지는 화면의 완성 상태
(screen-end)와 새 화면(screen-start). 한 덩어리였을 때는 촬영 지점이 사건에서
최대 2.54초까지 밀려났다.

측정 결과는 cache_dir에 캐시(detect_signals.npz, detect_adaptive.json)되어
재실행 시 전체 디코드를 건너뛴다. 캐시에 임계는 안 들어간다 — 임계는 판단의
소관이라 바꿔도 다시 측정할 이유가 없다.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from . import media
from .detect import adaptive, events as events_mod, overlay, signals
from .errors import log

# 프레임 번호를 실제 PTS로 옮기게 된 이후의 adaptive 캐시 (v1은 선언 fps 근사였다)
ADAPTIVE_SCHEMA = "adaptive/2"
# 컷 면적(cut_area)을 전환 검출에 도입하고 cum_* → anchor_* 로 개명한 이후의
# anchor 캐시. v1에는 area_series가 아예 없고 키 이름도 달라 재사용이 불가능하다.
SIGNALS_SCHEMA = "signals/1"

# 앵커를 언제 옮길지는 anchor_diff 신호의 내부 사정이라 사용자 임계와 분리한다.
# 판단(events)의 임계를 바꿔도 측정 캐시가 무효화되지 않게 하는 것이 목적이다.
ANCHOR_RESET_THRESHOLD = 0.02
CUT_RESET_THRESHOLD = 0.02
RATE_SETTLE_THRESHOLD = 0.0015


def _gray_for_compare(img_path: Path, w: int = 400, h: int = 225) -> np.ndarray:
    # float32로 내보낸다 — uint8로 두면 뺄셈이 감싸(|10-200| 이 190이 아니라 66)
    # 차이 계산이 조용히 틀린다.
    return np.asarray(Image.open(img_path).convert("L").resize((w, h)),
                      dtype=np.float32)


def _pair_changed(video_path: Path, t_pre: float, t_trigger: float,
                  threshold: float, band: tuple[float, float] = (0.0, 1.0)) -> bool:
    """두 시각이 실질적으로 같은 그림인가 — 이 한 쌍만 직접 본다.

    전역 중복 게이트에 맡기지 않는 이유: 그쪽은 **모든 채택 프레임**과 견주므로
    "이 화면 안에서 무슨 일이 있었나"라는 질문에 답하지 않는다. 반면 이 쌍은
    같은 화면의 시작과 끝이라 배경·조명·구도가 완전히 같은 동일 조건 비교이고,
    그래서 SSIM이 제 성능을 낸다. 실측 분포도 갈라진다 — 화면 안에서 실제로
    작업이 진행된 경우 video3 0.831~0.849, 뜬 뒤 그대로인 슬라이드는 0.98 이상.
    (video1은 애니메이션이라 연속 분포 — 그쪽에선 임계가 판단의 문제다)
    """
    a = media.extract_gray_array(video_path, t_pre, w=400, h=225)
    b = media.extract_gray_array(video_path, t_trigger, w=400, h=225)
    if a is None or b is None:
        return True  # 못 읽으면 후보를 살린다 — 판정 실패로 정보를 잃지 않는다
    return ssim(overlay.crop(a, band), overlay.crop(b, band)) < threshold


def _cached_signals(video_path: Path, out_dir: Path) -> dict:
    """측정 결과 캐시. 담기는 것은 **시계열과 띠뿐**이고 임계는 들어가지 않는다 —
    임계는 판단(events)의 소관이라, 바꿔도 디코드를 다시 할 이유가 없다."""
    cache = out_dir / "detect_signals.npz"
    if cache.exists():
        data = np.load(cache)
        schema = str(data["schema"]) if "schema" in data else ""
        if schema == SIGNALS_SCHEMA:
            log("[frames] 신호 측정 캐시 재사용 (detect_signals.npz)")
            return {
                "fps": float(data["fps"]),
                "band": (float(data["band"][0]), float(data["band"][1])),
                "time_series": data["time_series"],
                "anchor_series": data["anchor_series"],
                "rate_series": data["rate_series"],
                "area_series": data["area_series"],
                "row_change_freq": data["row_change_freq"],
            }
        log("[frames] 신호 측정 캐시가 구버전 — 다시 측정합니다")

    log("[frames] 1/2 오버레이 띠 산출 중...")
    freq = signals.scan_rows(video_path)
    band = overlay.body_band(freq)
    if band != overlay.FULL:
        log(f"[frames] 고정 오버레이 띠 — 본문 세로 {band[0]:.0%}~{band[1]:.0%}만 측정")
    else:
        log("[frames] 고정 오버레이 띠 없음 — 화면 전체를 측정")
    log("[frames] 2/2 신호 측정 중...")
    r = signals.measure(video_path, band, anchor_threshold=ANCHOR_RESET_THRESHOLD,
                        rate_threshold=RATE_SETTLE_THRESHOLD,
                        cut_area_threshold=CUT_RESET_THRESHOLD)
    r["row_change_freq"] = freq
    np.savez_compressed(
        cache, schema=SIGNALS_SCHEMA, fps=r["fps"], band=np.array(band),
        time_series=r["time_series"], anchor_series=r["anchor_series"],
        rate_series=r["rate_series"], area_series=r["area_series"],
        row_change_freq=freq)
    return r


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


def build_frames(video_path: Path, out_dir: Path, *,
                 cache_dir: Path | None = None,
                 window: tuple[float, float] | None = None,
                 anchor_threshold: float = 0.02, rate_threshold: float = 0.0015,
                 cut_area_threshold: float = 0.02,
                 blank_area_threshold: float = 0.001,
                 pair_dup_threshold: float = 0.93) -> dict:
    """out_dir = 이 분석 단위의 디렉터리, cache_dir = 검출 캐시를 둘 곳.

    검출은 영상 전체에 대해 한 번만 돌려 cache_dir에 두고, 단위는 자기 window로
    거른다. 단위마다 다시 검출하면 구간 수만큼 전 프레임 디코드를 반복하게 되고,
    구간별로 디코드를 잘라내면 신호 측정과 AdaptiveDetector가 공유하는 프레임
    **번호** 공간이 어긋난다(커밋 291e64e에서 397초 오차를 낸 그 결합).
    """
    cache_dir = cache_dir if cache_dir is not None else out_dir
    frames_dir = out_dir / "frames"
    rejected_dir = frames_dir / "rejected"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    duration = media.get_duration(video_path)
    w_start, w_end = window if window is not None else (0.0, duration)

    measured = _cached_signals(video_path, cache_dir)
    fps = measured["fps"]
    time_series = measured["time_series"]
    band = measured["band"]

    # 1단계 — 언제. 세 신호의 봉우리 합집합 + AdaptiveDetector(보조 검출기).
    adaptive_times = [e["detected_at"] for e in
                      _cached_adaptive(video_path, cache_dir, duration, time_series)]
    found = events_mod.find(
        measured, anchor_threshold=anchor_threshold, rate_threshold=rate_threshold,
        cut_area_threshold=cut_area_threshold, extra_times=adaptive_times)
    by_signal: dict[str, int] = {}
    for e in found:
        for sig in e["signals"]:
            by_signal[sig] = by_signal.get(sig, 0) + 1
    log(f"[frames] 사건 {len(found)}건 — 신호별 " +
        " ".join(f"{k} {v}" for k, v in sorted(by_signal.items())))

    def new_candidate(time: float, detected_at: float, source: str) -> dict:
        return {"time": time, "detected_at": detected_at, "sources": [source]}

    # 2단계 — 어디서. 사건마다 직후(새 화면의 시작)와, 그 화면이 사라지기 직전의
    # 완성 상태. 두 지점 모두 사건 주변에서 고르므로 사건에서 멀어질 수 없다.
    #
    # 구간의 첫 화면은 어떤 신호도 방출하지 않는다(전환이 구간 시작 전에
    # 일어났으므로) — 명시적 시드.
    initial_t = adaptive.pick_stable_time(video_path, w_start, duration, offset=0.5)
    candidates = [new_candidate(initial_t, w_start, "initial")]

    n_same = 0
    screen_start = initial_t  # 지금 보고 있는 화면이 시작된 시각
    for e in found:
        t_end = e["before_time"]
        # 화면의 끝 상태를 남길지는 **그 화면의 시작과 견줘** 정한다. 뜬 뒤
        # 그대로인 슬라이드는 두 장이 될 이유가 없다.
        if t_end - screen_start > 1.0 / max(fps, 1.0):
            if _pair_changed(video_path, screen_start, t_end, pair_dup_threshold, band):
                candidates.append(new_candidate(t_end, e["time"], "screen-end"))
            else:
                n_same += 1
        candidates.append(new_candidate(e["after_time"], e["time"], "screen-start"))
        screen_start = e["after_time"]
    if n_same:
        log(f"[frames] 화면 {len(found)}개 중 {n_same}개는 "
            f"시작부터 끝까지 그대로였다 — 끝 상태 후보 생략")

    # 구간 밖 후보는 버린다. initial 시드는 구간 시작에서 나왔으므로 살린다.
    n_all = len(candidates)
    candidates = [c for c in candidates
                  if c["sources"] == ["initial"] or w_start <= c["time"] <= w_end]
    if len(candidates) != n_all:
        log(f"[frames] 구간 {w_start:.1f}~{w_end:.1f}초 밖 후보 "
            f"{n_all - len(candidates)}건 제외")

    log(f"[frames] 후보 {len(candidates)}건 추출·게이트 판정 중...")
    records: list[dict] = []
    accepted: list[dict] = []

    def gate(c: dict, img: Path) -> None:
        """추출→내용량 게이트. 판정을 c에 기록하고 records/accepted를 갱신한다.

        후보를 **버리는 판정은 "그림이 비었나" 하나뿐**이다. 중복 게이트는 없앴다:
        같은 화면이 두 번 나와도 지울 이유가 없고, 무엇보다 그 게이트는 먼저 온
        것을 남기고 **나중 것을 버려서** 판서가 더 진행된 최신 상태를 잃었다.
        내용량 판정은 오버레이 띠를 뺀 본문에서 한다.
        """
        c["image"] = img.relative_to(out_dir).as_posix()
        if not media.extract_frame(video_path, c["time"], img):
            c.update(status="rejected", reject_reason="extract-failed", image=None)
            records.append(c)
            return
        area = overlay.content_area(overlay.crop(_gray_for_compare(img), band))
        c["yavg"] = round(media.yavg(img), 2)
        c["content_area"] = round(area, 4)
        if area <= blank_area_threshold:
            dst = rejected_dir / img.name
            img.rename(dst)
            c.update(status="rejected", reject_reason=f"blank(<={blank_area_threshold})",
                     image=dst.relative_to(out_dir).as_posix())
            records.append(c)
            return
        c["status"] = "accepted"
        accepted.append(c)
        records.append(c)

    # 순번 기반 파일명 — 시각 반올림 충돌로 채택 이미지가 덮어써지는 사고를 차단
    for seq, c in enumerate(sorted(candidates, key=lambda c: c["time"])):
        gate(c, frames_dir / f"scene_{seq:03d}_t{c['time']:07.2f}.jpg")

    records.sort(key=lambda r: r["time"])

    log(f"[frames] 완료: 채택 {len(accepted)}건 / 탈락 {len(records) - len(accepted)}건")
    in_window = [e for e in found if w_start <= e["time"] <= w_end]
    return {
        "records": records, "duration": duration, "fps": fps,
        "window": [round(w_start, 2), round(w_end, 2)],
        "events": in_window,
        "params": {
            "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
            "cut_area_threshold": cut_area_threshold,
            "blank_area_threshold": blank_area_threshold,
            "pair_dup_threshold": pair_dup_threshold,
            "body_band": [round(band[0], 3), round(band[1], 3)],
        },
    }
