"""The registry maps a Python platform URL to its acquirer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from thoth_control_plane.acquisition import browser, registry, threads_service, youtube_service
from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.instagram_service import InstagramAcquirer
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.registry import acquirer_for
from thoth_control_plane.acquisition.service import TikTokAcquisitionService
from thoth_control_plane.acquisition.threads_service import ThreadsAcquirer
from thoth_control_plane.acquisition.x_service import XAcquirer
from thoth_control_plane.acquisition.youtube_service import YouTubeAcquirer


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
        youtube = acquirer_for(
            "https://youtu.be/abcDEF123_-", client=client, materializer=materializer
        )
        assert isinstance(youtube, YouTubeAcquirer)


COOKIES = parse_cookies(
    "instagram",
    "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
    now=datetime(2026, 10, 7, tzinfo=UTC),
)
PROXY = "http://u:p@1.2.3.4:8080"


@pytest.mark.asyncio
async def test_a_session_reaches_every_access_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, dict] = {}
    monkeypatch.setattr(
        registry, "_default_session_factory", lambda **kw: seen.setdefault("browser", kw)
    )
    monkeypatch.setattr(
        registry, "_default_factory", lambda options: seen.setdefault("yt", options)
    )

    async def fake_get(url: str, **kwargs: object) -> None:
        seen["request"] = kwargs

    monkeypatch.setattr(registry, "_scrapling_get", fake_get)
    access = SessionAccess(COOKIES, PROXY)
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        instagram = acquirer_for(
            "https://www.instagram.com/p/abc/",
            client=client,
            materializer=materializer,
            access=access,
        )
        await instagram._request._get("https://www.instagram.com/p/abc/", impersonate="chrome")
        instagram._headless._session_factory(headless=True, max_pages=1)
        youtube = acquirer_for(
            "https://youtu.be/abcDEF123_-",
            client=client,
            materializer=materializer,
            access=access,
            scratch=tmp_path,
        )
        youtube._client._factory({"quiet": True})
    assert seen["request"] == {
        "impersonate": "chrome",
        "cookies": {"sessionid": "s"},
        "proxy": PROXY,
    }
    assert seen["browser"]["headless"] is True
    assert seen["browser"]["proxy"] == {
        "server": "http://1.2.3.4:8080",
        "username": "u",
        "password": "p",
    }
    assert [c["name"] for c in seen["browser"]["cookies"]] == ["sessionid"]
    assert (seen["yt"]["quiet"], seen["yt"]["proxy"]) == (True, PROXY)
    assert Path(seen["yt"]["cookiefile"]).parent == tmp_path


@pytest.mark.asyncio
async def test_without_a_session_the_default_access_is_untouched() -> None:
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        instagram = acquirer_for(
            "https://www.instagram.com/p/abc/", client=client, materializer=materializer
        )
        youtube = acquirer_for(
            "https://youtu.be/abcDEF123_-", client=client, materializer=materializer
        )
    assert instagram._request._get is threads_service._scrapling_get
    assert instagram._headless._session_factory is browser._default_session_factory
    assert youtube._client._factory is youtube_service._default_factory


@pytest.mark.asyncio
async def test_a_yt_dlp_session_needs_a_scratch_directory() -> None:
    async with httpx.AsyncClient() as client:
        materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
        with pytest.raises(ValueError):
            acquirer_for(
                "https://youtu.be/abcDEF123_-",
                client=client,
                materializer=materializer,
                access=SessionAccess(COOKIES),
            )
