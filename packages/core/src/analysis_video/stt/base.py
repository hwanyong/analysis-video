"""STT 백엔드 공통 계약.

모든 백엔드는 아래 스키마의 dict를 반환한다 — 소비자(frames·align·metadata)는
어느 백엔드가 돌았는지 몰라도 된다:

{
  "text":     str,                                             # 전체 전사
  "segments": [{"start": float, "end": float, "text": str}],   # 문장 단위
  "words":    [{"word": str, "start": float, "end": float}],   # 단어 타임스탬프
  "backend":  "mlx" | "faster-whisper",
  "device":   "metal" | "cuda" | "cpu",
  "model":    str,
}
"""

MODEL_SIZES = ("tiny", "base", "small", "medium", "large", "turbo")


def build_result(text: str, segments: list[dict], words: list[dict],
                 backend: str, device: str, model: str) -> dict:
    return {
        "text": text.strip(),
        "segments": segments,
        "words": words,
        "backend": backend,
        "device": device,
        "model": model,
    }
