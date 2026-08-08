"""사건 판단 — 세 시계열에서 "언제 화면이 바뀌었나"와 "어디서 찍을 것인가"를 정한다.

디코드를 하지 않는다. signals가 만든 시계열만 보고 판단하므로 임계를 바꿔 다시
돌리는 데 몇 밀리초면 된다.

**2단계로 나눈 이유.** 이전 구조는 "언제"와 "어디서"가 한 덩어리였다 — 임계를
넘으면 전환 시작으로 걸어 잠그고, 움직임이 잦아들 때까지 기다렸다가 그 자리에서
찍었다. 그래서 촬영 지점이 사건에서 멀어졌다(실측 video1 최대 2.54초). 애니메이션
처럼 계속 움직이는 영상에서는 '잦아드는 순간'이 언제 올지 알 수 없기 때문이다.
게다가 걸어 잠그는 동안 일어난 다른 봉우리는 통째로 삼켜졌다.

지금은 사건을 **봉우리 자체**로 정의한다. 그러면 촬영 지점이 사건에서 멀어질 수
없다 — 사건 주변에서만 고르기 때문이다.

한 번의 화면 전환이 세 신호에 동시에, 또 여러 프레임에 걸쳐 봉우리를 만들므로
가까운 봉우리들은 하나의 사건으로 묶는다. 대표 시각은 **가장 이른 봉우리** —
변화가 시작된 순간이 그 사건의 시각이다.
"""
import numpy as np

# 순간 변화율은 늘 자잘하게 출렁여서 임계(안정 판정선)를 그대로 봉우리 기준으로
# 쓰면 수백 개가 잡힌다. 사건으로 볼 만한 것은 그보다 확연히 큰 스파이크다.
RATE_PEAK_MULTIPLE = 8.0
# 이 안에 든 봉우리들은 한 번의 화면 전환으로 본다. 컷은 1~3프레임에 걸쳐
# 봉우리를 만들고 세 신호가 서로 몇 프레임씩 어긋나 봉우리를 낸다.
MERGE_WINDOW = 0.5
# 촬영 지점을 찾아 헤맬 최대 시간. 계속 움직이는 영상에서는 '조용한 프레임'이
# 영영 안 올 수 있는데, 그때 멀리까지 가면 다른 화면을 찍게 된다.
SETTLE_LIMIT = 1.0


def _peaks(series: np.ndarray, height: float) -> np.ndarray:
    """height를 넘는 국소 최대의 인덱스. scipy 없이 이웃 비교로 낸다 —
    같은 값이 이어지는 평평한 봉우리는 그 시작을 대표로 삼는다."""
    if len(series) < 3:
        return np.zeros(0, dtype=int)
    s = np.asarray(series, dtype=float)
    hit = s > height
    rise = s[1:-1] >= s[:-2]
    fall = s[1:-1] > s[2:]
    idx = np.flatnonzero(hit[1:-1] & rise & fall) + 1
    return idx


def find(measured: dict, *, anchor_threshold: float, rate_threshold: float,
         cut_area_threshold: float, extra_times=None,
         merge_window: float = MERGE_WINDOW,
         settle_limit: float = SETTLE_LIMIT) -> list[dict]:
    """사건 목록. 각 사건은 시각·집어낸 신호·촬영 두 지점(직전/직후)을 갖는다."""
    ts = np.asarray(measured["time_series"], dtype=float)
    if len(ts) == 0:
        return []
    rate = np.asarray(measured["rate_series"], dtype=float)

    tagged: list[tuple[int, str]] = []
    tagged += [(int(i), "cut") for i in _peaks(measured["area_series"],
                                               cut_area_threshold)]
    tagged += [(int(i), "anchor") for i in _peaks(measured["anchor_series"],
                                                  anchor_threshold)]
    tagged += [(int(i), "rate") for i in _peaks(rate,
                                                rate_threshold * RATE_PEAK_MULTIPLE)]
    for t in (extra_times or []):
        tagged.append((int(np.searchsorted(ts, float(t))), "adaptive"))
    tagged = [(i, s) for i, s in tagged if 0 <= i < len(ts)]
    if not tagged:
        return []
    tagged.sort()

    # 가까운 봉우리 묶기 — 대표는 가장 이른 것(변화가 시작된 순간)
    clusters: list[dict] = []
    for i, sig in tagged:
        if clusters and ts[i] - ts[clusters[-1]["index"]] <= merge_window:
            clusters[-1]["signals"].add(sig)
            clusters[-1]["last"] = max(clusters[-1]["last"], i)
            continue
        clusters.append({"index": i, "last": i, "signals": {sig}})

    events = []
    for k, c in enumerate(clusters):
        prev_bound = clusters[k - 1]["last"] if k else 0
        next_bound = clusters[k + 1]["index"] if k + 1 < len(clusters) else len(ts) - 1
        before = _settled(rate, ts, c["index"], -1, prev_bound, rate_threshold,
                          settle_limit)
        after = _settled(rate, ts, c["last"], +1, next_bound, rate_threshold,
                         settle_limit)
        events.append({
            "index": c["index"], "time": float(ts[c["index"]]),
            "signals": sorted(c["signals"]),
            "before_idx": before, "before_time": float(ts[before]),
            "after_idx": after, "after_time": float(ts[after]),
        })
    return events


def _settled(rate: np.ndarray, ts: np.ndarray, start: int, step: int,
             bound: int, rate_threshold: float, settle_limit: float) -> int:
    """start에서 step 방향으로 '조용한 프레임'을 찾는다.

    못 찾으면 훑은 범위에서 **가장 조용했던** 프레임을 쓴다. 빈손으로 돌아오면
    그 화면의 그림을 통째로 잃는데, 애니메이션 영상에서는 임계 아래로 내려가는
    프레임이 아예 없는 구간이 흔하다 — 완벽한 정지가 아니어도 가장 나은 한 장은
    있다. bound(이웃 사건)를 넘지 않는 것이 더 중요하다: 넘으면 다른 화면을 찍는다.
    """
    i = start
    best = start
    while True:
        nxt = i + step
        if not (0 <= nxt < len(rate)) or (nxt - bound) * step > 0:
            break
        if abs(ts[nxt] - ts[start]) > settle_limit:
            break
        i = nxt
        if rate[i] < rate[best]:
            best = i
        if rate[i] <= rate_threshold:
            return i
    return best
