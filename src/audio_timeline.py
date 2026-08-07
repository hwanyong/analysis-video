from pathlib import Path

import librosa
import mlx_whisper
import numpy as np


def transcribe(audio_path: Path, model: str = "mlx-community/whisper-tiny") -> dict:
    result = mlx_whisper.transcribe(str(audio_path), word_timestamps=True, path_or_hf_repo=model)
    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            words.append({"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])})
    segments = [
        {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return {"text": result["text"].strip(), "words": words, "segments": segments}


def emphasis_candidates(audio_path: Path, z_threshold: float = 1.5, hop_length: int = 512) -> list[dict]:
    """어조(음량 스파이크 + 피치 이탈)만으로 결정적 강조 후보를 계산한다.
    대사 의미 판단은 하지 않는다 — 그건 볼트 파이프라인(LLM)의 몫."""
    y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    f0, _, _ = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), hop_length=hop_length
    )
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    rms_z = (rms - np.nanmean(rms)) / (np.nanstd(rms) + 1e-9)
    voiced = f0[~np.isnan(f0)]
    f0_filled = np.nan_to_num(f0, nan=(np.nanmedian(voiced) if voiced.size else 0.0))
    f0_z = (f0_filled - np.nanmean(f0_filled)) / (np.nanstd(f0_filled) + 1e-9)

    score = rms_z + np.abs(f0_z)

    candidates = []
    above = score > z_threshold
    i, n = 0, len(above)
    while i < n:
        if not above[i]:
            i += 1
            continue
        j = i
        while j < n and above[j]:
            j += 1
        peak_idx = i + int(np.argmax(score[i:j]))
        candidates.append({"time": float(times[peak_idx]), "score": float(score[peak_idx])})
        i = j

    return sorted(candidates, key=lambda c: c["time"])
