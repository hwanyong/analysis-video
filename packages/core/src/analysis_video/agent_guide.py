"""`analysis-video agent-guide`가 stdout으로 내보내는 에이전트 온보딩 문서.

영문인 이유: 소비자가 특정 인간이 아니라 임의의 AI 에이전트(Claude Code, Codex,
Cline, Antigravity 등)이므로 최대 호환 언어로 작성한다. 사용법:
`analysis-video agent-guide >> AGENTS.md` (또는 CLAUDE.md, .clinerules).
"""

GUIDE = """\
# analysis-video — Agent Guide

Turns a lecture video into something you can actually read: one section per
on-screen state, with its image(s), the seconds it was displayed, and what was
said during it. That file is `context.md`. Start there.

## Pipeline

```
analysis-video analyze <video>
```

Runs everything (split → transcribe → detect → capture) and stops when
`context.md` is ready. No step in the middle is yours.

Frame extraction is driven by **one criterion: how much the picture changed**.
You do not pre-select "important moments" — earlier versions had you write a
points.json from the transcript, but choosing timestamps from text alone, before
seeing any image, produced a second and incompatible notion of "important frame".
Every on-screen state is captured anyway, so read `context.md` first and then ask
for extra frames if you still need them (see `frame --at` below).

## Analysing only part of a video

```
analysis-video analyze <video> --range 120-300 --range 900-1200
```

Each `--range` (seconds) produces a **separate, self-contained analysis** under
`runs/`. They are independent: ranges may overlap, and where they do, the same
timestamp can be grouped into different screens with different images in each
run. That is not a contradiction — pick one run and read it consistently.
`runs/index.json` and the top-level `context.md` list what exists.

Without `--range` you get a single run named `full`.

## Reading context.md

```markdown
## 63.13-87.73s
![](frames/scene_020_t0063.13.jpg)
![](frames/scene_021_t0087.70.jpg)
N1 없이 커지면 BN이라는값도 당연히 1 없이 커지게 됩니다. ...
```

- One section = one screen, or several screens that went by while a single
  sentence was being spoken.
- Several images = the same screen at different moments: as it appeared, and as
  it looked just before it changed. On handwriting videos that second image is
  the completed board — usually the one you want.
- Every sentence of the transcript appears exactly once across all sections.
  Nothing is duplicated, nothing is dropped.
- `(그림 없음 ...)` means the screen was too dark to capture; the dialogue is
  still there. `(앞 화면과 같은 그림 ...)` means the screen was identical to an
  earlier one, so its image is reused.

## Extra frames on demand

```
analysis-video frame <video> --at 421.8 --reason "why this moment matters"
```

Use it after reading `context.md`, when you want a frame at a moment the change
detector had no reason to capture. `--reason` is required and is kept in the
record. Add `--run <name>` when several runs exist. The image lands in
`runs/<name>/requested/` and is merged into that run's `metadata.json`.

## Commands

| command | effect |
|---|---|
| `analyze <video> [--range A-B ...]` | everything, end to end |
| `split <video>` | audio.wav + video.mkv |
| `transcribe <video> [--model tiny..large,turbo] [--language ko] [--force]` | transcript.json |
| `frames <video> [--range A-B ...]` | detection + capture + context.md |
| `frame <video> --at 421.8 --reason "..." [--run NAME]` | one extra frame (idempotent per at+reason) |
| `status <video>` | stage completion state |
| `doctor` | environment / STT backend report (exit 4 if no backend usable) |
| `agent-guide` | this document |
| `debug-report <video> [--run NAME] [--label L]` | detection graph PNG (needs `[viz]` extra) |

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
- Images are referenced as file PATHS in context.md — open the ones you need.

## Timeouts / resume

Every stage is resumable: if your harness kills a run, re-invoke the SAME
command — completed stages are skipped via state.json. Detection is cached per
video (detect_signals.npz, detect_adaptive.json) and shared by every run, so
adding a `--range` later does not re-scan the video.
NOTE: on long videos (30+ min) a cold pass can take several minutes — prefer a
harness timeout of 10 minutes, or re-invoke until it completes.

## Output directory layout

```
<video>.analysis/
├── state.json            # stage progress (resume)
├── audio.wav  video.mkv  # split resources (audio absent if video is silent)
├── transcript.json       # full STT: text, segments, word timestamps
├── detect_anchor.npz     # detection time-series cache, shared by all runs
├── detect_adaptive.json  # adaptive detector cache, shared by all runs
├── context.md            # ★ INDEX: which runs exist, and what each covers
└── runs/
    ├── index.json        # same list, machine-readable
    └── <name>/           # "full", or e.g. "00120_0-00300_0"
        ├── context.md    # ★ READ THIS — screens, images, dialogue
        ├── frames/       # captured images (rejected/ keeps gated-out ones)
        ├── requested/    # frames from `frame --at` (+ requests.json ledger)
        ├── frames.json   # every candidate with accept/reject verdict
        └── metadata.json # FULL RECORD, for auditing the detector — not for
                          #   reading end to end. window + screens[] +
                          #   frames[{time, image, sources, screen, interval,
                          #   dialogue}] + rejected[] (why each was dropped)
                          #   + requested[] + transcript + params
```
"""
