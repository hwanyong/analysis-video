from importlib.metadata import PackageNotFoundError, version

# 버전의 단일 출처는 pyproject.toml — 설치 메타데이터에서 읽어 이중 선언 발산 방지
try:
    __version__ = version("analysis-video")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

# 산출물 형식의 버전. manifest가 쓰고, **읽을 때마다 대조한다**(manifest._require_schema).
#
# @1 → @2: 자막을 전사 출처로 채택하면서 두 칸이 늘었다 — state.json의 split
# outputs에 subtitles(컨테이너 자막 트랙 열거)가, transcript.json에 source(대사가
# 어느 출처에서 왔는가)가 생겼다. 값을 올리지 않으면 그 칸이 없는 옛 디렉터리가
# 게이트를 그대로 통과해, 칸을 짚는 자리에서 KeyError로 죽는다. 이 프로젝트는
# 하위 호환을 두지 않기로 했으므로 옛 디렉터리는 **읽는 즉시 거부**되어야 한다.
#
# state@2 → @3: transcribe outputs에 언어 세 칸(language·target_language·
# language_mismatch)이 생겼다. --sub-lang을 주고 완료된 전사를 다시 여는 실행은
# 그중 language를 읽어 요청 언어와 대조하므로(cli._reuse_transcript), 칸이 없는 옛
# 디렉터리는 그 자리에서 KeyError = exit 1로 죽는다 — 게이트가 exit 2로 먼저
# 거부해야 한다. 플래그를 안 준 실행은 그 칸을 읽지 않아 살아남지만, 그때는 결과
# JSON에서 언어 세 칸만 빠진 채로 나간다: 출력 계약이 디렉터리의 나이에 따라
# 달라지는 것이라 어차피 거부가 맞다.
# metadata.json은 그 변경으로 모양이 달라지지 않아 @2 그대로였다: 두 값을 함께
# 올리면 "이 디렉터리의 어느 파일이 낡았는가"가 흐려진다.
#
# state@3 → @4: split outputs의 `audio`(뽑아 둔 wav의 경로 또는 null)가
# `has_audio`(원본에 오디오 스트림이 있는가)로 **대체**됐다. audio.wav를 아예
# 만들지 않기로 했기 때문이다(split.py 머리말). 칸 이름까지 바꾼 덕에 옛
# state.json은 새 칸이 없어 `_audio_transcript`가 KeyError로 죽는데, 그것은
# exit 1(도구의 버그)로 보이므로 게이트가 exit 2로 먼저 거부해야 한다.
#
# metadata@2 → @3: metadata.json에 `images` 블록이 생겼다 — 읽기용 축소 사본이
# 어디에 몇 장 있고 그것을 다 열면 얼마인가. `context.render`가 그 블록을
# **폴백 없이** 읽으므로(대체 키 폴백이 묶기를 조용히 무력화한 사고가 있었다)
# 칸이 없는 옛 metadata는 거부되어야 한다. 이번에는 두 값이 함께 오르지만
# 사유가 서로 다르고 각 주석이 그 사유를 따로 들고 있다.
METADATA_SCHEMA = "analysis-video/metadata@3"
STATE_SCHEMA = "analysis-video/state@4"
