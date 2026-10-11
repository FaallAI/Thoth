"""Record one RapidOCR calibration case from live traffic (operator-authorized; plan Task 10).

Run only inside the capture container. It acquires the post and runs the production main OCR
(`analyze_main_ocr`: the same samples, frame recovery, coverage rule, and corrections) through
recording ports, so the fixture holds exactly the boxes production classified, unrounded, and
the region tracker's and the caption judge's answers for an offline replay. The
fixture holds no key, no URL query, no CDN address, and no video.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thoth_control_plane.activities.source_investigation import build_production_acquisition_runner
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import (
    CaptionJudge,
    DurationProbe,
    FrameSampler,
    RegionTracker,
    TextReader,
)
from thoth_control_plane.assembly.subtitles import OcrBox
from thoth_control_plane.attribution.adapters.frames import FfmpegFrameSource, FfprobeDuration
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.config import Settings


class _Recording:
    def __init__(self, inner: TextReader) -> None:
        self._inner = inner
        self.frames: list[dict[str, Any]] = []

    async def read(self, frame: Frame) -> list[TextBox]:
        boxes = await self._inner.read(frame)
        self.frames.append(
            {
                "t": frame.second,
                "boxes": [[b.text, b.left, b.top, b.right, b.bottom] for b in boxes],
            }
        )
        return boxes


class _Answers:
    def __init__(self, tracker: RegionTracker | None, judge: CaptionJudge | None) -> None:
        self._tracker, self._judge = tracker, judge
        self.tracker: float | None = None
        self.vision: bool | None = None

    async def first_absent(
        self, video: Path, region: OcrBox, start: float, end: float
    ) -> float | None:
        assert self._tracker is not None
        self.tracker = await self._tracker.first_absent(video, region, start, end)
        return self.tracker

    async def speech_captions(self, frames: Sequence[Frame]) -> bool | None:
        assert self._judge is not None
        self.vision = await self._judge.speech_captions(frames)
        return self.vision


async def record_ocr(
    video: Path,
    duration: float,
    *,
    frames: FrameSampler,
    probe: DurationProbe,
    text: TextReader,
    max_frames: int,
    trim_allowed: bool = True,
    tracker: RegionTracker | None = None,
    judge: CaptionJudge | None = None,
) -> dict[str, Any]:
    recording = _Recording(text)
    answers = _Answers(tracker, judge)
    ocr = await analyze_main_ocr(
        video,
        duration,
        frames=frames,
        probe=probe,
        text=recording,
        max_frames=max_frames,
        now=datetime.now(UTC),
        trim_allowed=trim_allowed,
        tracker=answers if tracker is not None else None,
        judge=answers if judge is not None else None,
    )
    return {
        "duration": duration,
        "frames": recording.frames,
        "trim_allowed": trim_allowed,
        "tracker": answers.tracker,
        "vision": answers.vision,
        "captured": {
            "outcome": ocr.outcome,
            "trim_start": ocr.trim_start,
            "trim_refined": ocr.trim_refined,
            "blur_count": len(ocr.subtitle_blur),
            "blur": [region.model_dump() for region in ocr.subtitle_blur],
        },
        "ocr": ocr,
    }


async def capture(case: str, url: str, out: Path, *, original: bool) -> None:
    from thoth_control_plane.assembly.adapters.captions import AgnoCaptionJudge
    from thoth_control_plane.assembly.adapters.region import FfmpegRegionTracker
    from thoth_control_plane.attribution.adapters.ocr import RapidOcrReader

    settings = Settings()  # type: ignore[call-arg]
    with tempfile.TemporaryDirectory(prefix="thoth-ocr-capture-") as directory:
        root = Path(directory)
        result = await build_production_acquisition_runner(settings)("wf_ocr_golden", url, root)
        if result.report is None:
            code = result.failure.code if result.failure else "unknown"
            raise SystemExit(f"acquisition failed: {code}")
        video = next(m for m in result.report.media if m.kind == "video")
        path = root / video.location
        probe = FfprobeDuration(settings.THOTH_FFPROBE)
        duration = video.duration_seconds or await probe.duration(path)
        recorded = await record_ocr(
            path,
            duration,
            frames=FfmpegFrameSource(settings.THOTH_FFMPEG),
            probe=probe,
            text=RapidOcrReader(angle=False),
            max_frames=settings.THOTH_SUBTITLE_OCR_MAX_FRAMES,
            trim_allowed=not original,
            tracker=FfmpegRegionTracker(settings.THOTH_FFMPEG),
            judge=AgnoCaptionJudge(key, settings.THOTH_SOURCE_VISION_MODEL)
            if (key := settings.openrouter_api_key)
            else None,
        )
        recorded.pop("ocr")
        fixture = {
            "case": case,
            "platform": result.report.source.platform,
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **recorded,
            "expected": None,
        }
        out.write_text(json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        captured = fixture["captured"]
        print(
            f"{case}: {captured['outcome']} trim={captured['trim_start']} "
            f"refined={captured['trim_refined']} blur={captured['blur_count']} "
            f"tracker={fixture['tracker']} vision={fixture['vision']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    # A known original keeps its intro in production (amendment, 2026-10-12): no trim.
    parser.add_argument("--original", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(capture(arguments.case, arguments.url, arguments.out, original=arguments.original))


if __name__ == "__main__":
    main()
