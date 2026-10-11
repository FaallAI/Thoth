"""Text boxes from RapidOCR (PaddleOCR models on ONNX Runtime), on the CPU."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from typing import Any

from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

MAX_TEXT = 200


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

    def _get(self) -> Any:
        with self._lock:
            if self._engine is None:
                from rapidocr import RapidOCR

                self._engine = RapidOCR()
                # RapidOCR resets its logger to INFO while it builds, then logs every model
                # load and, at WARNING, every frame without text; keep only its errors.
                logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        return self._engine
