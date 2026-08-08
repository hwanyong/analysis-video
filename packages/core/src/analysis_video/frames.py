"""프레임 후보 통합 — initial ∪ anchor-diff ∪ screen-end ∪ AdaptiveDetector.

추출 기준은 **프레임 변화량 하나**다. 예전에는 호출 에이전트가 전사를 읽고
지정한 "중요한 시각"(importance-point)에서도 뽑았지만, 화면을 보지 못한 채
텍스트만으로 고른 시각이 시각적 검출과 같은 자리를 놓고 경쟁해 기준이 흐려졌다.
사후 정밀 추출은 `frame --at`이 맡는다.

anchor-diff 이벤트는 후보를 **둘** 낸다: 새 화면의 시작(anchor-diff = 트리거)과
그 화면의 끝 상태(screen-end = 다음 전환이 시작되기 직전의 마지막 안정 프레임).
어느 한쪽만 잡으면 반드시 잃는다 — 시작만 잡으면 판서가 채워지기 전의 빈 페이지만
남고, 끝만 잡으면 "무엇에서 무엇으로 갔는가"가 사라진다. 끝 상태를 남길지는
**그 화면의 시작과 견줘** 정한다(_pair_changed): 슬라이드처럼 뜬 뒤 그대로인
화면은 두 장이 될 이유가 없다 — 실측 video2는 24개 화면 중 3개만 끝 상태가 필요했다.

판정 기록 보존 원칙: 어떤 후보도 조용히 사라지지 않는다. 탈락 이미지는
frames/rejected/로 이동하고 레코드에 사유가 남으며, 중복으로 탈락해도
출처(sources)는 생존 레코드로 승계된다.

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
from .detect import adaptive, anchor, overlay
from .errors import log

# 프레임 번호를 실제 PTS로 옮기게 된 이후의 adaptive 캐시 (v1은 선언 fps 근사였다)
ADAPTIVE_SCHEMA = "adaptive/2"
# 컷 면적(cut_area)을 전환 검출에 도입하고 cum_* → anchor_* 로 개명한 이후의
# anchor 캐시. v1에는 area_series가 아예 없고 키 이름도 달라 재사용이 불가능하다.
ANCHOR_SCHEMA = "anchor/3"


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


def _cached_anchor(video_path: Path, out_dir: Path, anchor_threshold: float,
                   rate_threshold: float, cut_area_threshold: float) -> dict:
    cache = out_dir / "detect_anchor.npz"
    if cache.exists():
        # 캐시는 수치 배열 + JSON 문자열(유니코드 배열)만 담는다 — pickle 불필요/금지
        data = np.load(cache)
        # 구버전은 키 구성 자체가 달라 조회하면 KeyError로 죽는다. 스키마부터 본다.
        schema = str(data["schema"]) if "schema" in data else ""
        if schema != ANCHOR_SCHEMA:
            log("[frames] anchor-diff 캐시가 구버전 — 재검출합니다")
        elif (float(data["anchor_threshold"]) == anchor_threshold
                and float(data["rate_threshold"]) == rate_threshold
                and float(data["cut_area_threshold"]) == cut_area_threshold):
            log("[frames] anchor-diff 캐시 재사용 (detect_anchor.npz)")
            return {
                "fps": float(data["fps"]), "n_frames": int(data["anchor_series"].shape[0]),
                "anchor_series": data["anchor_series"], "rate_series": data["rate_series"],
                "area_series": data["area_series"], "time_series": data["time_series"],
                "events": json.loads(str(data["events_json"])),
                "row_change_freq": data["row_change_freq"],
                "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
                "cut_area_threshold": cut_area_threshold,
            }

    log("[frames] anchor-diff 전환추적 실행 중...")
    result = anchor.transition_aware_anchor_diff(
        video_path, anchor_threshold=anchor_threshold, rate_threshold=rate_threshold,
        cut_area_threshold=cut_area_threshold)
    np.savez_compressed(
        cache, schema=ANCHOR_SCHEMA,
        anchor_series=result["anchor_series"], rate_series=result["rate_series"],
        area_series=result["area_series"], time_series=result["time_series"],
        fps=result["fps"], anchor_threshold=anchor_threshold,
        rate_threshold=rate_threshold, cut_area_threshold=cut_area_threshold,
        row_change_freq=result["row_change_freq"],
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


def build_frames(video_path: Path, out_dir: Path, *,
                 cache_dir: Path | None = None,
                 window: tuple[float, float] | None = None,
                 anchor_threshold: float = 0.02, rate_threshold: float = 0.0015,
                 cut_area_threshold: float = 0.04,
                 blank_area_threshold: float = 0.001,
                 dup_area_threshold: float = 0.002,
                 pair_dup_threshold: float = 0.93) -> dict:
    """out_dir = 이 분석 단위의 디렉터리, cache_dir = 검출 캐시를 둘 곳.

    검출은 영상 전체에 대해 한 번만 돌려 cache_dir에 두고, 단위는 자기 window로
    거른다. 단위마다 다시 검출하면 구간 수만큼 전 프레임 디코드를 반복하게 되고,
    구간별로 디코드를 잘라내면 anchor-diff와 AdaptiveDetector가 공유하는 프레임
    **번호** 공간이 어긋난다(커밋 291e64e에서 397초 오차를 낸 그 결합).
    """
    cache_dir = cache_dir if cache_dir is not None else out_dir
    frames_dir = out_dir / "frames"
    rejected_dir = frames_dir / "rejected"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    duration = media.get_duration(video_path)
    w_start, w_end = window if window is not None else (0.0, duration)

    anchor_result = _cached_anchor(video_path, cache_dir, anchor_threshold,
                                   rate_threshold, cut_area_threshold)
    fps = anchor_result["fps"]
    time_series = anchor_result["time_series"]
    band = overlay.body_band(anchor_result["row_change_freq"])
    if band != overlay.FULL:
        log(f"[frames] 고정 오버레이 띠 감지 — 본문 세로 {band[0]:.0%}~{band[1]:.0%}만 비교")

    def new_candidate(time: float, detected_at: float, source: str) -> dict:
        return {"time": time, "detected_at": detected_at, "sources": [source]}

    # 구간의 첫 화면은 어떤 검출기도 방출하지 않는다(전환이 구간 시작 전에
    # 일어났으므로) — 명시적 시드. 오프닝 페이드 대비로 안정화를 거친다;
    # 어두우면 게이트가 사유와 함께 걸러준다.
    initial_t = adaptive.pick_stable_time(video_path, w_start, duration, offset=0.5)
    candidates = [new_candidate(initial_t, w_start, "initial")]

    n_same = 0
    screen_start = initial_t  # 지금 보고 있는 화면이 시작된 시각
    for e in anchor_result["events"]:
        # 전환추적된 트리거는 이미 안정 상태에서 잡힌 것 — 추가 안정화 불필요
        t = e.get("trigger_time", e["trigger_idx"] / fps)
        # 화면의 **끝 상태**. 트리거 하나만 잡으면 화면이 시작된 순간만 남는데,
        # 판서는 그 뒤 수십 초에 걸쳐 채워진다 — 실측 video3의 한 화면은 105초
        # 동안 885자를 설명하며 페이지를 채우는데 이미지는 거의 빈 페이지였다.
        # 남길지는 **그 화면의 시작과 견줘** 정한다. 전환 전후를 견주던 이전 방식은
        # 경계 너머 비교라 "이 화면 안에서 무슨 일이 있었나"를 묻지 않았다.
        si = e.get("settled_idx")
        if si is not None and 0 <= si < len(time_series):
            t_end = float(time_series[si])
            if t_end - screen_start > 1.0 / max(fps, 1.0):
                if _pair_changed(video_path, screen_start, t_end, pair_dup_threshold, band):
                    candidates.append(new_candidate(t_end, t_end, "screen-end"))
                else:
                    n_same += 1
        candidates.append(new_candidate(t, t, "anchor-diff"))
        screen_start = t
    if n_same:
        log(f"[frames] 화면 {len(anchor_result['events'])}개 중 {n_same}개는 "
            f"시작부터 끝까지 그대로였다 — 끝 상태 후보 생략")

    for entry in _cached_adaptive(video_path, cache_dir, duration,
                                  anchor_result["time_series"]):
        candidates.append(new_candidate(entry["time"], entry["detected_at"], "adaptive"))

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
        """추출→내용량→중복 게이트. 판정을 c에 기록하고 records/accepted를 갱신한다.

        두 판정 모두 **오버레이 띠를 뺀 본문**에서만 한다. 자막 띠를 함께 재면
        본문이 달라도 자막 변화에 묻히고(오병합), 본문이 같아도 자막 때문에
        달라 보인다.
        """
        c["image"] = img.relative_to(out_dir).as_posix()
        if not media.extract_frame(video_path, c["time"], img):
            c.update(status="rejected", reject_reason="extract-failed", image=None)
            records.append(c)
            return
        body = overlay.crop(_gray_for_compare(img), band)
        area = overlay.content_area(body)
        c["yavg"] = round(media.yavg(img), 2)
        c["content_area"] = round(area, 4)
        if area <= blank_area_threshold:
            dst = rejected_dir / img.name
            img.rename(dst)
            c.update(status="rejected", reject_reason=f"blank(<={blank_area_threshold})",
                     image=dst.relative_to(out_dir).as_posix())
            records.append(c)
            return
        # 중복 판정은 **본문에서 바뀐 픽셀의 면적** 하나로 한다.
        #
        # 전역 SSIM으로 확증하던 이전 방식은 배경이 같으면 통과했다 — 실측 video3에서
        # 서로 다른 판서 페이지가 SSIM 0.973으로 병합됐다(본문 면적으로는 0.44% 대
        # 0.00%로 갈린다). pHash 사전 필터도 뺐다. 저주파 구조만 보는 근사라 거의
        # 같은 슬라이드끼리도 거리가 4를 넘겨(실측 video2에서 본문 차이 0.03~0.11%인
        # 8쌍이 그 때문에 안 묶였다) 정작 정당한 병합을 막고 있었다.
        #
        # 뺄 수 있는 이유는 비용이 사라졌기 때문이다. 예전 측정에서 쌍당 비용의
        # 정체는 이미지 **로딩**(13.78ms)이었고 배열끼리의 비교는 5.71µs였다.
        # 지금은 채택 프레임의 본문 배열을 메모리에 들고 있으므로 로딩이 없다.
        dup = next(
            (a for a in accepted
             if float((np.abs(body - a["_body"]) > overlay.CHANGE_DELTA).mean())
             <= dup_area_threshold),
            None)
        if dup is not None:
            dst = rejected_dir / img.name
            img.rename(dst)
            # 중복 탈락이라도 출처는 생존 레코드로 승계 — provenance 소실 금지
            for s in c["sources"]:
                if s not in dup["sources"]:
                    dup["sources"].append(s)
            # dup_of는 사유 문자열과 별개의 기계 판독용 필드다. 소비자가 "of=…"를
            # 정규식으로 되파싱하게 두면 표현이 바뀔 때마다 조용히 끊긴다.
            c.update(status="rejected", reject_reason=f"dup(of={dup['time']:.2f})",
                     dup_of=round(dup["time"], 2),
                     image=dst.relative_to(out_dir).as_posix())
            records.append(c)
            return
        c["_body"] = body
        c["status"] = "accepted"
        accepted.append(c)
        records.append(c)

    # 순번 기반 파일명 — 시각 반올림 충돌로 채택 이미지가 덮어써지는 사고를 차단
    for seq, c in enumerate(sorted(candidates, key=lambda c: c["time"])):
        gate(c, frames_dir / f"scene_{seq:03d}_t{c['time']:07.2f}.jpg")

    records.sort(key=lambda r: r["time"])
    for r in accepted:
        r.pop("_body", None)  # 비교용 배열은 산출물에 나가지 않는다

    log(f"[frames] 완료: 채택 {len(accepted)}건 / 탈락 {len(records) - len(accepted)}건")
    events = [e for e in anchor_result["events"]
              if w_start <= e["trigger_time"] <= w_end]
    return {
        "records": records, "duration": duration, "fps": fps,
        "window": [round(w_start, 2), round(w_end, 2)],
        "anchor_events": events,
        "params": {
            "anchor_threshold": anchor_threshold, "rate_threshold": rate_threshold,
            "cut_area_threshold": cut_area_threshold,
            "blank_area_threshold": blank_area_threshold,
            "dup_area_threshold": dup_area_threshold,
            "pair_dup_threshold": pair_dup_threshold,
            "body_band": [round(band[0], 3), round(band[1], 3)],
        },
    }
