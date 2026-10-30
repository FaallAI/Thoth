"""Local speech: faster-whisper transcripts and sherpa-onnx speaker turns, CPU only.

Both models are baked into the image and loaded once per worker; a missing package or model
file is an `AttributionError` (operator, 2026-10-13). Audio is decoded with PyAV, which
faster-whisper ships with; a video without an audio stream yields no speech.
"""

from __future__ import annotations

import asyncio
import functools
import multiprocessing
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from thoth_control_plane.attribution.ports import AttributionError, Segment, Transcript, Turn

SAMPLE_RATE = 16_000
WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json")
DIARIZATION_FILES = ("segmentation.onnx", "embedding.onnx")
CLUSTER_THRESHOLD = 0.5


def missing(directory: Path, names: Sequence[str]) -> bool:
    return not all((directory / name).is_file() for name in names)


def load_audio(
    video: Path, seconds: float, failure: str, missing_code: str = "whisper_missing"
) -> Any:
    """Mono 16 kHz float32 samples of the first `seconds`; empty without an audio stream.

    The transcriber and the diarizer read the same video, so one decode serves both; it stops
    at `seconds` instead of decoding the whole track. Callers must not modify the array.
    """
    try:
        return _decode(str(video), video.stat().st_mtime_ns, seconds)
    except ImportError:
        raise AttributionError(missing_code) from None
    except Exception as error:
        raise AttributionError(failure) from error


@functools.lru_cache(maxsize=2)
def _decode(path: str, modified_ns: int, seconds: float) -> Any:
    import av
    import numpy as np

    limit = int(seconds * SAMPLE_RATE)
    chunks: list[Any] = []
    total = 0
    with av.open(path) as container:
        if not container.streams.audio:
            return np.zeros(0, dtype=np.float32)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                samples = resampled.to_ndarray().reshape(-1)
                chunks.append(samples)
                total += samples.size
            if total >= limit:
                break
    audio = (
        np.concatenate(chunks)[:limit].astype(np.float32) / 32768.0
        if chunks
        else np.zeros(0, dtype=np.float32)
    )
    audio.flags.writeable = False  # shared by the transcriber and the diarizer
    return audio


class WhisperTranscriber:
    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def transcribe(self, video: Path, *, seconds: float) -> Transcript:
        # ponytail: one transcription per worker; a pool if throughput matters
        async with self._lock:
            return await asyncio.to_thread(self._transcribe, video, seconds)

    def _load(self) -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise AttributionError("whisper_missing") from None
        if missing(self._dir, WHISPER_FILES):
            raise AttributionError("whisper_model_missing")
        if self._model is None:
            try:
                self._model = WhisperModel(
                    str(self._dir), device="cpu", compute_type="int8", local_files_only=True
                )
            except Exception as error:
                raise AttributionError("whisper_model_missing") from error
        return self._model

    def _transcribe(self, video: Path, seconds: float) -> Transcript:
        model = self._load()
        audio = load_audio(video, seconds, "transcription_failed")
        if audio.size == 0:
            return Transcript("")
        try:
            segments, info = model.transcribe(audio, vad_filter=True, beam_size=5)
            parts = tuple(
                Segment(segment.start, segment.end, segment.text.strip())
                for segment in segments
                if segment.text.strip()
            )
        except Exception as error:
            raise AttributionError("transcription_failed") from error
        return Transcript(info.language, parts)


class SherpaDiarizer:
    """Speaker turns, computed in a child process.

    sherpa-onnx holds the GIL through `process()`; in a thread it stalled the worker's event loop
    for 45.8 s on stage1 (2026-10-30), past Temporal's task deadlines. One spawned process keeps
    the engine loaded between calls, and the worker's loop stays free.
    """

    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._lock = asyncio.Lock()
        self._pool: ProcessPoolExecutor | None = None

    async def turns(self, video: Path, *, seconds: float) -> list[Turn]:
        async with self._lock:
            if self._pool is None:
                # spawn, not fork: the worker runs threads, and a forked copy of them is unsafe.
                self._pool = ProcessPoolExecutor(
                    max_workers=1, mp_context=multiprocessing.get_context("spawn")
                )
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(
                    self._pool, _diarize, str(self._dir), str(video), seconds
                )
            except BrokenProcessPool:
                # The child died (out of memory, a native crash): start a fresh one next time.
                self._pool = None
                raise AttributionError("diarization_failed") from None


@functools.cache
def _diarization_engine(model_dir: str) -> Any:
    """One engine per child process, built on its first call."""
    try:
        import sherpa_onnx
    except ImportError:
        raise AttributionError("diarization_missing") from None
    directory = Path(model_dir)
    if missing(directory, DIARIZATION_FILES):
        raise AttributionError("diarization_model_missing")
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(directory / "segmentation.onnx")
            )
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(directory / "embedding.onnx")
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=CLUSTER_THRESHOLD),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise AttributionError("diarization_model_missing")
    try:
        return sherpa_onnx.OfflineSpeakerDiarization(config)
    except Exception as error:
        raise AttributionError("diarization_model_missing") from error


def _diarize(model_dir: str, video: str, seconds: float) -> list[Turn]:
    """Runs in the child process; arguments and results cross the process boundary pickled."""
    engine = _diarization_engine(model_dir)
    audio = load_audio(Path(video), seconds, "diarization_failed", "diarization_missing")
    if audio.size == 0:
        return []
    try:
        result = engine.process(audio).sort_by_start_time()
    except Exception as error:
        raise AttributionError("diarization_failed") from error
    return [Turn(item.start, item.end, int(item.speaker)) for item in result]
