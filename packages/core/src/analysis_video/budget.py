"""읽기 예산 — 이미지를 몇 장 여는 것이 얼마인가.

이 파이프라인의 산출물은 사람이 아니라 **컨텍스트 창이 있는 모델**이 읽는다.
그런데 지금까지 산출물은 장수만 말하고 비용을 말하지 않았다. 실측하면 그 침묵이
비싸다: 프레임을 원본 해상도(1920x1080)로 저장하면 장당 1,843토큰이고, 5분
강의가 78~186장이라 146k~349k 토큰이다. 1시간으로 늘리면 1.08M~3.95M —
**여섯 편 전부 백만 토큰을 넘는다.** 그러니 "필요한 것만 열어라"는 안내는
근거를 주지 않는 한 지켜질 수 없었다.

여기서 하는 일은 둘뿐이다.

1. **읽기용 축소 사본의 크기를 정한다.** 긴 변 768px에서 장당 442토큰 —
   4.17배다. 본문 가독성은 실측으로 확인했다(판서·수식·슬라이드 세 종류에서
   문장·숫자·행렬이 모두 읽힌다). 잃는 것은 OS 크롬·썸네일 같은 주변부다.
   원본은 `frames/`에 그대로 남으므로 정밀 확인은 그쪽을 연다.
2. **비용을 산정해 산출물에 적는다.** 규칙 이름을 값과 함께 내보낸다 —
   아래 TOKEN_RULE 참조.

**등급(tier)은 두지 않는다.** 한때 "먼저 열 이미지"를 코어가 매기는 안을 검토했지만
버렸다. 첫째, 판단 근거가 이미 산출물에 있다 — context.md의 섹션 헤딩이 그 화면이
떠 있던 시간 범위를 그대로 적고 있어 "오래 떠 있던 화면"은 읽는 쪽에서 바로 보인다.
둘째, 실측상 화면 대다수가 이미지 한 장뿐이라(74개 중 70개) 접을 것이 거의 없었다.
셋째, 그리고 결정적으로, 코어가 "중요한 이미지"를 따로 매기기 시작하면 그것이
변화량 검출과 같은 자리를 놓고 경쟁하는 **두 번째 추출 기준**이 된다 — points.json을
폐기한 사유와 같은 고장이다. 무엇을 열지는 읽는 쪽이 정한다.
"""
from pathlib import Path

# 읽기용 사본의 긴 변. 이 값을 바꾸면 사본을 다시 만들어야 한다(frames 재실행).
READ_LONG_EDGE = 768

# 사본이 사는 곳 — 분석 단위 안. 원본 frames/와 파일명이 같아 서로 짝이 보인다.
READ_DIRNAME = "read"

# 토큰 산정 규칙을 **이름으로** 함께 내보낸다. 이 공식은 Anthropic 계열 모델의
# 것이고, 값만 던지면 다른 모델을 쓰는 소비자가 그 사실을 알 수 없다. 규칙이
# 함께 오면 자기 것이 아닐 때 무시할 수 있다.
#
# "맞춘 뒤"가 아니라 **"넘으면 …까지 줄인 뒤"**인 것이 중요하다. 이 문자열은
# context.md에 그대로 실려 나가고, 거기 실린 이미지는 이미 768px로 줄어 있다.
# "1568px에 맞춘다"로 읽으면 그 사본을 **키워서** 계산하게 되어 78장이
# 34,476이 아니라 143,754토큰으로 나온다 — 4.2배 과대 산정이라, 읽어도 되는
# 분량을 "예산 초과"로 오판하고 임계를 올리러 간다. 실제로 실행한 에이전트가
# 짚어낸 문구다.
TOKEN_RULE = "긴 변이 1568px를 넘으면 1568px까지 줄인 뒤 (가로*세로)/750"
TOKEN_RULE_EN = "if the long edge exceeds 1568px shrink it to 1568px, then (w*h)/750"

_MAX_LONG_EDGE = 1568
_PIXELS_PER_TOKEN = 750


def image_tokens(width: int, height: int) -> int:
    """이미지 한 장의 토큰. 소비자가 축소를 한 번 더 하므로 그것까지 반영한다."""
    long_edge = max(width, height)
    if long_edge > _MAX_LONG_EDGE:
        scale = _MAX_LONG_EDGE / long_edge
        width, height = round(width * scale), round(height * scale)
    return (width * height) // _PIXELS_PER_TOKEN


def reduced_size(width: int, height: int, long_edge: int = READ_LONG_EDGE
                 ) -> tuple[int, int]:
    """축소 사본의 크기. 원본이 이미 작으면 **키우지 않는다** — 없는 화소를
    만들어 내면 토큰만 늘고 읽히는 것은 그대로다."""
    current = max(width, height)
    if current <= long_edge:
        return width, height
    scale = long_edge / current
    return round(width * scale), round(height * scale)


def summary(sizes: list[tuple[int, int]], long_edge: int = READ_LONG_EDGE) -> dict:
    """metadata.json의 `images` 블록. sizes는 **축소 사본들의** 실제 크기다.

    장수와 토큰을 함께 담는다: 장수만으로는 비용을 알 수 없고(해상도가 영상마다
    다르다), 토큰만으로는 몇 장인지 알 수 없다."""
    return {
        "read_dir": READ_DIRNAME,
        "long_edge": long_edge,
        "count": len(sizes),
        "tokens": sum(image_tokens(w, h) for w, h in sizes),
        "rule": TOKEN_RULE,
    }


def cost(images: dict) -> dict:
    """결과 JSON에 싣는 비용 — `images` 블록에서 소비자가 볼 두 값만 추린다.

    metadata.json을 열지 않고도 "지금 이걸 다 읽으면 얼마인가"를 알아야 한다.
    `next`가 이것을 나른다."""
    return {"images": images["count"], "image_tokens": images["tokens"],
            "rule": images["rule"]}


def read_path(image: str, read_dir: str = READ_DIRNAME) -> str:
    """원본 프레임 경로 → 같은 이름의 읽기용 사본 경로.

    두 경로를 metadata에 나란히 적지 않는 이유: 같은 사실의 사본이 둘이 되고,
    한쪽만 고쳐지는 날 context.md와 감사 기록이 서로 다른 파일을 가리킨다.
    규칙 하나(같은 파일명, 다른 디렉터리)로 두면 갈릴 자리가 없다."""
    return f"{read_dir}/{Path(image).name}"
