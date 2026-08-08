"""분석 단위(run) — 한 영상에 대한 독립적인 분석 결과 하나.

`--range`를 여러 번 주면 그만큼의 **독립 결과물**이 나온다. 병합하지 않는다.
겹쳐도 무방하다 — 서로를 모르기 때문이다. 이것이 중요한 이유:

겹치는 구간을 하나의 산출물 안에 담으려면 같은 시각이 서로 다른 화면·이미지·
대사 묶음에 속하게 되고, 그 순간 `screens[]`가 시간축의 분할이기를 그만둔다.
그러면 metadata에 층(layer) 개념이 생기고, context.md는 같은 순간을 두 섹션에
다르게 실어야 하며, GUI는 어느 층을 보는지 따져야 한다 — 추상화가 전방위로
번진다. 단위를 디렉터리로 분리하면 **각 산출물의 형식이 지금과 완전히 동일**해서
그 전파가 일어나지 않는다.

    <video>.analysis/
    ├── video.mkv  audio.wav  transcript.json   ← 원본 전체, 1회, 공유
    ├── detect_signals.npz  detect_adaptive.json ← 측정 캐시도 공유(영상 전체 1회)
    ├── context.md                              ← 인덱스: 어떤 분석들이 있는가
    └── runs/<이름>/  metadata.json  context.md  frames/  requested/

검출을 단위마다 다시 돌리지 않는 이유: 검출기는 전 프레임을 훑어야 하는데
그 비용이 스테이지의 대부분이다. 한 번 돌려 두고 단위는 자기 구간으로 거르면
구간이 여러 개일수록 이득이고, 신호 측정과 AdaptiveDetector가 프레임 **번호**
공간을 공유하는 결합(커밋 291e64e 참조)도 건드리지 않는다.
"""
import json
from pathlib import Path

from .errors import EXIT_INPUT, CliError

FULL = "full"


def parse_range(text: str) -> tuple[float, float]:
    """"120-300" → (120.0, 300.0). 단위는 초 — `frame --at`과 통일한다."""
    part = text.strip()
    if part.count("-") != 1:
        raise CliError(EXIT_INPUT, "bad-range",
                       f"--range {text}: '시작-끝' 형식이어야 합니다 (초 단위)",
                       hint="예: --range 120-300 --range 900-1200")
    a, b = part.split("-")
    try:
        start, end = float(a), float(b)
    except ValueError:
        raise CliError(EXIT_INPUT, "bad-range",
                       f"--range {text}: 숫자로 읽을 수 없습니다 (초 단위)") from None
    if start >= end:
        raise CliError(EXIT_INPUT, "bad-range",
                       f"--range {text}: 시작({start})이 끝({end}) 이상입니다")
    return start, end


def resolve(texts: list[str] | None, duration: float) -> list[tuple[float, float] | None]:
    """CLI 인자 → 단위 목록. 구간이 없으면 [None](= 영상 전체 하나).

    정렬은 하되 **병합은 하지 않는다**(겹침이 곧 사용자의 의도다). 완전히 같은
    구간만 중복 제거한다 — 같은 분석을 두 번 만들 이유가 없고, 디렉터리 이름이
    충돌한다."""
    if not texts:
        return [None]
    seen: list[tuple[float, float]] = []
    for t in texts:
        rng = parse_range(t)
        if rng[0] < 0 or rng[1] > duration + 0.5:
            raise CliError(EXIT_INPUT, "range-out-of-range",
                           f"--range {t}: 영상 범위(0~{duration:.2f}초) 밖입니다")
        clipped = (max(rng[0], 0.0), min(rng[1], duration))
        if clipped not in seen:
            seen.append(clipped)
    return sorted(seen)


def name(rng: tuple[float, float] | None) -> str:
    return FULL if rng is None else f"{rng[0]:07.1f}-{rng[1]:07.1f}".replace(".", "_")


def label(rng: tuple[float, float] | None) -> str:
    return "영상 전체" if rng is None else f"{rng[0]:.1f}-{rng[1]:.1f}초"


def unit_dir(out_dir: Path, rng: tuple[float, float] | None) -> Path:
    return out_dir / "runs" / name(rng)


def window(rng: tuple[float, float] | None, duration: float) -> tuple[float, float]:
    return (0.0, duration) if rng is None else rng


def index_path(out_dir: Path) -> Path:
    return out_dir / "runs" / "index.json"


def write_index(out_dir: Path, entries: list[dict]) -> Path:
    p = index_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_index(out_dir: Path) -> list[dict]:
    p = index_path(out_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def merge_index(out_dir: Path, entries: list[dict]) -> list[dict]:
    """이번에 만든 단위를 기존 목록에 합친다 — 같은 이름은 새 것으로 대체.

    누적하는 이유: 나중에 구간을 하나 더 분석해도 앞서 만든 단위가 목록에서
    사라지면 안 된다(디렉터리는 남아 있는데 인덱스에만 없는 상태 = 미배선)."""
    by_name = {e["name"]: e for e in load_index(out_dir)}
    for e in entries:
        by_name[e["name"]] = e
    # 디렉터리가 사라진 단위는 목록에서도 뺀다 — 죽은 항목을 남기지 않는다
    alive = [e for e in by_name.values() if (out_dir / "runs" / e["name"]).is_dir()]
    alive.sort(key=lambda e: (e["range"] is not None, e["range"] or [0, 0]))
    write_index(out_dir, alive)
    return alive
