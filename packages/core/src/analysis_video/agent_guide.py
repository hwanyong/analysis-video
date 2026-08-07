"""`analysis-video agent-guide`가 stdout으로 내보내는 에이전트 온보딩 문서.

영문인 이유: 소비자가 특정 인간이 아니라 임의의 AI 에이전트(Claude Code, Codex,
Cline, Antigravity 등)이므로 최대 호환 언어로 작성한다. 사용법:
`analysis-video agent-guide >> AGENTS.md` (또는 CLAUDE.md, .clinerules).
"""

GUIDE = """\
# analysis-video — Agent Guide

Converts a slide-based lecture video into AI-consumable context:
scene frame images + dialogue timeline + a merged `metadata.json`.

## Pipeline contract (STRICT ORDER — enforced with exit code 3)

```
1. analysis-video analyze <video>
     Runs split + transcribe, then STOPS. The envelope includes `duration`
     (seconds) and the transcript path.
2. YOU (the calling agent) read transcript.json and select the moments that
   matter based on what is being SAID. Write points.json (schema below).
   This "text importance analysis" step is deliberately NOT in the tool.
3. analysis-video frames <video> --points points.json
     Scene-change detection + captures at your points + quality gates.
     Writes metadata.json. Refuses to run before transcribe.
4. Read metadata.json. Each frame bundles {time, image, dialogue}.
```

If no moment is important, you must opt out explicitly: `frames <video> --no-points`.

## points.json schema

```json
{
  "points": [
    {"time": 421.8, "reason": "instructor says this will be on the exam"}
  ]
}
```

- `time`: seconds. Must be within `[0, duration]` — take `duration` from the
  transcribe/analyze envelope (out-of-range = exit 2).
- `reason`: REQUIRED non-empty provenance — why this moment matters.
  It is preserved into metadata.json (`frames[].reasons`; if the capture was
  gated out, under `rejected[].reasons` — never silently dropped).

## Commands

| command | effect |
|---|---|
| `analyze <video>` | split + transcribe, stop for points (add `--points P.json` to run everything) |
| `split <video>` | audio.wav + video.mkv |
| `transcribe <video> [--model tiny..large,turbo] [--language ko] [--force]` | transcript.json; `--force` re-runs (e.g. model change) |
| `frames <video> --points P.json \\| --no-points` | detection + capture + metadata.json |
| `frame <video> --at 421.8 --reason "..."` | one extra on-demand frame after the fact (idempotent per at+reason) |
| `status <video>` | stage completion state |
| `doctor` | environment / STT backend report (exit 4 if no backend usable) |
| `agent-guide` | this document |
| `debug-report <video> [--label L]` | render analysis graph PNG (needs `[viz]` extra) |

- `--out DIR` is accepted by every command that takes `<video>`
  (default: `<video>.analysis/` next to the video). `doctor`/`agent-guide` take no paths.
- STT backend: auto-selected per platform (Apple Silicon→MLX, CUDA→GPU, else CPU).
  Override with `--stt-backend mlx|faster-whisper` or env `ANALYSIS_VIDEO_STT`.

## Output contract

- stdout: exactly ONE JSON envelope per invocation (small; safe to parse).
  `{"ok": true, ...}` or `{"ok": false, "error": {"kind", "message", "hint"}}`.
  This includes usage errors (bad flags → error envelope + exit 2).
  Exceptions: `agent-guide` prints this markdown; `--help` prints usage text.
- stderr: human-readable progress logs. Ignore for parsing.
- Exit codes: 0 ok · 1 internal · 2 bad input · 3 stage-order violation ·
  4 missing dependency/backend.
- Images are returned as file PATHS in metadata.json — read the ones you need.

## Timeouts / resume

Every stage is resumable: if your harness kills a run, re-invoke the SAME
command — completed stages are skipped via state.json. `frames` recomputes
deterministically, but its detector passes are cached (detect_anchor.npz,
detect_adaptive.json), so a re-invocation resumes from extraction.
NOTE: on long videos (30+ min) a cold `frames` pass can take several minutes —
prefer a harness timeout of 10 minutes, or re-invoke until it completes
(each retry makes progress thanks to the caches).

## Output directory layout

```
<video>.analysis/
├── state.json            # stage progress (resume)
├── audio.wav  video.mkv  # split resources (audio absent if video is silent)
├── transcript.json       # full STT: text, segments, word timestamps
├── points.json           # (written by YOU, if you keep it here)
├── frames/               # accepted frame images (full resolution)
│   └── rejected/         # gated-out frames, kept for audit (reasons in metadata)
├── requested/            # frames from `frame --at` (+ requests.json ledger)
├── detect_anchor.npz     # detection time-series cache (debug/GUI, resume)
├── detect_adaptive.json  # adaptive detector cache (resume)
├── frames.json           # every candidate with accept/reject verdict
├── debug_graph.png       # from `debug-report` (optional)
└── metadata.json         # FINAL: frames[{time, image, sources, interval,
                          #   dialogue, reasons?, point_times?, trigger_dialogue?}]
                          #   + rejected[] + requested[] + transcript + params
```
"""
