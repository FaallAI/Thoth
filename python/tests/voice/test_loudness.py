"""Narration voices normalised to one level (operator, 2026-11-12: narration too quiet)."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.voice.loudness import TARGET_LUFS, normalize_loudness


def _tone(volume_db: float, seconds: float = 4.0) -> bytes:
    """A speech-like test voice: a 300 Hz tone gated on and off, as mp3 at `volume_db`."""
    with tempfile.TemporaryDirectory() as work:
        target = Path(work) / "tone.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=300:duration={seconds}:sample_rate=44100",
                "-af",
                f"volume=enable='lt(mod(t,1),0.7)':volume=1,volume={volume_db}dB",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(target),
            ],
            check=True,
        )
        return target.read_bytes()


def _measure(audio: bytes) -> tuple[float, float]:
    """(integrated LUFS, duration seconds) of mp3 bytes."""
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "voice.mp3"
        source.write_bytes(audio)
        report = subprocess.run(
            ["ffmpeg", "-nostdin", "-i", str(source), "-af", "ebur128", "-f", "null", "-"],
            capture_output=True,
            text=True,
        ).stderr
    integrated = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", report)[-1])
    duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", report)
    assert duration is not None
    hours, minutes, seconds = duration.groups()
    return integrated, int(hours) * 3600 + int(minutes) * 60 + float(seconds)


@pytest.mark.parametrize("volume_db", [-24.0, -3.0])
def test_a_quiet_or_a_loud_voice_comes_out_at_the_target_level_and_length(volume_db: float) -> None:
    before = _tone(volume_db)
    after = normalize_loudness(before, "audio/mpeg")
    level, length = _measure(after)
    assert abs(level - TARGET_LUFS) <= 1.0
    # Only the level changes: word timings stay where the voice put them.
    assert abs(length - _measure(before)[1]) <= 0.08


def test_a_missing_ffmpeg_is_named_not_skipped() -> None:
    with pytest.raises(ToolMissing):
        normalize_loudness(_tone(-20.0), "audio/mpeg", ffmpeg="/nonexistent/ffmpeg")


def test_audio_ffmpeg_cannot_read_is_kept_as_it_came() -> None:
    assert normalize_loudness(b"not audio", "audio/mpeg") == b"not audio"


def test_a_format_it_does_not_know_is_kept_as_it_came() -> None:
    assert normalize_loudness(b"opus bytes", "audio/ogg") == b"opus bytes"
