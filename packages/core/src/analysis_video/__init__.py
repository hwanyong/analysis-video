from importlib.metadata import PackageNotFoundError, version

# 버전의 단일 출처는 pyproject.toml — 설치 메타데이터에서 읽어 이중 선언 발산 방지
try:
    __version__ = version("analysis-video")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

METADATA_SCHEMA = "analysis-video/metadata@1"
STATE_SCHEMA = "analysis-video/state@1"
