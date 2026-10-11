# Stage 5a Content Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a workflow runs with intent `identify_original`, Thoth builds a typed, validated
Content Set artifact (main with final renderer OCR, comments, figures) without Scout.

**Architecture:** A new package `thoth_control_plane.assembly` holds a pure port of Scout's
subtitle classifier, a pure comment merge, the figures prompt, the `ContentSet` v1 model, and a
`ContentAssembler` that reaches ffmpeg, ffprobe, RapidOCR, and OpenRouter only through ports. A
new Temporal activity `assemble_content` runs it after attribution and writes
`reports/<workflow_id>/content-set.json` atomically. A workflow input flag gates the stage, so
in-flight workflows replay unchanged.

**Tech Stack:** Python 3.12, Pydantic v2, Temporal (`temporalio`), `rapidocr` 3.9.2 with
`onnxruntime` 1.30.0 (PP-OCRv6 small models), `agno` 3.1.1 over OpenRouter, ffmpeg and ffprobe,
pytest with pytest-asyncio and respx, Bun 1.3 (only to generate the classifier parity fixture
from Scout).

**Spec:** `docs/superpowers/specs/2026-10-11-stage5a-content-assembly-design.md`
(operator-approved 2026-10-11). Read it before Task 1.

## Global Constraints

**Branch and stability**
- Branch `feat/stage5a-content-assembly` from `master`. Do not push, merge, or deploy.
- No live request in the test suite. HTTP is mocked with respx; the conftest offline guard stays.
- Task 10 is a HARD STOP: a live capture the operator authorizes separately.

**Language and commits**
- Chat to the operator: Indonesian. Code, comments, docs, and commit messages: English.
- Each commit is exactly one `git commit -m "<subject>"`, at most 72 characters, no body, no
  trailer, never `Co-Authored-By` or any AI attribution.
- Never stage `graphify-out/`, `build_log.txt`, `.superpowers/`, `.understand-anything/`,
  `.env.stage1.local*`, `dashboard/dist/`, or the untracked `design/` files.
- `docs/superpowers/` is gitignored: stage files there with `git add -f`.

**Files and line endings**
- Before editing an existing file, run `file <path>`. A CRLF file (`CHANGELOG.md`,
  `docs/python-scout-migration-roadmap.md`, `docs/operations/stage1-local-docker.md`,
  `.env.stage1.local.example` and any other the check reports) is edited only with a
  bytes-level script under `D:/thoth-tmp/bu/s5/` that reads and writes bytes and asserts the
  CRLF count is unchanged plus the lines added. Never a text-mode Python write.
- New files are LF; the Edit and Write tools are fine for LF files.
- Temporary files live under `D:/thoth-tmp`.

**Code rules (from the spec)**
- Optional dependencies (`rapidocr`, `PIL`, `agno`, `openai`) are imported inside adapter
  methods, never at module top. `thoth_control_plane.activities.content_assembly` must import
  without the `acquisition` extra, because the workflow module imports it.
- A missing ffmpeg or ffprobe is an explicit error (`ffmpeg_missing`, `ffprobe_missing`), never
  a skip and never a media failure code. Tests that need ffmpeg fail, not skip, when it is
  absent (operator, 2026-10-11).
- Temporal history carries only IDs, enums, counts, reason codes, and elapsed milliseconds.
  Never comment text, paths, prompts, or model output.
- Log messages carry enums and counts only.
- New Pydantic fields on existing models carry defaults so earlier artifacts and histories
  stay readable.
- `THOTH_FIGURES_MODEL` default `deepseek/deepseek-v4-flash-0731`; OpenRouter base URL
  `https://openrouter.ai/api/v1`; key `THOTH_OPENROUTER_API_KEY` (exists).
- `THOTH_SUBTITLE_OCR_MAX_FRAMES` default 12. Frames are 720 px wide, JPEG `-q:v 2`. RapidOCR
  runs with `use_cls=False` for assembly.
- `THOTH_CONTENT_ASSEMBLY_ENABLED` default `false`.

**Commands** (run from `C:/Users/mfr/Documents/MyTools/CLIPPER/python`)
- Tests (WSL, ffmpeg is installed there):
  `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh <paths> -p no:warnings`
- Ruff check and format:
  `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'`
- Format new files before each commit:
  `wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format <paths>'`
- Bun (Windows, Task 2 only), from the repository root: `bun <script.ts>`.

## Review Focus

1. A main video whose ffmpeg extraction fails on one sample must not produce a clean verdict:
   one missing frame is `incomplete_frame_coverage`. Pinned by
   `test_one_lost_frame_fails_coverage` (Task 6).
2. A machine without ffmpeg must say so, not report a broken video. Pinned by
   `test_missing_ffmpeg_is_its_own_code` (Task 6) and `test_frame_at_without_ffmpeg_raises_tool_missing`
   (Task 1).
3. A repost whose original was found must take the original as main, and keep the repost's
   discussion in the comments. Pinned by `test_replaced_main_is_the_original_with_both_discussions`
   (Task 7).
4. A post with no video and no image (text only) must use its real post card, and with no card
   either must fail with `main_media_missing`, never write a Content Set without media. Pinned by
   `test_text_post_uses_its_card` and `test_text_post_without_card_fails` (Task 7).
5. A retry after a crash must replace the Content Set, never append comments twice. Pinned by
   `test_a_second_run_replaces_the_content_set` (Task 8).

---

### Task 1: Settings, event payload, and the media adapters

**Files:**
- Modify: `python/src/thoth_control_plane/config.py`
- Modify: `python/src/thoth_control_plane/domain/models.py` (event payload allowlists)
- Modify: `python/src/thoth_control_plane/attribution/matching.py` (`TextBox`)
- Modify: `python/src/thoth_control_plane/attribution/adapters/ocr.py`
- Modify: `python/src/thoth_control_plane/attribution/adapters/frames.py`
- Modify: `python/tests/attribution/test_local_adapters.py`
- Create: `python/tests/assembly/__init__.py` (empty)
- Create: `python/tests/assembly/test_media_adapters.py`
- Test: `python/tests/test_config.py`, `python/tests/domain/` (whichever file tests `SourceProgressEvent`; find it with `rg -l "SourceProgressEvent" python/tests/domain`)

**Interfaces:**
- Produces:
  - `Settings.THOTH_CONTENT_ASSEMBLY_ENABLED: bool = False`
  - `Settings.THOTH_SUBTITLE_OCR_MAX_FRAMES: int = 12` (1..60)
  - `Settings.THOTH_FIGURES_MODEL: str = "deepseek/deepseek-v4-flash-0731"`
  - `ASSEMBLY_REASONS: frozenset[str]` in `domain/models.py`, merged into `SOURCE_EVENT_REASONS`
  - payload keys `ocr_outcome` (`clean|cover|subtitle|none`), `comment_count`, `figure_count` (int ≥ 0)
  - `TextBox(text, top, bottom, left=0.0, right=1.0)`
  - `RapidOcrReader(angle: bool = True)`
  - `ToolMissing(code)` and `FfmpegFrameSource.frame_at(video: Path, second: float, *, width: int) -> Frame`
  - `FfprobeDuration(ffprobe: str).duration(video: Path) -> float`, raising `ToolMissing("ffprobe_missing")` or `DurationError`

- [ ] **Step 1: Create the branch**

```bash
cd C:/Users/mfr/Documents/MyTools/CLIPPER
git switch -c feat/stage5a-content-assembly master
mkdir -p D:/thoth-tmp/bu/s5
```

- [ ] **Step 2: Write the failing settings and payload tests**

Append to `python/tests/test_config.py`:

```python
def test_content_assembly_settings_default_off() -> None:
    settings = Settings(THOTH_CONTROL_PLANE_API_KEY="test-key")

    assert settings.THOTH_CONTENT_ASSEMBLY_ENABLED is False
    assert settings.THOTH_SUBTITLE_OCR_MAX_FRAMES == 12
    assert settings.THOTH_FIGURES_MODEL == "deepseek/deepseek-v4-flash-0731"
```

Append to the domain test file that already covers `SourceProgressEvent` (if none exists, create
`python/tests/domain/test_assembly_events.py` with this content and the imports shown):

```python
import pytest

from thoth_control_plane.domain.models import SourceProgressEvent


def test_assembly_events_carry_counts_and_a_known_reason() -> None:
    event = SourceProgressEvent(
        kind="stage.completed",
        payload={
            "stage": "assembly",
            "status": "succeeded",
            "elapsed_ms": 9,
            "ocr_outcome": "cover",
            "comment_count": 12,
            "figure_count": 0,
        },
    )
    assert event.payload["ocr_outcome"] == "cover"
    failed = SourceProgressEvent(
        kind="stage.failed",
        payload={"stage": "assembly", "status": "failed", "reason": "incomplete_frame_coverage"},
    )
    assert failed.payload["reason"] == "incomplete_frame_coverage"


@pytest.mark.parametrize(
    "payload",
    [
        {"stage": "assembly", "ocr_outcome": "blurry"},
        {"stage": "assembly", "comment_count": -1},
        {"stage": "assembly", "figure_count": True},
        {"stage": "assembly", "reason": "something_else"},
    ],
)
def test_assembly_event_values_are_checked(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SourceProgressEvent(kind="stage.completed", payload=payload)
```

- [ ] **Step 3: Write the failing adapter tests**

Create `python/tests/assembly/test_media_adapters.py`:

```python
"""ffmpeg frames at a second, ffprobe durations, and RapidOCR box geometry."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import Frame

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _require(binary: str | None, name: str) -> str:
    # Operator, 2026-10-11: a missing ffmpeg is an error, never a skip.
    if binary is None:
        pytest.fail(f"{name} is required for this test and is not installed")
    return binary


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            _require(FFMPEG, "ffmpeg"),
            "-v", "error", "-f", "lavfi",
            "-i", "testsrc=duration=4:size=1080x1920:rate=10",
            "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    return video


@pytest.mark.asyncio
async def test_frame_at_returns_one_jpeg_at_the_requested_width(clip: Path) -> None:
    from PIL import Image

    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource

    frame = await FfmpegFrameSource(_require(FFMPEG, "ffmpeg")).frame_at(clip, 2.0, width=720)

    assert frame.second == 2.0
    with Image.open(io.BytesIO(frame.jpeg)) as image:
        assert image.size == (720, 1280)


@pytest.mark.asyncio
async def test_frame_at_past_the_end_raises_frame_error(clip: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FrameError

    with pytest.raises(FrameError):
        await FfmpegFrameSource(_require(FFMPEG, "ffmpeg")).frame_at(clip, 99.0, width=720)


@pytest.mark.asyncio
async def test_frame_at_without_ffmpeg_raises_tool_missing(clip: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, ToolMissing

    with pytest.raises(ToolMissing) as raised:
        await FfmpegFrameSource("/nonexistent/ffmpeg").frame_at(clip, 1.0, width=720)
    assert raised.value.code == "ffmpeg_missing"


@pytest.mark.asyncio
async def test_ffprobe_reads_the_duration(clip: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import FfprobeDuration

    duration = await FfprobeDuration(_require(FFPROBE, "ffprobe")).duration(clip)

    assert duration == pytest.approx(4.0, abs=0.05)


@pytest.mark.asyncio
async def test_ffprobe_failures_are_told_apart(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.frames import (
        DurationError,
        FfprobeDuration,
        ToolMissing,
    )

    with pytest.raises(ToolMissing) as raised:
        await FfprobeDuration("/nonexistent/ffprobe").duration(tmp_path / "x.mp4")
    assert raised.value.code == "ffprobe_missing"
    with pytest.raises(DurationError):
        await FfprobeDuration(_require(FFPROBE, "ffprobe")).duration(tmp_path / "missing.mp4")


@pytest.mark.asyncio
async def test_rapidocr_boxes_carry_left_and_right() -> None:
    pytest.importorskip("rapidocr")
    from PIL import Image, ImageDraw, ImageFont

    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    image = Image.new("RGB", (720, 1280), "white")
    ImageDraw.Draw(image).text(
        (400, 600), "KABAR TERKINI", fill="black", font=ImageFont.load_default(size=40)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)

    boxes = await RapidOcrReader(angle=False).read(Frame(0.0, buffer.getvalue()))

    found = [box for box in boxes if "TERKINI" in box.text]
    assert found, [box.text for box in boxes]
    assert 0.5 < found[0].left < found[0].right <= 1.0
    assert 0.4 < found[0].top < found[0].bottom < 0.55
```

In `python/tests/attribution/test_local_adapters.py`, replace the `skipif` marker so the two
Stage 4 ffmpeg tests fail when ffmpeg is absent, with a fixture:

```python
FFMPEG = shutil.which("ffmpeg")


@pytest.fixture
def ffmpeg() -> str:
    # Operator, 2026-10-11: a missing ffmpeg is an error, never a skip.
    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    return FFMPEG
```

Remove the `needs_ffmpeg = pytest.mark.skipif(...)` line and both `@needs_ffmpeg` decorators.
Give both ffmpeg tests an `ffmpeg: str` parameter and replace `FFMPEG` inside them with
`ffmpeg` (in the `subprocess.run` argv and in `FfmpegFrameSource(ffmpeg)`; drop the
`# type: ignore[arg-type]` comments that only existed for the `None` case).

- [ ] **Step 4: Run the tests to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/test_config.py tests/domain tests/assembly tests/attribution/test_local_adapters.py -p no:warnings`
Expected: FAIL — `Settings` has no `THOTH_CONTENT_ASSEMBLY_ENABLED`, the payload keys are
rejected, `frame_at`, `ToolMissing`, `FfprobeDuration`, `left`, and `angle` do not exist. The two
Stage 4 ffmpeg tests pass (ffmpeg is installed in WSL).

- [ ] **Step 5: Implement the settings**

In `python/src/thoth_control_plane/config.py`, after `THOTH_SOURCE_ATTRIBUTION_ENABLED`:

```python
    # Stage 5a content assembly. Off by default; the worker refuses to start with it on and
    # no ffmpeg or ffprobe (operator, 2026-10-11).
    THOTH_CONTENT_ASSEMBLY_ENABLED: bool = False
    THOTH_SUBTITLE_OCR_MAX_FRAMES: Annotated[int, Field(ge=1, le=60)] = 12
    THOTH_FIGURES_MODEL: str = "deepseek/deepseek-v4-flash-0731"
```

- [ ] **Step 6: Implement the event payload allowlist**

In `python/src/thoth_control_plane/domain/models.py`, add `"ocr_outcome"`, `"comment_count"`,
`"figure_count"` to `SOURCE_EVENT_PAYLOAD_KEYS`. Above `SOURCE_EVENT_REASONS` add:

```python
ASSEMBLY_REASONS = frozenset(
    {
        "source_report_missing",
        "original_report_missing",
        "main_media_missing",
        "ffmpeg_missing",
        "ffprobe_missing",
        "duration_probe_failed",
        "incomplete_frame_coverage",
        "content_set_invalid",
        "artifact_write_failed",
    }
)
OCR_OUTCOMES = frozenset({"clean", "cover", "subtitle", "none"})
```

and change `SOURCE_EVENT_REASONS = frozenset({...})` to
`SOURCE_EVENT_REASONS = frozenset({...}) | ASSEMBLY_REASONS` (keep the existing members). In
`SourceProgressEvent.validate_payload`, before the `progress` check, add:

```python
        if "ocr_outcome" in payload and payload["ocr_outcome"] not in OCR_OUTCOMES:
            raise ValueError("source event OCR outcome is unsupported")
        for count in ("comment_count", "figure_count"):
            value = payload.get(count)
            if count in payload and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("source event counts must be non-negative integers")
```

- [ ] **Step 7: Implement `TextBox` geometry and the RapidOCR angle switch**

In `python/src/thoth_control_plane/attribution/matching.py`, extend the frozen dataclass:

```python
@dataclass(frozen=True)
class TextBox:
    """One OCR line; `top`/`bottom` are fractions of the height, `left`/`right` of the width."""

    text: str
    top: float
    bottom: float
    left: float = 0.0
    right: float = 1.0
```

Replace `python/src/thoth_control_plane/attribution/adapters/ocr.py` `RapidOcrReader` with:

```python
class RapidOcrReader:
    def __init__(self, angle: bool = True) -> None:
        # Video text is upright; without the angle classifier a 720 px frame reads in about
        # 0.55 s instead of 0.84 s with the same text (bench, 2026-10-11).
        self._angle = angle
        self._engine: Any = None
        self._lock = threading.Lock()  # finalists read in parallel threads; build one engine

    async def read(self, frame: Frame) -> list[TextBox]:
        return await asyncio.to_thread(self._read, frame.jpeg)

    def _read(self, jpeg: bytes) -> list[TextBox]:
        from PIL import Image

        with Image.open(io.BytesIO(jpeg)) as image:
            width, height = image.size
        result = self._get()(jpeg, use_cls=self._angle)
        if result.boxes is None or result.txts is None:
            return []
        boxes: list[TextBox] = []
        for quad, text in zip(result.boxes, result.txts, strict=False):
            xs = [float(point[0]) for point in quad]
            ys = [float(point[1]) for point in quad]
            boxes.append(
                TextBox(
                    str(text)[:MAX_TEXT],
                    min(ys) / height,
                    max(ys) / height,
                    max(0.0, min(xs) / width),
                    min(1.0, max(xs) / width),
                )
            )
        return boxes
```

Keep `_get` unchanged.

- [ ] **Step 8: Implement `frame_at`, `ToolMissing`, and `FfprobeDuration`**

In `python/src/thoth_control_plane/attribution/adapters/frames.py`, below `FrameError` add:

```python
class ToolMissing(Exception):
    """A required binary is not installed: never a media failure (operator, 2026-10-11)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DurationError(Exception):
    """ffprobe ran but could not read a duration."""


async def _run(argv: list[str], missing: str, *, capture: bool = False) -> tuple[int, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise ToolMissing(missing) from None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except TimeoutError:
        raise FrameError("ffmpeg_timeout") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return process.returncode or 0, output or b""
```

Add to `FfmpegFrameSource`:

```python
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        """One JPEG at `second`, `width` px wide; FrameError when nothing decodes there."""
        with tempfile.TemporaryDirectory(prefix="thoth-frame-") as directory:
            target = Path(directory) / "frame.jpg"
            code, _ = await _run(
                [
                    self._ffmpeg, "-nostdin", "-v", "error",
                    "-ss", f"{second:.6f}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "2", str(target),
                ],
                "ffmpeg_missing",
            )
            if code != 0 or not target.is_file() or target.stat().st_size == 0:
                raise FrameError("ffmpeg_failed")
            return Frame(second, target.read_bytes())
```

And a new class at the end of the module:

```python
class FfprobeDuration:
    def __init__(self, ffprobe: str = "ffprobe") -> None:
        self._ffprobe = ffprobe

    async def duration(self, video: Path) -> float:
        code, output = await _run(
            [
                self._ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video),
            ],
            "ffprobe_missing",
            capture=True,
        )
        try:
            value = float(output.decode().strip())
        except ValueError:
            raise DurationError("duration_probe_failed") from None
        if code != 0 or not value > 0:
            raise DurationError("duration_probe_failed")
        return value
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/test_config.py tests/domain tests/assembly tests/attribution -p no:warnings`
Expected: PASS (the `rapidocr` test runs: `pt.sh` installs `rapidocr` and `onnxruntime`).

- [ ] **Step 10: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane tests && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/config.py python/src/thoth_control_plane/domain/models.py python/src/thoth_control_plane/attribution python/tests/test_config.py python/tests/domain python/tests/assembly python/tests/attribution/test_local_adapters.py
git commit -m "feat(assembly): settings, event payload, ffmpeg and ffprobe adapters"
```

---

### Task 2: Port the subtitle classifier with a Scout parity fixture

**Files:**
- Create: `python/src/thoth_control_plane/assembly/__init__.py`
- Create: `python/src/thoth_control_plane/assembly/subtitles.py`
- Create: `python/tests/assembly/scout_classifier_parity.ts` (fixture generator, run once with Bun)
- Create: `python/tests/fixtures/assembly/classifier_parity.json` (generated)
- Create: `python/tests/assembly/test_subtitles.py`

**Interfaces:**
- Produces (`thoth_control_plane.assembly.subtitles`):
  - `OcrBox(text: str, x0: float, y0: float, x1: float, y1: float)` (frozen dataclass)
  - `OcrFrame(t: float, boxes: tuple[OcrBox, ...] = (), error: str | None = None)`
  - `Region(x: float, y: float, w: float, h: float, start: float, end: float)`
  - `Verdict(outcome: Literal["clean","cover","subtitle"], trim_start: float, mute_audio: bool, subtitle_blur: tuple[Region, ...])`
  - `build_sample_times(duration: float, max_frames: int = 12) -> list[float]`
  - `classify_ocr_frames(frames: Sequence[OcrFrame], duration: float) -> Verdict`

- [ ] **Step 1: Write the fixture generator**

Create `python/tests/assembly/scout_classifier_parity.ts`. It runs Scout's own classifier on the
hand-written cases of `scout/lib/subtitle_vision.test.ts` (transcribed verbatim below) and on
300 seeded random cases, and records Scout's answers, so the Python port is checked against
Scout's code, never against hand-computed expectations.

```ts
// Generates python/tests/fixtures/assembly/classifier_parity.json from Scout's classifier.
// Run once from the repository root: bun python/tests/assembly/scout_classifier_parity.ts
// Re-run only if scout/lib/subtitle_vision.ts changes (it is frozen while Scout retires).
import fs from 'node:fs';
import path from 'node:path';
import {
  buildSampleTimes,
  classifyOcrFrames,
  type OcrBox,
  type OcrFrame,
} from '../../../scout/lib/subtitle_vision.ts';

const b = (text: string, x0: number, y0: number, x1: number, y1: number): OcrBox => ({
  text, x0, y0, x1, y1,
});
const f = (t: number, ...boxes: OcrBox[]): OcrFrame => ({ t, boxes });
const banner = (t: number, y1: number) => f(t, b('IDN TIMES', 0.25, 0.8, 0.75, y1));

// Verbatim inputs of every classifyOcrFrames call in scout/lib/subtitle_vision.test.ts.
const HAND: { name: string; frames: OcrFrame[]; duration: number }[] = [
  { name: 'cjk_captions', duration: 8, frames: [
    f(1, b('啊', 0.18, 0.72, 0.82, 0.8)), f(3, b('呢', 0.18, 0.72, 0.82, 0.8)),
    f(5, b('哦', 0.18, 0.72, 0.82, 0.8))] },
  { name: 'phantom_ocr', duration: 110, frames: [
    f(0.5, b('三', 0, 0.77, 0.424, 0.84)), f(1, b('1', 0, 0.75, 0.499, 0.808)),
    f(2, b('#', 0, 0.64, 0.66, 0.712)), f(3, b('#', 0, 0.75, 0.65, 0.844)),
    f(4, b('#', 0, 0.8, 0.6, 0.884)), f(5, b('#', 0.12, 0.777, 0.76, 0.852)),
    f(64.733334, b('福', 0, 0, 0.997, 0.997)), f(84.644445, b('福', 0, 0, 0.996, 0.996)),
    f(104.555556, b('1', 0, 0, 0.995, 0.999))] },
  { name: 'hybrid', duration: 26.935, frames: [
    f(0.5, b('CUCURELLA BUNGKUS TROFI', 0.05, 0.46, 0.82, 0.54)),
    f(1, b('CUCURELLA BUNGKUS TROFI', 0.05, 0.46, 0.82, 0.54)),
    f(3, b('CUCURELLA BUNGKUS TROFI', 0.05, 0.46, 0.82, 0.54)),
    f(5, b('BAWA PULANG', 0.25, 0.78, 0.75, 0.85)),
    f(8, b('KOK PIALA SEMEWAH', 0.18, 0.76, 0.82, 0.86)),
    f(12, b('REPLIKA RESMI YANG', 0.2, 0.75, 0.8, 0.86))] },
  { name: 'intro_then_moving_track', duration: 10, frames: [
    f(0.5, b('INTRO HEADLINE', 0.08, 0.4, 0.92, 0.52)),
    f(2, b('INTRO HEADLINE', 0.06, 0.39, 0.94, 0.53)),
    f(4, b('spoken one', 0.24, 0.74, 0.7, 0.8)),
    f(6, b('spoken two', 0.12, 0.72, 0.88, 0.84))] },
  { name: 'partial_failure', duration: 8, frames: [
    f(1, b('MATCH DAY', 0.1, 0.3, 0.9, 0.4)), f(2, b('MATCH DAY', 0.1, 0.3, 0.9, 0.4)),
    { t: 3, boxes: [], error: 'TimeoutError' }, f(4, b('MATCH DAY', 0.1, 0.3, 0.9, 0.4)),
    f(5)] },
  { name: 'real_geometry', duration: 10, frames: [
    f(1, b('CURELLA BUNGKUS TROFI', 0.09, 0.521, 0.803, 0.546),
      b('PIALA DUNIA PAKE KRESEK', 0.09, 0.568, 0.777, 0.595)),
    f(2, b('CUCURELLA BUNGKUS TROFI', 0.114, 0.521, 0.924, 0.546),
      b('PIALA DUNIA PAKE KRESEK', 0.114, 0.568, 0.894, 0.593)),
    f(3, b('CUCURELLA BUNGKUS TROFI', 0.117, 0.521, 0.919, 0.546),
      b('PIALA DUNIA PAKE KRESEK', 0.117, 0.567, 0.891, 0.592)),
    f(4, b('DIA NGGAK TAHU', 0.174, 0.758, 0.83, 0.799)),
    f(5, b('BAWA PULANG', 0.215, 0.755, 0.787, 0.799)),
    f(8, b('KOK PIALA SEMEWAH', 0.277, 0.733, 0.7, 0.824))] },
  { name: 'lower_third', duration: 8, frames: [
    f(1, b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89), b('BREAKING NEWS', 0.18, 0.84, 0.7, 0.89)),
    f(3, b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89), b('MARKETS RALLY', 0.182, 0.84, 0.66, 0.89)),
    f(5, b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89), b('MORE AT TEN', 0.181, 0.84, 0.62, 0.89))] },
  { name: 'left_captions', duration: 8, frames: [
    f(1, b('I SAW IT LIVE', 0.05, 0.72, 0.55, 0.79)),
    f(3, b('THIS TO HAPPEN', 0.052, 0.72, 0.52, 0.79)),
    f(5, b('WATCH UNTIL END', 0.051, 0.72, 0.58, 0.79))] },
  { name: 'stable_two_line', duration: 8, frames: [
    f(1, b('THIS LINE STAYS', 0.18, 0.7, 0.82, 0.75), b('SO DOES THIS', 0.25, 0.76, 0.75, 0.81)),
    f(3, b('THIS LINE STAYS', 0.18, 0.7, 0.82, 0.75), b('SO DOES THIS', 0.25, 0.76, 0.75, 0.81)),
    f(5, b('THIS LINE STAYS', 0.18, 0.7, 0.82, 0.75), b('SO DOES THIS', 0.25, 0.76, 0.75, 0.81))] },
  { name: 'watermark', duration: 10, frames: [
    f(1, b('@channel', 0.86, 0.03, 0.98, 0.06)), f(3, b('@channel', 0.86, 0.03, 0.98, 0.06)),
    f(8, b('@channel', 0.86, 0.03, 0.98, 0.06))] },
  { name: 'banner_jitter', duration: 20, frames: [
    banner(1, 0.8384), banner(2, 0.8404), banner(3, 0.8384), banner(4, 0.8404),
    banner(5, 0.8384)] },
  { name: 'real_cover', duration: 20, frames: [
    f(1, b('BREAKING STORY HEADLINE', 0.2, 0.3, 0.8, 0.42)),
    f(3, b('BREAKING STORY HEADLINE', 0.2, 0.3, 0.8, 0.42)), f(5)] },
  { name: 'cover', duration: 12, frames: [
    f(0.5, b('MATCH DAY', 0.1, 0.3, 0.9, 0.43)), f(2, b('MATCH DAY', 0.11, 0.3, 0.91, 0.43)),
    f(4), f(8)] },
  { name: 'subtitle_moving', duration: 10, frames: [
    f(1), f(3, b('SATU', 0.16, 0.73, 0.7, 0.8)), f(5, b('DUA', 0.25, 0.75, 0.85, 0.84)),
    f(8, b('TIGA', 0.1, 0.72, 0.74, 0.81))] },
  { name: 'separate_tracks', duration: 8, frames: [
    f(1), f(3, b('LEFT CAPTION', 0.05, 0.72, 0.35, 0.8)),
    f(5, b('RIGHT CAPTION', 0.65, 0.72, 0.95, 0.8))] },
  { name: 'simultaneous_tracks', duration: 8, frames: [
    f(1), f(3, b('LEFT ONE', 0.05, 0.72, 0.35, 0.8), b('RIGHT ONE', 0.65, 0.72, 0.95, 0.8)),
    f(5, b('LEFT TWO', 0.06, 0.72, 0.36, 0.8), b('RIGHT TWO', 0.64, 0.72, 0.94, 0.8))] },
  { name: 'split_transition', duration: 8, frames: [
    f(1), f(3, b('BROAD CAPTION', 0.2, 0.72, 0.8, 0.8)),
    f(5, b('LEFT SPLIT', 0.1, 0.72, 0.4, 0.8), b('RIGHT SPLIT', 0.6, 0.72, 0.9, 0.8))] },
  { name: 'two_line', duration: 8, frames: [
    f(1), f(3, b('BARIS SATU', 0.16, 0.7, 0.82, 0.76), b('BARIS DUA', 0.22, 0.77, 0.76, 0.84)),
    f(5, b('KALIMAT BARU', 0.14, 0.71, 0.8, 0.77), b('LANJUTANNYA', 0.2, 0.78, 0.78, 0.85))] },
  { name: 'headline_then_captions', duration: 9, frames: [
    f(1, b('HEADLINE', 0.1, 0.3, 0.9, 0.4)), f(2, b('HEADLINE', 0.1, 0.3, 0.9, 0.4)), f(3),
    f(5, b('CAPTION A', 0.2, 0.72, 0.8, 0.8)), f(7, b('CAPTION B', 0.2, 0.72, 0.8, 0.8))] },
  { name: 'repeated_merge', duration: 6, frames: [
    f(1, b('ONE', 0.2, 0.72, 0.8, 0.8)), f(2, b('TWO', 0.2, 0.72, 0.8, 0.8)),
    f(3, b('THREE', 0.2, 0.72, 0.8, 0.8)), f(4, b('FOUR', 0.2, 0.72, 0.8, 0.8)),
    f(5, b('FIVE', 0.2, 0.72, 0.8, 0.8))] },
];

// mulberry32: a tiny seeded generator so the fixture is reproducible.
function rng(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const WORDS = ['GEMPA', 'WARGA', 'banjir', 'LIVE NEWS', 'BREAKING NEWS', 'kata', 'PIALA',
  'jalan', 'RUMAH', 'akhirnya', 'netizen', '@akun', '2026', 'BERITA', 'SATU', 'DUA'];

function randomCase(index: number) {
  const r = rng(1000 + index);
  const pick = <T>(items: T[]) => items[Math.floor(r() * items.length)];
  const jit = (v: number) => Math.min(1, Math.max(0, v + (r() - 0.5) * 0.02));
  const duration = Number((3 + r() * 117).toFixed(3));
  const times = buildSampleTimes(duration, 12);
  const headline = r() < 0.5 ? pick(WORDS) + ' ' + pick(WORDS) + ' ' + pick(WORDS) : null;
  const headlineUntil = 1 + r() * 5;
  const subtitles = r() < 0.5;
  const subY = 0.68 + r() * 0.15;
  const chyron = r() < 0.25;
  const watermark = r() < 0.4;
  const frames: OcrFrame[] = times.map((t) => {
    if (r() < 0.04) return { t, boxes: [], error: 'frame_extract' };
    const boxes: OcrBox[] = [];
    if (headline && t <= headlineUntil) boxes.push(b(headline, jit(0.08), jit(0.3), jit(0.9), jit(0.36)));
    if (subtitles && t > headlineUntil && r() < 0.85) {
      const x0 = jit(0.12 + r() * 0.1);
      boxes.push(b(pick(WORDS) + ' ' + pick(WORDS), x0, jit(subY), Math.min(1, x0 + 0.4 + r() * 0.4), jit(subY + 0.05)));
      if (r() < 0.3) boxes.push(b(pick(WORDS), jit(0.2), jit(subY + 0.06), jit(0.75), jit(subY + 0.11)));
    }
    if (chyron) {
      boxes.push(b('LIVE NEWS', 0.02, 0.84, 0.14, 0.89));
      boxes.push(b(pick(WORDS) + ' ' + pick(WORDS), jit(0.18), 0.84, jit(0.7), 0.89));
    }
    if (watermark) boxes.push(b('@channel', 0.86, 0.03, 0.98, 0.06));
    if (r() < 0.15) boxes.push(b(pick(WORDS), r() * 0.8, r() * 0.9, r() * 0.2 + 0.8, r() * 0.1 + 0.9));
    return { t, boxes };
  });
  return { name: `random_${index}`, frames, duration };
}

const cases = [...HAND, ...Array.from({ length: 300 }, (_, i) => randomCase(i))].map((c) => ({
  ...c,
  verdict: classifyOcrFrames(c.frames, c.duration),
}));
const sampleTimes = [0, 0.3, 0.5, 0.6, 3, 5, 5.2, 7, 12, 30, 59.94, 90, 600].flatMap((duration) =>
  [1, 6, 12, 20].map((maxFrames) => ({ duration, maxFrames, times: buildSampleTimes(duration, maxFrames) })),
);
const out = path.join(import.meta.dirname, '..', 'fixtures', 'assembly', 'classifier_parity.json');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify({ source: 'scout/lib/subtitle_vision.ts', cases, sampleTimes }, null, 1) + '\n');
console.log(`wrote ${cases.length} cases and ${sampleTimes.length} sample-time cases`);
```

Before running, open `scout/lib/subtitle_vision.test.ts` lines 612–959 next to `HAND` and check
that every `classifyOcrFrames(` call there has an entry with identical frames and duration
(there are 20 calls; `banner_jitter` and `real_cover` share one block).

- [ ] **Step 2: Generate the fixture**

Run (repository root, Windows): `bun python/tests/assembly/scout_classifier_parity.ts`
Expected: `wrote 320 cases and 52 sample-time cases`, and
`python/tests/fixtures/assembly/classifier_parity.json` exists. Check that the fixture has a mix
of outcomes:
`python -c "import json,collections;d=json.load(open('python/tests/fixtures/assembly/classifier_parity.json',encoding='utf-8'));print(collections.Counter(c['verdict']['outcome'] for c in d['cases']))"`
Expected: all three outcomes, each at least 20 times. If one outcome has fewer than 20, raise
the share of the generator branch that produces it (for example the `subtitles` probability) and
regenerate.

- [ ] **Step 3: Write the failing parity test**

Create `python/tests/assembly/test_subtitles.py`:

```python
"""The Python classifier answers exactly as Scout's on Scout's cases and 300 random ones."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    build_sample_times,
    classify_ocr_frames,
)

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "assembly" / "classifier_parity.json").read_text(
        encoding="utf-8"
    )
)


def _frames(raw: list[dict[str, Any]]) -> list[OcrFrame]:
    return [
        OcrFrame(
            t=float(frame["t"]),
            boxes=tuple(
                OcrBox(box["text"], box["x0"], box["y0"], box["x1"], box["y1"])
                for box in frame["boxes"]
            ),
            error=frame.get("error"),
        )
        for frame in raw
    ]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=[c["name"] for c in FIXTURE["cases"]])
def test_classifier_matches_scout(case: dict[str, Any]) -> None:
    verdict = classify_ocr_frames(_frames(case["frames"]), float(case["duration"]))
    expected = case["verdict"]

    assert verdict.outcome == expected["outcome"]
    assert verdict.trim_start == pytest.approx(expected["trim_start"], abs=1e-9)
    assert verdict.mute_audio is expected["mute_audio"]
    assert len(verdict.subtitle_blur) == len(expected["subtitle_blur"])
    for region, scout in zip(verdict.subtitle_blur, expected["subtitle_blur"], strict=True):
        for name in ("x", "y", "w", "h", "start", "end"):
            assert getattr(region, name) == pytest.approx(scout[name], abs=1e-9), name


@pytest.mark.parametrize(
    "case",
    FIXTURE["sampleTimes"],
    ids=[f"{c['duration']}s_{c['maxFrames']}" for c in FIXTURE["sampleTimes"]],
)
def test_sample_times_match_scout(case: dict[str, Any]) -> None:
    assert build_sample_times(float(case["duration"]), case["maxFrames"]) == pytest.approx(
        case["times"], abs=1e-9
    )


def test_every_outcome_is_covered() -> None:
    outcomes = {case["verdict"]["outcome"] for case in FIXTURE["cases"]}
    assert outcomes == {"clean", "cover", "subtitle"}
```

- [ ] **Step 4: Run it to verify it fails**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_subtitles.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.assembly'`.

- [ ] **Step 5: Implement the port**

Create `python/src/thoth_control_plane/assembly/__init__.py`:

```python
"""Stage 5a content assembly: the main with its final OCR, comments, and figures."""
```

Create `python/src/thoth_control_plane/assembly/subtitles.py`:

```python
"""Speech captions and intro headlines from OCR boxes: a pure port of Scout's classifier.

Port of `classifyOcrFrames` and `buildSampleTimes` in `scout/lib/subtitle_vision.ts`; the
parity fixture in `tests/fixtures/assembly/classifier_parity.json` holds Scout's own answers.
Headline removal (`trim_start`) and subtitle censorship (blur windows, muted audio) are
independent: a clip can keep a positive trim_start and still carry later blur windows. An
editorial lower-third (a changing chyron anchored by a stable "LIVE NEWS" badge) is kept.
All geometry is normalized to 0..1.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

COVER_MAX = 5.0
# Above this share of the frame a persistent box is furniture worth reasoning about (a headline,
# a caption); below it, it is a watermark or a station badge that every frame carries.
STABLE_SMALL_AREA = 0.02
EDITORIAL_LABEL = re.compile(
    r"^(breaking news|live(?: news)?|exclusive|news(?: update)?|sports|weather|headlines?)$"
)
Outcome = Literal["clean", "cover", "subtitle"]


@dataclass(frozen=True)
class OcrBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class OcrFrame:
    t: float
    boxes: tuple[OcrBox, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    w: float
    h: float
    start: float
    end: float


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    trim_start: float
    mute_audio: bool
    subtitle_blur: tuple[Region, ...]


CLEAN = Verdict("clean", 0.0, False, ())


def build_sample_times(duration: float, max_frames: int = 12) -> list[float]:
    """The intro densely (headlines live there), the rest spread evenly to the end."""
    limit = max(1, math.floor(max_frames))
    if not math.isfinite(duration) or duration <= 0.5:
        return [0.0]
    intro = [float(t) for t in (0.5, 1, 2, 3, 4, 5) if t < duration][:limit]
    if len(intro) >= limit or duration <= 5:
        return intro
    remaining = limit - len(intro)
    safe_end = max(5.0, duration - min(0.1, duration / 100))
    tail = [round(5 + (safe_end - 5) * ((i + 1) / remaining), 6) for i in range(remaining)]
    return sorted(set(intro) | set(tail))[:limit]


def norm_text(text: str) -> str:
    """Lowercase; every run of characters that is not a letter or a digit becomes one space."""
    kept = "".join(c if unicodedata.category(c)[0] in "LN" else " " for c in text.lower())
    return " ".join(kept.split())


def _area(box: OcrBox) -> float:
    return max(0.0, box.x1 - box.x0) * max(0.0, box.y1 - box.y0)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) >> 1
    return ordered[mid] if len(ordered) % 2 == 1 else (ordered[mid - 1] + ordered[mid]) / 2


def _plausible_subtitle(box: OcrBox) -> bool:
    # One-glyph captions are valid in CJK; digits alone are not caption evidence. A near
    # full-frame OCR box is noise.
    text = norm_text(box.text)
    digits_only = all(unicodedata.category(c)[0] == "N" or c.isspace() for c in text)
    return bool(text) and not digits_only and not (box.x1 - box.x0 >= 0.9 and box.y1 - box.y0 >= 0.85)


def _iou(a: OcrBox, b: OcrBox) -> float:
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(
        0.0, min(a.y1, b.y1) - max(a.y0, b.y0)
    )
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _v_overlap(a: OcrBox, b: OcrBox) -> float:
    overlap = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return overlap / max(0.000001, min(a.y1 - a.y0, b.y1 - b.y0))


def _h_overlap(a: OcrBox, b: OcrBox) -> float:
    overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return overlap / max(0.000001, min(a.x1 - a.x0, b.x1 - b.x0))


def _gap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, max(a0, b0) - min(a1, b1))


def _linked(a: OcrBox, b: OcrBox) -> bool:
    return (_v_overlap(a, b) >= 0.5 and _gap(a.x0, a.x1, b.x0, b.x1) <= 0.08) or (
        _h_overlap(a, b) >= 0.3 and _gap(a.y0, a.y1, b.y0, b.y1) <= 0.07
    )


def _group(boxes: Sequence[OcrBox]) -> list[list[OcrBox]]:
    groups: list[list[OcrBox]] = []
    for box in boxes:
        connected = [i for i, group in enumerate(groups) if any(_linked(box, o) for o in group)]
        if not connected:
            groups.append([box])
            continue
        target = groups[connected[0]]
        target.append(box)
        for i in reversed(connected[1:]):
            target.extend(groups[i])
            del groups[i]
    return groups


def _multiline(boxes: Sequence[OcrBox]) -> bool:
    return any(
        i != j and _gap(a.y0, a.y1, b.y0, b.y1) <= 0.07 and _h_overlap(a, b) >= 0.3
        for i, a in enumerate(boxes)
        for j, b in enumerate(boxes)
    )


def _editorial(text: str) -> bool:
    return EDITORIAL_LABEL.match(norm_text(text)) is not None


def _lower_third(
    box: OcrBox, index: int, frames: Sequence[OcrFrame], labels: Sequence[OcrBox]
) -> bool:
    if box.y0 < 0.65 or box.x0 > 0.3:
        return False
    # A changing left-aligned caption is ambiguous alone: it is an editorial lower-third only
    # when a separate persistent label anchors the same band.
    center = (box.y0 + box.y1) / 2
    anchored = any(
        norm_text(label.text) != norm_text(box.text)
        and abs((label.y0 + label.y1) / 2 - center) <= 0.12
        and label.x0 < box.x0 - 0.03
        and _iou(label, box) < 0.2
        for label in labels
    )
    if not anchored:
        return False
    track = [
        (i, other)
        for i, frame in enumerate(frames)
        for other in frame.boxes
        if _v_overlap(box, other) >= 0.5 and abs(other.x0 - box.x0) <= 0.04
    ]
    if len({i for i, _ in track}) < 2:
        return False
    lefts = [other.x0 for _, other in track]
    return max(lefts) - min(lefts) <= 0.035 and any(
        i != index and norm_text(other.text) != norm_text(box.text) for i, other in track
    )


def _similarity(a: str, b: str) -> float:
    aa, bb = norm_text(a), norm_text(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    tokens_a, tokens_b = set(aa.split(" ")), set(bb.split(" "))
    union = len(tokens_a | tokens_b)
    token_score = len(tokens_a & tokens_b) / union if union else 0.0
    bigrams_a = {aa[i : i + 2] for i in range(len(aa) - 1)}
    bigrams_b = {bb[i : i + 2] for i in range(len(bb) - 1)}
    total = len(bigrams_a) + len(bigrams_b)
    dice = 2 * len(bigrams_a & bigrams_b) / total if total else 0.0
    return max(token_score, dice)


def _envelope(boxes: Sequence[OcrBox]) -> OcrBox:
    return OcrBox(
        " ".join(box.text for box in boxes),
        max(0.0, min(box.x0 for box in boxes) - 0.02),
        max(0.0, min(box.y0 for box in boxes) - 0.015),
        min(1.0, max(box.x1 for box in boxes) + 0.02),
        min(1.0, max(box.y1 for box in boxes) + 0.015),
    )


def _union(a: OcrBox, b: OcrBox) -> OcrBox:
    return OcrBox(
        f"{a.text} {b.text}".strip(), min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1)
    )


@dataclass
class _Window:
    frame_index: int
    start: float
    end: float
    region: OcrBox


def classify_ocr_frames(frames: Sequence[OcrFrame], duration: float) -> Verdict:
    # A failed sample is unknown, not clean: it must not read as a headline disappearing.
    ordered = sorted((frame for frame in frames if not frame.error), key=lambda frame: frame.t)
    if not ordered:
        return CLEAN
    stable = max(2, math.ceil(len(ordered) * 0.6))

    def same(a: OcrBox, b: OcrBox) -> bool:
        return norm_text(a.text) == norm_text(b.text) and _iou(a, b) >= 0.6

    every = [box for frame in ordered for box in frame.boxes]
    labels: list[OcrBox] = []
    for index, candidate in enumerate(every):
        if not _editorial(candidate.text) or candidate.y0 < 0.65 or _area(candidate) >= STABLE_SMALL_AREA:
            continue
        held = sum(
            1 for frame in ordered if any(_editorial(b.text) and same(b, candidate) for b in frame.boxes)
        )
        first = next((i for i, box in enumerate(every) if same(box, candidate)), -1)
        if held >= stable and first == index:
            labels.append(candidate)

    # A banner on the 2% cutoff jitters across it sample to sample; judge it by its median area
    # so all its samples are kept or dropped together (an 89 s video once lost 47 s to this).
    def stable_small(candidate: OcrBox) -> bool:
        areas = []
        for frame in ordered:
            match = next((box for box in frame.boxes if same(box, candidate)), None)
            if match is not None:
                areas.append(_area(match))
        return len(areas) >= stable and _median(areas) < STABLE_SMALL_AREA

    filtered = [
        replace(frame, boxes=tuple(box for box in frame.boxes if not stable_small(box)))
        for frame in ordered
    ]

    def headline_match(anchor: OcrBox, box: OcrBox) -> bool:
        return _similarity(anchor.text, box.text) >= 0.5 and _iou(anchor, box) >= 0.45

    trim_start = 0.0
    for index, frame in enumerate(filtered):
        if frame.t > COVER_MAX:
            break
        # Headlines often arrive one thin line at a time: wide, but only ~1.5-2% of the frame.
        for anchor in (b for b in frame.boxes if _area(b) >= 0.015 and b.x1 - b.x0 >= 0.45):
            matching = []
            for i in range(index, len(filtered)):
                if filtered[i].t > COVER_MAX:
                    break
                if any(headline_match(anchor, box) for box in filtered[i].boxes):
                    matching.append(i)
            if len(matching) < 2:
                continue
            last = matching[-1]
            absent = next(
                (
                    i
                    for i in range(last + 1, len(filtered))
                    if not any(headline_match(anchor, box) for box in filtered[i].boxes)
                ),
                -1,
            )
            if absent > last:
                trim_start = max(trim_start, (filtered[last].t + filtered[absent].t) / 2)

    raw = [
        replace(
            frame,
            boxes=tuple(
                box
                for box in frame.boxes
                if box.x1 - box.x0 >= 0.18 and box.y1 - box.y0 >= 0.025 and _plausible_subtitle(box)
            )
            if frame.t + 1e-9 >= trim_start
            else (),
        )
        for frame in filtered
    ]
    candidates = [
        replace(
            frame,
            boxes=tuple(box for box in frame.boxes if not _lower_third(box, index, raw, labels)),
        )
        for index, frame in enumerate(raw)
    ]
    multiline = [_multiline(frame.boxes) for frame in candidates]
    selected: list[list[OcrBox]] = []
    for index, frame in enumerate(candidates):
        keep = []
        for box in frame.boxes:
            changes = any(
                other_index != index
                and any(
                    _v_overlap(box, o) >= 0.5 and norm_text(box.text) != norm_text(o.text)
                    for o in other.boxes
                )
                for other_index, other in enumerate(candidates)
            )
            stacked = multiline[index] and any(
                other_index != index
                and multiline[other_index]
                and any(_v_overlap(box, o) >= 0.5 for o in other.boxes)
                for other_index, other in enumerate(candidates)
            )
            if changes or stacked:
                keep.append(box)
        selected.append(keep)

    windows: list[_Window] = []
    for i, boxes in enumerate(selected):
        if not boxes:
            continue
        start = (filtered[i - 1].t + filtered[i].t) / 2 if i > 0 else 0.0
        end = (filtered[i].t + filtered[i + 1].t) / 2 if i + 1 < len(filtered) else duration
        for group in _group(boxes):
            windows.append(_Window(i, max(trim_start, start), min(duration, end), _envelope(group)))

    merged: list[_Window] = []
    consumed: set[int] = set()
    current = -1
    for window in windows:
        if window.frame_index != current:
            consumed = set()
            current = window.frame_index
        match: _Window | None = None
        best = -1.0
        for candidate in merged:
            if id(candidate) in consumed or window.start > candidate.end + 1e-6:
                continue
            vertical = _v_overlap(candidate.region, window.region)
            horizontal = _h_overlap(candidate.region, window.region)
            iou = _iou(candidate.region, window.region)
            if iou < 0.6 and (vertical < 0.5 or horizontal < 0.5):
                continue
            score = max(iou, min(vertical, horizontal))
            if score > best:
                match, best = candidate, score
        if match is not None:
            match.end = max(match.end, window.end)
            match.region = _union(match.region, window.region)
            consumed.add(id(match))
        else:
            created = _Window(window.frame_index, window.start, window.end, window.region)
            merged.append(created)
            consumed.add(id(created))

    blur = tuple(
        Region(
            w.region.x0, w.region.y0, w.region.x1 - w.region.x0, w.region.y1 - w.region.y0,
            w.start, w.end,
        )
        for w in merged
    )
    if blur:
        return Verdict("subtitle", trim_start, True, blur)
    if trim_start > 0:
        return Verdict("cover", trim_start, False, ())
    return CLEAN
```

- [ ] **Step 6: Run the parity test until it passes**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_subtitles.py -p no:warnings`
Expected: PASS for all 320 classifier cases and 52 sample-time cases. If a case fails, compare
that function line by line with `scout/lib/subtitle_vision.ts` lines 175–575; never change the
fixture to match Python.

- [ ] **Step 7: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/assembly tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/assembly python/tests/assembly python/tests/fixtures/assembly
git commit -m "feat(assembly): port Scout's subtitle classifier with a parity fixture"
```

---

### Task 3: The `ContentSet` v1 model

**Files:**
- Create: `python/src/thoth_control_plane/assembly/models.py`
- Create: `python/tests/assembly/test_models.py`

**Interfaces:**
- Consumes: `acquisition.models` (`CommentText`, `MediaType`, `PublishedAt`, `SafeRelativeLocation`, `TikTokHandle`), `domain.models` (`Checksum`, `OpaqueId`, `StrictModel`)
- Produces (`thoth_control_plane.assembly.models`): `MediaRef`, `BlurRegion`, `MainOcr`,
  `Main`, `Comment`, `Figure`, `ContentSet`, constants `MAX_COMMENTS = 12`,
  `MAX_FIGURES = 5`, `OCR_ANALYZER_VERSION = "subtitle-classifier-v1"`. Field names and types
  exactly as in Step 3.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/assembly/test_models.py`:

```python
"""ContentSet v1: inconsistent OCR, a video without OCR, or a main without media cannot exist."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from thoth_control_plane.assembly.models import ContentSet

VIDEO = {
    "location": "reports/wf_a/media/tiktok-1.mp4",
    "media_type": "video/mp4",
    "checksum": "sha256:" + "a" * 64,
    "bytes": 20000,
    "duration_seconds": 30.0,
}
OCR = {
    "analyzed_at": "2026-10-11T12:00:00Z",
    "requested_frames": 12,
    "valid_frames": 12,
    "outcome": "clean",
    "trim_start": 0.0,
    "mute_audio": False,
    "subtitle_blur": [],
}


def content_set(**main: Any) -> dict[str, Any]:
    base = {
        "source": "input",
        "url": "https://www.tiktok.com/@creator/video/1234567890",
        "platform": "tiktok",
        "title": "judul",
        "description": "judul panjang",
        "owner_handle": "creator",
        "kind": "video",
        "video": VIDEO,
        "ocr": OCR,
    }
    base.update(main)
    return {
        "workflow_id": "wf_a",
        "attribution_verdict": "none",
        "main": base,
        "comments": [],
        "figures": [],
        "figures_status": "none",
    }


def parse(data: dict[str, Any]) -> ContentSet:
    return ContentSet.model_validate_json(json.dumps(data))


def test_a_clean_video_main_is_valid() -> None:
    parsed = parse(content_set())
    assert parsed.schema_version == 1
    assert parsed.main.ocr is not None and parsed.main.ocr.engine == "rapidocr"
    assert parsed.footage == ()


@pytest.mark.parametrize(
    ("ocr", "message"),
    [
        ({"outcome": "clean", "trim_start": 1.0}, "clean"),
        ({"outcome": "clean", "mute_audio": True}, "clean"),
        ({"outcome": "cover", "trim_start": 0.0}, "cover"),
        ({"outcome": "cover", "trim_start": 2.0, "mute_audio": True}, "cover"),
        ({"outcome": "subtitle", "mute_audio": False,
          "subtitle_blur": [{"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.1, "start": 0, "end": 4}]}, "subtitle"),
        ({"outcome": "subtitle", "mute_audio": True, "subtitle_blur": []}, "subtitle"),
        ({"valid_frames": 11}, "coverage"),
    ],
)
def test_inconsistent_ocr_is_rejected(ocr: dict[str, Any], message: str) -> None:
    broken = copy.deepcopy(OCR) | ocr
    with pytest.raises(ValidationError, match=message):
        parse(content_set(ocr=broken))


@pytest.mark.parametrize(
    "region",
    [
        {"x": 0.5, "y": 0.7, "w": 0.6, "h": 0.1},
        {"x": 0.1, "y": 0.95, "w": 0.5, "h": 0.1},
        {"x": 0.1, "y": 0.7, "w": 0.5, "h": 0.1, "start": 1.0},
        {"x": 0.1, "y": 0.7, "w": 0.5, "h": 0.1, "start": 3.0, "end": 2.0},
        {"x": 0.1, "y": 0.7, "w": 0.0, "h": 0.1},
    ],
)
def test_bad_blur_regions_are_rejected(region: dict[str, Any]) -> None:
    ocr = copy.deepcopy(OCR) | {"outcome": "subtitle", "mute_audio": True, "subtitle_blur": [region]}
    with pytest.raises(ValidationError):
        parse(content_set(ocr=ocr))


def test_a_subtitle_verdict_may_keep_a_trim() -> None:
    ocr = copy.deepcopy(OCR) | {
        "outcome": "subtitle",
        "trim_start": 4.0,
        "mute_audio": True,
        "subtitle_blur": [{"x": 0.2, "y": 0.75, "w": 0.6, "h": 0.1, "start": 4.0, "end": 12.0}],
    }
    assert parse(content_set(ocr=ocr)).main.ocr.trim_start == 4.0  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "main",
    [
        {"ocr": None},
        {"video": None},
        {"kind": "images", "video": None, "ocr": None, "images": []},
        {"kind": "card", "video": None, "ocr": None, "card": None},
        {"kind": "images", "ocr": None,
         "images": [VIDEO | {"media_type": "image/jpeg"}]},
        {"kind": "card", "video": None, "ocr": OCR,
         "card": VIDEO | {"media_type": "image/png"}},
    ],
)
def test_the_main_kind_decides_its_media(main: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse(content_set(**main))


def test_footage_stays_empty_in_5a() -> None:
    data = content_set() | {"footage": [{"url": "https://example.com"}]}
    with pytest.raises(ValidationError):
        parse(data)


@pytest.mark.parametrize(
    ("figures", "status"),
    [([], "ok"), ([{"name": "Prabowo", "type": "person"}], "none"),
     ([{"name": "Prabowo", "type": "person"}], "unavailable")],
)
def test_figures_status_matches_the_list(figures: list[Any], status: str) -> None:
    with pytest.raises(ValidationError):
        parse(content_set() | {"figures": figures, "figures_status": status})


def test_at_most_twelve_comments() -> None:
    comment = {"text": "mantap", "author": "a", "likes": 1, "source": "input"}
    with pytest.raises(ValidationError):
        parse(content_set() | {"comments": [comment] * 13})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_models.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.assembly.models'`.

- [ ] **Step 3: Implement the model**

Create `python/src/thoth_control_plane/assembly/models.py`:

```python
"""The Content Set: what a video is made from, typed and checksummed (schema 1).

It holds public post URLs, handles, bounded text, counts, and media locations relative to the
artifact root. Never a CDN URL, a cookie, a proxy, a prompt, or raw model output. The rules of
Scout's content-set lint (`scout/lib/validate.ts`) are validators here, so an invalid Content
Set cannot be built.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from thoth_control_plane.acquisition.models import (
    CommentText,
    MediaType,
    PublishedAt,
    SafeRelativeLocation,
    TikTokHandle,
)
from thoth_control_plane.domain.models import Checksum, OpaqueId, StrictModel

MAX_COMMENTS = 12
MAX_FIGURES = 5
OCR_ANALYZER_VERSION = "subtitle-classifier-v1"
EDGE = 1e-9  # envelope clamping can land a hair past 1.0
Platform = Literal["tiktok", "threads", "instagram", "x", "youtube"]
Seconds = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Extent = Annotated[float, Field(gt=0, le=1)]


class MediaRef(StrictModel):
    location: SafeRelativeLocation
    media_type: MediaType
    checksum: Checksum
    bytes: Annotated[int, Field(ge=1)]
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None
    duration_seconds: Seconds | None = None


class BlurRegion(StrictModel):
    x: Fraction
    y: Fraction
    w: Extent
    h: Extent
    start: Seconds | None = None
    end: Seconds | None = None

    @model_validator(mode="after")
    def inside_and_ordered(self) -> BlurRegion:
        if self.x + self.w > 1 + EDGE or self.y + self.h > 1 + EDGE:
            raise ValueError("a blur region must stay inside the frame")
        if (self.start is None) != (self.end is None):
            raise ValueError("a blur window needs both start and end")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("a blur window must not end before it starts")
        return self


class MainOcr(StrictModel):
    schema_version: Literal[1] = 1
    engine: Literal["rapidocr"] = "rapidocr"
    analyzer_version: Literal["subtitle-classifier-v1"] = OCR_ANALYZER_VERSION
    analyzed_at: AwareDatetime
    requested_frames: Annotated[int, Field(gt=0)]
    valid_frames: Annotated[int, Field(gt=0)]
    outcome: Literal["clean", "cover", "subtitle"]
    trim_start: Seconds
    mute_audio: bool
    subtitle_blur: list[BlurRegion] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def consistent(self) -> MainOcr:
        if self.valid_frames != self.requested_frames:
            raise ValueError("OCR coverage must be complete")
        if self.outcome == "clean" and (self.trim_start or self.mute_audio or self.subtitle_blur):
            raise ValueError("a clean verdict carries no trim, mute, or blur")
        if self.outcome == "cover" and (
            self.trim_start <= 0 or self.mute_audio or self.subtitle_blur
        ):
            raise ValueError("a cover verdict trims and carries no mute or blur")
        if self.outcome == "subtitle" and (not self.mute_audio or not self.subtitle_blur):
            raise ValueError("a subtitle verdict mutes and blurs")
        return self


class Main(StrictModel):
    source: Literal["input", "original"]
    url: HttpUrl
    platform: Platform
    title: Annotated[str, Field(max_length=120)] = ""
    description: Annotated[str, Field(max_length=50_000)] = ""
    owner_handle: TikTokHandle
    published_at: PublishedAt | None = None
    engagement: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    kind: Literal["video", "images", "card"]
    video: MediaRef | None = None
    images: list[MediaRef] = Field(default_factory=list, max_length=20)
    card: MediaRef | None = None
    profile_card: MediaRef | None = None
    ocr: MainOcr | None = None

    @model_validator(mode="after")
    def media_matches_kind(self) -> Main:
        if (self.kind == "video") != (self.video is not None):
            raise ValueError("a video main has exactly one video")
        if (self.kind == "video") != (self.ocr is not None):
            raise ValueError("a video main needs its OCR, and only a video main has one")
        if (self.kind == "images") != bool(self.images):
            raise ValueError("an images main has at least one image")
        if (self.kind == "card") != (self.card is not None):
            raise ValueError("a card main has its post card")
        if self.video is not None and self.video.media_type != "video/mp4":
            raise ValueError("the main video must be video/mp4")
        if any(image.media_type == "video/mp4" for image in self.images):
            raise ValueError("main images must be images")
        return self


class Comment(StrictModel):
    text: CommentText
    author: TikTokHandle
    likes: Annotated[int, Field(ge=0)] = 0
    source: Literal["input", "original"]
    card: MediaRef | None = None  # a real card crop or nothing, never a synthetic render


class Figure(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    type: Literal["person", "organization", "community"]
    role: Annotated[str, Field(max_length=200)] = ""
    description: Annotated[str, Field(max_length=300)] = ""


class ContentSet(StrictModel):
    schema_version: Literal[1] = 1
    workflow_id: OpaqueId
    attribution_verdict: Literal["original", "replaced", "unresolved", "none"]
    main: Main
    comments: list[Comment] = Field(default_factory=list, max_length=MAX_COMMENTS)
    figures: list[Figure] = Field(default_factory=list, max_length=MAX_FIGURES)
    figures_status: Literal["ok", "none", "unavailable"]
    # Always empty in 5a; 5b defines footage items.
    footage: tuple[()] = ()

    @model_validator(mode="after")
    def figures_match_status(self) -> ContentSet:
        if (self.figures_status == "ok") != bool(self.figures):
            raise ValueError("figures_status is ok exactly when figures are present")
        return self
```

- [ ] **Step 4: Run them to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_models.py -p no:warnings`
Expected: PASS. If `tuple[()]` rejects the JSON `[]` in strict mode, change the field to
`footage: Annotated[list[dict[str, str]], Field(max_length=0)] = Field(default_factory=list)`
and the `parsed.footage == ()` assertion to `== []`.

- [ ] **Step 5: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/assembly tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/assembly/models.py python/tests/assembly/test_models.py
git commit -m "feat(assembly): typed ContentSet v1 with the lint as validators"
```

---

### Task 4: The comment merge

**Files:**
- Create: `python/src/thoth_control_plane/assembly/comments.py`
- Create: `python/tests/assembly/test_comments.py`
- Create: `python/tests/assembly/support.py` (report builders shared by later tasks)

**Interfaces:**
- Consumes: `SourceReport`, `ReportComment`, `CardArtifact` (acquisition); `Comment`, `MediaRef`, `MAX_COMMENTS` (Task 3)
- Produces:
  - `merge_comments(sources: Sequence[tuple[Literal["input","original"], SourceReport]]) -> list[Comment]`
  - `card_ref(card: CardArtifact | None) -> MediaRef | None`
  - test helper `tests.assembly.support.report(...)` (signature in Step 1)

- [ ] **Step 1: Write the shared report builder**

Create `python/tests/assembly/support.py`:

```python
"""Source reports for assembly tests, built on the v3 contract fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.models import SourceReport

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tiktok" / "source_report_v3.json").read_text(
        encoding="utf-8"
    )
)
CARD = {
    "media_type": "image/png",
    "bytes": 2048,
    "checksum": "sha256:" + "c" * 64,
    "width": 600,
    "height": 120,
}


def comment(author: str, text: str, likes: int = 0, card: str | None = None) -> dict[str, Any]:
    return {
        "comment_id": f"c{abs(hash((author, text))) % 10**8:08d}",
        "author": author,
        "text": text,
        "likes": likes,
        "card": CARD | {"location": card} if card else None,
    }


def report(
    *,
    workflow_id: str = "wf_a",
    owner: str = "creator",
    url: str = "https://www.tiktok.com/@creator/video/1234567890",
    text: str = "Banjir di Jakarta hari ini",
    media: str = "video",
    duration: float | None = 30.0,
    comments: list[dict[str, Any]] | None = None,
    post_card: bool = False,
    profile_card: bool = False,
) -> SourceReport:
    data = copy.deepcopy(FIXTURE)
    data["workflow_id"] = workflow_id
    data["source"]["canonical_url"] = url
    data["post"].update(owner_handle=owner, text=text, published_at="2026-10-10T08:00:00Z")
    video = data["media"][0]
    video["location"] = f"reports/{workflow_id}/media/video.mp4"
    video["duration_seconds"] = duration
    if media == "images":
        data["media"] = [
            video | {"media_id": f"media_{n}", "kind": "image", "index": n,
                     "location": f"reports/{workflow_id}/media/{n}.jpg",
                     "media_type": "image/jpeg", "bytes": 5000, "duration_seconds": None}
            for n in (1, 2)
        ]
    elif media == "none":
        data["media"] = []
    data["comments"] = comments or []
    data["post_card"] = CARD | {"location": f"reports/{workflow_id}/cards/post.png"} if post_card else None
    data["profile_card"] = (
        CARD | {"location": f"reports/{workflow_id}/cards/profile.png"} if profile_card else None
    )
    return SourceReport.model_validate_json(json.dumps(data))
```

- [ ] **Step 2: Write the failing tests**

Create `python/tests/assembly/test_comments.py`:

```python
"""Comments from every report about the story: filtered, deduplicated, ranked, capped."""

from __future__ import annotations

from tests.assembly.support import comment, report
from thoth_control_plane.assembly.comments import merge_comments


def test_ranks_by_likes_and_caps_at_twelve() -> None:
    many = [comment(f"user{n}", f"komentar ke {n}", likes=n) for n in range(20)]

    merged = merge_comments([("input", report(comments=many))])

    assert [c.likes for c in merged] == list(range(19, 7, -1))


def test_drops_empty_sticker_and_link_comments() -> None:
    noisy = [
        comment("a", "[Sticker]", 99),
        comment("b", "[ stiker ]", 98),
        comment("c", "https://kliksumut.com | MEDAN berita", 97),
        comment("d", "beneran ini?", 1),
    ]

    assert [c.author for c in merge_comments([("input", report(comments=noisy))])] == ["d"]


def test_deduplicates_across_reports_and_keeps_the_first_source() -> None:
    original = report(comments=[comment("Budi", "Kasihan warganya", 5)])
    repost = report(
        workflow_id="wf_b",
        comments=[comment("budi", "kasihan warganya ", 50), comment("sari", "semoga cepat surut", 2)],
    )

    merged = merge_comments([("original", original), ("input", repost)])

    assert [(c.author, c.source, c.likes) for c in merged] == [
        ("Budi", "original", 5),
        ("sari", "input", 2),
    ]


def test_ties_keep_source_order() -> None:
    tied = [comment("a", "satu", 3), comment("b", "dua", 3), comment("c", "tiga", 3)]

    assert [c.author for c in merge_comments([("input", report(comments=tied))])] == ["a", "b", "c"]


def test_keeps_only_real_cards() -> None:
    with_card = comment("a", "ada kartunya", 2, card="reports/wf_a/cards/comment-1.png")
    without = comment("b", "tanpa kartu", 1)

    merged = merge_comments([("input", report(comments=[with_card, without]))])

    assert str(merged[0].card.location) == "reports/wf_a/cards/comment-1.png"  # type: ignore[union-attr]
    assert merged[1].card is None
```

- [ ] **Step 3: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_comments.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.assembly.comments'`.

- [ ] **Step 4: Implement the merge**

Create `python/src/thoth_control_plane/assembly/comments.py`:

```python
"""Audience comments for the video: a port of Scout's multi-source merge.

Sources come in priority order (the main's own post first). Sticker-only and link-first
comments carry nothing for narration and are dropped; the dedupe key is the author plus the
first 60 characters, both lowercased (`dedupeKeyComments` in `scout/lib/comment_engine.ts`).
Ranking is by likes, stable, so ties keep source order.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from thoth_control_plane.acquisition.models import CardArtifact, SourceReport
from thoth_control_plane.assembly.models import MAX_COMMENTS, Comment, MediaRef

STICKER = re.compile(r"^\[\s*sti?c?ker\s*\]$", re.IGNORECASE)
LINK_FIRST = re.compile(r"^https?://", re.IGNORECASE)
Source = Literal["input", "original"]


def card_ref(card: CardArtifact | None) -> MediaRef | None:
    if card is None:
        return None
    return MediaRef(
        location=card.location,
        media_type=card.media_type,
        checksum=card.checksum,
        bytes=card.bytes,
        width=card.width,
        height=card.height,
    )


def merge_comments(sources: Sequence[tuple[Source, SourceReport]]) -> list[Comment]:
    seen: set[str] = set()
    merged: list[Comment] = []
    for source, report in sources:
        for item in report.comments:
            text = item.text.strip()
            if not text or STICKER.match(text) or LINK_FIRST.match(text):
                continue
            key = f"{item.author.lower()}|{text[:60].lower()}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                Comment(
                    text=item.text,
                    author=item.author,
                    likes=item.likes,
                    source=source,
                    card=card_ref(item.card),
                )
            )
    merged.sort(key=lambda comment: -comment.likes)
    return merged[:MAX_COMMENTS]
```

- [ ] **Step 5: Run them to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_comments.py -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/assembly tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/assembly/comments.py python/tests/assembly/test_comments.py python/tests/assembly/support.py
git commit -m "feat(assembly): merge comments from the main and the repost"
```

---

### Task 5: Figures: prompt, normalization, and the OpenRouter adapter

**Files:**
- Create: `python/src/thoth_control_plane/assembly/figures.py`
- Create: `python/src/thoth_control_plane/assembly/adapters/__init__.py`
- Create: `python/src/thoth_control_plane/assembly/adapters/figures.py`
- Create: `python/tests/assembly/test_figures.py`

**Interfaces:**
- Consumes: `Figure`, `MAX_FIGURES` (Task 3)
- Produces:
  - `FigureItem`, `FigureAnswer` (Pydantic `BaseModel`, lenient: model output)
  - `figure_prompt(title: str, description: str, headline: str) -> str | None`
  - `normalize_figures(answer: FigureAnswer) -> list[Figure]`
  - `AgnoFigureModel(api_key: str, model: str, *, base_url: str = OPENROUTER_BASE_URL)` with `async read(prompt: str) -> FigureAnswer | None`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/assembly/test_figures.py`:

```python
"""Figures: who the post is about, or nothing; the model only proposes, code normalizes."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from thoth_control_plane.assembly.figures import (
    FigureAnswer,
    figure_prompt,
    normalize_figures,
)


def test_no_text_means_no_prompt() -> None:
    assert figure_prompt("", "  ", "") is None


def test_prompt_carries_bounded_text() -> None:
    prompt = figure_prompt("Judul", "d" * 900, "HEADLINE")

    assert prompt is not None
    assert "[TITLE]: Judul" in prompt and "[HEADLINE]: HEADLINE" in prompt
    assert "d" * 600 in prompt and "d" * 601 not in prompt


def test_normalization_trims_defaults_and_caps() -> None:
    answer = FigureAnswer.model_validate(
        {
            "figures": [
                {"name": "  Prabowo Subianto ", "type": "Person", "role": "Presiden"},
                {"name": "", "type": "person"},
                {"name": "Persija", "type": "club"},
                *({"name": f"Tokoh {n}", "type": "person"} for n in range(6)),
            ]
        }
    )

    figures = normalize_figures(answer)

    assert [(f.name, f.type) for f in figures[:2]] == [
        ("Prabowo Subianto", "person"),
        ("Persija", "person"),
    ]
    assert len(figures) == 5


@pytest.mark.asyncio
@respx.mock
async def test_adapter_reads_structured_figures_and_degrades_to_none() -> None:
    pytest.importorskip("openai")
    from thoth_control_plane.assembly.adapters.figures import (
        OPENROUTER_BASE_URL,
        AgnoFigureModel,
    )

    route = respx.post(f"{OPENROUTER_BASE_URL}/chat/completions")
    model = AgnoFigureModel("synthetic-key", "deepseek/deepseek-v4-flash-0731")
    content = json.dumps({"figures": [{"name": "Anies Baswedan", "type": "person"}]})
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    )

    answer = await model.read("prompt")

    assert answer is not None and answer.figures[0].name == "Anies Baswedan"
    assert "deepseek/deepseek-v4-flash-0731" in route.calls.last.request.content.decode()
    route.mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await model.read("prompt") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_figures.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the prompt and normalization**

Create `python/src/thoth_control_plane/assembly/figures.py`:

```python
"""Who the post is about: a port of Scout's `extract_figures` prompt and normalization.

The model proposes names and types; code trims, drops empty names, maps an unknown type to
`person` (as Scout does), and keeps at most five.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from thoth_control_plane.assembly.models import MAX_FIGURES, Figure

TYPES = ("person", "organization", "community")
PROMPT = """From the topic text below, identify the MAIN FIGURES being discussed: a specific,
publicly known PERSON, ORGANIZATION, or COMMUNITY.

RULES:
- Only those that are truly the subject of the discussion, not something mentioned in passing,
  a location, or a brand seen in the footage.
- Do NOT include the uploading or curating account (for example a reels or news account) unless
  it is the subject.
- If there is no specific figure, organization, or community (for example a story about an
  ordinary anonymous person), return an empty list.
- "type" is one of: person | organization | community.

TEXT:
[TITLE]: {title}
[DESCRIPTION]: {description}
[HEADLINE]: {headline}

Answer in JSON: {{"figures": [{{"name": "", "type": "", "role": "short title or role",
"description": "one sentence of context"}}]}}"""


class FigureItem(BaseModel):
    name: str = ""
    type: str = ""
    role: str = ""
    description: str = ""


class FigureAnswer(BaseModel):
    figures: list[FigureItem] = Field(default_factory=list)


def figure_prompt(title: str, description: str, headline: str) -> str | None:
    title, description, headline = title.strip(), description.strip(), headline.strip()
    if not (title or description or headline):
        return None
    return PROMPT.format(
        title=title[:200] or "(empty)",
        description=description[:600] or "(empty)",
        headline=headline[:200] or "(empty)",
    )


def normalize_figures(answer: FigureAnswer) -> list[Figure]:
    figures: list[Figure] = []
    for item in answer.figures:
        name = item.name.strip()[:120]
        if not name:
            continue
        kind = item.type.strip().lower()
        figures.append(
            Figure(
                name=name,
                type=kind if kind in TYPES else "person",  # type: ignore[arg-type]
                role=item.role.strip()[:200],
                description=item.description.strip()[:300],
            )
        )
        if len(figures) == MAX_FIGURES:
            break
    return figures
```

- [ ] **Step 4: Implement the adapter**

Create `python/src/thoth_control_plane/assembly/adapters/__init__.py`:

```python
"""Adapters for content assembly's ports."""
```

Create `python/src/thoth_control_plane/assembly/adapters/figures.py`:

```python
"""Figures through Agno over OpenRouter's OpenAI-compatible endpoint (structured output)."""

from __future__ import annotations

import logging

from thoth_control_plane.assembly.figures import FigureAnswer

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0


class AgnoFigureModel:
    def __init__(self, api_key: str, model: str, *, base_url: str = OPENROUTER_BASE_URL) -> None:
        self._key = api_key
        self._model = model
        self._base_url = base_url

    async def read(self, prompt: str) -> FigureAnswer | None:
        from agno.agent import Agent
        from agno.models.openai.like import OpenAILike

        agent = Agent(
            model=OpenAILike(
                id=self._model,
                api_key=self._key,
                base_url=self._base_url,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
                temperature=0.0,
            ),
            output_schema=FigureAnswer,
            use_json_mode=True,
            telemetry=False,
        )
        try:
            run = await agent.arun(input=prompt)
        except Exception:
            logger.warning("figures unavailable; the content set continues without them")
            return None
        return run.content if isinstance(run.content, FigureAnswer) else None
```

- [ ] **Step 5: Run them to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_figures.py -p no:warnings`
Expected: PASS. If Agno logs the 500 at ERROR and returns a run instead of raising, the
`isinstance` check already turns it into `None`; keep the test.

- [ ] **Step 6: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/assembly tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/assembly python/tests/assembly/test_figures.py
git commit -m "feat(assembly): figures prompt and OpenRouter adapter"
```

---

### Task 6: Main OCR analysis

**Files:**
- Create: `python/src/thoth_control_plane/assembly/ports.py`
- Create: `python/src/thoth_control_plane/assembly/ocr.py`
- Create: `python/tests/assembly/test_ocr.py`

**Interfaces:**
- Consumes: `build_sample_times`, `classify_ocr_frames`, `OcrBox`, `OcrFrame` (Task 2);
  `MainOcr`, `BlurRegion` (Task 3); `Frame` (attribution ports); `TextBox` with `left`/`right`,
  `FrameError`, `ToolMissing`, `DurationError` (Task 1)
- Produces:
  - `assembly.ports`: `FrameSampler` (`async frame_at(video, second, *, width) -> Frame`),
    `DurationProbe` (`async duration(video) -> float`), `TextReader` (re-export of the
    attribution protocol), `FigureModel` (`async read(prompt) -> FigureAnswer | None`),
    `AssemblyError(code)`
  - `assembly.ocr`: `FRAME_WIDTH = 720`, `analyze_main_ocr(video: Path, duration: float | None, *, frames: FrameSampler, probe: DurationProbe, text: TextReader, max_frames: int, now: datetime) -> MainOcr`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/assembly/test_ocr.py`:

```python
"""Main OCR: complete coverage or an explicit failure; tools missing are never media failures."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import AssemblyError

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
VIDEO = Path("main.mp4")


class Frames:
    """Frames encode their second; `broken` seconds fail, `missing` means no ffmpeg."""

    def __init__(self, broken: set[float] = frozenset(), missing: bool = False) -> None:
        self.broken, self.missing, self.calls = broken, missing, []

    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        self.calls.append((second, width))
        if self.missing:
            raise ToolMissing("ffmpeg_missing")
        if second in self.broken:
            raise FrameError("ffmpeg_failed")
        return Frame(second, f"{second}".encode())


class Probe:
    def __init__(self, value: float | Exception) -> None:
        self.value = value

    async def duration(self, video: Path) -> float:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Text:
    """A headline on the first two seconds, a changing caption afterwards."""

    async def read(self, frame: Frame) -> list[TextBox]:
        second = float(frame.jpeg.decode())
        if second <= 2:
            return [TextBox("BANJIR BESAR JAKARTA", 0.3, 0.36, 0.08, 0.92)]
        return [TextBox(f"kata {second}", 0.75, 0.8, 0.2, 0.8)]


def run(frames: Frames, duration: float | None = 30.0, probe: Probe | None = None):
    return asyncio.run(
        analyze_main_ocr(
            VIDEO, duration, frames=frames, probe=probe or Probe(30.0), text=Text(),
            max_frames=12, now=NOW,
        )
    )


def test_a_headline_then_captions_is_a_subtitle_verdict_with_a_trim() -> None:
    ocr = run(Frames())

    assert (ocr.requested_frames, ocr.valid_frames) == (12, 12)
    assert ocr.outcome == "subtitle" and ocr.mute_audio
    assert ocr.trim_start == 2.5
    assert ocr.analyzed_at == NOW and ocr.engine == "rapidocr"


def test_frames_are_720_wide() -> None:
    frames = Frames()
    run(frames)
    assert {width for _, width in frames.calls} == {720}


def test_a_failed_sample_recovers_at_an_earlier_second() -> None:
    frames = Frames(broken={1.0})

    ocr = run(frames)

    assert ocr.valid_frames == 12
    assert [second for second, _ in frames.calls[:4]] == [0.5, 1.0, 1.0, 0.75]


def test_one_lost_frame_fails_coverage() -> None:
    # Sample 4.0 recovers at 3.75; sample 5.0 then tries 5.0, 4.75, 4.5, 4.0, all unreadable.
    with pytest.raises(AssemblyError) as raised:
        run(Frames(broken={5.0, 4.75, 4.5, 4.0}))
    assert raised.value.code == "incomplete_frame_coverage"


def test_missing_ffmpeg_is_its_own_code() -> None:
    with pytest.raises(AssemblyError) as raised:
        run(Frames(missing=True))
    assert raised.value.code == "ffmpeg_missing"


def test_duration_comes_from_the_probe_when_the_report_has_none() -> None:
    assert run(Frames(), duration=None, probe=Probe(30.0)).requested_frames == 12


@pytest.mark.parametrize(
    ("error", "code"),
    [(ToolMissing("ffprobe_missing"), "ffprobe_missing"),
     (DurationError("duration_probe_failed"), "duration_probe_failed")],
)
def test_probe_failures_keep_their_code(error: Exception, code: str) -> None:
    with pytest.raises(AssemblyError) as raised:
        run(Frames(), duration=None, probe=Probe(error))
    assert raised.value.code == code


def test_an_ocr_crash_is_a_lost_frame() -> None:
    class Crashing(Text):
        async def read(self, frame: Frame) -> list[TextBox]:
            raise RuntimeError("onnx")

    with pytest.raises(AssemblyError) as raised:
        asyncio.run(
            analyze_main_ocr(
                VIDEO, 30.0, frames=Frames(), probe=Probe(30.0), text=Crashing(),
                max_frames=12, now=NOW,
            )
        )
    assert raised.value.code == "incomplete_frame_coverage"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_ocr.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.assembly.ocr'`.

- [ ] **Step 3: Implement the ports**

Create `python/src/thoth_control_plane/assembly/ports.py`:

```python
"""What content assembly needs from the outside world; adapters implement it."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from thoth_control_plane.assembly.figures import FigureAnswer
from thoth_control_plane.attribution.ports import Frame, TextReader

__all__ = ["AssemblyError", "DurationProbe", "FigureModel", "FrameSampler", "TextReader"]


class AssemblyError(Exception):
    """A required part of the Content Set failed; `code` is one of `ASSEMBLY_REASONS`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FrameSampler(Protocol):
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame: ...


class DurationProbe(Protocol):
    async def duration(self, video: Path) -> float: ...


class FigureModel(Protocol):
    async def read(self, prompt: str) -> FigureAnswer | None: ...
```

- [ ] **Step 4: Implement the analysis**

Create `python/src/thoth_control_plane/assembly/ocr.py`:

```python
"""Final OCR of a video main: Scout's sampling and coverage rule over local RapidOCR boxes.

Only complete coverage may produce a verdict: a frame that cannot be read is unknown, never
clean. A missing ffmpeg or ffprobe keeps its own code (operator, 2026-10-11).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from thoth_control_plane.assembly.models import BlurRegion, MainOcr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    DurationProbe,
    FrameSampler,
    TextReader,
)
from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    build_sample_times,
    classify_ocr_frames,
)
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.ports import Frame

logger = logging.getLogger(__name__)

FRAME_WIDTH = 720  # RapidOCR's detector scales the short side to 736 anyway
RECOVERY_OFFSETS = (0.0, 0.25, 0.5, 1.0)
EXTRACTION_ATTEMPTS = 2


def recovery_seconds(requested: float, previous: float | None) -> list[float]:
    """Scout's `frameRecoveryTimes`: step back, never behind the previous sample."""
    seconds: list[float] = []
    for offset in RECOVERY_OFFSETS:
        second = round(max(0.0, requested - offset), 6)
        if second not in seconds and (previous is None or second > previous):
            seconds.append(second)
    return seconds


async def _frame(
    frames: FrameSampler, video: Path, requested: float, previous: float | None
) -> Frame | None:
    for second in recovery_seconds(requested, previous):
        for _ in range(EXTRACTION_ATTEMPTS):
            try:
                return await frames.frame_at(video, second, width=FRAME_WIDTH)
            except ToolMissing as missing:
                raise AssemblyError(missing.code) from None
            except FrameError:
                continue
    return None


async def analyze_main_ocr(
    video: Path,
    duration: float | None,
    *,
    frames: FrameSampler,
    probe: DurationProbe,
    text: TextReader,
    max_frames: int,
    now: datetime,
) -> MainOcr:
    if not duration or duration <= 0:
        try:
            duration = await probe.duration(video)
        except ToolMissing as missing:
            raise AssemblyError(missing.code) from None
        except (DurationError, FrameError):
            raise AssemblyError("duration_probe_failed") from None

    requested = build_sample_times(duration, max_frames)
    read: list[OcrFrame] = []
    for second in requested:
        previous = read[-1].t if read else None
        frame = await _frame(frames, video, second, previous)
        if frame is None:
            read.append(OcrFrame(second, error="frame_extract"))
            continue
        try:
            boxes = await text.read(frame)
        except Exception:
            read.append(OcrFrame(frame.second, error="ocr_failed"))
            continue
        read.append(
            OcrFrame(
                frame.second,
                tuple(OcrBox(b.text, b.left, b.top, b.right, b.bottom) for b in boxes),
            )
        )

    valid = sum(1 for frame in read if frame.error is None)
    if valid != len(requested):
        logger.warning("main OCR incomplete: %d of %d frames", valid, len(requested))
        raise AssemblyError("incomplete_frame_coverage")

    verdict = classify_ocr_frames(read, duration)
    return MainOcr(
        analyzed_at=now,
        requested_frames=len(requested),
        valid_frames=valid,
        outcome=verdict.outcome,
        trim_start=verdict.trim_start,
        mute_audio=verdict.mute_audio,
        subtitle_blur=[
            BlurRegion(x=r.x, y=r.y, w=r.w, h=r.h, start=r.start, end=r.end)
            for r in verdict.subtitle_blur
        ],
    )
```

Check `test_a_failed_sample_recovers_at_an_earlier_second` against this code: sample 1.0 fails
twice at 1.0 (two attempts), then 0.75 succeeds (0.5 is excluded because it is not after the
previous sample 0.5). The expected calls are `[0.5, 1.0, 1.0, 0.75]`.

- [ ] **Step 5: Run them to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_ocr.py -p no:warnings`
Expected: PASS. In `test_one_lost_frame_fails_coverage`, sample 4.0 is broken and recovers at
3.75 (3.0 is not after the previous sample 3.0); sample 5.0 then tries 5.0, 4.75, 4.5, and 4.0
(after 3.75), all broken, so coverage is 11 of 12.

- [ ] **Step 6: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/assembly tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/assembly python/tests/assembly/test_ocr.py
git commit -m "feat(assembly): final main OCR with Scout's coverage rule"
```

---

### Task 7: The `ContentAssembler` service

**Files:**
- Create: `python/src/thoth_control_plane/assembly/service.py`
- Create: `python/tests/assembly/test_service.py`

**Interfaces:**
- Consumes: Tasks 3–6; `SourceReport`, `MaterializedMedia` (acquisition); `SourceAttribution` (attribution models)
- Produces:
  - `AssemblyPorts(frames: FrameSampler, probe: DurationProbe, text: TextReader, figures: FigureModel | None)` (frozen dataclass)
  - `AssemblyInputs(workflow_id: str, report: SourceReport, attribution: SourceAttribution | None, original: SourceReport | None, artifact_root: Path)` (frozen dataclass)
  - `ContentAssembler(ports: AssemblyPorts, *, max_frames: int = 12, clock: Callable[[], datetime] = ...)` with `async build(inputs: AssemblyInputs) -> ContentSet`, raising `AssemblyError`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/assembly/test_service.py`:

```python
"""The assembler end to end over fake ports."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.assembly.support import comment, report
from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.assembly.figures import FigureAnswer
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs, AssemblyPorts, ContentAssembler
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.attribution.ports import Frame

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
ORIGINAL_URL = "https://www.tiktok.com/@source/video/9999999999"


class Frames:
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        assert video.is_file()
        return Frame(second, b"jpeg")


class Probe:
    async def duration(self, video: Path) -> float:
        return 30.0


class Clean:
    async def read(self, frame: Frame) -> list[TextBox]:
        return []


class Figures:
    def __init__(self, answer: FigureAnswer | None | Exception = None) -> None:
        self.answer, self.prompts = answer, []

    async def read(self, prompt: str) -> FigureAnswer | None:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def attribution(verdict: str, headline: str | None = None) -> SourceAttribution:
    data: dict[str, Any] = {
        "workflow_id": "wf_a",
        "input": {"platform": "tiktok", "canonical_url": "https://www.tiktok.com/@creator/video/1234567890",
                  "owner_handle": "creator"},
        "verdict": verdict,
        "evidence": [{"kind": "cover_vision", "detail": f"headline: {headline}"}] if headline else [],
    }
    if verdict == "replaced":
        data["source"] = {"platform": "tiktok", "canonical_url": ORIGINAL_URL, "owner_handle": "source"}
    return SourceAttribution.model_validate_json(json.dumps(data))


def touch(root: Path, *reports: SourceReport) -> None:
    for item in reports:
        for media in item.media:
            path = root / media.location
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")


def build(
    tmp_path: Path,
    main: SourceReport,
    *,
    verdict: str | None = None,
    original: SourceReport | None = None,
    figures: Figures | None = None,
    headline: str | None = None,
):
    touch(tmp_path, main, *([original] if original else []))
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Clean(), figures=figures),
        clock=lambda: NOW,
    )
    return asyncio.run(
        assembler.build(
            AssemblyInputs(
                workflow_id="wf_a",
                report=main,
                attribution=attribution(verdict, headline) if verdict else None,
                original=original,
                artifact_root=tmp_path,
            )
        )
    )


def test_an_original_post_is_its_own_main(tmp_path: Path) -> None:
    content = build(tmp_path, report(profile_card=True), verdict="original")

    assert content.attribution_verdict == "original"
    assert content.main.source == "input" and content.main.kind == "video"
    assert content.main.title == "Banjir di Jakarta hari ini"
    assert content.main.ocr is not None and content.main.ocr.outcome == "clean"
    assert content.main.profile_card is not None
    assert content.figures_status == "unavailable"


def test_without_attribution_the_verdict_is_none(tmp_path: Path) -> None:
    assert build(tmp_path, report()).attribution_verdict == "none"


def test_replaced_main_is_the_original_with_both_discussions(tmp_path: Path) -> None:
    repost = report(comments=[comment("a", "ini repost", 9)])
    original = report(
        workflow_id="wf_a-c1", owner="source", url=ORIGINAL_URL,
        comments=[comment("b", "video asli", 3)],
    )

    content = build(tmp_path, repost, verdict="replaced", original=original)

    assert content.main.source == "original"
    assert str(content.main.url) == ORIGINAL_URL
    assert [(c.author, c.source) for c in content.comments] == [("a", "input"), ("b", "original")]


def test_replaced_without_the_original_report_fails(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError) as raised:
        build(tmp_path, report(), verdict="replaced")
    assert raised.value.code == "original_report_missing"


def test_an_images_post_needs_no_ocr(tmp_path: Path) -> None:
    content = build(tmp_path, report(media="images"))

    assert content.main.kind == "images" and len(content.main.images) == 2
    assert content.main.ocr is None


def test_text_post_uses_its_card(tmp_path: Path) -> None:
    content = build(tmp_path, report(media="none", post_card=True))

    assert content.main.kind == "card" and content.main.card is not None


def test_text_post_without_card_fails(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError) as raised:
        build(tmp_path, report(media="none"))
    assert raised.value.code == "main_media_missing"


def test_a_missing_video_file_fails(tmp_path: Path) -> None:
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Clean(), figures=None)
    )
    with pytest.raises(AssemblyError) as raised:
        asyncio.run(
            assembler.build(
                AssemblyInputs("wf_a", report(), None, None, tmp_path)  # no file written
            )
        )
    assert raised.value.code == "main_media_missing"


def test_figures_use_title_description_and_the_cover_headline(tmp_path: Path) -> None:
    figures = Figures(FigureAnswer.model_validate({"figures": [{"name": "Pramono Anung", "type": "person"}]}))

    content = build(tmp_path, report(), verdict="original", figures=figures, headline="BANJIR LAGI")

    assert content.figures_status == "ok" and content.figures[0].name == "Pramono Anung"
    assert "[HEADLINE]: BANJIR LAGI" in figures.prompts[0]


@pytest.mark.parametrize(
    ("answer", "status"),
    [(FigureAnswer(), "none"), (None, "unavailable"), (RuntimeError("down"), "unavailable")],
)
def test_figure_failures_never_fail_the_set(
    tmp_path: Path, answer: Any, status: str
) -> None:
    assert build(tmp_path, report(), figures=Figures(answer)).figures_status == status
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly/test_service.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.assembly.service'`.

- [ ] **Step 3: Implement the service**

Create `python/src/thoth_control_plane/assembly/service.py`:

```python
"""Build the Content Set of one workflow: main and its final OCR, comments, figures.

The main is the original when attribution replaced the post, else the post itself. Figures run
alongside the OCR (they never read it). Comments and figures degrade; the main, its OCR, and
validation are required and raise `AssemblyError` with a reason code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from thoth_control_plane.acquisition.models import MaterializedMedia, SourceReport
from thoth_control_plane.assembly.comments import card_ref, merge_comments
from thoth_control_plane.assembly.figures import figure_prompt, normalize_figures
from thoth_control_plane.assembly.models import ContentSet, Figure, Main, MainOcr, MediaRef
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    DurationProbe,
    FigureModel,
    FrameSampler,
    TextReader,
)
from thoth_control_plane.attribution.models import SourceAttribution

logger = logging.getLogger(__name__)
HEADLINE_PREFIX = "headline: "
FiguresStatus = Literal["ok", "none", "unavailable"]


@dataclass(frozen=True)
class AssemblyPorts:
    frames: FrameSampler
    probe: DurationProbe
    text: TextReader
    figures: FigureModel | None = None


@dataclass(frozen=True)
class AssemblyInputs:
    workflow_id: str
    report: SourceReport
    attribution: SourceAttribution | None
    original: SourceReport | None
    artifact_root: Path


def _media_ref(media: MaterializedMedia) -> MediaRef:
    return MediaRef(
        location=media.location,
        media_type=media.media_type,
        checksum=media.checksum,
        bytes=media.bytes,
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
    )


def _main_fields(report: SourceReport, source: Literal["input", "original"]) -> dict[str, Any]:
    text = report.post.text.strip()
    fields: dict[str, Any] = {
        "source": source,
        "url": report.source.canonical_url,
        "platform": report.source.platform,
        "title": text[:120],
        "description": text,
        "owner_handle": report.post.owner_handle,
        "published_at": report.post.published_at,
        "engagement": dict(report.post.engagement),
        "profile_card": card_ref(report.profile_card),
    }
    videos = [media for media in report.media if media.kind == "video"]
    images = [media for media in report.media if media.kind == "image"]
    if videos:
        fields.update(kind="video", video=_media_ref(videos[0]))
    elif images:
        fields.update(kind="images", images=[_media_ref(media) for media in images])
    elif report.post_card is not None:
        fields.update(kind="card", card=card_ref(report.post_card))
    else:
        raise AssemblyError("main_media_missing")
    return fields


def _headline(attribution: SourceAttribution | None) -> str:
    for item in attribution.evidence if attribution is not None else []:
        if item.kind == "cover_vision" and item.detail.startswith(HEADLINE_PREFIX):
            return item.detail[len(HEADLINE_PREFIX) :]
    return ""


def _video_path(root: Path, video: MediaRef) -> Path:
    base = root.resolve()
    path = (root / video.location).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise AssemblyError("main_media_missing")
    return path


class ContentAssembler:
    def __init__(
        self,
        ports: AssemblyPorts,
        *,
        max_frames: int = 12,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ports = ports
        self._max_frames = max_frames
        self._clock = clock

    async def build(self, inputs: AssemblyInputs) -> ContentSet:
        verdict = inputs.attribution.verdict if inputs.attribution is not None else "none"
        if verdict == "replaced":
            if inputs.original is None:
                raise AssemblyError("original_report_missing")
            main_report, source = inputs.original, "original"
            sources = [("original", inputs.original), ("input", inputs.report)]
        else:
            main_report, source = inputs.report, "input"
            sources = [("input", inputs.report)]

        fields = _main_fields(main_report, source)  # type: ignore[arg-type]
        figures_task = asyncio.create_task(
            self._figures(fields["title"], fields["description"], _headline(inputs.attribution))
        )
        try:
            ocr: MainOcr | None = None
            if fields["kind"] == "video":
                video: MediaRef = fields["video"]
                ocr = await analyze_main_ocr(
                    _video_path(inputs.artifact_root, video),
                    video.duration_seconds,
                    frames=self._ports.frames,
                    probe=self._ports.probe,
                    text=self._ports.text,
                    max_frames=self._max_frames,
                    now=self._clock(),
                )
        except BaseException:
            figures_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await figures_task
            raise
        figures, status = await figures_task

        try:
            return ContentSet(
                workflow_id=inputs.workflow_id,
                attribution_verdict=verdict,
                main=Main(**fields, ocr=ocr),
                comments=merge_comments(sources),  # type: ignore[arg-type]
                figures=figures,
                figures_status=status,
            )
        except ValidationError:
            logger.warning("content set rejected by its validators")
            raise AssemblyError("content_set_invalid") from None

    async def _figures(
        self, title: str, description: str, headline: str
    ) -> tuple[list[Figure], FiguresStatus]:
        prompt = figure_prompt(title, description, headline)
        if prompt is None:
            return [], "none"
        if self._ports.figures is None:
            return [], "unavailable"
        try:
            answer = await self._ports.figures.read(prompt)
        except Exception:
            logger.warning("figures unavailable; the content set continues without them")
            return [], "unavailable"
        if answer is None:
            return [], "unavailable"
        figures = normalize_figures(answer)
        return figures, "ok" if figures else "none"
```

- [ ] **Step 4: Run them to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/assembly -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/assembly tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/assembly/service.py python/tests/assembly/test_service.py
git commit -m "feat(assembly): ContentAssembler builds and validates the content set"
```

---

### Task 8: The `assemble_content` activity

**Files:**
- Create: `python/src/thoth_control_plane/activities/content_assembly.py`
- Modify: `python/src/thoth_control_plane/activities/__init__.py`
- Create: `python/tests/activities/test_content_assembly.py`

**Interfaces:**
- Consumes: `ContentAssembler`, `AssemblyInputs`, `AssemblyPorts` (Task 7); adapters (Tasks 1, 5); `ArtifactRef`, `SourceProgressEvent` (domain); `Settings`
- Produces:
  - `ContentAssemblyActivityInput(workflow_id: OpaqueId, original_report: str | None = None)`
  - `ContentAssemblyActivityResult(content_set: ArtifactRef | None = None, failure: str | None = None, events: list[SourceProgressEvent] = [])` with exactly one of `content_set` / `failure`
  - `assemble_content` (activity name `"assemble_content"`), `build_content_assembly_activity(settings, *, assembler=None)`
  - `CONTENT_SET_FILE = "content-set.json"`
- Refines spec section 4: a required part that fails returns a typed `failure` code instead of
  raising, so Temporal does not retry a deterministic failure; an unexpected crash still raises
  and is retried once (`maximum_attempts=2`), then ends as `content_assembly_failed`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/activities/test_content_assembly.py`:

```python
"""The activity reads persisted reports, writes the content set atomically, and redacts."""

from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from pathlib import Path

import pytest

from tests.assembly.support import comment, report
from thoth_control_plane.activities.content_assembly import (
    ContentAssemblyActivityInput,
    _run,
)
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs


class FakeAssembler:
    def __init__(self, error: str | None = None) -> None:
        self.error, self.inputs = error, []

    async def build(self, inputs: AssemblyInputs) -> ContentSet:
        self.inputs.append(inputs)
        if self.error:
            raise AssemblyError(self.error)
        return ContentSet.model_validate_json(
            json.dumps(
                {
                    "workflow_id": inputs.workflow_id,
                    "attribution_verdict": "none",
                    "main": {
                        "source": "input",
                        "url": "https://www.tiktok.com/@creator/video/1234567890",
                        "platform": "tiktok",
                        "owner_handle": "creator",
                        "kind": "card",
                        "card": {"location": "reports/wf_a/cards/post.png", "media_type": "image/png",
                                 "checksum": "sha256:" + "c" * 64, "bytes": 2048},
                    },
                    "comments": [{"text": "rahasia komentar", "author": "a", "source": "input"}],
                    "figures_status": "none",
                }
            )
        )


def persist(root: Path, workflow_id: str = "wf_a", **kwargs) -> None:
    folder = root / "reports" / workflow_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source-report.json").write_text(
        report(workflow_id=workflow_id, **kwargs).model_dump_json(), encoding="utf-8"
    )


def run(root: Path, assembler: FakeAssembler, **kwargs):
    return asyncio.run(_run(ContentAssemblyActivityInput(workflow_id="wf_a", **kwargs), root, assembler))


def test_writes_the_content_set_with_a_matching_checksum(tmp_path: Path) -> None:
    persist(tmp_path)

    result = run(tmp_path, FakeAssembler())

    written = (tmp_path / "reports" / "wf_a" / "content-set.json").read_bytes()
    assert result.content_set is not None and result.failure is None
    assert result.content_set.location == "reports/wf_a/content-set.json"
    assert result.content_set.checksum == "sha256:" + sha256(written).hexdigest()
    assert result.content_set.kind == "content_set"
    assert not list((tmp_path / "reports" / "wf_a").glob("*.part"))
    payload = result.events[0].payload
    assert payload["stage"] == "assembly" and payload["status"] == "succeeded"
    assert payload["comment_count"] == 1 and payload["ocr_outcome"] == "none"


def test_a_second_run_replaces_the_content_set(tmp_path: Path) -> None:
    persist(tmp_path, comments=[comment("a", "satu", 1)])
    run(tmp_path, FakeAssembler())
    second = run(tmp_path, FakeAssembler())

    stored = ContentSet.model_validate_json(
        (tmp_path / "reports" / "wf_a" / "content-set.json").read_bytes()
    )
    assert len(stored.comments) == 1
    assert second.content_set is not None


def test_no_report_is_a_failure(tmp_path: Path) -> None:
    result = run(tmp_path, FakeAssembler())

    assert result.failure == "source_report_missing" and result.content_set is None
    assert result.events[0].payload["reason"] == "source_report_missing"


def test_replaced_reads_the_original_report_it_is_given(tmp_path: Path) -> None:
    persist(tmp_path)
    persist(tmp_path, workflow_id="wf_a-c1", owner="source")
    (tmp_path / "reports" / "wf_a" / "source-attribution.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workflow_id": "wf_a",
                "input": {"platform": "tiktok", "canonical_url": "https://www.tiktok.com/@creator/video/1234567890", "owner_handle": "creator"},
                "verdict": "replaced",
                "source": {"platform": "tiktok", "canonical_url": "https://www.tiktok.com/@source/video/1", "owner_handle": "source"},
            }
        ),
        encoding="utf-8",
    )
    assembler = FakeAssembler()

    run(tmp_path, assembler, original_report="reports/wf_a-c1/source-report.json")

    assert assembler.inputs[0].original is not None
    assert assembler.inputs[0].original.post.owner_handle == "source"


@pytest.mark.parametrize("location", ["../etc/passwd", "/abs/source-report.json", "reports/x/other.json"])
def test_an_unsafe_original_location_is_ignored(tmp_path: Path, location: str) -> None:
    persist(tmp_path)
    assembler = FakeAssembler()

    run(tmp_path, assembler, original_report=location)

    assert assembler.inputs[0].original is None


def test_assembly_failures_keep_their_code_and_write_nothing(tmp_path: Path) -> None:
    persist(tmp_path)

    result = run(tmp_path, FakeAssembler(error="incomplete_frame_coverage"))

    assert result.failure == "incomplete_frame_coverage"
    assert not (tmp_path / "reports" / "wf_a" / "content-set.json").exists()


def test_results_carry_no_text(tmp_path: Path) -> None:
    persist(tmp_path)

    result = run(tmp_path, FakeAssembler())

    assert "rahasia" not in result.model_dump_json()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities/test_content_assembly.py -p no:warnings`
Expected: FAIL with `ModuleNotFoundError: No module named 'thoth_control_plane.activities.content_assembly'`.

- [ ] **Step 3: Implement the activity**

Create `python/src/thoth_control_plane/activities/content_assembly.py`:

```python
"""The `assemble_content` activity: build the Content Set from the persisted reports.

It reads `reports/<workflow_id>/source-report.json`, the attribution beside it when present,
and the original's report at the location the workflow passes, runs the assembler, and writes
`reports/<workflow_id>/content-set.json` atomically. A required part that fails returns its
reason code; nothing is written. Only IDs, codes, counts, and elapsed milliseconds reach
Temporal history.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import Field, model_validator
from temporalio import activity

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.assembly.models import ContentSet
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import ArtifactRef
from thoth_control_plane.domain.models import OpaqueId, SourceProgressEvent, StrictModel

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30.0
CONTENT_SET_FILE = "content-set.json"
REPORT_FILE = "source-report.json"
ATTRIBUTION_FILE = "source-attribution.json"
ORIGINAL_LOCATION = re.compile(r"^reports/[A-Za-z][A-Za-z0-9_-]{0,127}/source-report\.json$")
ReasonCode = str


class ContentAssemblyActivityInput(StrictModel):
    workflow_id: OpaqueId
    # Where attribute_source wrote the original's report; set only when it found one.
    original_report: str | None = None


class ContentAssemblyActivityResult(StrictModel):
    content_set: ArtifactRef | None = None
    failure: ReasonCode | None = None
    events: list[SourceProgressEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_outcome(self) -> ContentAssemblyActivityResult:
        if (self.content_set is None) == (self.failure is None):
            raise ValueError("an assembly result holds a content set or a failure")
        return self


class Assembler(Protocol):
    async def build(self, inputs: AssemblyInputs) -> ContentSet: ...


def _write(path: Path, content: bytes) -> None:
    part = path.with_name(path.name + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        part.write_bytes(content)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def _original(root: Path, location: str | None) -> SourceReport | None:
    if location is None or not ORIGINAL_LOCATION.fullmatch(location):
        return None
    try:
        return SourceReport.model_validate_json((root / location).read_bytes())
    except (OSError, ValueError):
        return None


def _attribution(path: Path) -> SourceAttribution | None:
    try:
        return SourceAttribution.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


async def _heartbeat() -> None:
    while True:
        if activity.in_activity():
            activity.heartbeat()
        await asyncio.sleep(HEARTBEAT_SECONDS)


def _failed(code: str, started: float) -> ContentAssemblyActivityResult:
    elapsed = int((time.monotonic() - started) * 1000)
    return ContentAssemblyActivityResult(
        failure=code,
        events=[
            SourceProgressEvent(
                kind="stage.failed",
                payload={"stage": "assembly", "status": "failed", "reason": code, "elapsed_ms": elapsed},
            )
        ],
    )


async def _run(
    input_: ContentAssemblyActivityInput, artifact_root: Path, assembler: Assembler
) -> ContentAssemblyActivityResult:
    started = time.monotonic()
    folder = PurePosixPath("reports") / input_.workflow_id
    try:
        report = SourceReport.model_validate_json((artifact_root / folder / REPORT_FILE).read_bytes())
    except (OSError, ValueError):
        logger.warning("content assembly skipped; no stage 3 report for this workflow")
        return _failed("source_report_missing", started)

    inputs = AssemblyInputs(
        workflow_id=input_.workflow_id,
        report=report,
        attribution=_attribution(artifact_root / folder / ATTRIBUTION_FILE),
        original=_original(artifact_root, input_.original_report),
        artifact_root=artifact_root,
    )
    heartbeat = asyncio.create_task(_heartbeat())
    try:
        content_set = await assembler.build(inputs)
    except AssemblyError as error:
        logger.warning("content assembly failed: %s", error.code)
        return _failed(error.code, started)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

    content = content_set.model_dump_json(indent=2).encode("utf-8")
    location = folder / CONTENT_SET_FILE
    try:
        _write(artifact_root / location, content)
    except OSError:
        logger.warning("content set could not be written")
        return _failed("artifact_write_failed", started)
    digest = sha256(content).hexdigest()
    ocr = content_set.main.ocr
    return ContentAssemblyActivityResult(
        content_set=ArtifactRef(
            artifact_id=f"art_content_set_{digest[:20]}",
            kind="content_set",
            label="Content set",
            media_type="application/json",
            location=location.as_posix(),
            checksum=f"sha256:{digest}",
            size_bytes=len(content),
        ),
        events=[
            SourceProgressEvent(
                kind="stage.completed",
                payload={
                    "stage": "assembly",
                    "status": "succeeded",
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "ocr_outcome": ocr.outcome if ocr is not None else "none",
                    "comment_count": len(content_set.comments),
                    "figure_count": len(content_set.figures),
                },
            )
        ],
    )


def build_production_assembler(settings: Settings) -> Assembler:
    from thoth_control_plane.assembly.adapters.figures import AgnoFigureModel
    from thoth_control_plane.assembly.service import AssemblyPorts, ContentAssembler
    from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    openrouter = settings.openrouter_api_key
    return ContentAssembler(
        AssemblyPorts(
            frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
            probe=FfprobeDuration(settings.THOTH_FFPROBE),
            text=RapidOcrReader(angle=False),
            figures=AgnoFigureModel(openrouter, settings.THOTH_FIGURES_MODEL) if openrouter else None,
        ),
        max_frames=settings.THOTH_SUBTITLE_OCR_MAX_FRAMES,
    )


@activity.defn(name="assemble_content")
async def assemble_content(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_content_assembly_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_content_assembly_activity(
    settings: Settings, *, assembler: Assembler | None = None
) -> Callable[[ContentAssemblyActivityInput], Awaitable[ContentAssemblyActivityResult]]:
    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected = assembler or build_production_assembler(settings)

    @activity.defn(name="assemble_content")
    async def configured_content_assembly_activity(
        input_: ContentAssemblyActivityInput,
    ) -> ContentAssemblyActivityResult:
        return await _run(input_, artifact_root, selected)

    return configured_content_assembly_activity
```

In `python/src/thoth_control_plane/activities/__init__.py`, import and export
`ContentAssemblyActivityInput`, `ContentAssemblyActivityResult`, `assemble_content`, and
`build_content_assembly_activity` next to the attribution names, in the same style (add them to
`__all__`).

Check: `thoth_control_plane.activities.content_assembly` must import without the
`acquisition` extra. Its top-level imports are `assembly.models`, `assembly.ports`,
`assembly.service`, which import `assembly.ocr` and `attribution.adapters.frames` (standard
library only) and `assembly.figures` (Pydantic only). `rapidocr` and `agno` load only inside
`build_production_assembler` and the adapters.

- [ ] **Step 4: Run them to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/activities/test_content_assembly.py tests/assembly -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane/activities tests/activities && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane/activities python/tests/activities/test_content_assembly.py
git commit -m "feat(assembly): assemble_content activity writes the content set"
```

---

### Task 9: Workflow, gateway, worker, and compose wiring

**Files:**
- Modify: `python/src/thoth_control_plane/domain/models.py` (`SourceInvestigationWorkflowInput`)
- Modify: `python/src/thoth_control_plane/workflows/source_investigation.py`
- Modify: `python/src/thoth_control_plane/infrastructure/temporal_gateway.py`
- Modify: `python/src/thoth_control_plane/worker.py`
- Modify: `compose.stage1.local.yml` (api and worker environment)
- Modify: `.env.stage1.local.example` (check line endings first)
- Modify: `python/tests/workflows/test_source_investigation.py`
- Modify: `python/tests/test_worker.py`

**Interfaces:**
- Consumes: `assemble_content`, `ContentAssemblyActivityInput`, `ContentAssemblyActivityResult` (Task 8)
- Produces: workflow input `assemble_content: bool = False`; gateway kwarg `assemble_content`;
  `worker.check_media_tools(settings) -> None`; artifact kind `content_set` after the
  attribution artifacts; failure `WorkflowFailure(code="content_assembly_failed", failed_stage="assembly", retryable=True)`

- [ ] **Step 1: Write the failing workflow tests**

Append to `python/tests/workflows/test_source_investigation.py` (after the attribution tests;
add `ContentAssemblyActivityInput`, `ContentAssemblyActivityResult` to the imports from
`thoth_control_plane.activities.content_assembly`):

```python
ASSEMBLY_RELEASE: asyncio.Event | None = None
ASSEMBLY_INPUTS: list[ContentAssemblyActivityInput] = []


@activity.defn(name="assemble_content")
async def fake_assemble(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    ASSEMBLY_INPUTS.append(input_)
    return ContentAssemblyActivityResult.model_validate(
        {
            "content_set": _attribution_artifact(input_.workflow_id, "content_set", "content-set.json"),
            "events": [
                {
                    "kind": "stage.completed",
                    "payload": {"stage": "assembly", "status": "succeeded", "elapsed_ms": 7,
                                "ocr_outcome": "clean", "comment_count": 3, "figure_count": 1},
                }
            ],
        }
    )


@activity.defn(name="assemble_content")
async def failing_assemble(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    return ContentAssemblyActivityResult.model_validate(
        {
            "failure": "incomplete_frame_coverage",
            "events": [
                {"kind": "stage.failed",
                 "payload": {"stage": "assembly", "status": "failed",
                             "reason": "incomplete_frame_coverage"}}
            ],
        }
    )


@activity.defn(name="assemble_content")
async def crashing_assemble(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    raise RuntimeError("assembly detail must not enter history")


@activity.defn(name="assemble_content")
async def blocking_assemble(input_: ContentAssemblyActivityInput) -> ContentAssemblyActivityResult:
    assert ASSEMBLY_RELEASE is not None
    await ASSEMBLY_RELEASE.wait()
    return await fake_assemble(input_)


def _assembled(attribute: bool = True) -> SourceInvestigationWorkflowInput:
    return workflow_input(VALID_IDENTIFY_REQUEST).model_copy(
        update={"attribute_source": attribute, "assemble_content": True}
    )


@pytest.mark.asyncio
async def test_assembly_appends_the_content_set_after_attribution(
    workflow_env: WorkflowEnvironment,
) -> None:
    ASSEMBLY_INPUTS.clear()
    async with Worker(
        workflow_env.client,
        task_queue="test",
        workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute, fake_assemble],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_assembled()],
            id="wf_test_assembly", task_queue="test",
        )

    assert result.status == "succeeded"
    assert [a.kind for a in result.artifacts] == [
        "source_report", "source_attribution", "original_source_report", "content_set",
    ]
    assert ASSEMBLY_INPUTS[-1].original_report == "reports/wf_test_assembly-c1/source-report.json"


@pytest.mark.asyncio
async def test_assembly_runs_without_attribution(workflow_env: WorkflowEnvironment) -> None:
    ASSEMBLY_INPUTS.clear()
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_assemble],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_assembled(attribute=False)],
            id="wf_test_assembly_alone", task_queue="test",
        )

    assert [a.kind for a in result.artifacts] == ["source_report", "content_set"]
    assert ASSEMBLY_INPUTS[-1].original_report is None


@pytest.mark.asyncio
async def test_a_failed_assembly_fails_the_workflow_with_its_reason(
    workflow_env: WorkflowEnvironment,
) -> None:
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute, failing_assemble],
    ):
        handle = await workflow_env.client.start_workflow(
            SourceInvestigationWorkflow.run, args=[_assembled()],
            id="wf_test_assembly_failed", task_queue="test",
        )
        result = await handle.result()
        events = await handle.query(SourceInvestigationWorkflow.source_events)

    assert result.status == "failed"
    assert result.failure is not None
    assert (result.failure.code, result.failure.failed_stage) == ("content_assembly_failed", "assembly")
    assert [a.kind for a in result.artifacts][-1] != "content_set"
    assert any(e.payload.get("reason") == "incomplete_frame_coverage" for e in events)


@pytest.mark.asyncio
async def test_a_crashing_assembly_fails_without_leaking(workflow_env: WorkflowEnvironment) -> None:
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, crashing_assemble],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_assembled(attribute=False)],
            id="wf_test_assembly_crash", task_queue="test",
        )

    assert result.status == "failed" and result.failure.code == "content_assembly_failed"  # type: ignore[union-attr]
    assert "assembly detail" not in str(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_cancel_during_assembly_finishes_as_cancelled(workflow_env: WorkflowEnvironment) -> None:
    global ASSEMBLY_RELEASE
    ASSEMBLY_RELEASE = asyncio.Event()
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, blocking_assemble],
    ):
        handle = await workflow_env.client.start_workflow(
            SourceInvestigationWorkflow.run, args=[_assembled(attribute=False)],
            id="wf_test_assembly_cancel", task_queue="test",
        )
        for _ in range(100):
            events = await handle.query(SourceInvestigationWorkflow.workflow_events)
            if any(event.stage and event.stage.name == "assembly" for event in events):
                break
            await asyncio.sleep(0.01)
        await handle.signal(SourceInvestigationWorkflow.request_cancel)
        await wait_for_status(handle, "cancelled")
        ASSEMBLY_RELEASE.set()


@pytest.mark.asyncio
async def test_the_flag_off_keeps_todays_behavior(workflow_env: WorkflowEnvironment) -> None:
    async with Worker(
        workflow_env.client, task_queue="test", workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_attribute, fake_assemble],
    ):
        result = await workflow_env.client.execute_workflow(
            SourceInvestigationWorkflow.run, args=[_attributed()],
            id="wf_test_assembly_off", task_queue="test",
        )

    assert "content_set" not in [a.kind for a in result.artifacts]


@pytest.mark.asyncio
async def test_the_gateway_requests_assembly_when_enabled(workflow_env: WorkflowEnvironment) -> None:
    async with Worker(
        workflow_env.client, task_queue=TASK_QUEUE, workflows=[SourceInvestigationWorkflow],
        activities=[fake_inspect, fake_assemble],
    ):
        gateway = TemporalWorkflowGateway(workflow_env.client, assemble_content=True)
        summary = await gateway.start(
            VALID_IDENTIFY_REQUEST,
            actor=Actor(actor_id="owner", actor_type="user"),
            idempotency_key="assembly-001",
        )
        result = await workflow_env.client.get_workflow_handle_for(
            SourceInvestigationWorkflow.run, summary.workflow_id
        ).result()

    assert [a.kind for a in result.artifacts][-1] == "content_set"
```

`fake_attribute` returns `original_report` at `reports/<workflow_id>-c1/source-report.json`
(see its `_attribution_artifact(f"{input_.workflow_id}-c1", ...)`), which is why the first test
expects that location.

Append to `python/tests/test_worker.py`:

```python
def test_assembly_refuses_to_start_without_ffmpeg() -> None:
    from thoth_control_plane.config import SettingsValidationError

    off = Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_FFMPEG="/nonexistent/ffmpeg")
    worker.check_media_tools(off)  # assembly off: nothing to check

    on = off.model_copy(update={"THOTH_CONTENT_ASSEMBLY_ENABLED": True})
    with pytest.raises(SettingsValidationError, match="ffmpeg_missing"):
        worker.check_media_tools(on)
    probe_missing = on.model_copy(
        update={"THOTH_FFMPEG": "ffmpeg", "THOTH_FFPROBE": "/nonexistent/ffprobe"}
    )
    with pytest.raises(SettingsValidationError, match="ffprobe_missing"):
        worker.check_media_tools(probe_missing)
```

(If `test_worker.py` lacks `import pytest` or `Settings`, add them.)

- [ ] **Step 2: Run them to verify they fail**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/workflows/test_source_investigation.py tests/test_worker.py -p no:warnings`
Expected: FAIL — no `assemble_content` field, gateway kwarg, or `check_media_tools`.

- [ ] **Step 3: Implement the input flag and the gateway**

In `domain/models.py` `SourceInvestigationWorkflowInput`, after `attribute_source`:

```python
    # Absent from histories started before Stage 5a, so those replay without the new stage.
    assemble_content: bool = False
```

In `infrastructure/temporal_gateway.py`: add `assemble_content: bool = False` to `__init__`
(store `self._assemble_content`), pass
`assemble_content=settings.THOTH_CONTENT_ASSEMBLY_ENABLED` in `connect`, and
`assemble_content=self._assemble_content` in the `SourceInvestigationWorkflowInput(...)` of
`start`.

- [ ] **Step 4: Implement the workflow stage**

In `workflows/source_investigation.py`, inside `imports_passed_through()` add:

```python
    from thoth_control_plane.activities.content_assembly import (
        ContentAssemblyActivityInput,
        assemble_content,
    )
```

In `__init__`, add `self._original_report: str | None = None`. In `_attribute`, inside the
loop that appends artifacts, record the original's location:

```python
        for artifact in (result.attribution, result.original_report):
            if artifact is not None:
                self._artifacts.append(artifact)
                self._record_event(EventKind.ARTIFACT_CREATED, artifact=artifact)
                self._event_sequence += 1
        if result.original_report is not None:
            self._original_report = result.original_report.location
```

Replace the `identify_original` branch with:

```python
        if input_.intent == "identify_original":
            # Legacy Scout writes no v3 report, so there is nothing to attribute or assemble.
            if not self._report_from_legacy:
                if input_.attribute_source:
                    await self._attribute()
                    if self._cancel_requested:
                        self._transition(WorkflowStatus.CANCELLED)
                        self._record_event(EventKind.WORKFLOW_CANCELLED)
                        return self._summary()
                if input_.assemble_content:
                    assembled = await self._assemble()
                    if self._cancel_requested:
                        self._transition(WorkflowStatus.CANCELLED)
                        self._record_event(EventKind.WORKFLOW_CANCELLED)
                        return self._summary()
                    if not assembled:
                        self._failure = WorkflowFailure(
                            code="content_assembly_failed",
                            message="Content assembly failed",
                            failed_stage="assembly",
                            retryable=True,
                        )
                        self._transition(WorkflowStatus.FAILED)
                        self._record_event(EventKind.WORKFLOW_FAILED)
                        return self._summary()
            self._transition(WorkflowStatus.SUCCEEDED)
            self._record_event(EventKind.WORKFLOW_COMPLETED)
            return self._summary()
```

Add the method after `_attribute`:

```python
    async def _assemble(self) -> bool:
        """Build the content set; False when a required part failed (the workflow fails)."""
        self._record_event(
            EventKind.STAGE_STARTED, stage=StageProgress(name="assembly", progress=0.0)
        )
        task = asyncio.create_task(
            workflow.execute_activity(
                assemble_content,
                ContentAssemblyActivityInput(
                    workflow_id=self._workflow_id, original_report=self._original_report
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        )
        await workflow.wait_condition(lambda: self._cancel_requested or task.done())
        if self._cancel_requested and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ActivityError):
                await task
            return False
        try:
            result = await task
        except ActivityError:
            self._record_event(
                EventKind.STAGE_FAILED, stage=StageProgress(name="assembly", progress=1.0)
            )
            return False
        self._source_events.extend(result.events)
        self._event_sequence += len(result.events)
        self._updated_at = workflow.now()
        if result.content_set is None:
            self._record_event(
                EventKind.STAGE_FAILED, stage=StageProgress(name="assembly", progress=1.0)
            )
            return False
        self._artifacts.append(result.content_set)
        self._record_event(EventKind.ARTIFACT_CREATED, artifact=result.content_set)
        self._event_sequence += 1
        self._record_event(
            EventKind.STAGE_COMPLETED, stage=StageProgress(name="assembly", progress=1.0)
        )
        return True
```

`EventKind` has no stage-failed member (only `STAGE_STARTED`, `STAGE_PROGRESS`,
`STAGE_COMPLETED`), so replace both `EventKind.STAGE_FAILED` lines above with
`EventKind.STAGE_COMPLETED`, as `_attribute` does on failure; the failure itself is the
`stage.failed` source event and the workflow's `WorkflowFailure`.

- [ ] **Step 5: Implement the worker check and registration**

In `worker.py`: `import shutil`; register the activity in
`build_source_investigation_worker`'s `activities=[...]` list as
`build_content_assembly_activity(settings)` (import it from `thoth_control_plane.activities`);
add the check and call it first in `run_worker`, right after `runtime_settings = ...`:

```python
def check_media_tools(settings: Settings) -> None:
    """Content assembly needs ffmpeg and ffprobe: refuse to start without them.

    Operator, 2026-10-11: a missing tool is an explicit error, never a silent degradation.
    """
    if not settings.THOTH_CONTENT_ASSEMBLY_ENABLED:
        return
    for code, binary in (
        ("ffmpeg_missing", settings.THOTH_FFMPEG),
        ("ffprobe_missing", settings.THOTH_FFPROBE),
    ):
        if shutil.which(binary) is None:
            raise SettingsValidationError(code)
```

`build_content_assembly_activity(settings)` builds `RapidOcrReader` lazily (its engine loads on
first read), so registration does not need `rapidocr` installed.

- [ ] **Step 6: Wire the compose environment**

In `compose.stage1.local.yml`, add to both the `api` and the `worker` `environment:` blocks:

```yaml
      # Stage 5a content assembly; the worker refuses to start with it on and no ffmpeg.
      THOTH_CONTENT_ASSEMBLY_ENABLED: ${THOTH_CONTENT_ASSEMBLY_ENABLED:-false}
```

Run `file .env.stage1.local.example`; append (through a bytes script if it is CRLF):

```
# Stage 5a: build the content set after attribution (true/false).
THOTH_CONTENT_ASSEMBLY_ENABLED=false
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests/workflows tests/test_worker.py tests/deployment -p no:warnings`
Expected: PASS, including the existing compose contract tests.

- [ ] **Step 8: Format, lint, commit**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format src/thoth_control_plane tests && ~/.local/bin/uvx ruff check .'
git add python/src/thoth_control_plane python/tests/workflows/test_source_investigation.py python/tests/test_worker.py compose.stage1.local.yml .env.stage1.local.example
git commit -m "feat(assembly): run assembly after attribution behind a flag"
```

---

### Task 10: HARD STOP — RapidOCR calibration goldens (live, operator-authorized)

**Files:**
- Create: `python/tests/assembly/capture_ocr.py`
- Create: `python/tests/assembly/test_ocr_golden.py`
- Create: `python/tests/fixtures/assembly/ocr/*.json` (captured)

Do not run the capture without the operator's explicit authorization for this gate. Steps 1–3
(writing the tool and the replay test) are offline and may run before authorization.

**Interfaces:**
- Consumes: `build_production_acquisition_runner` (activities.source_investigation),
  `analyze_main_ocr`, `FRAME_WIDTH` (Task 6), `classify_ocr_frames`, `OcrBox`, `OcrFrame` (Task 2)
- Produces: fixture shape `{"case", "platform", "duration", "frames": [{"t", "boxes": [[text, x0, y0, x1, y1]]}], "captured": {verdict}, "expected": {verdict} | null}`

- [ ] **Step 1: Write the replay test**

Create `python/tests/assembly/test_ocr_golden.py`:

```python
"""Live RapidOCR boxes of real videos replay through the classifier to the confirmed verdict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.assembly.subtitles import OcrBox, OcrFrame, classify_ocr_frames

CASES = sorted((Path(__file__).parents[1] / "fixtures" / "assembly" / "ocr").glob("*.json"))


def _case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CASES, ids=[path.stem for path in CASES])
def test_golden_ocr_verdict(path: Path) -> None:
    case = _case(path)
    assert case["expected"] is not None, "the operator has not confirmed this verdict yet"
    frames = [
        OcrFrame(frame["t"], tuple(OcrBox(*box) for box in frame["boxes"]))
        for frame in case["frames"]
    ]

    verdict = classify_ocr_frames(frames, case["duration"])

    expected = case["expected"]
    assert verdict.outcome == expected["outcome"]
    assert verdict.trim_start == pytest.approx(expected["trim_start"], abs=0.01)
    assert len(verdict.subtitle_blur) == expected["blur_count"]
```

- [ ] **Step 2: Write the capture tool**

Create `python/tests/assembly/capture_ocr.py`:

```python
"""Record one RapidOCR calibration case from live traffic (operator-authorized; plan Task 10).

Run only inside the capture container. It acquires the post, samples the main video exactly as
assembly does, and records every frame's boxes and the classifier's verdict. The fixture holds
no key, no URL query, no CDN address, and no video.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from thoth_control_plane.activities.source_investigation import build_production_acquisition_runner
from thoth_control_plane.assembly.ocr import FRAME_WIDTH
from thoth_control_plane.assembly.subtitles import (
    OcrBox,
    OcrFrame,
    build_sample_times,
    classify_ocr_frames,
)
from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader
from thoth_control_plane.config import Settings


async def capture(case: str, url: str, out: Path) -> None:
    settings = Settings()  # type: ignore[call-arg]
    with tempfile.TemporaryDirectory(prefix="thoth-ocr-capture-") as directory:
        root = Path(directory)
        result = await build_production_acquisition_runner(settings)("wf_ocr_golden", url, root)
        if result.report is None:
            raise SystemExit(f"acquisition failed: {result.failure.code if result.failure else 'unknown'}")
        video = next(m for m in result.report.media if m.kind == "video")
        path = root / video.location
        duration = video.duration_seconds or await FfprobeDuration(settings.THOTH_FFPROBE).duration(path)
        frames_source = FfmpegFrameSource(settings.THOTH_FFMPEG)
        reader = RapidOcrReader(angle=False)
        frames = []
        for second in build_sample_times(duration, settings.THOTH_SUBTITLE_OCR_MAX_FRAMES):
            frame = await frames_source.frame_at(path, second, width=FRAME_WIDTH)
            boxes = await reader.read(frame)
            frames.append(
                OcrFrame(
                    second,
                    tuple(OcrBox(b.text, round(b.left, 4), round(b.top, 4), round(b.right, 4), round(b.bottom, 4)) for b in boxes),
                )
            )
        verdict = classify_ocr_frames(frames, duration)
        out.write_text(
            json.dumps(
                {
                    "case": case,
                    "platform": result.report.source.platform,
                    "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "duration": duration,
                    "frames": [
                        {"t": f.t, "boxes": [[b.text, b.x0, b.y0, b.x1, b.y1] for b in f.boxes]}
                        for f in frames
                    ],
                    "captured": {
                        "outcome": verdict.outcome,
                        "trim_start": verdict.trim_start,
                        "blur_count": len(verdict.subtitle_blur),
                        "blur": [asdict(r) for r in verdict.subtitle_blur],
                    },
                    "expected": None,
                },
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"{case}: {verdict.outcome} trim={verdict.trim_start} blur={len(verdict.subtitle_blur)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(capture(arguments.case, arguments.url, arguments.out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit the tool and the empty replay test**

With no fixture yet the replay test collects zero cases and passes.

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff format tests/assembly && ~/.local/bin/uvx ruff check .'
git add python/tests/assembly/capture_ocr.py python/tests/assembly/test_ocr_golden.py
git commit -m "test(assembly): OCR calibration capture tool and replay test"
```

- [ ] **Step 4: STOP and ask the operator**

Report in Indonesian and ask for: (a) authorization for the live capture; (b) four to six
public video URLs: an intro headline (cover), speech subtitles, a news lower-third, a clean
video, and a hybrid (headline, then captions). Wait.

- [ ] **Step 5: Capture (after authorization)**

Copy `D:/thoth-tmp/bu/s4/capture.sh` to `D:/thoth-tmp/bu/s5/capture_ocr.sh`, changing only the
final `exec` line to run `-m tests.assembly.capture_ocr --case "$CASE" --url "$URL" --out
"/out/$CASE.json"` and the output directory to `/mnt/d/thoth-tmp/bu/s5/golden`. Run one case per
URL. Copy each JSON into `python/tests/fixtures/assembly/ocr/`.

- [ ] **Step 6: Confirm with the operator**

Show each case's captured verdict (outcome, trim seconds, blur region count) in Indonesian and
ask the operator to confirm or correct it against the video. Write the confirmed verdict into
`expected` as `{"outcome", "trim_start", "blur_count"}`.

- [ ] **Step 7: Calibrate if needed**

If a confirmed verdict differs from the captured one, find the classifier threshold that
RapidOCR geometry trips (line boxes versus DeepSeek blocks), change the smallest constant, add
a sentence with the evidence to the spec as an amendment, regenerate nothing (the Scout parity
fixture stays Scout's), and update `test_classifier_matches_scout` to skip only the cases that
the amendment deliberately changes, each listed by name with the reason. Re-run the whole
assembly suite.

- [ ] **Step 8: Commit**

```bash
git add python/tests/fixtures/assembly/ocr python/src/thoth_control_plane/assembly
git add -f docs/superpowers/specs/2026-10-11-stage5a-content-assembly-design.md
git commit -m "test(assembly): RapidOCR calibration goldens"
```

---

### Task 11: Verification and documentation

**Files:**
- Modify: `CHANGELOG.md` (CRLF), `docs/python-scout-migration-roadmap.md` (CRLF)
- Modify: `docs/superpowers/specs/2026-10-11-stage5a-content-assembly-design.md` (status line)
- Create: `.superpowers/sdd/2026-10-11-stage5a-content-assembly/progress.md` (gitignored checkpoint)

- [ ] **Step 1: Full suite, lint, format**

```bash
env MSYS_NO_PATHCONV=1 timeout 590 wsl -e bash /mnt/d/thoth-tmp/bu/pt.sh tests -p no:warnings
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && ~/.local/bin/uvx ruff check . && ~/.local/bin/uvx ruff format --check .'
```

Expected: 0 failed. Record passed and skipped counts; each skip must be one of the existing
non-ffmpeg reasons (Playwright, disposable Postgres, live). No test may skip for ffmpeg.

- [ ] **Step 2: Import check without the acquisition extra**

```bash
wsl -e bash -lc 'cd /mnt/c/Users/mfr/Documents/MyTools/CLIPPER/python && PYTHONPATH=src ~/.local/bin/uv run --no-project --python 3.12 --with pydantic --with pydantic-settings --with temporalio python -c "import thoth_control_plane.workflows.source_investigation, thoth_control_plane.activities.content_assembly; print(\"ok\")"'
```

Expected: `ok`.

- [ ] **Step 3: Documentation**

Through a bytes-level CRLF script under `D:/thoth-tmp/bu/s5/`:
- `CHANGELOG.md`: a new top entry "2026-10-11 - Stage 5a: content assembly in Python" with what
  was built, verification evidence (suite counts, parity cases, ruff), departures from Scout
  (spec section 10), and a **Next steps** section: Stage 5b footage; the operator gates (push,
  deploy, the calibration capture if not done); follow-ups from spec section 12.
- `docs/python-scout-migration-roadmap.md`: a "Stage 5a status (2026-10-11)" section in the
  style of the Stage 4 section.

Edit the spec status line to "implemented on branch `feat/stage5a-content-assembly` (see
`docs/superpowers/plans/2026-10-11-stage5a-content-assembly.md`)". Write the checkpoint
`progress.md` with the same next steps.

- [ ] **Step 4: Index refresh and commit**

```bash
graphify update .
git add CHANGELOG.md docs/python-scout-migration-roadmap.md
git add -f docs/superpowers/specs/2026-10-11-stage5a-content-assembly-design.md docs/superpowers/plans/2026-10-11-stage5a-content-assembly.md
git commit -m "docs: record Stage 5a content assembly"
```

- [ ] **Step 5: Report**

Report to the operator in Indonesian: what was built, evidence, departures, and a **Next steps**
section (Stage 5b; push, merge, and deploy as separate gates; deploy also means setting
`THOTH_CONTENT_ASSEMBLY_ENABLED=true`; the parked items from memory).


---

## Addendum (2026-10-12): post-classification corrections

Spec amendment of 2026-10-12. The operator chose: region-diff trim refinement, trim only for a
main that may be a repost, persistent overlays blurred without mute, scene text guarded by rules
plus one vision confirmation. `classify_ocr_frames` and its parity fixture do not change.
Task 10's capture resumes after Task 16 with the new fields; verdicts are confirmed then.

### Task 12: Schema, reason code, and worker check

- `MainOcr.outcome` gains `"overlay"`: `mute_audio` false, at least one blur region, any trim.
- `MainOcr.trim_refined: bool = False`.
- `ASSEMBLY_REASONS` gains `opencv_missing`; `check_media_tools` refuses to start without
  `cv2` when assembly is on.
- Tests: an overlay verdict is valid; overlay with mute or without blur is rejected; the worker
  check names `opencv_missing`.

### Task 13: `assembly/refine.py`, pure corrections

- `region_boxes(frames, region) -> list[tuple[OcrFrame, list[OcrBox]]]`: frames inside the
  window, boxes inside the region (tolerance 0.01).
- `sort_windows(frames, verdict) -> Windows(captions, overlays, dropped)`: edge-cut share at
  least a third → dropped; text constant across the window (joined, normalized, similarity at
  least 0.6 to the first frame) → overlay if the window covers at least 80% of the usable
  frames, else dropped; otherwise caption.
- `without_trim(verdict)`, `retrim(verdict, trim)`: move `trim_start`; a window that began at
  the old trim begins at the new one; `cover` without trim becomes `clean`.
- `settle(verdict, windows, confirmed) -> Verdict`: captions kept only if `confirmed` is not
  False; outcome `subtitle` if captions remain (mute, blur captions and overlays), `overlay` if
  only overlays, `cover` if trim, else `clean`.
- Tests: synthetic frames for each rule, plus the captured shapes (deRDs6DCX07 band → overlay;
  kabinetketiduran LED → dropped; detikjatim captions → caption).

### Task 14: Adapters

- `assembly/adapters/region.py` `FfmpegRegionTracker(ffmpeg).first_absent(video, region,
  start, end) -> float | None`: one ffmpeg process decodes `[start, end]` at 10 fps, scaled to
  720 px, cropped to the region, grey; Canny edges; first frame whose correlation with the first
  frame is below 0.5. `ToolMissing("opencv_missing")` without `cv2`.
- `assembly/adapters/captions.py` `AgnoCaptionJudge(key, model).speech_captions(frames) ->
  bool | None` (structured `{"speech_captions": bool}`, None on any failure).
- Ports `RegionTracker`, `CaptionJudge` in `assembly/ports.py`.
- Tests: ffmpeg test clip with a drawn box that vanishes at a known second (no skip without
  ffmpeg); respx-mocked judge yes, no, and 500.

### Task 15: Wiring

- `analyze_main_ocr(..., trim_allowed: bool, tracker: RegionTracker | None, judge:
  CaptionJudge | None)`: classify, then `without_trim` or refine with the tracker, then
  `sort_windows`, the judge on up to three caption frames (kept JPEGs), `settle`.
- `ContentAssembler` passes `trim_allowed = source == "input" and verdict in {"unresolved",
  "none"}` and the two new ports; production wires them.
- Tests: trim not allowed for verdict original; refinement moves the trim; judge "no" drops
  captions; judge unavailable keeps them.

### Task 16: Calibration replay with the new fields

- `capture_ocr.py` records `refined_trim` (the tracker's answer) and `vision` (the judge's) and
  the settled verdict; `test_ocr_golden.py` replays frames through the classifier and
  `refine.py` with recorded tracker and judge answers.
- Recapture the seven cases, show the operator each settled verdict, write `expected` after
  confirmation.
