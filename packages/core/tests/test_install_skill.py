"""install-skill은 멱등이어야 한다 — 그게 존재 이유다.

`agent-guide >> AGENTS.md`가 추가 연산이라 업그레이드마다 사용법 전문을 중복
누적시켰고, 그러면 한 파일 안의 두 사본이 서로 다른 기본값을 주장한다. 이 커맨드는
그 문제를 없애려고 있으므로, 중복이 쌓이지 않는다는 것 자체를 고정해 둔다.
사용자 홈에 쓰는 부수효과가 있으니 테스트는 반드시 tmp_path로만 향해야 한다.

멱등만으로는 부족했다는 것이 뒤늦게 드러났다: 마커 한쪽만 남은 파일에서 이 명령이
**사용자 문서를 지웠다**(재현 완료 — orphan 마커 테스트들이 그 시나리오 그대로다).
쓰기 자체도 성질로 고정한다 — 실패한 쓰기가 남의 규칙 파일을 반쯤 잘라 놓으면 안 된다.
"""
import json
import re

import pytest
import yaml

from analysis_video import frames, manifest, skill
from analysis_video.agent_guide import GUIDE
from analysis_video.cli import main
from analysis_video.errors import EXIT_INPUT, CliError

VERSION = "9.9.9"


# ---------- Claude Code 개인 스킬 ----------

def test_creates_skill_then_reports_unchanged(tmp_path):
    root = tmp_path / "skills"
    first = skill.install_claude_skill(VERSION, root)
    assert first["action"] == "created"

    path = tmp_path / "skills" / "analysis-video" / "SKILL.md"
    assert path.exists()
    assert first["path"] == str(path.resolve())

    again = skill.install_claude_skill(VERSION, root)
    assert again["action"] == "unchanged"


def test_skill_has_frontmatter_with_the_name_the_loader_keys_on(tmp_path):
    """로더가 하는 그대로 — 문자열 포함이 아니라 **YAML 파서**로 확인한다.

    `"name: analysis-video" in text` 는 프론트매터가 문법적으로 깨져도(따옴표
    안 닫힘·들여쓰기 어긋남) 통과한다. 그러면 로더는 스킬을 통째로 못 읽는데
    테스트는 초록이다. 여기서 파싱까지 해 두면 그 간극이 없다."""
    path = skill.install_claude_skill(VERSION, tmp_path)["path"]
    text = open(path, encoding="utf-8").read()
    assert text.startswith("---\n"), "YAML 프론트매터로 시작해야 로더가 인식한다"

    front = yaml.safe_load(text.split("---", 2)[1])
    assert isinstance(front, dict), "프론트매터는 매핑 하나여야 한다"
    assert front["name"] == skill.SKILL_NAME
    # description은 로더가 이 스킬을 언제 꺼낼지 판단하는 유일한 재료다.
    assert front["description"].strip(), "description이 비면 스킬이 트리거되지 않는다"
    assert set(front) == {"name", "description"}, \
        "로더가 모르는 키를 늘리지 않는다 — 생성 안내는 YAML 주석으로 둔다"


def test_skill_points_at_agent_guide_instead_of_copying_it(tmp_path):
    """본문을 복사하면 패키지 업그레이드와 스킬 갱신이 갈린다 — 정본은 하나여야 한다."""
    path = skill.install_claude_skill(VERSION, tmp_path)["path"]
    text = open(path, encoding="utf-8").read()
    assert "agent-guide" in text
    # 가이드의 실제 본문 조각이 스킬에 복사돼 있으면 안 된다
    assert "## Shared options" not in text
    # 플래그 목록은 가이드의 소관이다 — 스킬이 카탈로그를 다시 적으면 두 문서가
    # 서로 다른 값을 주장하게 된다(이 저장소의 README가 겪은 그 고장).
    for flag in ("--out", "--range", "--run", "--model", "--force"):
        assert flag not in text, f"{flag}는 agent-guide에만 있어야 한다"
    assert len(text) < len(GUIDE) / 2, "스킬은 짧은 안내여야 한다"


def test_no_number_reaches_the_skill_the_version_line_excepted(tmp_path):
    """예전 규칙("숫자는 상수에서 주입한다")의 **정반대**로 뒤집힌 자리.

    주입은 렌더되는 순간의 값만 맞춰 줄 뿐, 파일이 사용자 홈에 놓인 다음의 표류는
    막지 못한다 — SKILL.md는 설치 시점의 스냅샷이고 갱신 트리거도 낡음 경고도 없다.
    실제로 컷 면적 기본값은 여섯 커밋에서 네 번 움직이는 동안 버전은 0.1.0 그대로였다.
    낡는 주기와 재설치 주기가 무관하므로, 숫자는 아예 두지 않고 agent-guide에 맡긴다.
    버전 줄만 예외다 — 그것은 "이 파일은 어느 버전이 쓴 스냅샷인가"의 기록이라
    낡아 있는 것 자체가 정보다."""
    text = open(skill.install_claude_skill(VERSION, tmp_path)["path"],
                encoding="utf-8").read()
    assert VERSION in text, "버전은 남아야 한다 — 낡은 사본을 식별하는 유일한 단서"
    body = "\n".join(ln for ln in text.splitlines() if VERSION not in ln)

    assert str(frames.DEFAULT_CUT_AREA_THRESHOLD) not in body
    assert str(frames.RECOMMENDED_CUT_AREA_THRESHOLD) not in body
    for pattern, what in ((r"\d\.\d", "0.002 같은 임계값"),
                          (r"\d\s*%", "95% 같은 실측 비율"),
                          (r"\d+\s*[-–]\s*\d+", "17-43 같은 실측 구간")):
        found = re.search(pattern, body)
        assert found is None, \
            f"{what}이 남아 있다({found.group(0)!r}) — 값은 agent-guide 소관이다"
    assert re.search(r"@[A-Z_]+@", text) is None, "치환 안 된 자리표시자가 남았다"


def test_the_budget_advice_delegates_values_but_keeps_the_trap_warning(tmp_path):
    """숫자를 뺐다고 조언까지 빼면 예산 절이 무의미해진다 — 방향은 남아야 한다.

    특히 `--rate-threshold`는 올리면 이미지가 **늘어난다**. 임계를 올리면 준다는
    일반 직관의 예외라, 이 경고가 빠지면 예산을 줄이려던 시도가 도리어 비용을
    키운다. 이건 숫자가 아니라 방향이므로 낡지 않는다."""
    text = open(skill.install_claude_skill(VERSION, tmp_path)["path"],
                encoding="utf-8").read()

    assert "--cut-area-threshold" in text, "어느 다이얼을 돌릴지는 알려야 한다"
    assert "--rate-threshold" in text and "more" in text
    # 값을 어디서 받을지 명시하지 않으면 에이전트가 기억에서 숫자를 지어낸다.
    budget = text.split("## Budget", 1)[1]
    assert "agent-guide" in budget


def test_version_is_recorded_so_a_stale_copy_is_identifiable(tmp_path):
    path = skill.install_claude_skill(VERSION, tmp_path)["path"]
    assert VERSION in open(path, encoding="utf-8").read()


def test_claude_config_dir_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    result = skill.install_claude_skill(VERSION)
    assert result["path"].startswith(str((tmp_path / "cfg" / "skills").resolve()))


def test_default_root_is_the_home_skill_dir(tmp_path, monkeypatch):
    """CLAUDE_CONFIG_DIR이 없을 때의 기본 분기 — 실사용자 전원이 지나는 경로인데
    다른 테스트는 전부 --dir이나 환경변수로 우회해서 여기를 한 번도 밟지 않았다.

    홈에 **쓰지 않고** 경로 계산만 본다: Path.home을 tmp로 바꿔 두면 이 함수가
    ~/.claude/skills를 어떻게 조립하는지 그대로 드러난다(부수효과 없음 — 이 테스트가
    설치를 실행하면 실행자의 진짜 홈을 건드릴 위험이 남는다)."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(skill.Path, "home", classmethod(lambda cls: tmp_path))

    assert skill._skills_root() == tmp_path / ".claude" / "skills"
    assert not (tmp_path / ".claude").exists(), "경로만 계산하고 만들지는 않는다"


def test_the_file_says_it_is_generated_and_how_to_get_it_back(tmp_path):
    """이 파일은 두 자리(사용자 홈·저장소 루트)에 놓이는 생성물이다.

    손으로 고칠 수 있는 자리에 있으면서 생성물이라고 말하지 않으면, 고친 사람은
    다음 설치에서 자기 편집이 사라지는 것을 이유 없이 겪는다. 안내는 프론트매터
    **주석**으로 둔다 — YAML 주석이라 로더가 읽는 매핑은 그대로고(위 파서 테스트가
    키 집합을 고정한다), 파일 머리에서 먼저 눈에 띈다."""
    text = open(skill.install_claude_skill(VERSION, tmp_path)["path"],
                encoding="utf-8").read()
    head = text.split("---", 2)[1]
    notice = "\n".join(ln for ln in head.splitlines() if ln.startswith("#"))

    assert "skill.py" in notice, "정본이 어디인지 적혀야 한다"
    assert "install-skill" in notice, "다시 만드는 방법이 적혀야 한다"


def test_uvx_invocation_pins_latest(tmp_path):
    """uvx는 처음 해석한 버전을 캐시해 계속 그것을 쓴다 — @latest가 없으면
    에이전트는 그 기계가 이 도구를 처음 부른 날의 버전에 고정된다."""
    text = open(skill.install_claude_skill(VERSION, tmp_path)["path"],
                encoding="utf-8").read()
    for line in text.splitlines():
        if "uvx analysis-video" in line:
            assert "uvx analysis-video@latest" in line
            break
    else:
        pytest.fail("uvx 호출 예시가 사라졌다 — 설치 없이 쓰는 유일한 경로다")


# ---------- 규칙 파일 (AGENTS.md 등) ----------

def test_agents_file_created_when_absent(tmp_path):
    target = tmp_path / "AGENTS.md"
    result = skill.install_agents_file(target, VERSION, GUIDE)
    assert result["action"] == "created"
    text = target.read_text(encoding="utf-8")
    assert "## Shared options" in text, "규칙 파일에는 가이드 전문이 들어간다"


def test_existing_content_is_preserved_and_block_appended(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_text("# 내 규칙\n\n건드리지 말 것.\n", encoding="utf-8")

    result = skill.install_agents_file(target, VERSION, GUIDE)
    assert result["action"] == "appended"
    text = target.read_text(encoding="utf-8")
    assert "# 내 규칙" in text and "건드리지 말 것." in text


def test_rerunning_replaces_the_block_and_never_accumulates(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_text("서두\n", encoding="utf-8")
    skill.install_agents_file(target, VERSION, GUIDE)
    once = target.read_text(encoding="utf-8")

    # 새 버전으로 다시 설치 — 덧붙이지 않고 그 구간만 바뀌어야 한다
    result = skill.install_agents_file(target, "9.9.10", GUIDE)
    assert result["action"] == "updated"
    twice = target.read_text(encoding="utf-8")

    assert twice.count(skill._BEGIN) == 1
    assert twice.count(skill._END) == 1
    assert "9.9.10" in twice and VERSION not in twice
    assert twice.count("## Shared options") == once.count("## Shared options") == 1
    assert twice.startswith("서두\n")


def test_unchanged_when_nothing_differs(tmp_path):
    target = tmp_path / "AGENTS.md"
    skill.install_agents_file(target, VERSION, GUIDE)
    assert skill.install_agents_file(target, VERSION, GUIDE)["action"] == "unchanged"


def _orphaned(tmp_path, keep: str) -> tuple:
    """마커 한쪽만 남은 규칙 파일을 만든다. `keep`은 살려 둘 마커."""
    target = tmp_path / "AGENTS.md"
    target.write_text(f"# 내 규칙\n\n건드리지 말 것.\n\n{keep}\n\n마지막 줄.\n",
                      encoding="utf-8")
    return target, target.read_text(encoding="utf-8")


@pytest.mark.parametrize("keep, counts", [
    (skill._BEGIN, (1, 0)),   # 사용자가 END를 지웠거나 편집 중 잘렸다
    (skill._END, (0, 1)),     # BEGIN이 잘려 나갔다
])
def test_orphan_marker_aborts_instead_of_eating_the_users_document(tmp_path, keep, counts):
    """짝이 안 맞는 마커에 덧붙이면 **다음 실행이 사용자 문서를 지운다**(재현 완료).

    옛 동작: BEGIN만 남은 파일에 설치하면 끝에 블록을 붙여 BEGIN 2 / END 1이 된다
    (run1 — 이때는 아직 멀쩡하다). 그 다음 실행이 둘 다 있다고 보고 정규식
    `BEGIN.*?END`(DOTALL·non-greedy)로 **첫(고아) BEGIN부터 유일한 END까지**를 한
    덩어리로 치환해, 그 사이에 있던 사용자 문장이 사라졌다(run2 — 재현 확인). 고아
    마커가 파일 머리에 있으면 남는 것은 생성 블록 하나뿐이다.

    고친 동작: 짝이 1:1이 아니면 쓰지 않고 exit 2로 알린다. 남의 규칙 파일이라
    추측 복구는 하지 않고, 무엇이 몇 개 몇 번째 줄에 있는지 돌려준다."""
    target, before = _orphaned(tmp_path, keep)

    with pytest.raises(CliError) as caught:
        skill.install_agents_file(target, VERSION, GUIDE)

    err = caught.value
    assert err.code == EXIT_INPUT
    assert target.read_text(encoding="utf-8") == before, "한 글자도 쓰면 안 된다"
    assert [p.name for p in tmp_path.iterdir()] == ["AGENTS.md"], \
        "임시 파일도 남기지 않는다"

    # 사용자가 스스로 고치려면 무엇이 어긋났는지 알아야 한다.
    payload = err.as_json()["error"]
    assert payload["details"]["begin"]["count"] == counts[0]
    assert payload["details"]["end"]["count"] == counts[1]
    lines = payload["details"]["begin"]["lines"] + payload["details"]["end"]["lines"]
    assert lines == [5], "남은 마커가 몇 번째 줄인지 알려준다"
    assert payload["hint"]


def test_the_run2_that_destroyed_the_file_can_no_longer_happen(tmp_path):
    """①의 재현 시나리오 전체 — run1이 막히므로 run2가 존재할 수 없다."""
    target, before = _orphaned(tmp_path, skill._BEGIN)

    for _ in range(2):   # run1, run2 — 둘 다 같은 자리에서 멈춘다
        with pytest.raises(CliError):
            skill.install_agents_file(target, VERSION, GUIDE)

    after = target.read_text(encoding="utf-8")
    assert after == before
    assert "건드리지 말 것." in after and "마지막 줄." in after


def test_markers_in_the_wrong_order_are_refused(tmp_path):
    """개수는 1:1인데 END가 먼저 오는 파일. 옛 코드는 정규식이 안 맞아 원문 그대로를
    돌려주고는 `unchanged`라고 보고했다 — 아무 일도 안 하면서 성공했다고 말하는 쪽이
    제일 나쁘다. 사용자는 설치됐다고 믿고, 에이전트는 영영 가이드를 못 본다."""
    target = tmp_path / "AGENTS.md"
    broken = f"{skill._END}\n\n내 규칙\n\n{skill._BEGIN}\n"
    target.write_text(broken, encoding="utf-8")

    with pytest.raises(CliError) as caught:
        skill.install_agents_file(target, VERSION, GUIDE)
    assert caught.value.code == EXIT_INPUT
    assert target.read_text(encoding="utf-8") == broken


def test_two_complete_blocks_are_also_refused(tmp_path):
    """짝의 개수가 맞아도 1:1이 아니면 안전하지 않다 — 옛 정규식은 첫 구간만 바꾸고
    둘째 사본을 남겨, 한 파일 안의 두 사본이 서로 다른 기본값을 주장하게 된다
    (이 커맨드가 없애려던 바로 그 상태)."""
    target = tmp_path / "AGENTS.md"
    skill.install_agents_file(target, VERSION, GUIDE)
    doubled = target.read_text(encoding="utf-8") * 2
    target.write_text(doubled, encoding="utf-8")

    with pytest.raises(CliError) as caught:
        skill.install_agents_file(target, "9.9.10", GUIDE)
    assert caught.value.code == EXIT_INPUT
    assert target.read_text(encoding="utf-8") == doubled


def test_a_failed_write_leaves_the_previous_file_whole(tmp_path, monkeypatch):
    """남의 규칙 파일과 사용자 홈을 덮어쓰는 자리라 반쯤 쓰인 파일을 남기면 안 된다.

    manifest.write_text_atomic(임시 파일 + os.replace)에 위임했는지를 구현이 아니라
    성질로 본다: 교체가 실패해도 원본이 통째로 남아 있어야 한다. 직접 write_text로
    쓰면 이 시점에 파일이 잘려 있다."""
    target = tmp_path / "AGENTS.md"
    target.write_text("# 내 규칙\n\n건드리지 말 것.\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("교체 실패")

    monkeypatch.setattr(manifest.os, "replace", boom)
    with pytest.raises(OSError):
        skill.install_agents_file(target, VERSION, GUIDE)

    assert target.read_text(encoding="utf-8") == before


def test_damage_inside_the_block_is_repaired_not_duplicated(tmp_path):
    target = tmp_path / "AGENTS.md"
    skill.install_agents_file(target, VERSION, GUIDE)
    target.write_text(
        target.read_text(encoding="utf-8").replace("## Shared options", "[훼손]", 1),
        encoding="utf-8")

    assert skill.install_agents_file(target, VERSION, GUIDE)["action"] == "updated"
    text = target.read_text(encoding="utf-8")
    assert "[훼손]" not in text
    assert text.count(skill._BEGIN) == 1


# ---------- CLI 연결 ----------

@pytest.mark.parametrize("argv_tail, expect_key", [
    (["--dir", "SKILLS"], "claude-skill"),
    (["--agents-file", "AGENTS.md"], "agents-file"),
])
def test_cli_connects_both_modes_and_reports_json(tmp_path, capsys, argv_tail, expect_key):
    tail = [str(tmp_path / a) if a in ("SKILLS", "AGENTS.md") else a for a in argv_tail]
    assert main(["install-skill", *tail]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["target"] == expect_key
    assert payload["action"] == "created"
    assert payload["path"].startswith(str(tmp_path.resolve()))


def test_cli_reports_broken_markers_as_an_input_error(tmp_path, capsys):
    """마커 불일치는 도구의 버그가 아니라 **파일 상태**다 — 사용법/입력 오류와 같은
    종료코드 2로 낸다. 에이전트는 종료코드만으로 분기하므로(errors.py 계약),
    여기서 새 코드를 발명하면 계약을 아는 쪽이 아무도 없다. 재시도해도 소용없고
    사람이 파일을 고쳐야 한다는 뜻이 2에 이미 들어 있다."""
    target, before = _orphaned(tmp_path, skill._BEGIN)

    assert main(["install-skill", "--agents-file", str(target)]) == EXIT_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "agents-file-markers"
    assert payload["error"]["details"]["begin"]["count"] == 1
    assert target.read_text(encoding="utf-8") == before
