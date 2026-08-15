<!-- analysis-video:review BEGIN (생성됨 — 직접 수정하지 마세요) -->
<!-- {"at": "2026-08-14T21:59:53-07:00", "context": "runs/full/context.md", "context_sha256": "eceeb61ef26f3af784ba86fbb29daa80e81a1fed9cda5dc702164a6f91dc5c9f", "run": "full", "schema": "analysis-video/review@1", "version": "0.1.1"} -->
# demo-pipeline.mp4 — full

| 항목 | 값 |
|---|---|
| 분석 단위 | `full` — `runs/full` |
| 읽은 것 | `runs/full/context.md` · sha256 `eceeb61ef26f3af7…` |
| 원본 | `demo-pipeline.mp4` |
| 작성 | 2026-08-14T21:59:53-07:00 · analysis-video 0.1.1 |
<!-- analysis-video:review END -->
## The question

*What does this clip say `analysis-video` does, and does its own output hold up
if I check it?*

## Answer

It holds up, and the way it fails to hold up for the transcript is the point.

The clip is 41 seconds, five screens, six images. Reading those six images and
the speech attached to them, I can answer the question. Reading the speech
alone, I would have gotten the tool's own description **wrong** — and I can
point at exactly where.

## What the words carry, and what only the pictures carry

Four of the five screens put something on the board that is never spoken
anywhere in the clip:

| Screen | Spoken | On screen only |
|---|---|---|
| 5.13–10.0s | frames are near-duplicates; the transcript never says what was on screen | a third problem: *"no marks at all — nothing records when a screen appeared or left"* |
| 10.13–29.0s | "the tool works in four moves, and I will write them out" | **the four moves.** split (audio out, video out; *nothing is decided here*) · transcribe (subtitles first, speech only if there are none) · frames (**three signals: a cut, a drift, a burst**; their union is the list of events) · shoot twice (the screen when it appeared, and the same screen finished) |
| 29.07–35.0s | "each screen becomes one section of a Markdown file" | the section's actual shape — `## <start>-<end>s`, then an image line per shot, then everything said while it was up; and the note that the full record stays in `metadata.json` beside it |
| 35.13–41.0s | "one command, no network" | the two commands: `uv run python examples/make_demo_video.py` and `uvx analysis-video analyze docs/media/demo-pipeline.mp4` |

The sharpest case is the third detection signal. The narration names a cut and
a drift. **"Burst" is spoken nowhere in this clip** — the word exists only in
`read/scene_003_t0028.93.jpg`. An agent working from the transcript would
report that the detector runs on two signals. It runs on three, and it takes
their union.

That is the claim at 5.13s ("a transcript that never says what was on screen")
demonstrated on the clip's own material, not asserted.

## The two-shot pair

Screen 2 (10.13–29.0s) is the only screen that produced two images, and the
pair is the whole argument:

- `read/scene_002_t0010.13.jpg` — title, right-hand column, and a left panel
  that is an **empty grey rectangle**.
- `read/scene_003_t0028.93.jpg` — same title, **pixel-for-pixel the same
  right-hand column**, and the left panel now holding the four-move list.

Nothing between them is a cut. The board was written into over 18.8 seconds,
each frame nearly identical to the one before it. A detector that only looked
for cuts would have kept the empty rectangle and nothing else — which is to
say, it would have kept the screen and lost its content.

The other four screens are one image each. `metadata.json` labels the shots
`initial`, `screen-start` and `screen-end`, and only screen 2 has a
`screen-end` entry: a screen that never changed after it appeared has no
second state worth a second image. So the second shot is not a fixed sampling
interval — it is conditional on that screen having actually moved.

## Where the boundary landed

Screen 2's finished shot is at **28.93s**; screen 3's appearance shot is at
**29.07s**. 0.14 seconds apart, at 15.17 fps — about two frames. The finished
state was captured against the screen's departure, not against a clock.

## What this cost

| | |
|---|---|
| Source | 41.0s at 15.17 fps ≈ **622 frames** |
| Kept | **6 images** — 0.96% of them |
| To read all six | **2,652 tokens** (768px long edge) |
| Screens | 5 sections, each with its interval and its speech |

## What I still cannot tell you from this

- **The order the four moves were written in.** The pair gives me the endpoints
  of an 18.8-second fill and nothing between. If that order mattered, it would
  take `analysis-video frame docs/media/demo-pipeline.mp4 --at 19` or similar
  to pull an intermediate state.
- **Anything about audio beyond the words.** The transcript here came from the
  sidecar `demo-pipeline.en.srt`, so there is no confidence signal, no speaker
  separation, and no non-speech sound.
- **Whether the clip's description of the tool is *true*.** I checked it for
  internal consistency — the clip describes a two-shot rule and its own output
  exhibits exactly that rule, on the one screen where the rule should fire.
  That is evidence, not proof. The clip is drawn by
  `examples/make_demo_video.py`, so it is a controlled case by construction.

## For the record

This is a synthetic clip, generated by a script in this repository and
therefore free to redistribute. Every number above is from
`runs/full/context.md`, `runs/full/metadata.json`, and the six images in
`runs/full/read/`.
