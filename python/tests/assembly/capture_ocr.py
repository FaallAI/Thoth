"""Record one RapidOCR calibration case from live traffic (operator-authorized; plan Task 10).

Run only inside the capture container. It acquires the post and runs the production main OCR
(`analyze_main_ocr`: the same samples, frame recovery, and coverage rule) through a recording
text reader, so the fixture holds exactly the boxes production classified, unrounded. The
fixture holds no key, no URL query, no CDN address, and no video.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thoth_control_plane.activities.source_investigation import build_production_acquisition_runner
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import DurationProbe, FrameSampler, TextReader
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


async def record_ocr(
    video: Path,
    duration: float,
    *,
    frames: FrameSampler,
    probe: DurationProbe,
    text: TextReader,
    max_frames: int,
) -> dict[str, Any]:
    recording = _Recording(text)
    ocr = await analyze_main_ocr(
        video,
        duration,
        frames=frames,
        probe=probe,
        text=recording,
        max_frames=max_frames,
        now=datetime.now(UTC),
    )
    return {
        "duration": duration,
        "frames": recording.frames,
        "captured": {
            "outcome": ocr.outcome,
            "trim_start": ocr.trim_start,
            "blur_count": len(ocr.subtitle_blur),
            "blur": [region.model_dump() for region in ocr.subtitle_blur],
        },
        "ocr": ocr,
    }


async def capture(case: str, url: str, out: Path) -> None:
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
            f"blur={captured['blur_count']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(capture(arguments.case, arguments.url, arguments.out))


if __name__ == "__main__":
    main()
