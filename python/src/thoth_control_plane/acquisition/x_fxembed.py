"""The FxEmbed (FxTwitter API) client: X posts, replies, and profile media, signed out.

The base URL is `THOTH_X_FXEMBED_URL` (default the public API), so moving to a self-hosted
instance is one environment value. Never raises past `RequestFetchError`; a missing post or an
unreadable body is None, and every refusal is logged with its HTTP status.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from thoth_control_plane.acquisition.browser import _is_timeout
from thoth_control_plane.acquisition.models import AcquisitionReason
from thoth_control_plane.acquisition.threads_service import RequestFetchError, _scrapling_get

logger = logging.getLogger(__name__)

DEFAULT_FXEMBED_URL = "https://api.fxtwitter.com"
USER_AGENT = "Thoth/1.0 (+https://github.com/FaallAI/Thoth)"
# A plain API: no browser impersonation, an honest User-Agent.
OPTIONS: dict[str, Any] = {
    "timeout": 30,
    "retries": 1,
    "follow_redirects": "safe",
    "headers": {"User-Agent": USER_AGENT},
}
MAX_PAGE = 100


class FxEmbedClient:
    def __init__(
        self,
        get: Callable[..., Awaitable[Any]] | None = None,
        base_url: str | None = None,
    ) -> None:
        self._get = get or _scrapling_get
        base = base_url or os.environ.get("THOTH_X_FXEMBED_URL") or DEFAULT_FXEMBED_URL
        self._base = base.rstrip("/")

    async def _json(self, path: str) -> dict[str, Any] | None:
        try:
            response = await self._get(f"{self._base}{path}", **OPTIONS)
        except Exception as error:
            reason = (
                AcquisitionReason.REQUEST_TIMEOUT
                if _is_timeout(error)
                else AcquisitionReason.REQUEST_BLOCKED
            )
            logger.warning("x fxembed unreachable reason=%s", reason.value)
            raise RequestFetchError(reason) from None
        status = getattr(response, "status", None)
        if status == 404:
            return None
        if status != 200:
            logger.warning("x fxembed refused status=%s", status)
            raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
        body = getattr(response, "body", b"")
        try:
            payload = json.loads(
                body.decode("utf-8", "replace") if isinstance(body, bytes) else body
            )
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict):
            logger.warning("x fxembed unreadable")
            return None
        return None if payload.get("code") == 404 else payload

    async def status(self, post_id: str) -> dict[str, Any] | None:
        payload = await self._json(f"/2/status/{post_id}")
        status = payload.get("status") if payload else None
        return status if isinstance(status, dict) else None

    async def replies(self, post_id: str) -> list[dict[str, Any]]:
        """The conversation's first page of replies only; the card crops cap what is useful."""
        payload = await self._json(f"/2/conversation/{post_id}")
        replies = payload.get("replies") if payload else None
        return (
            [item for item in replies if isinstance(item, dict)]
            if isinstance(replies, list)
            else []
        )

    async def profile_media(self, handle: str, count: int) -> dict[str, Any] | None:
        return await self._json(f"/2/profile/{quote(handle)}/media?count={min(count, MAX_PAGE)}")
