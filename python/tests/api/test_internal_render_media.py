"""The renderer's media routes: assets in, the finished render out (spec 2026-10-17)."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from tests.api.test_internal_render_jobs import (
    CREATOR_HEADERS,
    INTERNAL_HEADERS,
    internal_settings,
    render_job,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.application.render_job_ports import (
    ArtifactUnavailable,
    ReceivedOutput,
    RenderJobNotFound,
    RenderOutputTooLarge,
)
from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable

ASSET_URL = "/internal/render-jobs/rj_001/assets/asset_main"
OUTPUT_URL = "/internal/render-jobs/rj_001/output"
ASSET = b"\x00\x00\x00\x18ftypmp42clip-bytes"


class MediaService:
    """The two media calls the routes make, with one fixed failure each when set."""

    def __init__(
        self,
        *,
        asset_error: Exception | None = None,
        output_error: Exception | None = None,
        max_bytes: int = 1024,
    ) -> None:
        self.job = render_job()
        self.asset_error = asset_error
        self.output_error = output_error
        self.max_bytes = max_bytes
        self.received: list[bytes] = []

    async def asset_location(self, render_job_id: str, asset_id: str) -> str:
        if self.asset_error is not None:
            raise self.asset_error
        if asset_id != "asset_main":
            raise ArtifactUnavailable()
        return "uploads/project_001/asset_main.mp4"

    def object_size(self, location: str) -> int:
        return len(ASSET)

    def read_object(self, location: str, start: int, end: int | None):
        yield ASSET[start : None if end is None else end + 1]

    async def receive_output(self, render_job_id: str, chunks) -> ReceivedOutput:
        if self.output_error is not None:
            raise self.output_error
        body = b""
        async for chunk in chunks:
            body += chunk
            if len(body) > self.max_bytes:
                raise RenderOutputTooLarge()
        self.received.append(body)
        import hashlib

        return ReceivedOutput(
            size_bytes=len(body), checksum="sha256:" + hashlib.sha256(body).hexdigest()
        )

    async def reconcile_expired(self, now: datetime) -> int:
        return 0


def client(gateway, service: MediaService) -> httpx.AsyncClient:
    app = create_app(internal_settings(), gateway, render_job_service=service)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_an_asset_in_the_bundle_streams_with_its_length(gateway) -> None:
    async with client(gateway, MediaService()) as http:
        response = await http.get(ASSET_URL, headers=INTERNAL_HEADERS)

    assert response.status_code == 200
    assert response.content == ASSET
    assert response.headers["content-length"] == str(len(ASSET))


@pytest.mark.asyncio
async def test_an_asset_outside_the_bundle_is_not_served(gateway) -> None:
    async with client(gateway, MediaService()) as http:
        response = await http.get(
            "/internal/render-jobs/rj_001/assets/asset_other", headers=INTERNAL_HEADERS
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "render_asset_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [ASSET_URL, OUTPUT_URL])
async def test_the_media_routes_refuse_the_creator_key_and_a_missing_credential(
    gateway, url: str
) -> None:
    service = MediaService()
    async with client(gateway, service) as http:
        for headers in ({}, CREATOR_HEADERS):
            response = await http.request(
                "GET" if url == ASSET_URL else "PUT", url, headers=headers, content=b"x"
            )
            assert response.status_code == 403
    assert service.received == []


@pytest.mark.asyncio
async def test_output_upload_answers_its_size_and_checksum(gateway) -> None:
    service = MediaService()
    async with client(gateway, service) as http:
        response = await http.put(OUTPUT_URL, headers=INTERNAL_HEADERS, content=b"render")

    assert response.status_code == 200
    assert response.json()["size_bytes"] == 6
    assert response.json()["checksum"].startswith("sha256:")
    assert service.received == [b"render"]


@pytest.mark.asyncio
async def test_an_oversized_output_is_413(gateway) -> None:
    async with client(gateway, MediaService(max_bytes=4)) as http:
        response = await http.put(OUTPUT_URL, headers=INTERNAL_HEADERS, content=b"too-large")

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "render_output_too_large"


@pytest.mark.asyncio
async def test_output_upload_for_an_unknown_job_is_404(gateway) -> None:
    async with client(gateway, MediaService(output_error=RenderJobNotFound())) as http:
        response = await http.put(OUTPUT_URL, headers=INTERNAL_HEADERS, content=b"render")

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["asset", "output"])
async def test_a_store_outage_is_503(gateway, route: str) -> None:
    outage = MediaStoreUnavailable("media_store_unavailable")
    service = MediaService(asset_error=outage, output_error=outage)
    async with client(gateway, service) as http:
        if route == "asset":
            response = await http.get(ASSET_URL, headers=INTERNAL_HEADERS)
        else:
            response = await http.put(OUTPUT_URL, headers=INTERNAL_HEADERS, content=b"render")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "media_store_unavailable"


@pytest.mark.asyncio
async def test_the_asset_is_read_off_the_event_loop_thread(gateway) -> None:
    import threading

    loop_thread = threading.get_ident()
    threads: list[int] = []

    class Watching(MediaService):
        def read_object(self, location: str, start: int, end: int | None):
            threads.append(threading.get_ident())
            return super().read_object(location, start, end)

    async with client(gateway, Watching()) as http:
        response = await http.get(ASSET_URL, headers=INTERNAL_HEADERS)

    assert response.content == ASSET
    assert threads and all(thread != loop_thread for thread in threads)
