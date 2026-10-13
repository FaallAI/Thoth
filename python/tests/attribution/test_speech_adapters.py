"""faster-whisper and sherpa-onnx on clips made by ffmpeg; a missing model is an error."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from thoth_control_plane.attribution.ports import AttributionError

FFMPEG = shutil.which("ffmpeg")


def _required(variable: str) -> Path:
    # Operator, 2026-10-11/13: a missing tool or model fails the test, never a skip.
    value = os.environ.get(variable)
    if not value or not Path(value).is_dir():
        pytest.fail(f"{variable} must point to the fetched test models (plan Task 2)")
    return Path(value)


@pytest.fixture
def whisper_dir() -> Path:
    return _required("THOTH_TEST_WHISPER_MODEL_DIR")


@pytest.fixture
def diarization_dir() -> Path:
    return _required("THOTH_TEST_DIARIZATION_MODEL_DIR")


def _clip(tmp_path: Path, *, audio: bool) -> Path:
    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    video = tmp_path / ("silent.mp4" if audio else "mute.mp4")
    argv = [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=3:r=25"]
    if audio:
        argv += ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3", "-shortest"]
    subprocess.run([*argv, "-pix_fmt", "yuv420p", str(video)], check=True)
    return video


@pytest.mark.asyncio
async def test_silence_is_an_empty_transcript_and_no_turns(
    tmp_path: Path, whisper_dir: Path, diarization_dir: Path
) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    video = _clip(tmp_path, audio=True)

    transcript = await WhisperTranscriber(whisper_dir).transcribe(video, seconds=180)
    turns = await SherpaDiarizer(diarization_dir).turns(video, seconds=180)

    assert transcript.segments == () and turns == []


@pytest.mark.asyncio
async def test_a_video_without_audio_is_an_empty_transcript(
    tmp_path: Path, whisper_dir: Path, diarization_dir: Path
) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    video = _clip(tmp_path, audio=False)

    assert (await WhisperTranscriber(whisper_dir).transcribe(video, seconds=180)).segments == ()
    assert await SherpaDiarizer(diarization_dir).turns(video, seconds=180) == []


@pytest.mark.asyncio
async def test_a_missing_model_directory_is_its_own_code(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    video = tmp_path / "x.mp4"
    with pytest.raises(AttributionError) as whisper:
        await WhisperTranscriber(tmp_path / "none").transcribe(video, seconds=180)
    with pytest.raises(AttributionError) as diarization:
        await SherpaDiarizer(tmp_path / "none").turns(video, seconds=180)
    assert (whisper.value.code, diarization.value.code) == (
        "whisper_model_missing",
        "diarization_model_missing",
    )


@pytest.mark.asyncio
async def test_an_unreadable_video_is_a_transcription_failure(
    tmp_path: Path, whisper_dir: Path
) -> None:
    from thoth_control_plane.attribution.adapters.speech import WhisperTranscriber

    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")

    with pytest.raises(AttributionError) as raised:
        await WhisperTranscriber(whisper_dir).transcribe(broken, seconds=180)
    assert raised.value.code == "transcription_failed"
