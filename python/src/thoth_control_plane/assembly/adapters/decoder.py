"""Many frames from one pass over a video, instead of one ffmpeg process per frame.

The half-second caption read spent about 0.19 s per frame starting ffmpeg and seeking; one pass
over the whole 72 s video took about 1.2 s (bench, 2026-11-03). Each frame is the one `ffmpeg -ss`
answers with: the first at or after the second, a high-quality JPEG. The samples stay YCbCr as
in ffmpeg's JPEG: through RGB, saturated colours clip and shifted the luma by up to 4.6 levels.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Sequence
from pathlib import Path

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.attribution.ports import Frame

logger = logging.getLogger(__name__)

THREADS = 2  # like ORT_THREADS: a long video must not take every core from the workflow thread
JPEG_QUALITY = 95  # about `-q:v 2`, what one frame's extraction uses
SLACK = 1e-6


class PyAvFrameDecoder:
    async def decode(
        self,
        video: Path,
        seconds: Sequence[float],
        *,
        width: int,
        top: float = 0.0,
        bottom: float = 1.0,
    ) -> dict[float, Frame]:
        """The frames at `seconds`, cut to the band; a second past the end is left out."""
        return await asyncio.to_thread(self._decode, video, sorted(seconds), width, top, bottom)

    def _decode(
        self, video: Path, seconds: list[float], width: int, top: float, bottom: float
    ) -> dict[float, Frame]:
        try:
            import av
        except ImportError:
            raise ToolMissing("pyav_missing") from None
        from PIL import Image

        found: dict[float, Frame] = {}
        at = 0
        with av.open(str(video)) as container:
            stream = container.streams.video[0]
            stream.codec_context.thread_count = THREADS
            origin = stream.start_time or 0
            height = round(stream.height * width / stream.width / 2) * 2
            first, last = int(height * top), int(height * bottom)
            for frame in container.decode(stream):
                if frame.rotation:
                    # ffmpeg turns such a video upright; here it would be read on its side.
                    logger.info("rotated video; frames are extracted alone")
                    return {}
                if frame.pts is None:
                    continue
                second = float((frame.pts - origin) * stream.time_base)
                if second < seconds[at] - SLACK:
                    continue
                samples = frame.reformat(
                    width=width, height=height, format="yuvj444p", interpolation="BICUBIC"
                ).to_ndarray()
                buffer = io.BytesIO()
                Image.frombytes(
                    "YCbCr",
                    (width, last - first),
                    samples.transpose(1, 2, 0)[first:last].tobytes(),
                ).save(buffer, format="JPEG", quality=JPEG_QUALITY)
                while at < len(seconds) and second >= seconds[at] - SLACK:
                    found[seconds[at]] = Frame(seconds[at], buffer.getvalue())
                    at += 1
                if at == len(seconds):
                    break
        return found
