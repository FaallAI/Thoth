"""When does an intro headline leave? Its region compared frame by frame, no OCR.

One ffmpeg process decodes only the gap between the last sample that holds the headline and the
first that does not, at 10 frames per second, cropped to the headline and grey. Canny edges of
each frame are correlated with the first; text leaving drops it from above 0.8 to about 0.2
(research, 2026-10-12: detikjatim 6.5 s and officialinews 9.6 s, both within 0.1 s of OCR
bisection).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from thoth_control_plane.assembly.subtitles import OcrBox
from thoth_control_plane.attribution.adapters.frames import ToolMissing, _run

FPS = 10.0
WIDTH = 720
THRESHOLD = 0.5


class FfmpegRegionTracker:
    def __init__(self, ffmpeg: str = "ffmpeg") -> None:
        self._ffmpeg = ffmpeg

    async def first_absent(
        self, video: Path, region: OcrBox, start: float, end: float
    ) -> float | None:
        """The first second after `start` where the region no longer holds what it held."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            raise ToolMissing("opencv_missing") from None
        crop = (
            f"crop=iw*{region.x1 - region.x0:.4f}:ih*{region.y1 - region.y0:.4f}"
            f":iw*{region.x0:.4f}:ih*{region.y0:.4f}"
        )
        with tempfile.TemporaryDirectory(prefix="thoth-region-") as directory:
            code, _ = await _run(
                [
                    self._ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{max(0.0, end - start):.3f}",
                    "-i",
                    str(video),
                    "-vf",
                    f"fps={FPS:g},scale={WIDTH}:-2,{crop},format=gray",
                    str(Path(directory) / "r%05d.png"),
                ],
                "ffmpeg_missing",
            )
            files = sorted(Path(directory).glob("r*.png"))
            if code != 0 or len(files) < 2:
                return None
            edges = [
                cv2.Canny(cv2.imread(str(path), cv2.IMREAD_GRAYSCALE), 80, 200).astype(np.float32)
                for path in files
            ]
        reference = edges[0]
        energy = float((reference * reference).sum())
        if energy == 0:
            return None  # nothing to track: a flat region
        for index, frame in enumerate(edges[1:], start=1):
            if frame.shape != reference.shape:
                continue
            score = float((reference * frame).sum()) / (
                (energy * float((frame * frame).sum())) ** 0.5 or 1.0
            )
            if score < THRESHOLD:
                return round(start + index / FPS, 3)
        return None
