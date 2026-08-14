"""분석 디렉터리에서 되만들 수 있는 것을 지운다.

분석 디렉터리는 원본 영상보다 크다(실측 1.9~2.8배, 분당 5.85MB → audio.wav를
없앤 뒤 3.93MB). 1시간 강의 한 편이 0.27GB이고 열 편이면 2.7GB인데, 지금까지
**정리 수단이 하나도 없었다** — 사용자가 직접 `rm -rf` 하는 수밖에 없고,
무엇을 지워도 되는지 알려 주는 것도 없었다.

`review`가 생기면서 그 상태가 더 위험해진다. 그전까지 이 디렉터리의 모든 것은
원본 영상만 있으면 되만들 수 있었지만, **review.md는 아니다** — 그것은 호출 AI가
컨텍스트를 태워 쓴 글이고, 되만들려면 분석을 처음부터 다시 시켜야 한다.
공간을 비우려는 `rm -rf` 한 번에 그것이 함께 사라지면 안 된다.

그래서 이 명령의 기본값은 **삭제가 아니라 보고**다. `--level` 없이 부르면
무엇이 얼마나 있는지만 답한다. 지우는 것은 레벨을 명시했을 때뿐이다.

## 지우지 않는 것 (어느 레벨에서도)

- `reviews/` — 되만들 수 없다. 이 파일의 존재 이유.
- `transcript.json` — whisper가 돌았다면 되만드는 데 모델 추론이 다시 든다.
- `runs/*/read/` — `context.md`가 그것을 가리킨다. 지우면 산출물이 깨진다.
- `runs/*/requested/` — 호출자가 근거(`--reason`)를 적어 주문한 것이고,
  `runs.reset_unit`조차 이것만은 살린다.
- `runs/*/metadata.json` · `context.md` · `frames.json` — 기록이고, 작다.
- `detect_signals.npz` · `detect_adaptive.json` — 캐시지만 되만드는 데 전 프레임
  디코드(수 분)가 들고, 40KB뿐이라 지울 이유가 없다.
"""
import shutil
from pathlib import Path

# 레벨은 **누적**이다 — images는 cache가 지우는 것도 함께 지운다. 독립이면
# "어느 조합을 줬더라"를 사용자가 기억해야 하고, 조합마다 남은 상태가 다르다.
LEVELS = ("cache", "images")

_WHAT = {
    "cache": "분리된 영상 리소스(video.mkv)",
    "images": "원본 해상도 프레임(runs/*/frames/)",
}
_COST = {
    # `_video_resource`가 파일이 없으면 원본으로 폴백하고 경고만 낸다.
    # 같은 스트림이라 프레임이 바이트 동일함을 실측으로 확인했다.
    "cache": "없음 — 다시 필요해지면 원본 영상에서 그대로 읽는다",
    "images": "GUI와 정밀 확인이 안 된다. context.md는 읽기용 사본을 가리키므로 그대로 읽힌다",
}


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return 0


def targets(out_dir: Path, level: str) -> list[Path]:
    """이 레벨이 지우는 경로들. 존재 여부는 보지 않는다 — 호출부가 거른다."""
    paths = [out_dir / "video.mkv"]
    if level == "images":
        paths += sorted((out_dir / "runs").glob("*/frames"))
    return paths


def survey(out_dir: Path) -> dict:
    """무엇이 얼마나 있는가 — 레벨별 회수 가능량과 그 대가.

    삭제하지 않는다. `--level` 없이 부른 `clean`이 그대로 내보내는 값이고,
    이것이 있어야 "무엇을 지워도 되는가"가 처음으로 산출물에서 답해진다."""
    total = _size(out_dir)
    levels = []
    seen: set[Path] = set()
    cumulative = 0
    for level in LEVELS:
        fresh = [p for p in targets(out_dir, level) if p not in seen and p.exists()]
        seen.update(fresh)
        cumulative += sum(_size(p) for p in fresh)
        levels.append({
            "level": level, "removes": _WHAT[level], "cost": _COST[level],
            "frees_bytes": cumulative,
            "frees_mb": round(cumulative / 1e6, 1),
            "paths": [str(p) for p in sorted(seen)],
        })
    return {"total_bytes": total, "total_mb": round(total / 1e6, 1), "levels": levels}


def clean(out_dir: Path, level: str) -> dict:
    """지우고 무엇을 얼마나 지웠는지 돌려준다. 이미 없는 것은 조용히 건너뛴다
    (멱등 — 같은 명령을 두 번 불러도 두 번째는 0바이트를 보고한다)."""
    removed, freed = [], 0
    for lv in LEVELS[:LEVELS.index(level) + 1]:
        for p in targets(out_dir, lv):
            if not p.exists():
                continue
            freed += _size(p)
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed.append(str(p))
    return {"level": level, "removed": removed, "freed_bytes": freed,
            "freed_mb": round(freed / 1e6, 1)}
