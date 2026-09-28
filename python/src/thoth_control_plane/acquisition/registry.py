"""Map a Python-platform source URL to the acquirer that inspects it."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import httpx

from thoth_control_plane.acquisition.adapters.tikwm import TikWmResolver
from thoth_control_plane.acquisition.browser import ScraplingHeadlessBrowser
from thoth_control_plane.acquisition.materializer import MediaMaterializer
from thoth_control_plane.acquisition.models import AcquisitionResult
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.acquisition.service import TikTokAcquisitionService
from thoth_control_plane.acquisition.threads_service import (
    ThreadsAcquirer,
    ThreadsHeadlessBrowser,
    ThreadsRequestFetcher,
)


class Acquirer(Protocol):
    """One platform's single-post acquisition; it owns and closes its own browser."""

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult: ...


def acquirer_for(
    source_url: str, *, client: httpx.AsyncClient, materializer: MediaMaterializer
) -> Acquirer:
    platform = platform_of(source_url)
    if platform == "tiktok":
        return TikTokAcquisitionService(
            ScraplingHeadlessBrowser(), TikWmResolver(client), materializer
        )
    if platform == "threads":
        return ThreadsAcquirer(ThreadsRequestFetcher(), ThreadsHeadlessBrowser(), materializer)
    raise LookupError("no python acquirer for this platform")
