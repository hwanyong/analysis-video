"""에이전트 가이드는 파서의 전수 반영이어야 한다.

`agent-guide`는 사람이 아니라 에이전트가 읽는 유일한 사용법 문서다. 플래그를
하나 추가하고 문서에 안 적으면 에이전트에게는 그 플래그가 **없는 것**이고,
기본값을 문서에 복사해 두면 상수를 고칠 때 조용히 갈린다. 그래서 존재 여부는
여기서 파서와 대조해 강제하고, 값은 agent_guide가 상수에서 주입한다.
"""
import argparse
import re

import pytest

from analysis_video.agent_guide import GUIDE
from analysis_video.cli import build_parser
from analysis_video.frames import (DEFAULT_ANCHOR_THRESHOLD,
                                   DEFAULT_CUT_AREA_THRESHOLD,
                                   DEFAULT_RATE_THRESHOLD)
from analysis_video.stt import BACKENDS
from analysis_video.stt.base import DEFAULT_MODEL, MODEL_SIZES


def _subcommands() -> dict[str, argparse.ArgumentParser]:
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("서브커맨드가 없는 파서")


def _section(name: str) -> str:
    """'### <커맨드> — ...' 로 시작하는 그 커맨드의 문서 조각."""
    for chunk in GUIDE.split("\n### "):
        if chunk.startswith(f"{name} —"):
            return chunk
    raise AssertionError(f"'{name}' 커맨드 절이 가이드에 없습니다")


SUBCOMMANDS = _subcommands()


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_every_subcommand_has_a_section_with_its_synopsis(name):
    section = _section(name)
    takes_video = any(a.dest == "video" for a in SUBCOMMANDS[name]._actions)
    synopsis = f"analysis-video {name} <video>" if takes_video else f"analysis-video {name}"
    assert synopsis in section, f"{name}: 호출 형태({synopsis})가 절에 없습니다"


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_every_option_appears_in_its_command_section(name):
    """플래그가 전역 어딘가가 아니라 **그 커맨드 절**에 있어야 한다 —
    공유 옵션도 각 커맨드의 호출 형태에 그대로 나열되므로 이 조건이 성립한다."""
    section = _section(name)
    for action in SUBCOMMANDS[name]._actions:
        for flag in action.option_strings:
            if flag in ("-h", "--help"):
                continue
            assert flag in section, f"{name}: {flag} 가 가이드에 안내되지 않았습니다"


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_every_choice_value_is_documented(name):
    for action in SUBCOMMANDS[name]._actions:
        for choice in action.choices or ():
            assert str(choice) in GUIDE, \
                f"{name} {action.option_strings}: 선택지 '{choice}' 가 가이드에 없습니다"


def test_global_options_are_documented():
    assert "--version" in GUIDE
    assert "--help" in GUIDE


def test_defaults_come_from_the_constants_not_from_prose():
    for value in (DEFAULT_MODEL, *MODEL_SIZES, "auto", *BACKENDS,
                  DEFAULT_ANCHOR_THRESHOLD, DEFAULT_RATE_THRESHOLD,
                  DEFAULT_CUT_AREA_THRESHOLD):
        assert str(value) in GUIDE, f"기본값 {value} 가 가이드에 반영되지 않았습니다"


def test_no_placeholder_is_left_unrendered():
    leftover = re.findall(r"@[A-Z_]+@", GUIDE)
    assert not leftover, f"치환되지 않은 자리표시자: {leftover}"


def test_cache_filenames_match_the_real_ones():
    """레이아웃 도식이 실제 캐시 파일명과 어긋나면 에이전트가 없는 파일을 찾는다."""
    from analysis_video import frames as frames_mod
    src = frames_mod.__file__
    assert "detect_signals.npz" in GUIDE
    assert "detect_adaptive.json" in GUIDE
    with open(src, encoding="utf-8") as f:
        code = f.read()
    assert 'cache = out_dir / "detect_signals.npz"' in code
    assert 'cache = out_dir / "detect_adaptive.json"' in code
