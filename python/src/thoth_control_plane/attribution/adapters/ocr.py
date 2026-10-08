"""Text boxes from RapidOCR (PaddleOCR models on ONNX Runtime), on the CPU."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

MAX_TEXT = 200


class RapidOcrReader:
    def __init__(self) -> None:
        self._engine: Any = None

    async def read(self, frame: Frame) -> list[TextBox]:
        return await asyncio.to_thread(self._read, frame.jpeg)

    def _read(self, jpeg: bytes) -> list[TextBox]:
        from PIL import Image

        with Image.open(io.BytesIO(jpeg)) as image:
            height = image.height
        result = self._get()(jpeg)
        if result.boxes is None or result.txts is None:
            return []
        boxes: list[TextBox] = []
        for quad, text in zip(result.boxes, result.txts, strict=False):
            ys = [float(point[1]) for point in quad]
            boxes.append(TextBox(str(text)[:MAX_TEXT], min(ys) / height, max(ys) / height))
        return boxes

    def _get(self) -> Any:
        if self._engine is None:
            from rapidocr import RapidOCR

            # RapidOCR logs every model load at INFO; keep the worker log to warnings.
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            self._engine = RapidOCR()
        return self._engine
