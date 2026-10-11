"""Tests asserting worker startup ordering for provider log redaction."""

from __future__ import annotations

import asyncio

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
        await worker.run_worker(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"))
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
        await worker.run_worker(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"))
    await asyncio.sleep(0)
    assert cancelled == [True]


def test_assembly_refuses_to_start_without_ffmpeg() -> None:
    from thoth_control_plane.config import SettingsValidationError

    off = Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_FFMPEG="/nonexistent/ffmpeg")
    worker.check_media_tools(off)  # assembly off: nothing to check

    on = off.model_copy(update={"THOTH_CONTENT_ASSEMBLY_ENABLED": True})
    with pytest.raises(SettingsValidationError, match="ffmpeg_missing"):
        worker.check_media_tools(on)
    probe_missing = on.model_copy(
        update={"THOTH_FFMPEG": "ffmpeg", "THOTH_FFPROBE": "/nonexistent/ffprobe"}
    )
    with pytest.raises(SettingsValidationError, match="ffprobe_missing"):
        worker.check_media_tools(probe_missing)
