"""검출 계층 — 측정(signals)과 판단(events)을 나눠 둔다.

signals: 영상을 훑어 세 시계열을 낸다. 디코드가 여기서만 일어난다.
events:  그 시계열에서 "언제 바뀌었고 어디서 찍을까"를 정한다. 디코드 없음.
overlay: 고정 오버레이 띠(번인 자막) 산출 — 측정이 어디를 볼지 정한다.
adaptive: PySceneDetect 보조 검출기 — 사건 후보를 보탠다.
"""
from . import adaptive, events, overlay, signals

__all__ = ["signals", "events", "overlay", "adaptive"]
