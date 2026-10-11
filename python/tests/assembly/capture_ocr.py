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
            raise SystemExit(
                f"acquisition failed: {result.failure.code if result.failure else 'unknown'}"
            )
        video = next(m for m in result.report.media if m.kind == "video")
        path = root / video.location
        duration = video.duration_seconds or await FfprobeDuration(settings.THOTH_FFPROBE).duration(
            path
        )
        frames_source = FfmpegFrameSource(settings.THOTH_FFMPEG)
        reader = RapidOcrReader(angle=False)
        frames = []
        for second in build_sample_times(duration, settings.THOTH_SUBTITLE_OCR_MAX_FRAMES):
            frame = await frames_source.frame_at(path, second, width=FRAME_WIDTH)
            boxes = await reader.read(frame)
            frames.append(
                OcrFrame(
                    second,
                    tuple(
                        OcrBox(
                            b.text,
                            round(b.left, 4),
                            round(b.top, 4),
                            round(b.right, 4),
                            round(b.bottom, 4),
                        )
                        for b in boxes
                    ),
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
        print(
            f"{case}: {verdict.outcome} trim={verdict.trim_start} blur={len(verdict.subtitle_blur)}"
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
