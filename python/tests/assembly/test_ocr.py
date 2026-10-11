"""Main OCR: complete coverage or an explicit failure; tools missing are never media failures."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

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
            VIDEO,
            duration,
            frames=frames,
            probe=probe or Probe(30.0),
            text=Text(),
            max_frames=12,
            now=NOW,
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
    [
        (ToolMissing("ffprobe_missing"), "ffprobe_missing"),
        (DurationError("duration_probe_failed"), "duration_probe_failed"),
    ],
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
                VIDEO,
                30.0,
                frames=Frames(),
                probe=Probe(30.0),
                text=Crashing(),
                max_frames=12,
                now=NOW,
            )
        )
    assert raised.value.code == "incomplete_frame_coverage"


def test_a_missing_ocr_engine_is_its_own_code() -> None:
    # Operator, 2026-10-11: a missing tool is an explicit error, never a media failure.
    class Uninstalled(Text):
        async def read(self, frame: Frame) -> list[TextBox]:
            raise ModuleNotFoundError("No module named 'rapidocr'")

    with pytest.raises(AssemblyError) as raised:
        asyncio.run(
            analyze_main_ocr(
                VIDEO,
                30.0,
                frames=Frames(),
                probe=Probe(30.0),
                text=Uninstalled(),
                max_frames=12,
                now=NOW,
            )
        )
    assert raised.value.code == "rapidocr_missing"
