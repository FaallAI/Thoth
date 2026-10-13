"""Tests asserting worker startup ordering for provider log redaction."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane import worker
from thoth_control_plane.config import Settings


class _StopWorker(Exception):
    """Sentinel raised to stop `run_worker` right after the capability check."""


@pytest.mark.asyncio
async def test_worker_configures_provider_logging_before_capability_check(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(worker, "configure_provider_logging", lambda: calls.append("logging"))

    async def capability():
        calls.append("capability")
        raise _StopWorker

    monkeypatch.setattr(worker, "check_scrapling_capability", capability)
    with pytest.raises(_StopWorker):
        await worker.run_worker(
            Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SOURCE_ATTRIBUTION_ENABLED=False)
        )
    assert calls == ["logging", "capability"]


@pytest.mark.asyncio
async def test_the_yt_dlp_check_runs_in_the_background_and_stops_with_the_worker(
    monkeypatch,
) -> None:
    started = asyncio.Event()
    cancelled: list[bool] = []

    async def capability():
        return None

    async def freshness():
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def connect(*args, **kwargs):
        await started.wait()
        raise _StopWorker

    monkeypatch.setattr(worker, "configure_provider_logging", lambda: None)
    monkeypatch.setattr(worker, "check_scrapling_capability", capability)
    monkeypatch.setattr(worker, "check_freshness", freshness)
    monkeypatch.setattr(worker.Client, "connect", connect)
    with pytest.raises(_StopWorker):
        await worker.run_worker(
            Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_SOURCE_ATTRIBUTION_ENABLED=False)
        )
    await asyncio.sleep(0)
    assert cancelled == [True]


def test_assembly_refuses_to_start_without_ffmpeg() -> None:
    from thoth_control_plane.config import SettingsValidationError

    off = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_FFMPEG="/nonexistent/ffmpeg",
        THOTH_SOURCE_ATTRIBUTION_ENABLED=False,
    )
    worker.check_media_tools(off)  # assembly off: nothing to check

    on = off.model_copy(update={"THOTH_CONTENT_ASSEMBLY_ENABLED": True})
    with pytest.raises(SettingsValidationError, match="ffmpeg_missing"):
        worker.check_media_tools(on)
    probe_missing = on.model_copy(
        update={"THOTH_FFMPEG": "ffmpeg", "THOTH_FFPROBE": "/nonexistent/ffprobe"}
    )
    with pytest.raises(SettingsValidationError, match="ffprobe_missing"):
        worker.check_media_tools(probe_missing)


def test_assembly_refuses_to_start_without_rapidocr(monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane.config import SettingsValidationError

    monkeypatch.setattr(worker, "find_spec", lambda name: None)
    on = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_CONTENT_ASSEMBLY_ENABLED=True,
        THOTH_SOURCE_ATTRIBUTION_ENABLED=False,
        THOTH_FFMPEG="sh",
        THOTH_FFPROBE="sh",
    )
    with pytest.raises(SettingsValidationError, match="rapidocr_missing"):
        worker.check_media_tools(on)


def test_assembly_refuses_to_start_without_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane.config import SettingsValidationError

    monkeypatch.setattr(worker, "find_spec", lambda name: None if name == "cv2" else object())
    on = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_CONTENT_ASSEMBLY_ENABLED=True,
        THOTH_SOURCE_ATTRIBUTION_ENABLED=False,
        THOTH_FFMPEG="sh",
        THOTH_FFPROBE="sh",
    )
    with pytest.raises(SettingsValidationError, match="opencv_missing"):
        worker.check_media_tools(on)


def _attribution_settings(tmp_path: Path, **overrides: Any) -> Settings:
    whisper = tmp_path / "whisper"
    diarization = tmp_path / "diarization"
    whisper.mkdir(exist_ok=True)
    diarization.mkdir(exist_ok=True)
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (whisper / name).write_bytes(b"x")
    for name in ("segmentation.onnx", "embedding.onnx"):
        (diarization / name).write_bytes(b"x")
    values: dict[str, Any] = {
        "THOTH_CONTROL_PLANE_API_KEY": "test-only",
        "THOTH_SOURCE_ATTRIBUTION_ENABLED": True,
        "THOTH_OPENROUTER_API_KEY": "synthetic-key",
        "THOTH_WHISPER_MODEL_DIR": whisper,
        "THOTH_DIARIZATION_MODEL_DIR": diarization,
    }
    return Settings(**{**values, **overrides})


def test_attribution_starts_with_every_tool_present(tmp_path: Path) -> None:
    worker.check_media_tools(_attribution_settings(tmp_path))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"THOTH_OPENROUTER_API_KEY": None}, "openrouter_key_missing"),
        ({"THOTH_FFMPEG": "/nonexistent/ffmpeg"}, "ffmpeg_missing"),
        ({"THOTH_FFPROBE": "/nonexistent/ffprobe"}, "ffprobe_missing"),
        ({"THOTH_WHISPER_MODEL_DIR": Path("/nonexistent")}, "whisper_model_missing"),
        ({"THOTH_DIARIZATION_MODEL_DIR": Path("/nonexistent")}, "diarization_model_missing"),
    ],
)
def test_attribution_refuses_to_start_without_a_tool(
    tmp_path: Path, change: dict[str, Any], code: str
) -> None:
    from thoth_control_plane.config import SettingsValidationError

    with pytest.raises(SettingsValidationError, match=code):
        worker.check_media_tools(_attribution_settings(tmp_path, **change))


@pytest.mark.parametrize(
    ("module", "code"),
    [
        ("faster_whisper", "whisper_missing"),
        ("sherpa_onnx", "diarization_missing"),
        ("rapidocr", "rapidocr_missing"),
        ("cv2", "opencv_missing"),
        ("PIL", "pillow_missing"),
        ("camoufox", "camoufox_missing"),
    ],
)
def test_attribution_refuses_to_start_without_a_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, code: str
) -> None:
    from thoth_control_plane.config import SettingsValidationError

    real = worker.find_spec
    monkeypatch.setattr(worker, "find_spec", lambda name: None if name == module else real(name))

    with pytest.raises(SettingsValidationError, match=code):
        worker.check_media_tools(_attribution_settings(tmp_path))
