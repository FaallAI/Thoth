"""The creator photo fetcher (spec 5c-2, G4): an image or nothing, never an oversized body."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from thoth_control_plane.footage.adapters.photos import (
    MAX_PHOTO_BYTES,
    HttpPhotoFetcher,
    PhotoError,
)

URL = "https://p16.example/photo.jpeg"


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buffer, "JPEG")
    return buffer.getvalue()


def _fetcher(body: bytes, status: int = 200) -> HttpPhotoFetcher:
    return HttpPhotoFetcher(
        httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    )


@pytest.mark.asyncio
async def test_a_photo_is_written_with_the_suffix_of_its_format(tmp_path: Path) -> None:
    path = await _fetcher(_jpeg()).fetch(URL, tmp_path / "photo-1")
    assert path == tmp_path / "photo-1.jpg"
    assert Image.open(path).format == "JPEG"


@pytest.mark.asyncio
async def test_photo_fetch_refuses_non_images(tmp_path: Path) -> None:
    with pytest.raises(PhotoError):
        await _fetcher(b"<html>login</html>").fetch(URL, tmp_path / "photo-1")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_photo_fetch_caps_size(tmp_path: Path) -> None:
    with pytest.raises(PhotoError):
        await _fetcher(_jpeg() + b"\0" * MAX_PHOTO_BYTES).fetch(URL, tmp_path / "photo-1")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_failed_request_is_a_photo_error(tmp_path: Path) -> None:
    with pytest.raises(PhotoError):
        await _fetcher(b"", status=403).fetch(URL, tmp_path / "photo-1")


@pytest.mark.asyncio
async def test_a_decompression_bomb_is_a_photo_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(PhotoError):
        await _fetcher(_jpeg()).fetch(URL, tmp_path / "photo-1")
    assert list(tmp_path.iterdir()) == []
