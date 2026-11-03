"""Main OCR: complete coverage or an explicit failure; tools missing are never media failures."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from thoth_control_plane.assembly import ocr as ocr_module
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.subtitles import build_sample_times
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.ports import Frame

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
VIDEO = Path("main.mp4")
CAPTION = ("rocky", "apapun", "minumnya", "sendiri", "betul", "tobat", "makanannya", "paling")


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
        return [TextBox(CAPTION[round(second * 2) % len(CAPTION)], 0.75, 0.8, 0.2, 0.8)]


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


class Tracker:
    def __init__(self, answer: float | Exception | None) -> None:
        self.answer, self.calls = answer, []

    async def first_absent(self, video, region, start, end):  # type: ignore[no-untyped-def]
        self.calls.append((region.text, start, end))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Judge:
    def __init__(self, answer: bool | None) -> None:
        self.answer, self.seen = answer, []

    async def speech_captions(self, frames):  # type: ignore[no-untyped-def]
        self.seen.append([frame.second for frame in frames])
        return self.answer


def corrected(**kwargs):  # type: ignore[no-untyped-def]
    return asyncio.run(
        analyze_main_ocr(
            VIDEO,
            30.0,
            frames=Frames(),
            probe=Probe(30.0),
            text=Text(),
            max_frames=12,
            now=NOW,
            **kwargs,
        )
    )


def test_an_original_keeps_its_intro() -> None:
    ocr = corrected(trim_allowed=False)

    assert ocr.trim_start == 0.0 and ocr.outcome == "subtitle"


def test_the_tracker_moves_the_trim_and_the_first_caption_window() -> None:
    tracker = Tracker(2.2)

    ocr = corrected(tracker=tracker)

    assert tracker.calls == [("BANJIR BESAR JAKARTA", 2.0, 3.0)]
    assert (ocr.trim_start, ocr.trim_refined) == (2.2, True)
    assert ocr.subtitle_blur[0].start == 2.2


def test_an_unmeasured_boundary_keeps_the_midpoint() -> None:
    for answer in (None, RuntimeError("decode")):
        ocr = corrected(tracker=Tracker(answer))
        assert (ocr.trim_start, ocr.trim_refined) == (2.5, False)


def test_missing_opencv_is_its_own_code() -> None:
    from thoth_control_plane.attribution.adapters.frames import ToolMissing

    with pytest.raises(AssemblyError) as raised:
        corrected(tracker=Tracker(ToolMissing("opencv_missing")))
    assert raised.value.code == "opencv_missing"


def test_the_judge_decides_whether_captions_mute() -> None:
    judge = Judge(False)

    rejected = corrected(judge=judge)

    assert (rejected.outcome, rejected.mute_audio, rejected.subtitle_blur) == ("cover", False, [])
    assert len(judge.seen[0]) == 3 and all(second > 2.5 for second in judge.seen[0])
    assert corrected(judge=Judge(True)).outcome == "subtitle"
    assert corrected(judge=Judge(None)).outcome == "subtitle"  # no answer: the rules stand


def test_a_reader_reporting_a_missing_engine_keeps_its_code() -> None:
    # The shared RapidOCR adapter reports a missing engine as ToolMissing (review 2026-10-13).
    class Missing(Text):
        async def read(self, frame: Frame) -> list[TextBox]:
            raise ToolMissing("rapidocr_missing")

    with pytest.raises(AssemblyError) as raised:
        asyncio.run(
            analyze_main_ocr(
                VIDEO,
                30.0,
                frames=Frames(),
                probe=Probe(30.0),
                text=Missing(),
                max_frames=12,
                now=NOW,
            )
        )
    assert raised.value.code == "rapidocr_missing"


# --- Blur follows the text (operator, rev 19, 2026-11-02) ---


class Spoken:
    """A caption to 2 s and from 6 s to 10.5 s, the same watermark throughout."""

    def __init__(self) -> None:
        self.read_at: list[float] = []

    async def read(self, frame: Frame) -> list[TextBox]:
        second = float(frame.jpeg.decode())
        self.read_at.append(second)
        boxes = [TextBox("Kabinet Rakyat", 0.47, 0.52, 0.32, 0.68)]
        if second <= 2 or 6 <= second <= 10.5:
            boxes.append(TextBox(CAPTION[int(second * 2) % len(CAPTION)], 0.84, 0.89, 0.3, 0.7))
        return boxes


def followed(frames: Frames | None = None, **kwargs):  # type: ignore[no-untyped-def]
    return asyncio.run(
        analyze_main_ocr(
            VIDEO,
            20.0,
            frames=frames or Frames(),
            probe=Probe(20.0),
            text=kwargs.pop("text", Spoken()),
            max_frames=12,
            now=NOW,
            trim_allowed=False,
            **kwargs,
        )
    )


def test_blur_opens_and_closes_with_the_caption_and_skips_the_watermark() -> None:
    ocr = followed()

    assert ocr.outcome == "subtitle" and ocr.mute_audio
    # Each edge is read out of its half-second gap. A window closes on the first read without its
    # text: a midpoint left the caption's last frame showing (rev 18 source, 2026-11-03).
    assert [(r.start, r.end) for r in ocr.subtitle_blur] == [(0.0, 2.0625), (5.96875, 10.5625)]
    assert all(r.y > 0.8 for r in ocr.subtitle_blur)


def test_a_sample_is_not_read_twice_when_following_the_text() -> None:
    text = Spoken()

    followed(text=text)

    assert len(text.read_at) == len(set(text.read_at))
    assert 7.5 in text.read_at


def test_a_clean_video_is_not_read_again() -> None:
    class Quiet:
        def __init__(self) -> None:
            self.reads = 0

        async def read(self, frame: Frame) -> list[TextBox]:
            self.reads += 1
            return []

    text = Quiet()

    assert followed(text=text).outcome == "clean"
    assert text.reads == 12


def test_a_frame_lost_while_following_keeps_the_sampled_windows() -> None:
    ocr = followed(Frames(broken={7.5, 7.25, 7.0, 6.75, 6.5}))

    assert ocr.outcome == "subtitle" and ocr.subtitle_blur


def test_a_caller_that_only_needs_the_verdict_reads_the_samples_only() -> None:
    text = Spoken()

    ocr = followed(text=text, follow=False)

    assert len(text.read_at) == 12 and ocr.outcome == "subtitle"


def test_a_missing_tool_while_following_keeps_its_code() -> None:
    class Dies(Spoken):
        async def read(self, frame: Frame) -> list[TextBox]:
            if len(self.read_at) >= 12:
                raise ToolMissing("rapidocr_missing")
            return await super().read(frame)

    with pytest.raises(AssemblyError) as raised:
        followed(text=Dies())
    assert raised.value.code == "rapidocr_missing"


def test_the_lines_of_one_caption_share_the_reads_of_their_edges() -> None:
    class TwoLines(Spoken):
        async def read(self, frame: Frame) -> list[TextBox]:
            boxes = await super().read(frame)
            second = float(frame.jpeg.decode())
            if second <= 2 or 6 <= second <= 10.5:
                boxes.append(TextBox(CAPTION[int(second * 2) % 7 + 1], 0.74, 0.79, 0.3, 0.7))
            return boxes

    text = TwoLines()

    ocr = followed(text=text)

    assert len(ocr.subtitle_blur) == 4
    assert len(text.read_at) == len(set(text.read_at))


def test_a_frame_lost_at_an_edge_keeps_that_edge_within_its_gap() -> None:
    frames = Frames(broken={2.25})

    ocr = followed(frames)

    assert [(r.start, r.end) for r in ocr.subtitle_blur] == [(0.0, 2.25), (5.96875, 10.5625)]
    assert 2.0 not in [second for second, _ in frames.calls[frames.calls.index((2.25, 720)) + 1 :]]


def test_too_many_edges_stay_within_half_a_second(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(ocr_module, "EDGE_MAX_READS", 8)
    text = Spoken()

    ocr = followed(text=text)

    assert [(r.start, r.end) for r in ocr.subtitle_blur] == [(0.0, 2.25), (5.75, 10.75)]
    assert all(
        second * 2 == int(second * 2) or second in build_sample_times(20.0)
        for second in text.read_at
    )
    assert "caption edges" in caplog.text


def test_a_missing_tool_at_an_edge_keeps_its_code() -> None:
    class DiesAtAnEdge(Spoken):
        async def read(self, frame: Frame) -> list[TextBox]:
            if float(frame.jpeg.decode()) == 2.25:
                raise ToolMissing("rapidocr_missing")
            return await super().read(frame)

    with pytest.raises(AssemblyError) as raised:
        followed(text=DiesAtAnEdge())
    assert raised.value.code == "rapidocr_missing"


# --- One decode pass and the caption band (operator, 2026-11-03) ---

SHARP = [(0.0, 2.0625), (5.96875, 10.5625)]


class OnePass:
    def __init__(self, missing: set[float] = frozenset(), fails: bool = False) -> None:
        self.missing, self.fails, self.calls = missing, fails, []

    async def decode(
        self,
        video: Path,
        seconds: list[float],
        *,
        width: int,
        top: float = 0.0,
        bottom: float = 1.0,
    ) -> dict[float, Frame]:
        self.calls.append((list(seconds), width, top, bottom))
        if self.fails:
            raise FrameError("decode_failed")
        return {s: Frame(s, f"{s}".encode()) for s in seconds if s not in self.missing}


class Banded(Spoken):
    def __init__(self, broken: set[float] = frozenset()) -> None:
        super().__init__()
        self.broken, self.band_at = broken, []

    async def read_band(self, frame: Frame, top: float, bottom: float) -> list[TextBox]:
        second = float(frame.jpeg.decode())
        self.band_at.append(second)
        if second in self.broken:
            raise RuntimeError("unreadable")
        boxes = await Spoken.read(self, frame)
        self.read_at.pop()
        return [box for box in boxes if top <= box.top and box.bottom <= bottom]


def windows(ocr) -> list[tuple[float, float]]:  # type: ignore[no-untyped-def]
    return [(region.start, region.end) for region in ocr.subtitle_blur]


def test_the_half_second_frames_come_from_one_pass() -> None:
    frames, decoder = Frames(), OnePass()

    ocr = followed(frames, decoder=decoder)

    assert windows(ocr) == SHARP
    assert 7.5 not in [second for second, _ in frames.calls]
    assert 7.5 in decoder.calls[0][0] and decoder.calls[0][1] == 720
    assert decoder.calls[0][2:] == (0.0, 1.0)


def test_a_second_the_pass_did_not_reach_is_extracted_alone() -> None:
    frames = Frames()

    ocr = followed(frames, decoder=OnePass(missing={7.5}))

    assert windows(ocr) == SHARP
    assert (7.5, 720) in frames.calls


def test_a_failed_pass_gives_the_same_windows_slower(caplog: pytest.LogCaptureFixture) -> None:
    frames, text = Frames(), Banded()

    ocr = followed(frames, text=text, decoder=OnePass(fails=True), bands=text)

    assert windows(ocr) == SHARP
    assert (7.5, 720) in frames.calls and not text.band_at
    assert "decode pass failed" in caplog.text


def test_edges_are_read_from_the_caption_band_only() -> None:
    frames, text, decoder = Frames(), Banded(), OnePass()

    ocr = followed(frames, text=text, decoder=decoder, bands=text)

    assert windows(ocr) == SHARP
    assert len(text.band_at) == 9  # three edges, three reads each
    top, bottom = decoder.calls[1][2:]
    assert top < 0.84 and bottom > 0.89 and bottom - top < 0.13  # the caption line, no watermark
    assert set(text.band_at) <= set(decoder.calls[1][0])
    assert not set(text.band_at) & {second for second, _ in frames.calls}


def test_a_band_frame_the_pass_missed_is_read_whole() -> None:
    frames, text = Frames(), Banded()

    ocr = followed(frames, text=text, decoder=OnePass(missing={2.25}), bands=text)

    assert windows(ocr) == SHARP
    assert (2.25, 720) in frames.calls


def test_a_band_read_that_fails_keeps_that_edge_within_its_gap() -> None:
    text = Banded(broken={2.25})

    ocr = followed(text=text, decoder=OnePass(), bands=text)

    assert windows(ocr) == [(0.0, 2.25), (5.96875, 10.5625)]


def test_without_a_band_reader_the_edges_are_read_whole() -> None:
    frames = Frames()

    ocr = followed(frames, decoder=OnePass())

    assert windows(ocr) == SHARP
    assert (2.25, 720) in frames.calls
