"""Local speech: faster-whisper transcripts and sherpa-onnx speaker turns, CPU only.

Both models are baked into the image and loaded once per worker; a missing package or model
file is an `AttributionError` (operator, 2026-10-13). Audio is decoded with PyAV, which
faster-whisper ships with; a video without an audio stream yields no speech.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.attribution.ports import AttributionError, Segment, Transcript, Turn

SAMPLE_RATE = 16_000
WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json")
DIARIZATION_FILES = ("segmentation.onnx", "embedding.onnx")
CLUSTER_THRESHOLD = 0.5


def missing(directory: Path, names: Sequence[str]) -> bool:
    return not all((directory / name).is_file() for name in names)


def _audio(video: Path, seconds: float, failure: str) -> Any:
    """Mono 16 kHz float32 samples of the first `seconds`; empty without an audio stream."""
    try:
        import av
        import numpy as np
        from faster_whisper import decode_audio
    except ImportError:
        raise AttributionError("whisper_missing") from None
    try:
        with av.open(str(video)) as container:
            if not container.streams.audio:
                return np.zeros(0, dtype=np.float32)
        audio = decode_audio(str(video), sampling_rate=SAMPLE_RATE)
    except Exception as error:
        raise AttributionError(failure) from error
    return audio[: int(seconds * SAMPLE_RATE)]


class WhisperTranscriber:
    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def transcribe(self, video: Path, *, seconds: float) -> Transcript:
        async with (
            self._lock
        ):  # ponytail: one transcription per worker; a pool if throughput matters
            return await asyncio.to_thread(self._transcribe, video, seconds)

    def _load(self) -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise AttributionError("whisper_missing") from None
        if missing(self._dir, WHISPER_FILES):
            raise AttributionError("whisper_model_missing")
        if self._model is None:
            self._model = WhisperModel(
                str(self._dir), device="cpu", compute_type="int8", local_files_only=True
            )
        return self._model

    def _transcribe(self, video: Path, seconds: float) -> Transcript:
        model = self._load()
        audio = _audio(video, seconds, "transcription_failed")
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
    def __init__(self, model_dir: Path) -> None:
        self._dir = model_dir
        self._engine: Any = None
        self._lock = asyncio.Lock()

    async def turns(self, video: Path, *, seconds: float) -> list[Turn]:
        async with self._lock:
            return await asyncio.to_thread(self._turns, video, seconds)

    def _load(self) -> Any:
        try:
            import sherpa_onnx
        except ImportError:
            raise AttributionError("diarization_missing") from None
        if missing(self._dir, DIARIZATION_FILES):
            raise AttributionError("diarization_model_missing")
        if self._engine is None:
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(self._dir / "segmentation.onnx")
                    )
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(self._dir / "embedding.onnx")
                ),
                clustering=sherpa_onnx.FastClusteringConfig(
                    num_clusters=-1, threshold=CLUSTER_THRESHOLD
                ),
                min_duration_on=0.3,
                min_duration_off=0.5,
            )
            if not config.validate():
                raise AttributionError("diarization_model_missing")
            self._engine = sherpa_onnx.OfflineSpeakerDiarization(config)
        return self._engine

    def _turns(self, video: Path, seconds: float) -> list[Turn]:
        engine = self._load()
        audio = _audio(video, seconds, "diarization_failed")
        if audio.size == 0:
            return []
        try:
            result = engine.process(audio).sort_by_start_time()
        except Exception as error:
            raise AttributionError("diarization_failed") from error
        return [Turn(item.start, item.end, int(item.speaker)) for item in result]
