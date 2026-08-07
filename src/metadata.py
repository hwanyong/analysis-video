import json
from pathlib import Path


def build_metadata(source: dict, audio: dict, video_candidates: list[dict], alignment: list[dict]) -> dict:
    return {
        "source": source,
        "audio": {
            "text": audio["text"],
            "segments": audio["segments"],
            "emphasis_candidates": audio["emphasis"],
        },
        "video": {
            "candidates": video_candidates,
        },
        "alignment": alignment,
    }


def write_metadata(metadata: dict, out_path: Path) -> None:
    out_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
