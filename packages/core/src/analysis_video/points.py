"""points.json — 텍스트 중요도 분석을 수행한 호출자(에이전트)가 frames 스테이지에
넘기는 계약. 파이프라인 직렬 흐름의 ②(텍스트 분석)와 ④(프레임 분석)를 잇는 유일한
접점이며, 패키지 자신은 AI를 포함하지 않는다.

스키마:
{
  "points": [
    {"time": <초, float>, "reason": "<이 시각이 중요한 이유 — 근거 대사 요약>"},
    ...
  ]
}
"""
import json
from pathlib import Path

from .errors import EXIT_INPUT, CliError


def load_points(path: Path, duration: float) -> list[dict]:
    if not path.exists():
        raise CliError(EXIT_INPUT, "points-not-found", f"points 파일이 없습니다: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise CliError(EXIT_INPUT, "points-invalid-json", f"points 파일이 JSON이 아닙니다: {e}")

    raw = data.get("points")
    if not isinstance(raw, list):
        raise CliError(EXIT_INPUT, "points-schema",
                       'points 파일 최상위에 "points" 배열이 필요합니다',
                       hint='{"points": [{"time": 123.4, "reason": "..."}]}')

    problems = []
    points = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            problems.append(f"points[{i}]: 객체가 아님")
            continue
        t = p.get("time")
        reason = p.get("reason")
        if not isinstance(t, (int, float)):
            problems.append(f"points[{i}].time: 숫자(초)가 아님")
            continue
        if not (0.0 <= float(t) <= duration):
            # 환각 타임스탬프 차단 — 영상 범위 밖의 시각은 거부한다
            problems.append(f"points[{i}].time={t}: 영상 범위(0~{duration:.1f}초) 밖")
            continue
        if not isinstance(reason, str) or not reason.strip():
            problems.append(f"points[{i}].reason: 비어 있음 — 근거(provenance) 필수")
            continue
        points.append({"time": float(t), "reason": reason.strip()})

    if problems:
        raise CliError(EXIT_INPUT, "points-schema", "points 항목 검증 실패", details=problems)

    return sorted(points, key=lambda p: p["time"])
