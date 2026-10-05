"""`MediaMaterializer.adopt`: a local file gets the same validation as a download."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import httpx
import pytest

from thoth_control_plane.acquisition import materializer as materializer_module
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.models import AcquisitionStrategy

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20_000
LOCATION = PurePosixPath("reports/wf_yt_001/media/youtube-abc-1")


async def _adopt(tmp_path: Path, payload: bytes | None, **kwargs) -> tuple[object, Path]:
    source = tmp_path / "download" / "merged.mp4"
    source.parent.mkdir(parents=True)
    if payload is not None:
        source.write_bytes(payload)
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        result = await materializer.adopt(
            source,
            tmp_path / LOCATION,
            LOCATION,
            AcquisitionStrategy.YT_DLP,
            duration_seconds=12.5,
            **kwargs,
        )
    return result, source


@pytest.mark.asyncio
async def test_a_valid_mp4_is_placed_and_described(tmp_path: Path) -> None:
    result, source = await _adopt(tmp_path, MP4)
    assert result.location == LOCATION.with_suffix(".mp4")
    assert (result.media_type, result.bytes, result.kind) == ("video/mp4", len(MP4), "video")
    assert result.checksum == "sha256:" + hashlib.sha256(MP4).hexdigest()
    assert result.acquisition_strategy is AcquisitionStrategy.YT_DLP
    assert result.duration_seconds == 12.5
    assert (tmp_path / LOCATION.with_suffix(".mp4")).read_bytes() == MP4
    assert not source.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [b"<html>not a video</html>" + b"\x00" * 20_000, MP4[:5_000], b"", None],
)
async def test_a_bad_file_is_rejected_and_removed(tmp_path: Path, payload: bytes | None) -> None:
    with pytest.raises(MediaMaterializationError):
        await _adopt(tmp_path, payload)
    assert not (tmp_path / "download" / "merged.mp4").exists()
    assert not (tmp_path / LOCATION.with_suffix(".mp4")).exists()


@pytest.mark.asyncio
async def test_a_file_over_the_bound_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(materializer_module.MEDIA_BYTE_BOUNDS, "video", (10, 1_000))
    with pytest.raises(MediaMaterializationError):
        await _adopt(tmp_path, MP4)
    assert not (tmp_path / "download" / "merged.mp4").exists()


@pytest.mark.asyncio
async def test_an_image_kind_must_be_an_image(tmp_path: Path) -> None:
    with pytest.raises(MediaMaterializationError):
        await _adopt(tmp_path, MP4, kind="image")
