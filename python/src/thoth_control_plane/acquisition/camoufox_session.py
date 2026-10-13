"""Camoufox (Firefox patched at the C level) shaped like the Scrapling sessions we use.

Spec 2026-10-13, section 3.4: only the sessions that need `url`, `status`, and `body` use it
(signed-in Instagram reels discovery). The account's Firefox fingerprint (fpgen), its Camoufox
profile, locale, and timezone stay the same on every visit. The timezone is the account's own,
never looked up from the proxy's IP.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from thoth_control_plane.attribution.adapters.frames import ToolMissing


def _camoufox() -> Any:
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        raise ToolMissing("camoufox_missing") from None
    return AsyncCamoufox


class CamoufoxSession:
    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._manager: Any = None
        self._context: Any = None

    async def __aenter__(self) -> CamoufoxSession:
        get = self._kwargs.get
        options: dict[str, Any] = {
            "headless": get("headless", True),
            "persistent_context": True,
            "user_data_dir": get("user_data_dir"),
            "locale": get("locale"),
            "proxy": get("proxy"),
            "fingerprint": get("fingerprint"),
            "config": {"timezone": get("timezone_id")} if get("timezone_id") else None,
            "geoip": False,
        }
        self._manager = _camoufox()(**{k: v for k, v in options.items() if v is not None})
        self._context = await self._manager.__aenter__()
        try:
            if get("cookies"):
                await self._context.add_cookies(get("cookies"))
        except BaseException as error:
            await self._manager.__aexit__(type(error), error, error.__traceback__)
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._manager.__aexit__(*exc)

    async def fetch(
        self, url: str, *, page_setup: Any = None, page_action: Any = None, timeout: int = 90_000
    ) -> SimpleNamespace:
        page = await self._context.new_page()
        if page_setup is not None:
            await page_setup(page)
        response = await page.goto(url, timeout=timeout)
        if page_action is not None:
            await page_action(page)
        return SimpleNamespace(
            url=page.url,
            status=getattr(response, "status", None),
            body=(await page.content()).encode(),
        )
