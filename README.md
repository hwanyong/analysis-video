# analysis-video — turn video into AI-readable context

**Convert lecture, screencast, and slide-based video into a single Markdown file an LLM can actually read: keyframes + timestamps + transcript, aligned screen by screen.**

[![PyPI](https://img.shields.io/pypi/v/analysis-video)](https://pypi.org/project/analysis-video/)
[![CI](https://github.com/hwanyong/analysis-video/actions/workflows/ci.yml/badge.svg)](https://github.com/hwanyong/analysis-video/actions/workflows/ci.yml)
[![Python 3.11–3.14](https://img.shields.io/badge/python-3.11%E2%80%933.14-blue)](#platform-support)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[한국어 README](README.ko.md)

![One section of context.md beside the two frames it points to](docs/media/context-example.png)

*One screen of the demo clip below. The Markdown on the left is verbatim output; the two
images are what its `![]()` lines point to. The board was written line by line, so the tool
keeps both the empty board and the finished one — a cut detector alone would have kept only
the empty one.*

Ask Claude to analyze a YouTube video and all it gets is the subtitles — the speech, and
nothing that was written, drawn, coded, or shown on screen. Subtitles make a good
transcript and a poor record of a video. This tool uses them as the transcript and adds
back the missing half.

`analysis-video` samples frames by **how much the screen changed** rather than at a fixed
interval, and writes **an image of every distinct screen, the time range it was on screen,
and the speech that happened during it** as one Markdown file — one you can grep, index,
version, and hand to any model.

It is built for **AI agents as the primary consumer**, not humans: one JSON object on
stdout per call, decisions expressible through exit codes alone, absolute paths
everywhere, and resumable stages.

```bash
uvx analysis-video@latest analyze lecture.mp4
# → lecture.mp4.analysis/runs/full/context.md
```

No API key. No cloud upload. **Your video never leaves your machine.**

---

## What the output looks like

```markdown
## 63.13-87.73s
![](read/scene_020_t0063.13.jpg)
![](read/scene_021_t0087.70.jpg)
N1 없이 커지면 BN이라는 값도 당연히 1 없이 커지게 됩니다. ...
```

One entry = one screen — or the screens a single sentence spanned, since a screen with no
dialogue of its own is folded into the section of the sentence that was being said over it.
So an entry can carry more than two images. When a screen has two, they are its first and
last appearance — for handwriting or progressive slides, the second one is the completed
state. The transcript is distributed across screens exactly once, with nothing dropped.

The images it links are **downscaled reading copies** under `read/`; the originals stay at
full resolution in `frames/` under the same filenames, and `--read-long-edge` sets the
copy's size. That is a context-window decision, not a disk one: measured, a copy costs
**4.17× fewer tokens** than the full-resolution frame, which is the difference between a
one-hour lecture that fits in a 1M-token window and one that does not. The opening
paragraph of `context.md` states the copy size, the image count, and roughly what opening
all of them costs — so a model can decide how many to open *before* opening any.

The sample above is a Korean lecture; the dialogue comes from a subtitle file when the
video has a usable one, and otherwise from Whisper, which supports any major language.

### Try it on the clip in this repository

![The GUI timeline window plotting the three detection signals against their baselines](docs/media/gui-timeline.png)

*The optional GUI (`analysis-video-gui`) plots the three signals against their baselines.
The four spikes are slide cuts; the slow blue climb from 10s to 29s is the board filling in
— the drift a cut detector cannot see.*

```bash
uv run python examples/make_demo_video.py      # a synthetic, copyright-free lecture clip
uv run analysis-video analyze docs/media/demo-pipeline.mp4
uv run python examples/make_context_figure.py  # rebuilds the figure at the top
uv run python examples/make_gui_screenshot.py  # rebuilds the one above
```

The clip is already committed: [`docs/media/demo-pipeline.mp4`](docs/media/demo-pipeline.mp4)
(41s, 489KB, silent) with its subtitles beside it, so the second command works on a fresh
clone. Nothing in it is anyone else's material — every pixel is drawn by
`examples/make_demo_video.py`, which is also where the expected result is recorded:
**5 screens, 6 images, 0 rejected**. Details in [`examples/README.md`](examples/README.md).

## Why frames *and* transcript

Slide-based teaching puts the *claim* on screen and the *reasoning* in speech. A subtitle
track is an excellent record of that second half — a person wrote it, so the proper nouns
and the numbers are right — which is exactly why this tool reads it when there is one. But
it is still only the second half, and nothing in it records which sentence belonged to
which slide. Frames alone lose the explanation. You need both, aligned.

What each approach leaves you with:

| Approach | What you get |
|---|---|
Subtitles alone — the usual agent fallback for YouTube | speech only; slides, code, diagrams, handwriting all gone |
Claude Messages API | images, not video — animated formats are read as their **first frame only** |
Claude Cowork "Record a skill" | screenshots + input events + narration; the recording is converted first and **not retained** |
Gemini native video input | fixed-rate frames + audio — ~3,600 frames per hour at the 1 fps default, re-sent every request |
`ffmpeg` frame dump every N seconds | thousands of near-duplicates, unlinked to speech |
Manual timestamp picking | requires a human to watch the video first |
**analysis-video** | **every distinct screen + its time range + its speech, as one Markdown file** |

Frames are selected by **how much the screen changed**, not by a fixed interval and not
by timestamps you supply. You do not need to know in advance which moments matter.

## Use cases

- **Feed a lecture, webinar, or conference talk to Claude, GPT, or Gemini** as context
- **RAG / vector-store ingestion** of video content as text + image references
- **Summarize a tutorial or screencast** without watching it
- **Search inside recorded courses** — the Markdown is grep-able
- **Turn a recorded meeting or demo into written notes**
- **Build a dataset** of screen-state → spoken-explanation pairs

## Install

```bash
uvx analysis-video@latest analyze lecture.mp4   # run without installing (like npx)
uv tool install analysis-video                  # install as a global command
pip install analysis-video                      # install into an existing environment
```

`@latest` matters: `uvx` caches the version it resolved the first time and keeps running
that one until told otherwise.

**No ffmpeg installation required.** Decoding uses PyAV, which ships its own binaries.

### Do you need speech recognition?

**The base install has no whisper backend, and most videos never need one.** When the video
has a subtitle beside it or a text track inside the container, that is where the dialogue
comes from — no model is loaded, no weights are downloaded, and nothing touches the
network. Speech recognition is the `stt` extra:

| Your video | What to install |
|---|---|
has a subtitle beside it (`lecture.ko.srt`) or a text track inside the container | **base install** — analysed end to end, offline |
you name a subtitle yourself with `--transcript FILE` | **base install** |
has no usable subtitle anywhere | **`analysis-video[stt]`** |

```bash
uvx 'analysis-video[stt]@latest' analyze lecture.mp4
uv tool install 'analysis-video[stt]'
pip install 'analysis-video[stt]'
```

The split is there because the backend is nearly the whole install: measured on macOS
Apple Silicon, the base install is **108MB downloaded / 308MB on disk**, and `[stt]` takes
it to **326MB / 1,180MB** — 476MB of that is a `torch` this tool never imports, pulled in
by an upstream dependency that declares it unconditionally. On Linux, where neither torch
nor MLX is involved, the extra costs about 70MB rather than 218MB.

Guessing wrong is cheap. `analysis-video doctor` reports the missing capability and still
**exits 0**, and the only run that fails is a transcription that actually reached whisper —
exit **4**, with the install command in `error.hint`.

### Install from the repository

Works before the first release, and afterwards for anything on `main` that is not released
yet. The repository holds two packages, so the subdirectory has to be named:

```bash
uvx --from 'git+https://github.com/hwanyong/analysis-video#subdirectory=packages/core' \
    analysis-video analyze lecture.mp4

# with speech recognition — the extra goes on the name, not on the URL
uvx --from 'analysis-video[stt] @ git+https://github.com/hwanyong/analysis-video#subdirectory=packages/core' \
    analysis-video analyze lecture.mp4

# permanent install, or into an existing environment
uv tool install 'git+https://github.com/hwanyong/analysis-video#subdirectory=packages/core'
pip install 'git+https://github.com/hwanyong/analysis-video#subdirectory=packages/core'
```

Optional debugging GUI (separate package, versioned independently):

```bash
uvx analysis-video-gui@latest <video or .analysis path>
uvx --from 'git+https://github.com/hwanyong/analysis-video#subdirectory=packages/gui' \
    analysis-video-gui <video or .analysis path>      # before the release
```

## Use it from an AI agent

This is the part most video tools miss. One line makes the tool discoverable to your
agent from **any project folder**:

```bash
uvx analysis-video@latest install-skill
```

That installs a short Claude Code personal skill at `~/.claude/skills/analysis-video/`.
No plugin, no marketplace, no MCP server to run. The same file is committed at
[`SKILL.md`](SKILL.md) if you would rather read it before installing anything. For
harnesses without a skill mechanism (Codex, Cline, Cursor, and anything reading
`AGENTS.md`):

```bash
analysis-video install-skill --agents-file AGENTS.md
```

That inserts the full guide between markers and **replaces** that block on re-run, so
upgrading never leaves two conflicting copies in your rules file. If the markers in that
file are not a matched pair, nothing is written and the command exits 2 saying so — it
will not eat the text around them.

The single source of truth for usage is `analysis-video agent-guide`, generated from the
actual code constants — change a threshold and the documentation changes with it.

## How it works

```
video ─► split ────────────► transcribe ─────────► frames ─────► context.md ─► review
         video resource      subtitles first,      scene-change  screens +     what your
         + subtitle tracks   Whisper as fallback   (image ops)   time +        agent read
                                                                 dialogue      it and wrote
```

- **split** — writes a video resource and demuxes any subtitle tracks the container
  carries (PyAV, no external ffmpeg). **No audio file is extracted**: Whisper decodes the
  original video directly, which is bit-identical to decoding a WAV pulled out first and
  saves a third of the analysis directory
- **transcribe** — takes the dialogue from a subtitle file when the video has a usable
  one, and falls back to Whisper (the `[stt]` extra) otherwise. See
  [Where the transcript comes from](#where-the-transcript-comes-from)
- **frames** — detects screen changes and extracts the frames that matter — image
  processing, not a model. Each frame is written twice in one decode: full resolution to
  `frames/`, a reading copy to `read/`
- **context.md** — the AI entry point; `metadata.json` is the full audit record
- **review** — the one step whose content the tool does not write for you. Your agent
  reads `context.md`, writes the analysis, and pipes it back; the tool stores it and tracks
  whether it still matches what was read

**This tool does not interpret anything.** There is no LLM call anywhere in the pipeline —
a subtitle file is read as written, Whisper is a speech-recognition model, and frame
detection is pixel math. What the tool produces is **readable material**; deciding what the
content *means* is done by the AI agent you use (Claude or otherwise) when it reads
`context.md`. That is exactly why the chain ends at `review` and not at `context.md`: the
interpretation happens outside the tool, and `review` is the place it is kept instead of
evaporating with the chat session.

Stages run strictly in order and each one is resumable. If a run is cut off by a timeout,
call the same command again and completed stages are skipped. Every `<video>` command
answers with the same `next` object saying which link of that chain is due, so an agent
never has to work it out.

## Keeping the analysis, and reclaiming the space

```bash
analysis-video review lecture.mp4 --write -   # body on stdin — your agent's analysis
analysis-video review lecture.mp4             # no --write: just report the state
analysis-video clean  lecture.mp4             # no --level: report only, deletes nothing
analysis-video clean  lecture.mp4 --level images
```

**`review`** keeps the analysis at `<video>.analysis/reviews/<run>.md` — deliberately
outside the analysis unit, which is wiped every time frames are re-extracted at a different
threshold. The tool owns only the header: which `context.md` was read and its sha256. That
is what lets a later call answer `current` or `stale` — re-detect at a new threshold and
the stored analysis marks itself out of date instead of quietly aging. The body is never
written or rewritten by the tool. `--export-dir DIR` puts a second copy wherever you want
one, without moving the original.

**`clean`** removes what can be rebuilt. Called with no `--level` it deletes nothing and
only reports what is there and what each level would free. Levels are cumulative: `cache`
drops the split video resource (no cost — frame extraction falls back to the original
video), `images` also drops the full-resolution `frames/`. Never removed at any level:
`reviews/`, `transcript.json`, the `read/` copies `context.md` links to, frames you ordered
with `frame --at`, and the JSON records.

## Where the transcript comes from

A subtitle written by a person beats any recognizer: the proper nouns, the jargon, and the
numbers are spelled the way the author meant, and the timings were already cut against the
video. So the dialogue is taken from the **first source that works**:

| | Source | If it can't be used |
|---|---|---|
1 | `--transcript FILE` — an `.srt` / `.vtt` / `.smi` file you name | **stops with exit 2** when the file yields nothing to use. You named this file; silently substituting another source would return something other than what you asked for |
2 | **the subtitles this video already has** — every sidecar beside it (`lecture.ko.srt`, `lecture.srt`, `lecture.mp4.srt`) *and* every text track inside the container (demuxed by `split` to `subs/track<n>.srt`), ranked as **one** list | records why, then opens the next candidate; falls through only when every one is spent |
3 | **Whisper**, decoding the original video's audio directly (no intermediate file) | if the video has no audio at all, the transcript is written empty rather than failing |

Step 2 being a single step is the point: its candidates are ordered by **language first**
and by where they came from only afterwards, so a container track in the language you
asked for beats a sidecar file in a different one. Rank a whole pool ahead of the other
instead, and "the right language" would only ever win inside a pool.

Not every subtitle file is a transcript, so each candidate has to earn the slot. It is
rejected — and the next candidate is opened — when it covers less than **30%** of the
video's duration (the signature of a *forced* track that only translates foreign lines),
has fewer than **5 cues**, runs past the end of the video (a subtitle belonging to some
other file), or is more than **30% roll-up**, where each cue restates the one before it
and grows.

That last one is what **auto-generated captions** look like. They are refused on purpose:
re-using another engine's speech recognition is strictly worse than running Whisper, where
you choose the model and the output records which engine produced it. Embedded tracks are
filtered earlier still — bitmap subtitles (PGS, VobSub) carry no text at all, and tracks
the container flags `forced` are never extracted.

Those four checks belong to step 2, where the tool is choosing among candidates it found
for itself. **Name a file with `--transcript` and the choosing is already done**: the file
is used even if a check would have refused it, and the finding becomes a line in
`source.notes` plus a warning on stderr. That is how you use a partial forced-subtitle
track deliberately. What still stops the run at step 1 is a file with nothing in it to
use — missing, unreadable, or holding no cues at all.

Every step is written to `transcript.json` under `source`: `kind`
(`explicit` · `sidecar` · `embedded` · `whisper` · `none`), the file path or track index,
cue count, coverage, and a note for each source that was passed over. You can always tell
why Whisper ran.

`--no-subtitles` skips the ladder entirely and transcribes the audio — for a video that
arrived with auto-generated captions attached, or when you want the audio's version. And
if you swap the subtitle file and run again, the transcription is redone without
`--force` — the path and size of the **top-ranked sidecar** are recorded as input to the
stage, so replacing it invalidates the result the way a different video would. (Only that
one file is watched: a run whose winner was a container track still records the sidecar,
and `--force` is what re-runs the choice.)

Whenever a new transcript is actually written — that case, or an explicit
`transcribe --force` — the `frames` stage goes back to incomplete and has to run again.
`context.md` distributes the dialogue over the screens, so a rebuilt transcript makes the
previous build stale; running `frames` (or `analyze`) after a re-transcription is the
step that brings them back into agreement.

### Which language, and why nothing is translated

**`--sub-lang CODE` says which language you want the subtitles in.** It is the **first**
key of rung 2's ranking, and that ranking spans sidecar files and container tracks
together — so this flag, not the source, decides what is opened first: the language you
asked for, then candidates that declare no language at all (an untagged `lecture.srt` is
the file you put there yourself; an untagged track is usually the container's only
dialogue track), then everything else. Source only breaks a tie between candidates that
are equal on language: a file you placed beside the video, then a track that merely came
with the container. It never rejects anything — a subtitle in the wrong language still
beats no subtitle, so a mismatch is a demotion, and if nothing matches the best remaining
candidate is used anyway. `ko` and `kor` count as the same language (ISO 639-1 vs 639-2),
and region subtags are ignored (`ko` = `ko-KR`).

**With no flag the target language is your system locale** (`LC_ALL` > `LC_MESSAGES` >
`LANG` > `LANGUAGE`, reduced to its primary tag: `ko_KR.UTF-8` → `ko`). On a Korean
desktop `lecture.ko.srt` is therefore picked over `lecture.en.srt` with nothing passed at
all — and the same command can pick differently on a machine set to another language,
which is why the resolved target and the runners-up are recorded in `source.notes`. `C`,
`POSIX`, or no locale set means no language preference, not an error. Note that
**`--language` is a different flag**: it tells Whisper what language the *speech* is in and
has no say in which subtitle is chosen. The two are separate because they can disagree —
an English lecture you want to read with the Korean subtitle shipped beside it.

**Nothing is translated.** The subtitle that won, or Whisper's output, may well be in
another language than the one you asked for; when that happens the run says so and leaves
the dialogue exactly as it is. Three fields record it: `source.language` in
`transcript.json` (what the transcript actually is — declared by the filename or the
container, detected by the model for Whisper), `source.target_language` beside it (what
was asked for, whether by flag or by locale), and `language_mismatch` in the command's
JSON result (whether the two differ; `source.notes` says the same in one sentence). Read
that flag rather than comparing the two strings, since it knows `ko` = `kor`. Translating
is out of scope on purpose: the dialogue is the material you line up against what is on
screen, and a translated line no longer matches the words in the frame. Whisper's own
translate mode only ever produces English, so it could not serve a request for Korean
either. Turning a mismatch into text you can read is the job of the agent reading
`context.md`.

### If you downloaded the video

Downloading is out of scope: this tool reads local files and never fetches content. But
`yt-dlp`'s default layout is already the one it looks for.

```bash
yt-dlp --write-subs --sub-langs ko --convert-subs srt <url>
# → lecture.mp4 + lecture.ko.srt      ← picked up with no extra flags
```

- **`--write-subs` only — never `--write-auto-subs`.** The two write the *same filename*
  (`lecture.ko.vtt`), so nothing in the name says which one you got. The roll-up check
  usually catches machine captions, but it is a content heuristic, not a guarantee; the
  reliable move is not to download them.
- `--convert-subs srt` is optional — `.vtt` and `.smi` are read as they are. `.ass` is not
  supported.
- The language tag is read as the **first piece after the video's name**, not the last piece
  before the extension: `lecture.ko.srt` declares `ko`, but `lecture.720p.ko.srt` declares
  `720p` — the file is still a candidate, just with no language the picker can match.
- Downloading several languages leaves several candidates, so say which one you mean with
  **`--sub-lang ko`** — or leave it out and let your system locale decide, as above.
  (`--language` is a different flag: the speech hint Whisper uses when it has to listen to
  the audio. It has no say in which subtitle is chosen.)

### Speech-to-text backends

Installed by the `[stt]` extra, and only reached when no usable subtitle exists. Chosen
automatically per platform; transcription runs on your machine and no audio is sent
anywhere.

| Environment | Backend | Note |
|---|---|---|
macOS Apple Silicon | `mlx-whisper` (Metal) | measured 37.6× realtime with `tiny` |
NVIDIA GPU | `faster-whisper` (float16) | `[cuda]` extra, **not verified on real hardware** |
Intel Mac · Linux · Windows | `faster-whisper` (CPU int8) | |

Override with `--stt-backend` or `ANALYSIS_VIDEO_STT`. Requesting a backend that is not
installed exits with code 4 rather than silently falling back to the other one — and so
does reaching this rung at all with the extra absent. That failure names the install
command and lists why every subtitle candidate was passed over, because "put a `.srt` next
to the video" is often the better answer than installing 872MB.

Model weights are a **separate** download, from Hugging Face, the first time Whisper
actually runs (`tiny` ≈ 74MB · default `small` ≈ 460MB · `large` ≈ 3.1GB), and are cached
afterwards. `analysis-video doctor` reports cache state without touching the network.

## Output contract for agents

- **stdout** — exactly one JSON object per call: `{"ok": true, ...}` or
  `{"ok": false, "error": {"kind", "message", "hint"}}`. Exceptions: `agent-guide` prints
  Markdown, and `--help` / `--version` print plain text.
- **stderr** — human-readable progress logs, never parse them
- **exit codes** — `0` ok · `1` internal · `2` bad input · `3` stage order violation ·
  `4` something the run needed is missing — raised where the need arises, not where the
  environment is inspected (`doctor` exits 0 on a machine with no speech recognition,
  because subtitles need none)
- **paths** — always absolute, so the working directory never matters. `<video>` takes
  either the video file or the `.analysis` directory of a run you already have
- **resume** — re-running a command skips completed stages
- **`next`** — every `<video>` command ends with the same object, so the caller never has
  to know which command it just ran:

```json
{"do": "run",  "command": "analysis-video analyze …", "why": "…"}
{"do": "read", "read": ["/abs/runs/full/context.md"],
               "command": "analysis-video review … --run full --write -",
               "why": "…", "remaining": ["full"],
               "cost": {"images": 78, "image_tokens": 34476, "rule": "…"}}
{"do": "done", "why": "…"}
```

`run` hands you a command to execute. `read` hands you the files to open plus the command
that writes the result back — with `cost` saying what opening them is worth in tokens
*before* you open them. `done` means answer the user. `status` reports the same object
alongside a `runs[]` list carrying each unit's `context.md` path and its review state.

**Analysis directories are not upgraded across versions.** `state.json` and
`metadata.json` record the format they were written in (currently
`analysis-video/state@4` and `analysis-video/metadata@3`), it is checked on every read, and
a directory from an older version is refused — `schema-mismatch`, exit 2, with a hint to
pass a fresh `--out` or delete the directory and analyze the video again. There is no
migration path, deliberately: letting a half-recognized directory through only moves the
failure later and deeper, where it looks like a bug in the tool instead of something you
can fix. Nothing in the directory is deleted for you, and the video is never touched.

Full contract: [`packages/core/README.md`](packages/core/README.md).

## Platform support

Python 3.11–3.14. Install resolution is verified on every combination below.

| | macOS (Apple Silicon / Intel) | Linux x86_64 / ARM64 | Windows x64 | Windows ARM64 |
|---|---|---|---|---|
Python 3.11–3.13 | ✅ | ✅ | ✅ | ❌ |
Python 3.14 | ⚠️ no `[stt]` backend exists | ✅ | ✅ | ❌ |

⚠️ means the tool installs and analyses subtitled video end to end; the `[stt]` extra
resolves there but no upstream backend publishes a wheel for that combination. ❌ is the
base install itself: `opencv-python-headless` has no Windows ARM64 wheel.

Known limits (upstream wheel availability, install size, transcription verification
status) are listed honestly in [`packages/core/README.md`](packages/core/README.md).

## FAQ

**Claude already summarizes YouTube videos. What's missing?**
The screen. That summary comes from the subtitles — fine for a talking-head interview, lossy
for anything taught on screen: the slide, the code, the diagram, the equation being worked
out. This tool reads the same subtitles, but does not stop there: it restores the visual
half and pins each line of speech to the screen it belongs to.

**My video already has subtitles — will it use them, or run Whisper anyway?**
It uses them, as long as they hold up: a sidecar file next to the video or a text track
inside the container is preferred over Whisper, and `--transcript FILE` names one directly.
Whisper is then never loaded — which is why that path also needs no `[stt]` extra and no
network. Auto-generated captions and forced (foreign-lines-only) tracks are rejected, and
that is the case where Whisper runs instead. See
[Where the transcript comes from](#where-the-transcript-comes-from).

**Claude can analyze a screen recording — doesn't that cover it?**
Claude Cowork's "Record a skill" does take a recording, but converts it first: what it keeps
is a set of screenshots plus your input events plus the audio narration, and the video
itself is not retained. That is the same decomposition this tool performs — scoped to
capturing a workflow, on macOS, inside that one product. It does not produce a portable file
for an arbitrary lecture video, and the Messages API has no video input at all (animated
image formats are read as their first frame only).

**Gemini accepts video directly — why would I use this?**
Three reasons. Fixed-rate sampling is the wrong shape for screen-stable content: at the
default 1 fps an hour of lecture is ~3,600 frames, nearly all duplicates, and Google's own
docs tell you to hand-tune the rate down for lectures — this tool does that adaptively, by
detecting screen changes. Second, you get a **file**, not a one-shot API call: `context.md`
can be grepped, indexed for RAG, committed, and re-read for free. Third, it works with
models that take no video at all, and it never uploads yours.

**Does it upload my video anywhere?**
No. Video decoding, scene detection, and transcription all run locally. The only network
access is the one-time download of Whisper model weights — and when the transcript comes
from a subtitle file or subtitle track, even that never happens: reading subtitles needs no
model, so such a video can be analyzed on a fully offline machine.

**How much disk does the analysis directory take?**
More than the video: measured at **1.9–2.8× the source**, or about **4.48MB per minute** —
roughly 0.27GB for a one-hour lecture, 2.7GB for ten of them. It used to be 5.85MB/min;
dropping the intermediate audio file took 1.92MB/min off that (a third of the directory)
and the reading copies added 0.55MB/min back. `analysis-video clean <video>` reports what
is reclaimable before deleting anything — on a measured sample `--level images` took a
directory from 9.8MB to 1.4MB. It never touches `reviews/`, `transcript.json`, the `read/`
images `context.md` links to, or frames you ordered with `frame --at`, so nothing that
would need an LLM or a fresh transcription to rebuild is ever removed.

**The context is still too large for my model. What do I cut?**
Open fewer images before extracting fewer: `context.md` states what opening all of them
costs, and each section's time range tells you which screens were held longest. If you do
want fewer extracted, raise the cut-area threshold — `analysis-video agent-guide` is the
single source of truth for those flags and their values, generated from the code constants.
This README deliberately keeps no second copy of them.

**Do I need to install ffmpeg?**
No. PyAV bundles its own decoders.

**How big is the install?**
Measured on macOS Apple Silicon: **108MB downloaded, 308MB on disk** — no whisper backend,
no torch. Adding `[stt]` takes it to **326MB / 1,180MB**, and 476MB of that is a `torch`
this tool never imports (an upstream dependency declares it unconditionally). On Linux the
extra costs about 70MB rather than 218MB, because neither torch nor MLX is involved there.
Whisper model weights are a separate download on first use.

**Do I need `[stt]`?**
Only for video with no usable subtitle. A subtitle file beside the video, a text track
inside the container, or `--transcript FILE` all work on the base install with no model and
no network. `analysis-video doctor` tells you what the current install can do and exits 0
either way; the run that actually needs a backend and cannot find one exits 4 and names the
install command.

**Can I use it without installing anything?**
Yes — `uvx analysis-video@latest …` runs it in a throwaway environment, the Python
equivalent of `npx`. Before the first release, point it at the repository instead:
`uvx --from 'git+https://github.com/hwanyong/analysis-video#subdirectory=packages/core' analysis-video …`.

**Is there an MCP server?**
No, deliberately. The CLI already returns structured JSON with an exit-code contract; an
MCP wrapper around it would be a 1:1 restatement with an extra process to keep running.
`install-skill` gives agents the same discoverability with none of that.

**Which video formats work?**
Whatever PyAV/FFmpeg decodes — MP4, MOV, MKV, WebM, and so on. Note that Qt's bundled
FFmpeg cannot decode AV1, which is why playback in the GUI uses PyAV too.

**Does it work on non-slide video?**
It is designed for screen-stable content — lectures, screencasts, slide decks, coding
tutorials, whiteboard recordings. Continuously moving footage produces many screen
changes and is not the target.

**Can I analyze only part of a video?**
Yes: `analysis-video analyze lecture.mp4 --range 120-300 --range 900-1200`. Each range
becomes an independent analysis unit; ranges are never merged.

**What if I need a frame the detector had no reason to pick?**
`analysis-video frame lecture.mp4 --at 421.8 --reason "why this moment matters"` — an
on-demand single frame after the fact.

## Repository layout

| Package | Role |
|---|---|
[`packages/core`](packages/core) — `analysis-video` | **The product.** Complete on its own |
[`packages/gui`](packages/gui) — `analysis-video-gui` | Debugging GUI for reviewing output and tuning detection (PySide6) |
[`examples`](examples) | Scripts that draw the demo clip and the figures in this README |

The CLI is the product; the GUI is a verification tool. They are published as separate
PyPI packages with independent versions — fixing the GUI does not require re-releasing
the core, and CLI-only users never download Qt.

## Development

```bash
uv sync          # uv workspace — both packages, every extra ([stt], [viz], …)
uv run pytest    # core + GUI tests
```

Release procedure: [`docs/RELEASING.md`](docs/RELEASING.md).
Changes: [`CHANGELOG.md`](CHANGELOG.md).

## License

MIT ([LICENSE](LICENSE)). The GUI depends on PySide6-Essentials (LGPL), which carries its
own notice obligations when redistributed; the core CLI does not.

---

<sub>Keywords: video to markdown · video to text for LLM · lecture video analysis ·
screencast to text · slide extraction · keyframe extraction · scene detection ·
Whisper transcription CLI · SRT VTT SMI subtitle to transcript · local speech to text ·
AI agent tool · LLM context from video ·
video RAG preprocessing · multimodal context · Claude Code skill · offline video analysis</sub>
