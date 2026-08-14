"""종료코드 체계와 stdout 결과 JSON 규약.

에이전트 계약: stdout에는 결과 JSON 딱 한 건만 나간다(Claude Code 30,000자
잘림 안전). 로그·진행 상황은 전부 stderr. 종료코드만으로 분기 가능해야 한다.
"""
import json
import sys

EXIT_OK = 0        # 성공
EXIT_INTERNAL = 1  # 내부 오류 (버그·예기치 못한 실패)
EXIT_INPUT = 2     # 입력/인자 오류 (파일 없음, 알 수 없는 플래그, 잘못된 --range 등)
EXIT_ORDER = 3     # 스테이지 순서 위반 (선행 스테이지 미완료 — 직렬 흐름 강제)
# 환경/의존성 결손. **없는 것이 아니라 "필요해졌는데 없는 것"이 이 코드다.**
# STT 백엔드·matplotlib은 선택 설치(extra)라 부재 자체는 상태일 뿐이고,
# doctor는 그것을 능력 목록으로 보고하며 exit 0으로 끝난다(cmd_doctor 독스트링).
# 이 코드가 나는 자리는 넷이다:
#   - 자막을 하나도 못 써 음성을 받아써야 하는데 STT 백엔드가 없다 (stt.resolve_backend)
#   - 모델 가중치를 가져올 수 없다 (stt.base.model_download_guard)
#   - debug-report를 부탁받았는데 matplotlib이 없다 (debug_viz)
#   - doctor가 **필수** 모듈(코어의 무조건 의존)의 결손을 발견했다
EXIT_DEPS = 4


class CliError(Exception):
    def __init__(self, code: int, kind: str, message: str, hint: str | None = None,
                 details: dict | list | None = None):
        super().__init__(message)
        self.code = code
        self.kind = kind
        self.hint = hint
        self.details = details

    def as_json(self) -> dict:
        err: dict = {"kind": self.kind, "message": str(self)}
        if self.hint:
            err["hint"] = self.hint
        if self.details is not None:
            err["details"] = self.details
        return {"ok": False, "error": err}


def emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)
