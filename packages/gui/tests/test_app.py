"""기동 시 입력 해석 — GUI가 여는 디렉토리는 코어가 여는 것과 같아야 한다.

코어는 형식이 맞지 않는 분석 디렉토리를 읽는 즉시 거부한다(exit 2). GUI가 그
대조를 건너뛰면 같은 디렉토리를 CLI는 거부하고 GUI는 여는 상태가 되고, 사용자는
창이 절반쯤 비어 있는 이유를 어디서도 듣지 못한다. 여기서 못박는 것은 "거부한다"와
"어느 경로로 들어와도 거부한다" 둘이다.
"""
import json

import pytest
from analysis_video import STATE_SCHEMA
from analysis_video_gui import app

OLD_STATE_SCHEMA = "analysis-video/state@1"


def _analysis_dir(tmp_path, schema):
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")
    out_dir = tmp_path / "lecture.mkv.analysis"
    out_dir.mkdir()
    state = {"stages": {}, "source": {"path": str(video), "size": video.stat().st_size}}
    if schema is not None:
        state["schema"] = schema
    (out_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return video, out_dir


@pytest.mark.parametrize("schema", [OLD_STATE_SCHEMA, None])
def test_an_old_analysis_directory_is_refused(tmp_path, schema):
    _video, out_dir = _analysis_dir(tmp_path, schema)

    with pytest.raises(SystemExit) as e:
        app._resolve(out_dir)

    assert out_dir.name in str(e.value)
    assert STATE_SCHEMA in str(e.value), "무엇이 필요한지 말해 주지 않으면 조치할 수 없다"


def test_the_video_path_is_not_a_way_around_the_check(tmp_path):
    """비디오를 지목해도 결국 옆의 .analysis를 읽는다 — 그 길에도 대조가 있어야 한다."""
    video, _out_dir = _analysis_dir(tmp_path, OLD_STATE_SCHEMA)

    with pytest.raises(SystemExit) as e:
        app._resolve(video)

    assert STATE_SCHEMA in str(e.value)


def test_a_video_without_any_analysis_still_opens(tmp_path):
    """아직 분석하지 않은 영상은 플레이어만으로도 열려야 한다(app.warn.no_outputs)."""
    video = tmp_path / "lecture.mkv"
    video.write_bytes(b"video")

    resolved, out_dir = app._resolve(video)

    assert resolved == video
    assert out_dir == tmp_path / "lecture.mkv.analysis"


def test_a_current_analysis_directory_resolves_to_its_source(tmp_path):
    video, out_dir = _analysis_dir(tmp_path, STATE_SCHEMA)

    assert app._resolve(out_dir) == (video, out_dir)
