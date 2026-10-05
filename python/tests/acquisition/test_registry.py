"""The registry maps a Python platform URL to its acquirer."""

from __future__ import annotations

import httpx
import pytest

from thoth_control_plane.acquisition.instagram_service import InstagramAcquirer
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.registry import acquirer_for
from thoth_control_plane.acquisition.service import TikTokAcquisitionService
from thoth_control_plane.acquisition.threads_service import ThreadsAcquirer
from thoth_control_plane.acquisition.x_service import XAcquirer


@pytest.mark.asyncio
async def test_acquirer_for_routes_tiktok_and_refuses_legacy_hosts() -> None:
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        acquirer = acquirer_for(
            "https://www.tiktok.com/@a/video/1234567", client=client, materializer=materializer
        )
        assert isinstance(acquirer, TikTokAcquisitionService)
        with pytest.raises(LookupError):
            acquirer_for("https://vimeo.com/123", client=client, materializer=materializer)
        threads = acquirer_for(
            "https://www.threads.net/@a/post/B", client=client, materializer=materializer
        )
        assert isinstance(threads, ThreadsAcquirer)
        instagram = acquirer_for(
            "https://www.instagram.com/p/code_001/", client=client, materializer=materializer
        )
        assert isinstance(instagram, InstagramAcquirer)
        x = acquirer_for(
            "https://x.com/user_001/status/1800000000000000001",
            client=client,
            materializer=materializer,
        )
        assert isinstance(x, XAcquirer)
