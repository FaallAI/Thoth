"""Narration voices brought to one level before they are stored (operator, 2026-11-12).

The four beats of one draft measured -16.6 to -20.7 LUFS, so the narration rose and fell between
beats and sat low under the ducked main video. ffmpeg's two-pass `loudnorm` in linear mode moves
the level only; the voice's own dynamics and its length, so its word timings, stay as they came.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from thoth_control_plane.attribution.adapters.frames import ToolMissing

logger = logging.getLogger(__name__)

#: Integrated loudness and true-peak ceiling for every voice.
# Level with most TikTok videos (operator, 2026-11-12: "setarakan video tiktok pada umumnya").
TARGET_LUFS = -14.0
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0
#: Formats the provider returns, by media type: (container suffix, encoder arguments).
_FORMATS: dict[str, tuple[str, list[str]]] = {
    "audio/mpeg": (".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "audio/mp3": (".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "audio/wav": (".wav", ["-c:a", "pcm_s16le"]),
    "audio/x-wav": (".wav", ["-c:a", "pcm_s16le"]),
}
_TIMEOUT_SECONDS = 120
#: loudnorm cannot measure a voice shorter than this: ffmpeg 5.1 (the worker's) turned a 2.87 s
#: voice from -14 to -41 dB (draft edoc_3ee4719b, 2026-11-17). Silence pads the measurement to
#: it and the result is cut back, so the voice keeps its own length and word timings.
MIN_MEASURE_SECONDS = 3
_DURATION = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        raise ToolMissing("ffmpeg_missing") from None


def normalize_loudness(audio: bytes, media_type: str, *, ffmpeg: str = "ffmpeg") -> bytes:
    """`audio` at TARGET_LUFS, in the same format. A missing ffmpeg fails loud; audio ffmpeg
    cannot read, or a format it does not know, is kept as it came, with a warning."""
    known = _FORMATS.get(media_type.split(";")[0].strip().lower())
    if known is None:
        logger.warning("narration loudness skipped: unknown media type %s", media_type)
        return audio
    suffix, encoder = known
    target = f"I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
    pad = f"apad=whole_dur={MIN_MEASURE_SECONDS}"  # only a shorter voice gains silence
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / f"voice{suffix}"
        result = Path(work) / f"normalised{suffix}"
        source.write_bytes(audio)
        measured = _run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-i",
                str(source),
                "-af",
                f"{pad},loudnorm={target}:print_format=json",
                "-f",
                "null",
                "-",
            ]
        )
        try:
            # The JSON block is followed by ffmpeg's own progress lines.
            start = measured.stderr.rindex("{")
            stats = json.loads(measured.stderr[start : measured.stderr.index("}", start) + 1])
            second = (
                f"{pad},loudnorm={target}:measured_I={stats['input_i']}"
                f":measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}:linear=true"
            )
            found = _DURATION.search(measured.stderr)
            if found is None:
                raise ValueError("no duration")
            hours, minutes, seconds = found.groups()
            duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            if duration < MIN_MEASURE_SECONDS:
                second += f",atrim=end={duration:.3f}"  # back to the voice's own length
        except (ValueError, KeyError):
            logger.warning("narration loudness skipped: ffmpeg could not measure the voice")
            return audio
        # loudnorm works at 192 kHz internally: the voice keeps the provider's 44.1 kHz.
        written = _run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-af",
                second,
                "-ar",
                "44100",
                *encoder,
                str(result),
            ]
        )
        if written.returncode != 0 or not result.exists():
            logger.warning("narration loudness skipped: ffmpeg could not write the voice")
            return audio
        logger.debug("narration loudness from=%s LUFS to=%s LUFS", stats["input_i"], TARGET_LUFS)
        return result.read_bytes()
