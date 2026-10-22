"""Fetch one creator photo (spec 2026-10-22 5c-2, G4): a checked image file or a PhotoError.

The link is the platform's own ephemeral CDN URL from the profile listing; it is used once and
never stored. A body that is not a JPEG, PNG or WebP image, or that runs past MAX_PHOTO_BYTES,
leaves nothing behind.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx

MAX_PHOTO_BYTES = 10 * 1024 * 1024
TIMEOUT_SECONDS = 20.0
SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class PhotoError(RuntimeError):
    """The photo could not be fetched as a usable image."""


class HttpPhotoFetcher:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, url: str, target: Path) -> Path:
        """Write the photo next to `target`, suffixed by its format, and return its path."""
        body = bytearray()
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport, timeout=TIMEOUT_SECONDS, follow_redirects=True
                ) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code != 200:
                    raise PhotoError(f"status {response.status_code}")
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_PHOTO_BYTES:
                        raise PhotoError("too large")
        except httpx.HTTPError as error:
            raise PhotoError(type(error).__name__) from None
        suffix = _image_suffix(bytes(body))
        path = target.with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path


def _image_suffix(body: bytes) -> str:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
            kind = image.format or ""
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise PhotoError("not an image") from None
    if kind not in SUFFIXES:
        raise PhotoError("unsupported image format")
    return SUFFIXES[kind]
