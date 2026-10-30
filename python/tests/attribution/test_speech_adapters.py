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


@pytest.mark.asyncio
async def test_a_corrupt_model_is_a_model_code(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer, WhisperTranscriber

    whisper = tmp_path / "whisper"
    diarization = tmp_path / "diarization"
    whisper.mkdir()
    diarization.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (whisper / name).write_bytes(b"not a model")
    for name in ("segmentation.onnx", "embedding.onnx"):
        (diarization / name).write_bytes(b"not a model")
    video = _clip(tmp_path, audio=True)

    with pytest.raises(AttributionError) as transcriber:
        await WhisperTranscriber(whisper).transcribe(video, seconds=180)
    with pytest.raises(AttributionError) as diarizer:
        await SherpaDiarizer(diarization).turns(video, seconds=180)
    assert (transcriber.value.code, diarizer.value.code) == (
        "whisper_model_missing",
        "diarization_model_missing",
    )


def test_audio_is_decoded_once_and_only_its_first_seconds(tmp_path: Path) -> None:
    from thoth_control_plane.attribution.adapters.speech import SAMPLE_RATE, load_audio

    video = _clip(tmp_path, audio=True)

    first = load_audio(video, 1.0, "transcription_failed")
    again = load_audio(video, 1.0, "diarization_failed")

    assert first is again  # the transcriber and the diarizer share one decode
    assert abs(first.size - SAMPLE_RATE) <= SAMPLE_RATE // 10


@pytest.mark.asyncio
async def test_diarization_leaves_the_event_loop_free(
    tmp_path: Path, diarization_dir: Path
) -> None:
    """Stage1, 2026-10-30: sherpa-onnx held the GIL through `process()` and stalled the worker's
    event loop for 45.8 s (TMPRL1104, expired queries). Diarization must run off this process."""
    import asyncio
    import time

    from thoth_control_plane.attribution.adapters.speech import SherpaDiarizer

    if FFMPEG is None:
        pytest.fail("ffmpeg is required for this test and is not installed")
    audio = tmp_path / "noise.wav"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=60:c=pink:a=0.3",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio),
        ],
        check=True,
    )
    diarizer = SherpaDiarizer(diarization_dir)
    await diarizer.turns(audio, seconds=1)  # load the engine first; only the work is measured
    worst, done = 0.0, False

    async def watch() -> None:
        nonlocal worst
        last = time.monotonic()
        while not done:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            worst, last = max(worst, now - last - 0.02), now

    watcher = asyncio.create_task(watch())
    await diarizer.turns(audio, seconds=60)
    done = True
    await watcher
    assert worst < 0.5, f"the event loop stalled for {worst:.2f} s"
