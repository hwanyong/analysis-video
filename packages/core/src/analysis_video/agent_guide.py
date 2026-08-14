"""`analysis-video agent-guide`가 stdout으로 내보내는 에이전트 온보딩 문서.

영문인 이유: 소비자가 특정 인간이 아니라 임의의 AI 에이전트(Claude Code, Codex,
Cline, Antigravity 등)이므로 최대 호환 언어로 작성한다. 사용법:
`analysis-video agent-guide >> AGENTS.md` (또는 CLAUDE.md, .clinerules).

기본값·선택지는 본문에 적지 않고 `@…@` 자리표시자로 두고 실제 상수에서 주입한다.
문서에 숫자를 복사해 두면 임계 하나 바꿀 때마다 "문서가 말하는 기본값"과 "코드가
쓰는 기본값"이 갈린다 — frames.py가 임계 상수를 한 군데로 모아 둔 것과 같은 이유다.
파라미터 누락은 tests/test_agent_guide.py가 파서와 대조해 막는다.
"""
from .budget import READ_LONG_EDGE
from .frames import (DEFAULT_ANCHOR_THRESHOLD, DEFAULT_CUT_AREA_THRESHOLD,
                     DEFAULT_RATE_THRESHOLD, RECOMMENDED_CUT_AREA_THRESHOLD)
from .review import MAX_BYTES as REVIEW_MAX_BYTES
from .stt import BACKENDS, STT_EXTRA
from .stt.base import DEFAULT_MODEL, MODEL_SIZES
from .stt.subtitles import MAX_ROLLUP, MIN_COVERAGE, MIN_CUES

_TEMPLATE = """\
# analysis-video — Agent Guide

Turns a lecture video into something you can actually read: one section per
on-screen state, with its image(s), the seconds it was displayed, and what was
said during it. That file is `context.md`. Start there — and finish by writing
what you made of it back with `review`, which is where your analysis is kept.

## What you need first: the video, as a file

`<video>` is always a path on the machine you are running on — the video file
itself, or an `.analysis` directory a previous run produced (see "The `<video>`
argument"). There is no URL form: a link passed where `<video>` goes is just a
path that does not exist (`video-not-found`, exit 2). Everything below reads a
file that is already on disk — no video is ever fetched for you.

The tool reaches the network for one thing, and only when it actually has to
recognise speech: the STT model weights, pulled from HuggingFace the first time
whisper runs and then cached (`tiny` about 74MB, `small` about 460MB, `large`
about 3.1GB; @MODEL_DEFAULT@ is the default). **A transcript that came from
subtitles needs neither the network nor a model** — see "Where the dialogue
comes from". So a first run inside a network-isolated sandbox ends in
`stt-model-unavailable` (exit 4) only when the video has no usable subtitles
either. Run `analysis-video doctor` first — it reports whether a backend is
installed at all and whether the weights are already cached, and it is the
cheapest way to warm that cache before you start timing real work.

Getting that file there is not part of this pipeline. So:

- **Use the path the user gave you.** If they named a file, use exactly that.
- **If no file was named, ask for one.** Do not go hunting around the filesystem
  for something that looks like a lecture video, and do not substitute a
  different video because it was easier to find.
- **If the video is not on disk yet, say so and stop there.** Obtaining it is a
  separate step, outside this tool, under whatever instructions and rules you
  are operating by — whether a particular source may be retrieved at all is a
  question of that source's terms and of the law where you are running, and it
  is not one this tool answers, performs, or sanctions. It reads local files;
  that is the whole of its contract.

What the file itself has to satisfy — usually nothing you need to act on:

- **Any container FFmpeg can demux** (mp4, mkv, webm, mov, ...). It is read
  directly; there is no need to convert, re-encode, or otherwise prepare it
  first, and doing so only costs you quality.
- **No audio stream is fine.** `split` still succeeds and reports
  `"has_audio": false`. If the video comes with subtitles the transcript is
  still complete — they are read as text, not heard. Otherwise it comes out
  empty and every screen simply has no dialogue.
- **A subtitle file beside the video is used instead of speech recognition,**
  automatically, with no flag from you: `lecture.mp4` + `lecture.ko.srt` in the
  same directory is all it takes. Same for subtitle tracks inside the container.
  Bring one along when you can — it is the difference between a transcript that
  is exact and one that is inferred, and between seconds and minutes.
- **Leave it where it is.** The first run records the source by resolved path
  and byte size, and every later invocation is checked against that record.
  Moving it, renaming it, re-encoding it, or replacing it with a fresh copy
  part-way through gives you `source-mismatch` (exit 2) — the guard exists so a
  resumed pipeline cannot silently continue against a different original. Put
  the file at its final location before you start, and pass the same path every
  time. To analyse a genuinely different file, give it a fresh `--out`.
- **Somewhere writable.** Output defaults to `<video>.analysis/` next to the
  video; `--out` moves it if that directory is read-only.

## Speech recognition is an optional install

**The base install has no whisper backend in it, and most videos never need
one.** The transcript comes from subtitles whenever the video has any (next
section), and that path loads no backend, downloads no weights and opens no
socket. The backends live behind an extra, `@STT_EXTRA@`, because they are
the overwhelming majority of the install size (measured: 883MB of a 1,190MB
installation, most of it a torch that is never imported).

```
uvx '@STT_EXTRA@@latest' analyze <video>   # one-off run, with recognition
uv tool install '@STT_EXTRA@'              # or keep it installed
pip install '@STT_EXTRA@'
```

`@latest` is not decoration: `uvx` caches the version it resolved the first time
and keeps running that one until you say otherwise.

**Do not install it pre-emptively, and do not refuse to analyse a video because
it is absent.** A missing backend is a capability this environment does not
have, not a broken environment: `doctor` reports it and still exits 0, and the
only thing that fails is a video with no usable subtitle anywhere. That failure
is `stt-backend-missing` (exit 4), and it carries the install command in
`error.hint` plus every reason the subtitle ladder came up empty in
`error.details.notes`. Read those before you install anything — "put a `.srt`
next to the video" is often the cheaper fix, and it gives a better transcript
than whisper would have.

## Where the dialogue comes from

The transcript is not necessarily speech recognition. Three sources are tried in
this order, and the first one that passes validation wins:

1. **`--transcript PATH`** — the subtitle file you named.
2. **The subtitles this video already has** — every subtitle file beside it and
   every text track inside the container, ranked as **one** list.
3. **whisper** — only once nothing in step 2 could be used.

Step 2 being a single step is the point. Its candidates are ordered by
**language first** and by where they came from only afterwards, so a container
track in the language you asked for beats a sidecar file in a different one. Rank
a whole pool ahead of the other instead, and "the right language" would only ever
win inside a pool — which is exactly how a video with an English sidecar and a
Korean track inside it used to be transcribed in English.

The order in full:

1. the language you asked for — `--sub-lang`, or the system locale;
2. candidates that declare no language at all — an untagged `lecture.srt` is the
   file you put there yourself, and an untagged track is usually the only
   dialogue track the container has;
3. everything else — a mismatch is a demotion, never a rejection.

Ties on language are broken by source (a file you placed beside the video, then a
track that merely came with the container), and after that by the rules each kind
always had: anything named `forced` last, the track the container marks `default`
first, `srt` > `vtt` > `smi`, then stream index or filename.

What counts as a candidate: `<stem>.<lang>.srt` (`lecture.ko.srt` for
`lecture.mp4`), plain `<stem>.srt`, or `<whole filename>.srt`
(`lecture.mp4.srt`), with `.vtt`/`.webvtt` and `.smi`/`.sami` read the same way;
plus every text track `split` demuxed to `subs/track<n>.srt`.

**A refused candidate is not the end of step 2.** Each one is opened in rank
order and every rejection is recorded before the next is tried, so an
auto-generated file that happened to rank first costs one wasted read and the
step continues with the candidate below it. whisper runs only after the last one
has failed.

The difference between step 1 and step 2 is what happens on failure. A file you
named is a demand: if it cannot be used the run **stops** (exit 2) rather than
quietly transcribing something else, because a transcript built from a source you
did not ask for is not the thing you requested. The automatic step is a search,
so it notes the reason and moves down.

Either way the reasons survive into `transcript.json`: `source.kind` is
`explicit` | `sidecar` | `embedded` | `whisper` | `none` and tells you which step
won — and, within step 2, which pool the winner came from. `source.notes` names
the candidate that was picked over which others, and why each rejected one was
rejected. Read those two before concluding that a poor transcript means a poor
model.

A subtitle is refused when it looks like something other than the dialogue of
this video:

- fewer than @MIN_CUES@ cues — not a dialogue track at all;
- covering less than @MIN_COVERAGE@ of the running time — the signature of a
  forced-subtitle track, which translates only the foreign-language moments and
  would leave most of the lecture looking silent;
- a time span far outside the video's duration — subtitles cut for a different
  edit of the same material;
- more than @MAX_ROLLUP@ of cues starting with the previous cue's text — the way
  **automatically generated** captions are built. Refusing those is the point,
  not a limitation: they are speech recognition already, no better than what
  runs here, and their rollup repetition would put one sentence on several
  screens in a row.

These four decide **which candidate wins** among the ones the tool found for
itself, so they apply to steps 2 and 3 only. Name a file with `--transcript`
and the choosing is already done: that file is used, and a finding becomes a
line in `source.notes` instead of a refusal. Use that when you know the
subtitle is partial and want it anyway.

One structural consequence: `transcript.json` has an empty `words` array for
every subtitle source. Cue timing is per line, not per word. Nothing in
`context.md` depends on word timing, so this costs you nothing — but do not
build on `words` being populated.

### Which language you got, and which you asked for

Three fields answer that, in `transcript.json` and in the `transcribe` result.
`source.language` is what the transcript **actually is** — declared by the
filename or the container for a subtitle source, detected by the model for
whisper. `source.target_language` is what was **asked for**: `--sub-lang`, or
the system locale when you did not pass it. `source.target_language_source`
says which of those two it was: `requested` or `locale` (`null` when neither
said anything).

When they differ the result carries `"language_mismatch": true` and
`source.notes` says so in one sentence. Trust that flag rather than comparing
the two strings yourself: the same language arrives as `ko` from a filename and
`kor` from a container (ISO 639-1 vs 639-2), and those are treated as equal.

**Read `target_language_source` before you treat a mismatch as a problem.** On
`locale` the target is a default nobody asked for, and a Korean lecture
transcribed correctly from Korean subtitles still reports a mismatch on a
machine whose locale is English. That is the flag working, not a fault: it
answers "is this the language you would have wanted?", and the honest answer
when nobody stated a want is "we assumed one". On `requested` the mismatch is
about something the caller actually asked for, and is worth surfacing to them.

The two places can disagree, and that is not a bug: when a finished transcript
is reused, the **result** answers the invocation you just made, while
`transcript.json` keeps the request it was built with. The transcript is not
rewritten just because you asked about it in a different language.

**Nothing is translated.** A mismatch means the dialogue is simply in another
language; the transcript stays in that language, verbatim. Translating is your
call to make afterwards, on text you can now see is not what you asked for. It
is also not always an error — an English lecture with only English subtitles
reports a mismatch against a Korean locale and is still the best transcript
that exists. Both fields are `null` when nothing said otherwise: an untagged
`lecture.srt` on a machine with no locale set is not a mismatch, it is an
unknown, and unknowns are not reported as problems.

### Subtitles for a video you had to download

Nothing above changes the boundary: this tool downloads nothing, and fetching
the video — subtitles included — is a separate step outside it, under the rules
you are operating by. What is worth knowing is that the downloader's flags
decide whether whisper has to run at all. With yt-dlp:

- **`--write-subs`** (with `--sub-langs ko,en` when you want particular
  languages, and `--convert-subs srt` to be sure of the format) — these are the
  subtitles a human wrote. Its default naming already produces
  `<stem>.<lang>.srt` beside the video, which is exactly what step 2 looks for.
  `--sub-langs` is yt-dlp's flag and decides what gets downloaded; this tool's
  `--sub-lang` only ranks the files you already have.
- **Not `--write-auto-subs`.** Those are the automatically generated captions,
  written in rollup form, and the rollup check above refuses them — you would
  pay for the download and run whisper anyway. When a video only has automatic
  captions, do not fetch them; whisper is the better source of the two.
- `.ass`/`.ssa` is not read as a sidecar file (its styling and its text share a
  line, which needs a different parser); `--convert-subs srt` avoids the
  question. The same subtitle **inside** the container is fine — `split`
  rewrites every text track to SRT on the way out.
- Keep the video and its subtitle in one directory with one stem. Nothing is
  searched for elsewhere; a subtitle that lives somewhere else has to be named
  with `--transcript`.

## Pipeline

```
# 1. build it
analysis-video analyze <video>
# 2. read runs/<name>/context.md, then
# 3. write down what you made of it
analysis-video review <video> --run <name> --write - <<'EOF'
...your analysis...
EOF
```

Step 1 runs everything mechanical (split → transcribe → detect → capture) and
stops when `context.md` is ready. No step in the middle is yours.

**The pipeline does not end there.** `context.md` is the material, not the
answer: what the user asked for is your reading of the lecture, and if it stays
in the chat it is gone with the session while the directory claims the work is
complete. `review` is the place for it — one markdown file per analysis unit,
kept beside the analysis and never overwritten by a re-run. A video is finished
when **every unit has a current review**, not when `context.md` exists.

You do not have to keep track of where you are in that chain. Every command
that takes a `<video>` ends its result with a `next` object that says what to do
now — `do: "run"` (execute `command`), `do: "read"` (open `read[]`, then submit
with `command`), `do: "done"` (answer the user). `analysis-video status <video>`
answers the same question without doing any work. See "Output contract".

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

Each unit is reviewed on its own: `review … --run <name>` writes one file per
unit, and `next` walks them one at a time (`remaining` names the ones still
waiting). Reading two units and writing one combined analysis leaves the other
unit `missing` forever.

## Reading context.md

```markdown
## 63.13-87.73s
![](read/scene_020_t0063.13.jpg)
![](read/scene_021_t0087.70.jpg)
N1 없이 커지면 BN이라는값도 당연히 1 없이 커지게 됩니다. ...
```

The file opens with a counts line (screens · images · duration) and then one
paragraph of **cost**: how large the reading copies are, how many there are, and
roughly how many tokens opening all of them would spend, with the rule that
number was computed by. Read that paragraph before you start opening images —
it is there so "open only what you need" is an instruction you can actually act
on rather than a plea. The same two numbers arrive in `next.cost` (`images`,
`image_tokens`, `rule`) without opening any file at all.

- The images `context.md` points at live in `read/` and are **reduced copies**,
  long edge @READ_LONG_EDGE@ px by default. Measured: 442 tokens for one of them
  against 1,843 for the same frame at 1920×1080 — 4.17× cheaper, and text,
  formulas and handwriting all stay legible. Open these.
- **The originals are in `frames/`, under the same filename.** Swap the
  directory in the path when you need pixel-level detail (a number you cannot
  quite read, a thin line). Nothing else differs — same frame, same moment.
- One section = one screen, or several screens that went by while a single
  sentence was being spoken.
- Several images = the same screen at different moments: as it appeared, and as
  it looked just before it changed. On handwriting videos that second image is
  the completed board — usually the one you want.
- Every sentence of the transcript appears exactly once across all sections.
  Nothing is duplicated, nothing is dropped.
- `(그림 없음 ...)` means no frame passed the gate for that screen: the frame had
  almost no content (a blank slide or board), not that it was dark. The dialogue
  is still there.
- `(무음)` stands in for the dialogue when a screen has images but nothing was
  said over it.

## Extra frames on demand

```
analysis-video frame <video> --at 421.8 --reason "why this moment matters"
```

Use it after reading `context.md`, when you want a frame at a moment the change
detector had no reason to capture. `--reason` is required and is kept in the
record. Add `--run <name>` when several runs exist. The image lands in
`runs/<name>/requested/` and is merged into that run's `metadata.json`.

It is written at **full resolution and has no reading copy**: it is not part of
`context.md`, so nothing points at it but you, and you asked for this one moment
deliberately. Opening it therefore costs what a full-resolution frame costs —
about 4× one image in `read/` (see `--read-long-edge`). That is the right trade
for a handful of frames and the wrong one for dozens.

## Commands

Every command, with every flag it takes. Nothing else exists: an unknown flag is
a usage error (error result, exit 2), not a warning. `<video>` is always the
original video file. Options shared by several commands (`--out`, the subtitle
flags, the STT trio, the three thresholds, `--read-long-edge`, `--range`) are
specified once under **Shared options**.

### analyze — the whole pipeline, end to end

```
analysis-video analyze <video> [--out DIR]
    [--transcript PATH] [--sub-lang CODE] [--no-subtitles]
    [--model SIZE] [--stt-backend NAME] [--language CODE]
    [--range A-B ...] [--anchor-threshold F] [--rate-threshold F]
    [--cut-area-threshold F] [--read-long-edge PIXELS]
    [--until split|transcribe|frames]
```

- `--until` — where to stop. `split` returns once the video resource and the
  subtitle tracks are separated out, `transcribe` after transcript.json,
  `frames` (the default) goes all the way to `context.md`.
- It stops at `context.md` by design; the step after it is yours to take —
  read that file and record what you make of it with `review`.
- Nothing here has to be told where the dialogue comes from: the source ladder
  runs on its own, and `--transcript` / `--sub-lang` / `--no-subtitles` are only
  there to override it.
- There is deliberately no `--force` here: a finished transcript is reused even
  if `--model` asks for a different size. To change the model of an existing
  analysis, run `transcribe --force` first, then `analyze`. The one thing that
  does re-transcribe by itself is a changed subtitle input — see `transcribe`.

### split — video.mkv + subs/, and no audio file at all

```
analysis-video split <video> [--out DIR]
```

Takes no other flags. It writes exactly two kinds of thing: `video.mkv` (the
video stream, copied without re-encoding) and `subs/track<n>.srt`.

**There is no `audio.wav`, and nothing downstream wants one.** When whisper has
to run it decodes the original video directly — measured on three videos, the
audio array it gets that way is bit-identical to the one an extracted wav would
have given (the decoder does not care which container it reads). A wav file was
therefore a pure intermediate: a third of the analysis directory (1.92 MB per
minute of video) written so it could be read once and never again. On a video
whose dialogue comes from subtitles it was never read at all.

Two things in its result matter later. `"has_audio": false` means the video has
no audio stream — not an error, and not necessarily an empty transcript either,
since subtitles may still supply the dialogue. It is a fact about the original,
not a report about a file that was written; nothing is produced for the audio
either way. `subtitles` is every text subtitle track found in the container,
each usable one demuxed to `subs/track<n>.srt`, which is what step 2 of the
ladder ranks against the subtitle files beside the video. Tracks that were left
alone (bitmap subtitles, forced-subtitle tracks) stay in that list with a
`skipped` reason instead of vanishing, so "there were none" stays distinguishable
from "there were, and none could be used".

### transcribe — transcript.json (runs split first if needed)

```
analysis-video transcribe <video> [--out DIR] [--transcript PATH]
    [--sub-lang CODE] [--no-subtitles] [--model SIZE] [--stt-backend NAME]
    [--language CODE] [--force]
```

- `--force` — re-transcribe even though the stage is already done. This is the
  only way to change the model of an existing analysis. Without it a completed
  transcript is returned as is, plus a `note` in the result when the `--model`
  you asked for differs from the one on disk.
- **The subtitle input is the exception to that reuse.** Which file the
  transcript was built from is recorded — by path and byte size — so adding a
  subtitle next to the video, replacing it, editing it, deleting it, or naming a
  different one with `--transcript` makes the next run re-transcribe *without*
  `--force`. Reusing a transcript whose source no longer says the same thing
  would be reusing a stale answer; the `--model` rule above is the opposite case
  (the source is unchanged and only your preference moved). The one change this
  cannot see is an edit that leaves the byte size identical — use `--force`
  after that kind of hand edit.
- **Writing a new transcript un-completes `frames`.** Both routes to it count:
  `--force`, and the automatic re-transcription just described. `context.md` and
  `metadata.json` hold the previous dialogue already distributed over the
  screens, and nothing in them records which transcript that was — so the
  completion mark for `frames` is dropped (the files themselves are left where
  they are). Re-transcribing is therefore never the last step: run `frames`, or
  `analyze`, after it. Until you do, `frame --at` refuses with `stage-order`
  (exit 3) and its `hint` is the command to run. A transcript that was reused or
  skipped changes nothing here — the stage has to actually rewrite
  `transcript.json`.
- `--model` and `--stt-backend` only take effect when whisper actually runs.
  With a subtitle source `outputs.model_size` is `null`, and asking for another
  `--model` gets you a `note` explaining that, not a new transcript.
- `--sub-lang` follows the same reuse rule, and what the stage watches is the
  **top-ranked sidecar file** — so a new language re-transcribes on its own only
  when it promotes a *different file beside the video* to first place. When the
  language you now want lives in a container track, or the directory holds only
  one sidecar, the input is unchanged and the finished transcript comes back as
  is, with a `note` saying which language you got instead; `--force` is what
  re-runs the choice. Without the flag nothing is compared — a transcript is
  never re-examined because the machine's locale moved.

### frames — detection + capture + context.md (needs transcribe)

```
analysis-video frames <video> [--out DIR] [--range A-B ...]
    [--anchor-threshold F] [--rate-threshold F] [--cut-area-threshold F]
    [--read-long-edge PIXELS]
```

Each run directory is emptied and rebuilt, so re-running with different
thresholds is deterministic — no verdict from the previous run leaks into the
new one. The one thing that survives is `requested/`: frames you obtained with
`frame --at` are kept, and their `interval`/`dialogue` are recomputed against
the new frame set before being merged back into `metadata.json`. Tuning a
threshold therefore never costs you the frames you asked for by hand.

This is also the stage a new transcript sends back to not-done: after
`transcribe --force`, or after a re-transcription triggered by a changed
subtitle, run this again. The dialogue in `context.md` comes from
`transcript.json`, so leaving the previous build in place would be serving a
transcript that no longer exists.

Rebuilding a unit also invalidates any review written against it: the review
records the sha256 of the `context.md` it read, so the next `status` reports
that unit as `stale` and `next` sends you back to read it again. That is the
intended behaviour, not a nuisance — an analysis of screens that no longer
exist is not an analysis of this run. The review file itself is never touched:
it lives outside the run directory precisely so re-running cannot delete it.

### frame — one extra frame at a chosen moment (needs frames)

```
analysis-video frame <video> [--out DIR] --at SECONDS --reason TEXT [--run NAME]
```

- `--at` (**required**, seconds, float) — must lie inside the video
  (`time-out-of-range`) and inside the window of the run you target
  (`time-out-of-window`); both are exit 2. What gets written is not that exact
  timestamp but a *settled* one: normally `at + 0.3 s`, and `at + 1.3 s` when
  the picture is still moving there, clamped to just before the end of the
  video. So the returned `time` usually differs from `at` — both are recorded,
  and `said_at` tells you what was being said at `at` itself.
- `--reason` (**required**, free text) — provenance, stored in
  `requested/requests.json`. Together with `--at` it is also the idempotency
  key: repeating the same pair returns the earlier result with
  `"skipped": true` instead of extracting again, so re-invoking after a timeout
  is safe.
- `--run` — which analysis unit to write into. Optional when only one run
  exists, required when there are several (`run-ambiguous`, exit 2).
- A dark or blank result is not an error. The result always carries `yavg`,
  plus a `warning` when it is below 5.

### review — where your analysis is written down (needs frames)

```
analysis-video review <video> [--out DIR] [--run NAME] [--write -]
    [--force] [--export-dir DIR]
```

This is the last step of the pipeline and the only one whose content comes from
you. The tool owns the place, the provenance and the verdict; the prose is
yours, written after reading `runs/<run>/context.md`. Nothing consumes it — no
later stage reads it back, so it can never compete with the detector the way a
machine-readable AI input would.

```
analysis-video review lecture.mp4 --run full --write - <<'EOF'
# 요약
...
EOF
```

- **`--write -` reads the body from standard input**, as UTF-8, and `-` is the
  only accepted value: the tool never opens a path you name here. Without a
  pipe on a terminal you get `stdin-is-tty` (exit 2) rather than a command that
  hangs until your harness kills it. An empty body is `empty-review`, one that
  is not UTF-8 is `review-not-text`, and one above @REVIEW_MAX@ is
  `review-too-large` — all exit 2.
- **Without `--write` it only reports.** `state` is `missing` (no file),
  `unreadable` (the header is gone or broken), `stale` (the `context.md` it was
  written from has changed since), or `current`.
- The canonical file is `<out>/reviews/<run>.md` — **outside** the run
  directory. `frames` empties and rebuilds `runs/<name>/`, so a review kept in
  there would be destroyed by every threshold you tried.
- The tool prepends a header: a machine-readable JSON line inside an HTML
  comment, plus a small markdown table. Do not write those markers yourself —
  a body containing them is `review-contains-marker` (exit 2). Below the header
  the file is exactly what you piped in.
- The fingerprint is one thing: the **sha256 of `runs/<run>/context.md`**. That
  file is what you read, and every threshold change, re-transcription and
  re-capture shows up in it. Nothing about the review is recorded in
  `state.json`, so a `frames` run cannot wipe the record by rewriting a stage
  entry, and the file is always its own truth.
- The result's `action` is `created`, `unchanged` (same body, same fingerprint —
  nothing was written), `refreshed` (same body, new fingerprint: you re-read a
  changed `context.md` and stand by what you wrote, so the stale mark clears),
  or `updated`.
- `--force` — overwrite a review that is still `current` with a different body.
  Without it that case is `review-exists` (exit 2), because replacing an
  analysis nothing invalidated is more likely a mistake than an intention. A
  `stale` review needs no flag: it is superseded, not overwritten.
- `--run` — which analysis unit. Same rule as in `frame`: optional when only
  one exists, required when there are several (`run-ambiguous`, exit 2).
- `--export-dir DIR` — after the canonical file is written, drop a copy in that
  directory as `<video filename>.<run>.review.md` (the name carries both, so
  several runs and several videos can share one folder). The canonical location
  does not move, and the copy is recorded nowhere: delete or move it freely.
  A path that exists and is not a directory is `export-not-a-directory`.
- A unit with no `context.md` yet is `context-missing` (exit 3), and the `hint`
  is the `frames` command to run first.

### clean — remove what can be rebuilt

```
analysis-video clean <video> [--out DIR] [--level cache|images]
```

An analysis directory is larger than the video it came from, and until you ask
there is no way to know which parts of it are cheap to lose.

- **Without `--level` nothing is deleted.** You get the directory's total size
  and, for each level, what it would remove, how many bytes that frees, and
  what it costs you. Report that and let the user choose.
- **Levels are cumulative**, in order of what they cost:
  - `cache` — `video.mkv`. Costs nothing at all: when a later stage needs it
    and it is gone, the original video is read instead, with a warning, and the
    frames come out byte-identical (measured). Resuming still works.
  - `images` — the above, plus `runs/*/frames/`. You lose the GUI and
    pixel-level inspection. `context.md` still reads correctly, because it
    points at `read/`, which is kept.
- **Never removed, at any level**: `reviews/` (your analysis — the one thing in
  the directory that cannot be rebuilt from the video), `transcript.json`,
  `runs/*/read/`, `runs/*/requested/` (frames you asked for by hand, with the
  reasons you gave), `metadata.json` / `context.md` / `frames.json`, and the
  detection caches `detect_signals.npz` / `detect_adaptive.json` (40 KB that
  would cost a full decode to rebuild).
- Idempotent: running it twice frees 0 bytes the second time. Measured on one
  analysis: 9.8 MB down to 1.4 MB.
- The directory is read through the same schema gate as everything else, so a
  directory this version does not recognise is refused rather than emptied.

### status — how far the pipeline got, and what is left

```
analysis-video status <video> [--out DIR]
```

Takes no other flags, and runs nothing. Reports the source file it is bound to,
the per-stage completion state read from `state.json`, and `runs[]` — one entry
per analysis unit with the absolute path of its `context.md` and the state of
its `review` (`missing` | `unreadable` | `stale` | `current`). `next` closes it
with the single thing to do now. This is the cheapest way to re-enter a job you
did not start yourself: one call tells you whether to build, to read, or to
answer.

### doctor — environment report

```
analysis-video doctor
```

Takes **no arguments at all** (not even `--out`). It reports what this
installation can do; it does not judge whether that is enough for a video it has
not been shown.

- `modules.required` — the libraries the tool cannot run without. A `false`
  anywhere here is the one thing `doctor` calls broken: `ok: false`, exit 4,
  with `error.kind` `core-deps-missing`.
- `modules.optional` — what the extras put there, as raw facts.
- `capabilities` — the judgement built from those facts. Each entry has
  `available`, `needed_for` (what you lose without it) and `install` (the exact
  command). `speech-recognition` also carries `installed_backends`,
  `resolved_backend` (what `auto` would pick, `null` when there is none) and
  `cuda_available`; `debug-report` is matplotlib.

**A missing backend is `available: false`, not an error, and `doctor` still
exits 0.** It takes no `<video>`, so it cannot know whether you need speech
recognition at all — and a video that comes with subtitles is analysed end to
end with no backend installed. Read `capabilities`, then run the pipeline: the
exit 4 for a missing backend is raised by `transcribe`, at the moment the
ladder has actually run out of subtitles.

When a backend is present, `speech-recognition` also carries the weights
situation for the default `--model`, worked out without touching the network:
`repo` (where they come from), `cached` (`true`, `false`, or `null` when it
cannot be determined), and `cache_dir`. `cached: false` means a first
`transcribe` that reaches whisper will download before it transcribes — call
`doctor` on its own, with a generous timeout, if you would rather not have that
happen inside the run you are timing.

### agent-guide — this document

```
analysis-video agent-guide
```

Takes no arguments. Prints markdown to stdout: the one command that does not
print a JSON result.

### install-skill — make agents find this tool, once, for every project

```
analysis-video install-skill [--dir DIR] [--agents-file PATH]
```

Writes a short pointer document that tells an agent this tool exists and to run
`agent-guide` for the real instructions. It does not copy the instructions —
that is the point, so the two can never disagree.

- default target is the Claude Code personal skill directory
  (`~/.claude/skills/analysis-video/SKILL.md`, or under `CLAUDE_CONFIG_DIR` when
  that is set), which every project of that user then sees.
- `--dir` — put the skill directory somewhere else instead.
- `--agents-file PATH` — for harnesses without a skill mechanism, write into a
  rules file (`AGENTS.md`, `CLAUDE.md`, `.clinerules`, ...) instead. Here the
  **whole** guide goes in, wrapped in `<!-- ... BEGIN -->` / `<!-- ... END -->`
  markers, and a later run replaces that block rather than appending — so
  unlike `agent-guide >> AGENTS.md` it is safe to re-run after an upgrade.

This is the only command that writes outside the analysis directory, and it does
so only when called directly. The result reports `path` and an `action` of
`created`, `updated`, `appended`, or `unchanged` — `appended` is what you get the
first time `--agents-file` targets an existing file that has no markers yet.

If the target file's markers are not a single clean `BEGIN … END` pair — one of
them missing, two blocks, or `END` before `BEGIN` — the command **writes nothing**
and exits 2 (`agents-file-markers`), reporting the counts and line numbers in
`details`. Fix the markers, or point `--agents-file` at a different file. This is
a rules file someone wrote by hand, so guessing at the intended span would put
their document at risk; refusing costs a rerun.

### debug-report — detection graph PNG (needs frames, and the `[viz]` extra)

```
analysis-video debug-report <video> [--out DIR] [--run NAME] [--label TEXT]
```

- `--label` — title drawn on the graph. Default: `<video> — <run>`.
- `--run` — same rule as in `frame`: required only when several runs exist.

Requires matplotlib (`pip install 'analysis-video[viz]'`); without it the
command fails with exit 4.

### Global

```
analysis-video --version        # version string, then exit
analysis-video <command> --help # usage text
```

Neither prints a JSON result. A missing or unknown subcommand is a usage
error: error result + exit 2.

## Shared options

### The `<video>` argument
Every command that takes one accepts **either the source video or an
`.analysis` directory you already have**. Once a run exists, `status`,
`review`, `frame` and `clean` are things you do while holding the outputs, so
the directory in your hand is a valid way to name the work — the source path is
already recorded in its `state.json`. A directory with no `state.json` is
`not-analyzed`, and one whose recorded source has moved away is
`source-missing` (both exit 2).

### `--out DIR`
Accepted by every command that takes a `<video>`. Default: `<video>.analysis/`
next to the video file. `doctor` and `agent-guide` take no paths. Pass the same
`--out` on every later invocation, or the resumed stages will not be found. It
cannot be combined with naming an `.analysis` directory directly
(`target-conflict`, exit 2) — both say where the output lives, so a
disagreement would silently discard one of them.

### `--transcript PATH` — analyze, transcribe
Take the transcript from this subtitle file: `.srt`, `.vtt`/`.webvtt`,
`.smi`/`.sami`. Naming a file is a demand, not a preference: it is used **even
when the quality checks would have refused it**. Those checks (cue count,
coverage, rollup, span) exist to choose among candidates the tool found by
itself, and naming a file is that choice already made — so a forced-subtitle
track covering 11% of the runtime, or an auto-generated one, is accepted, with
the finding kept in `source.notes` and logged as a warning. What still stops
the run is a file that yields nothing to use: a missing file is
`transcript-not-found`, and an unreadable or cue-less one is
`transcript-rejected` (both exit 2, with the individual reasons in
`error.details.notes`). Neither ever falls through quietly to some other
source. This is also how you pick one specific track out of a container: run
`split`, read its `subtitles` list, and pass the `subs/track<n>.srt` you want.
Cannot be combined with `--no-subtitles` (`conflicting-options`, exit 2).

### `--sub-lang CODE` — analyze, transcribe
Which language the **subtitles** should be in (`ko`, `en`, `ko-KR`, `kor`, ...).
It is the **first** key of step 2's ranking, and that ranking spans sidecar files
and container tracks together — so this flag, not the source, decides which of
them is opened first. Source only breaks a tie between two candidates that are
equal on language. It never rejects: if nothing matches, the best remaining
candidate is still used, because a subtitle in the wrong language beats no
subtitle at all — and the mismatch is reported (see "Which language you got").
`--transcript` overrides it entirely; a file you named is used whatever its
language.

**Default: the system locale** (`LC_ALL` > `LC_MESSAGES` > `LANG` > `LANGUAGE`;
`ko_KR.UTF-8` becomes `ko`). `C`, `POSIX`, or nothing set means no language
preference at all, and then the ranking starts at "declares no language",
followed by the source, `forced`, `default`, format and name rules. Whatever was
resolved is recorded as `source.target_language`, so you can always see what the
run was aiming at.

Three-letter codes are matched against two-letter ones (`ko` = `kor`, `de` =
`deu`), and region subtags are ignored (`ko` = `ko-KR`). The old ISO 639-2/B
spellings (`ger`, `fre`, `chi`) are **not** mapped; if a file or track is
labelled that way, name it with `--transcript` instead.

### `--no-subtitles` — analyze, transcribe
Ignore subtitles entirely and transcribe the audio. This is for what the
automatic checks cannot see: a subtitle that is structurally sound but wrong for
your purpose — a translation where you need the original wording, a caption
track that paraphrases, a file you already know is out of sync. It is not the
flag for auto-generated captions; those are refused on their own. The run then
needs an STT backend (the `@STT_EXTRA@` extra) and the model weights, and
on an installation without one this flag is what turns a video that would
have analysed fine into `stt-backend-missing`, exit 4.

### `--model SIZE` — analyze, transcribe
One of: @MODELS@. Default @MODEL_DEFAULT@. Only ever used when whisper runs; a
transcript that came from subtitles has no model size at all. Larger models cost
noticeably more time; on Korean lecture audio what they mostly buy you is better
sentence segmentation. Note the reuse rule under `--force` above.

### `--stt-backend NAME` — analyze, transcribe
One of: @BACKENDS@. Resolution order is flag → `ANALYSIS_VIDEO_STT` environment
variable → `auto`. `auto` picks mlx on Apple Silicon, otherwise faster-whisper,
otherwise whichever of the two is installed. Both backends come from the
`@STT_EXTRA@` extra and neither is present in a plain install; naming one
that is not installed is `stt-backend-missing` (exit 4) — there is no silent
fallback, and no fallback to the other backend either. `analysis-video doctor`
lists what is installed and what `auto` would pick. None of this is consulted
when subtitles supply the transcript: that path never loads a backend, so the
flag can be set on a machine that has none and nothing will notice.

### `--language CODE` — analyze, transcribe
The language of the **speech**, for whisper only (`ko`, `en`, ...). Default:
auto-detect. Giving it removes the detection step and the mistakes that step
makes on short or quiet audio; the language that ended up being used — yours or
the detected one — is recorded as `source.language`.

It has **no effect on which subtitle is chosen**; that is `--sub-lang`, and the
two are deliberately separate because they can disagree (an English lecture you
want to read with the Korean subtitles that ship beside it). Passing
`--language` alone will not make a Korean sidecar win, and passing `--sub-lang`
alone will not tell whisper what to listen for. On a video with usable subtitles
`--language` is never consulted at all: no audio is transcribed.

### `--range A-B` — analyze, frames
`START-END` in seconds; decimals allowed (`--range 120.5-300`). Exactly one `-`
is permitted, so negative numbers are not accepted, and `START` must be smaller
than `END` (otherwise `bad-range`, exit 2). `END` may overshoot the video by up
to 0.5 s and is clipped to its duration; further than that is
`range-out-of-range`, exit 2. Repeat the flag for more units. Identical ranges
are deduplicated and units are sorted by start time, but overlapping ranges are
**never** merged — see "Analysing only part of a video".

### `--anchor-threshold` / `--rate-threshold` / `--cut-area-threshold` — analyze, frames
The baselines of the three signals the detector watches. Lower value = more
events = more frames.

| flag | default | signal |
|---|---|---|
| `--anchor-threshold` | @ANCHOR@ | distance from the current anchor frame; catches slow accumulation, e.g. handwriting filling a board |
| `--rate-threshold` | @RATE@ | instantaneous change against the previous frame; doubles as the "screen has settled" test, and a spike above 8× it is an event by itself |
| `--cut-area-threshold` | @CUT@ | share of pixels that changed hard; an area, not an average, so a small but total change is not diluted away |

Thresholds are a judgement, not a measurement, so they are **not** part of the
detection cache: re-running `frames` with different values reuses
`detect_signals.npz` and skips the full decode. That makes tuning cheap.
`debug-report` draws these three signals against your thresholds.

**Only one of the three is a usable dial for "give me fewer images", and the
other two behave in ways you would not guess.** Measured over 6 videos × 13
threshold grids = 78 runs. "Recall" below is the share of the frames the default
settings produced that still have a match (SSIM ≥ 0.9) among the frames the
raised threshold produced — i.e. how much of the original evidence survives.

- **`--cut-area-threshold` @CUT@ → @CUT_RECOMMENDED@ : 17–43% fewer images at
  95.2–100% recall.** This is the one to reach for when a unit is too expensive
  to read in full. The default is unchanged, and a run without the flag behaves
  exactly as before; @CUT_RECOMMENDED@ is a recommendation you pass explicitly.
- **`--anchor-threshold` @ANCHOR@ → `0.08` : 1–15% fewer images, recall down to
  83%.** A bad trade — you give up real screens for almost no saving.
- **Raising `--rate-threshold` gives you MORE images, not fewer** (−8% to +2%).
  It is not only an event test: it doubles as the "the picture has settled"
  test, so a higher value declares the screen settled sooner and photographs an
  earlier, less finished moment. You do not save anything and the images get
  worse — this is the one to leave alone.
- Presets combining all three are Pareto-dominated by the cut-area change on its
  own: the same reduction with worse recall.

**No dialogue is lost by raising a threshold.** Going from 74 screens to 34 on
the same video still places all 62 sentences exactly once each: sentences are
assigned to screens by maximum overlap, which is a complete partition of the
transcript whatever the number of screens. What you lose is images, and on
inspection the ones that went were intermediate states of an animation.

### `--read-long-edge PIXELS` — analyze, frames
The long edge of the reading copies in `runs/<name>/read/` — the images
`context.md` points at. Default @READ_LONG_EDGE@, and that default is what the
cost paragraph in `context.md` and `next.cost` are computed from.

This is the other half of the cost story, and it is a different lever from the
thresholds: they decide **how many** screens you get, this decides **how much
each one costs to look at**. At the default a frame is 442 tokens against 1,843
for the same frame at 1920×1080 — 4.17×, which is the difference between a
one-hour lecture that fits in a 1M-token context and six of them that do not
(measured: 0.26–0.95M instead of 1.08–3.95M). Raise it when the material is
genuinely fine-grained and you can afford it; lower it when you cannot.

Frames are never enlarged, so a value above the video's own resolution changes
nothing. The originals stay in `frames/` at full resolution whatever you pass,
so a small value costs you nothing you cannot get back by opening the other
directory. Changing it means re-running `frames`: the copies are written during
capture, in the same decode as the originals.

## Output contract

- stdout: exactly ONE JSON result per invocation (small; safe to parse).
  `{"ok": true, ...}` or `{"ok": false, "error": {"kind", "message", "hint"}}`.
  This includes usage errors (bad flags → error result + exit 2).
  Exceptions: `agent-guide` prints this markdown; `--help`/`--version` print
  plain text.
- stderr: human-readable progress logs. Ignore for parsing.
- Exit codes: 0 ok · 1 internal · 2 bad input · 3 stage-order violation ·
  4 the environment is missing something **the run actually needed**. Exit 4 is
  never a bug in your input — read `error.hint`, which names the command that
  fixes it. The four ways to get it:
  `stt-backend-missing` (speech recognition was needed — no usable subtitle
  anywhere, or you named a backend yourself — and none is installed),
  `stt-model-unavailable` (the weights could not be fetched),
  `viz-missing` (`debug-report` without matplotlib), and
  `core-deps-missing` (`doctor` found a required library gone — a broken
  installation). Optional things being absent is not itself exit 4: nothing
  fails until something asks for them.
- **An analysis directory written by an older version is refused, not
  upgraded.** `state.json` and `metadata.json` carry the format version they
  were written with, it is checked on every read, and a mismatch is
  `schema-mismatch` (exit 2) with `path` / `expected` / `found` in
  `error.details`. There is no migration and re-running is pointless: do what
  `error.hint` says — give the analysis a fresh `--out`, or delete that
  directory and analyse the video again from the start. The video itself is
  never touched, and neither is anything else in the directory, so you can still
  read the old `context.md` before removing it. This is an input error on
  purpose: an unrecognised directory that got past the check would fail later,
  deeper, and as exit 1 — which reads as a bug in the tool rather than as
  something you can act on.
- **Directory paths you get back are absolute**, whatever you passed in. You may
  call from any working directory, and you may pass `<video>` relative — nothing
  in the output or in `state.json` depends on where you ran it, so a later stage
  invoked from somewhere else still resumes.
  The one exception is `image`: `frame --at` reports it relative to the analysis
  unit (`requested/req_0042.10.jpg`), the same form `metadata.json` and
  `context.md` use. Join it onto the unit directory to open it.
- **`next` is an object, and it is the same object from every command that takes
  a `<video>`.** Branch on `do`, which is one of three values:
  - `"run"` — `command` is a runnable command line with the video path and
    `--out` already in it. Execute it as given.
  - `"read"` — `read` is a list of absolute paths to open (the `context.md` of
    the first unit without a current review) and `command` is the
    `review … --run <name> --write -` invocation to make once you have read
    them and written your analysis. `remaining` lists every unit still waiting,
    including this one. `cost` says what opening all of this unit's images
    costs before you open any of them: `images`, `image_tokens`, `rule`.
  - `"done"` — nothing is left; answer the user.

  `why` is a one-sentence reason in every case. There is deliberately no `do`
  value meaning "you are reading now": reading and submitting are one step, and
  the tool cannot observe the moment between them.

  ```json
  {"do": "read", "read": ["/abs/runs/full/context.md"],
   "command": "analysis-video review /abs/lecture.mp4 --run full --write -",
   "why": "...", "remaining": ["full"],
   "cost": {"images": 78, "image_tokens": 34476, "rule": "..."}}
  ```

  Two results still answer with a plain sentence instead of this object, and
  both are outside the chain: `install-skill` (there is no video to reason
  about) and `clean` without `--level` (a report, not a step).
- Images are referenced as file PATHS in context.md — open the ones you need.
  Those paths are relative to the unit directory (`read/scene_020_....jpg`), so
  join them onto the directory the `context.md` you are reading came from.

## Timeouts / resume

Every stage is resumable: if your harness kills a run, re-invoke the SAME
command — completed stages are skipped via state.json. Detection is cached per
video (detect_signals.npz, detect_adaptive.json) and shared by every run, so
adding a `--range` later does not re-scan the video.
NOTE: on long videos (30+ min) a cold pass can take several minutes — prefer a
harness timeout of 10 minutes, or re-invoke until it completes.

Two things do not resume, and both are deliberate:

- **A directory written by an older version of this tool.** It is refused on
  read with `schema-mismatch` (exit 2), never migrated — see "Output contract".
  Re-invoking cannot get past it; a fresh `--out`, or deleting the directory,
  can. Read `error.hint` rather than retrying.
- **`frames`, once the transcript has been rewritten.** Re-running is then the
  correct move, not a wasted one — see `transcribe`.

## Output directory layout

```
<video>.analysis/
├── state.json            # stage progress (resume) + the format version this
│                         #   directory was written with (checked on every read)
├── video.mkv             # the video stream, copied without re-encoding.
│                         #   There is NO audio.wav: whisper reads the original
│                         #   video when it has to, and usually it does not
├── subs/                 # track<n>.srt — text subtitle tracks demuxed from
│                         #   the container (absent when it had none)
├── transcript.json       # text + segments + `source` (which subtitle file,
│                         #   which track, or which model produced them).
│                         #   `words` holds word timestamps only when whisper
│                         #   ran; it is empty for every subtitle source
├── detect_signals.npz    # detection time-series cache, shared by all runs
├── detect_adaptive.json  # adaptive detector cache, shared by all runs
├── context.md            # ★ INDEX: which runs exist, and what each covers
├── reviews/              # <run>.md — ★ YOUR analysis, one file per run.
│                         #   Written by `review`, outside runs/ so that
│                         #   re-running `frames` cannot delete it. The only
│                         #   thing here that cannot be rebuilt from the video
└── runs/
    ├── index.json        # same list, machine-readable
    └── <name>/           # "full", or e.g. "00120_0-00300_0"
        ├── context.md    # ★ READ THIS — screens, images, dialogue
        ├── read/         # ★ the images context.md points at: reduced copies
        │                 #   (long edge --read-long-edge), same filenames
        ├── frames/       # the same frames at full resolution — open these
        │                 #   only for detail (rejected/ keeps gated-out ones)
        ├── requested/    # frames from `frame --at`, full resolution, no
        │                 #   reduced copy (+ requests.json ledger)
        ├── frames.json   # every candidate with accept/reject verdict
        └── metadata.json # FULL RECORD, for auditing the detector — not for
                          #   reading end to end. window + screens[] +
                          #   frames[{time, image, sources, screen, interval,
                          #   dialogue}] + rejected[] (why each was dropped)
                          #   + requested[] + transcript + images (how many
                          #   reading copies, and what they cost) + params
```
"""

_VALUES = {
    "@MODELS@": " | ".join(f"`{m}`" for m in MODEL_SIZES),
    "@MODEL_DEFAULT@": f"`{DEFAULT_MODEL}`",
    "@BACKENDS@": " | ".join(f"`{b}`" for b in ("auto", *BACKENDS)),
    # extra 이름은 stt 모듈이 단일 출처다 — 설치 안내가 CLI 힌트(오류의 hint)와
    # 이 문서에 각각 적히는데, 두 곳이 갈리면 안내를 따른 에이전트가 또 실패한다.
    "@STT_EXTRA@": STT_EXTRA,
    "@ANCHOR@": f"`{DEFAULT_ANCHOR_THRESHOLD}`",
    "@RATE@": f"`{DEFAULT_RATE_THRESHOLD}`",
    "@CUT@": f"`{DEFAULT_CUT_AREA_THRESHOLD}`",
    # 권장값은 **기본값이 아니다** — 플래그로 명시했을 때만 쓰인다. 그래도 같은
    # 규칙으로 주입하는 이유는 같다: 실측이 다시 돌아 권장선이 움직이면 상수만
    # 고치면 되고, 문서가 옛 숫자를 계속 권하는 일이 생기지 않는다.
    "@CUT_RECOMMENDED@": f"`{RECOMMENDED_CUT_AREA_THRESHOLD}`",
    "@READ_LONG_EDGE@": f"`{READ_LONG_EDGE}`",
    "@REVIEW_MAX@": (f"{REVIEW_MAX_BYTES // 1024}KB" if REVIEW_MAX_BYTES < 1 << 20
                     else f"{REVIEW_MAX_BYTES / (1 << 20):g}MB"),
    # 자막 거부 임계도 상수에서 주입한다 — 이 셋은 플래그가 아니라 에이전트가
    # 통제할 수 없는 판정선이라, 문서와 코드가 갈리면 "왜 내 자막이 거부됐나"에
    # 대한 답이 틀린 채로 남는다. 위 기본값들과 같은 이유다.
    "@MIN_CUES@": f"{MIN_CUES}",
    "@MIN_COVERAGE@": f"{MIN_COVERAGE:.0%}",
    "@MAX_ROLLUP@": f"{MAX_ROLLUP:.0%}",
}


def render() -> str:
    text = _TEMPLATE
    for token, value in _VALUES.items():
        text = text.replace(token, value)
    return text


GUIDE = render()
