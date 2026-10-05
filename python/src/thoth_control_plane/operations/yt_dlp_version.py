"""How far the installed yt-dlp is behind PyPI.

yt-dlp releases often, and YouTube changes often; a stale yt-dlp fails YouTube extraction.
The worker calls `check_freshness` once at startup and warns when it is behind; the daily
`.github/workflows/yt-dlp-update.yml` bumps the pin. Nothing here installs anything.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from importlib import metadata

import httpx

logger = logging.getLogger(__name__)
PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
TIMEOUT_SECONDS = 5.0


def parse_version(text: object) -> tuple[int, ...] | None:
    """yt-dlp's date versions: `2026.8.19`, `2026.08.19`, or `2026.08.19.1`."""
    if not isinstance(text, str):
        return None
    parts = text.split(".")
    if not 3 <= len(parts) <= 4 or not all(p.isascii() and p.isdecimal() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_behind(installed: object, latest: object) -> bool:
    current, newest = parse_version(installed), parse_version(latest)
    return current is not None and newest is not None and current < newest


def latest_from_pypi(payload: object) -> str | None:
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return version if parse_version(version) is not None else None


def installed_version() -> str | None:
    """From package metadata: importing yt_dlp at worker startup would be slow."""
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return None


async def _fetch_json(url: str) -> object:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def check_freshness(
    fetch: Callable[[str], Awaitable[object]] | None = None,
    installed: str | None = None,
) -> bool | None:
    """True when behind (and warn), False when current, None when unknown. Never raises."""
    current = installed or installed_version()
    if current is None:
        return None
    try:
        payload = await asyncio.wait_for((fetch or _fetch_json)(PYPI_URL), TIMEOUT_SECONDS)
    except Exception:
        logger.info("yt-dlp freshness unknown: pypi unreachable")
        return None
    latest = latest_from_pypi(payload)
    if latest is None:
        return None
    behind = is_behind(current, latest)
    if behind:
        logger.warning(
            "yt-dlp is behind pypi installed=%s latest=%s; the daily update workflow bumps it",
            current,
            latest,
        )
    return behind
