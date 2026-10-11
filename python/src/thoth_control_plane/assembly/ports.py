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
