# analysis-video-gui

**Desktop GUI for reviewing [`analysis-video`](https://pypi.org/project/analysis-video/)
output and tuning its scene-change detection.** A hub plus several independent OS windows
(no docking).

[![PyPI](https://img.shields.io/pypi/v/analysis-video-gui)](https://pypi.org/project/analysis-video-gui/)
[![Python](https://img.shields.io/pypi/pyversions/analysis-video-gui)](https://pypi.org/project/analysis-video-gui/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/hwanyong/analysis-video/blob/main/LICENSE)

The CLI is the product; this is the verification tool. It exists to answer "did the
detector pick the right frames, and is the dialogue aligned?" by eye. The two are
**separate packages with independent versions** — fixing the GUI never forces a core
re-release, and CLI-only users never download Qt. The core is pulled in automatically as
a dependency.

## Install

```bash
uvx analysis-video-gui@latest <video or .analysis path>   # run without installing
uv tool install analysis-video-gui                        # install as a global command
```

Keep the `@latest`: without it `uvx` reuses whatever version it resolved the first time,
and you would keep running the old one after a release.

First run downloads about 111MB of Qt **on top of the core's own download** (108MB on
macOS, 165MB on Linux — the core is a required dependency). Afterwards it starts from
cache. The GUI does not pull the core's `[stt]` extra: it reads an analysis directory
that already exists and never runs the pipeline itself.

**Linux needs one system package** — `libportaudio2`, for audio playback.

```bash
sudo apt install libportaudio2
```

`sounddevice` bundles PortAudio (the audio I/O C library) only in its macOS and Windows
wheels; the Linux wheel is pure Python and relies on the system copy. Without it the
install still succeeds and playback fails **later**, so install it up front.

## Windows

| Window | Purpose |
|---|---|
Hub | Session root: UI language, analysis-unit picker, window toggles, layout save/restore, status |
Player | Video playback and scrubbing |
Timeline | Three detection signals with thresholds, colored by cause, mark navigation |
Gallery | Accepted and rejected frames at a glance |
Compare | Precision/recall report — your ground-truth flags vs the detector's picks, exportable as `compare.json` |
Dialogue sync / Frame sync | Review dialogue and frame alignment |

Playback decodes with PyAV rather than QtMultimedia — Qt's bundled FFmpeg was shown by a
spike to decode zero frames for AV1, so playback uses the same path as the analysis
pipeline.

## Supported environments

Python 3.11–3.14. Install resolution verified directly on each of these.

| Platform | Status |
|---|---|
macOS (Apple Silicon · Intel) | ✅ |
Linux x86_64 | ✅ glibc 2.28+ |
Linux aarch64 | ⚠️ **glibc 2.31+** — below that no Qt wheel exists, install fails |
Windows x64 | ✅ |
Windows ARM64 | ❌ same cause as the core (no `opencv-python-headless` wheel) |

**On older Linux, Qt silently resolves to an older release** rather than failing —
x86_64 with glibc 2.28 lands on PySide6 6.9.3, aarch64 with glibc 2.31 on 6.8.0.2.
Current Qt (6.11) needs glibc 2.34 (x86_64) or 2.39 (aarch64). It is a quiet downgrade
rather than an error, which makes it hard to diagnose later — hence this note. On macOS,
current Qt requires macOS 13 or newer.

## Links

- **Source & issues**: https://github.com/hwanyong/analysis-video
- **한국어 문서**: https://github.com/hwanyong/analysis-video/blob/main/README.ko.md
- **Core CLI**: https://pypi.org/project/analysis-video/

## License

MIT.

**PySide6-Essentials is LGPL.** Redistributing this GUI carries the corresponding notice
obligations. Keeping the core CLI as a separate package is partly for this reason — the
core ships without them.

---

<sub>Keywords: video analysis GUI · scene detection tuning · keyframe review ·
transcript alignment · lecture video inspector · PySide6 desktop app ·
Qt video player · analysis-video companion</sub>
