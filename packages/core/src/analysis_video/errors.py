"""종료코드 체계와 stdout 봉투 규약.

에이전트 계약: stdout에는 봉투 JSON 딱 한 건만 나간다(Claude Code 30,000자
잘림 안전). 로그·진행 상황은 전부 stderr. 종료코드만으로 분기 가능해야 한다.
"""
import json
import sys

EXIT_OK = 0        # 성공
EXIT_INTERNAL = 1  # 내부 오류 (버그·예기치 못한 실패)
EXIT_INPUT = 2     # 입력/인자 오류 (파일 없음, points.json 스키마 위반 등)
EXIT_ORDER = 3     # 스테이지 순서 위반 (선행 스테이지 미완료 — 직렬 흐름 강제)
EXIT_DEPS = 4      # 환경/의존성 결손 (사용 가능한 STT 백엔드 없음 등)


class CliError(Exception):
    def __init__(self, code: int, kind: str, message: str, hint: str | None = None,
                 details: dict | list | None = None):
        super().__init__(message)
        self.code = code
        self.kind = kind
        self.hint = hint
        self.details = details

    def envelope(self) -> dict:
        err: dict = {"kind": self.kind, "message": str(self)}
        if self.hint:
            err["hint"] = self.hint
        if self.details is not None:
            err["details"] = self.details
        return {"ok": False, "error": err}


def emit(envelope: dict) -> None:
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
