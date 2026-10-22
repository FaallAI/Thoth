"""The main creator's listing for footage (spec 2026-10-22 5c-2, G3), over ProfileDiscoverer.

A blocked or failed listing is None: the run goes on with search footage. A missing tool is an
explicit error, as everywhere else.
"""

from __future__ import annotations

import logging
from typing import Any

from thoth_control_plane.attribution.adapters.discovery import CreatorListing
from thoth_control_plane.attribution.adapters.frames import ToolMissing

logger = logging.getLogger(__name__)


class CreatorListings:
    def __init__(self, discoverer: Any) -> None:
        self._discoverer = discoverer

    async def listing_of(self, platform: str, handle: str, limit: int) -> CreatorListing | None:
        try:
            return await self._discoverer.creator(platform, handle, limit)
        except ToolMissing:
            raise
        except Exception as error:
            logger.warning(
                "creator listing unavailable platform=%s error=%s", platform, type(error).__name__
            )
            return None
