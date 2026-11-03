# C++ for reverse decoding: what it would gain and how it would wire to Python

Date: 2026-11-03. Asked by the operator after the half-second caption reading landed. No product code came from this research.

## Status

Parked by the operator on 2026-11-03: C++ waits until a case fits it. Nothing was built.

## Direction

The operator's direction is C++ for backward video processing (reverse decoding), with the wiring to Python researched first. This note answers that, and it measures where the time goes.

## Measurements

All in the stage1 worker: 28 CPUs, Python 3.12, PyAV 19.0.2. The video is the rev 18 source: 72 s, 1080x1920, H.264, 2158 frames, 31 keyframes, largest gap between keyframes 4.8 s.

| Work | Time | Note |
|---|---|---|
| Half-second caption read, whole video, 149 frames | 121 s | As production would run it |
| OCR, one frame | 0.62 s | About 88 s of the 143 half-second frames. ONNX Runtime, already native code |
| One ffmpeg process per frame, the current way | 0.16 s per frame | About 23 s for 143 frames |
| One ffmpeg pass, forward, 2 fps, as JPEG | 1.25 s | All 144 frames |
| Forward decode, every frame, PyAV | 1.05 s | 2058 fps. The floor for any language using libavcodec on this file |
| Reverse by keyframe span, every frame, PyAV | 1.57 s | 1373 fps, frames not converted |
| Same, as a whole-frame grey array | 2.56 s | 844 fps, 298 MB held for the largest span |
| Same, as a grey caption band | 2.45 s | 882 fps, 44 MB held |
| Seek to every frame backward, OpenCV, 5 s of video | 4.98 s | About 14 times slower per frame than reversing a span |
| ffmpeg `reverse` filter, 5 s of video | 0.38 s | Buffers the whole clip in memory; FFmpeg's own patch notes say to trim first |
| OCR on a cropped caption band | 1.20 s per frame | Slower than the whole frame as called here. Cause not investigated |

Another thread's worst gap during a PyAV decode was 2.4 ms, so PyAV's decoding does not starve the loop on this file.

Recent renders took 38-39 s for 34.5 s of video. They run in the Remotion renderer and were not profiled.

## What this means

- Reversing the whole video takes about 2 s in Python today. C++ uses the same libavcodec, so it cannot beat about 1 s on this file. The saving is at most about 1 to 1.5 s, which is about 1% of the caption read. This is an inference from the floor, not a measured C++ run.
- The caption read is slow because of OCR, which is already native. C++ around it does not change that.
- The cheap gain needs no C++: one decode pass instead of one ffmpeg per frame saves about 22 s of the 121 s. `FfmpegFrameSource.frames` already reads that way.
- OCR calls can drop by reading a frame only when its caption band changed. `FfmpegRegionTracker` already compares a region's edges without OCR. This has not been measured for captions.
- Nothing in Thoth reverses video today: `python/src` has no reverse decode and no reverse clip.
- Reverse decoding is mainly a memory problem. Decoding has to run forward from a keyframe, so a whole span sits in memory ([libav-user](https://ffmpeg.org/pipermail/libav-user/2016-October/009772.html), [US6879770B1](https://patents.google.com/patent/US6879770)). At 1080p grey that was 298 MB here. A long keyframe gap costs more. Native code could hold less by keeping only the crop, but the band above already does that from Python.
- Long or high-resolution sources may change this picture. These numbers come from one 72 s video on 28 CPUs. A smaller host decodes slower, though the ratio to OCR should hold, since both slow down.

## Wiring options

| Option | How it joins Python | Frames cross as | A crash takes down | Fits Thoth because |
|---|---|---|---|---|
| A. C++ command-line tool | `asyncio` subprocess, like ffmpeg today, behind the `RegionTracker` port | JSON answers, no frames | That one call | Same shape as `FfmpegRegionTracker`: `_run`, `ToolMissing`, one missing-tool code |
| B. nanobind module in a spawned process | `ProcessPoolExecutor`, like `SherpaDiarizer` | numpy arrays, copied between processes or through shared memory | The child; the pool breaks | The worker loop stays free, as Temporal's 2 s activation deadline needs |
| C. nanobind module in the worker | Direct call with `call_guard<gil_scoped_release>` | numpy arrays, zero copy with a capsule owner | The whole worker | Fastest call, highest risk |
| D. PyAV, no C++ | Already in the image | numpy arrays | The call, unless native code crashes | Nothing to build; the baseline above |

Notes on the options:

- nanobind binds C++ with a stable-ABI wheel from Python 3.12, built through scikit-build-core ([packaging](https://nanobind.readthedocs.io/en/latest/packaging.html), [GIL guard](https://nanobind.readthedocs.io/en/latest/functions.html), [ndarray owner](https://nanobind.readthedocs.io/en/latest/ndarray.html)). Its own benchmarks claim smaller and faster bindings than pybind11 ([benchmark](https://nanobind.readthedocs.io/en/latest/benchmark.html)). Those are the project's numbers on trivial functions.
- Option C can load two FFmpeg builds in one process: the module's and the one inside the PyAV and OpenCV wheels. PyAV here reports libavcodec 63, while the image's apt ffmpeg is 5.1. Whether that conflicts has not been tested.
- A native call that keeps the GIL has stalled this worker before, for 45.8 s (PR #92). `gil_scoped_release` is required in option C, and building Python objects needs the GIL back.
- The image has no compiler. Options A to C need a builder stage with `g++`, `cmake` and the `libav*-dev` packages from the same Debian release as the runtime ffmpeg, so that the runtime libraries already in the image match. The licence of the linked FFmpeg build needs checking before this image is distributed outside the operator's own infrastructure.
- The Rust engine was retired on 2026-10-31 to keep one language in the control plane. C++ brings back a native build, a CI stage and memory-safety risk on untrusted media, so it needs an ADR and an update to the stack line in `AGENTS.md`.

## Recommendation

If C++ goes ahead, use option A: a small command-line tool that decodes one keyframe span at a time, walks it backward on a cropped grey band, and prints the boundary it found. Python keeps the logic and calls it through the existing `RegionTracker` port. No frames cross the boundary, a crash on a bad file costs one call, and the loop stays free. Move to option B only if a later feature needs frames in Python.

Before building it, name the feature that needs it and measure against the PyAV baseline with a long source. Without such a feature, the expected gain is about 1%.

For the caption read itself, the two larger gains are one decode pass (measured) and reading only when the band changed (not measured).

For fast editing, three separate paths need their own measurements: preview runs in the browser, render runs in the Remotion renderer, and analysis runs in the worker. C++ in the worker reaches only the last.

## Open questions for the operator

1. Which feature needs reverse decoding: exact caption boundaries, a reverse effect on clips, or something else?
2. Which part of editing feels slow: preview, render, or the wait for a draft?
