"""Frame-to-frame change of sampled frames, local and model-free (spec 5.8).

A still image shown in a reaction does not change between 1 fps samples; a video does. The
change is the mean absolute grey difference at 64x64, from 0 (identical) to 1.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence
from itertools import pairwise

from thoth_control_plane.attribution.ports import Frame

STILL_THRESHOLD = 0.02  # JPEG noise between identical frames stays well below this
SIZE = (64, 64)


class PillowMotion:
    async def changes(self, frames: Sequence[Frame]) -> list[float]:
        return await asyncio.to_thread(self._changes, list(frames))

    def _changes(self, frames: list[Frame]) -> list[float]:
        import numpy as np
        from PIL import Image

        grey = []
        for frame in frames:
            with Image.open(io.BytesIO(frame.jpeg)) as image:
                small = image.convert("L").resize(SIZE)
                grey.append(np.asarray(small, dtype=np.float32) / 255.0)
        return [float(np.abs(after - before).mean()) for before, after in pairwise(grey)]
