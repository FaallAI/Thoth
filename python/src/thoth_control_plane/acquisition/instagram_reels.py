"""Instagram reels listed in a signed-in browser (plan Task 16, spec 5.9).

The anonymous profile grid holds 12 posts and keeps only its videos (3 for a photo-heavy
account), and Instagram's web `api/v1` endpoints redirect a web session (probe, 2026-10-13).
A real browser with the leased account's cookies and proxy opens `/<handle>/reels/` and reads
the GraphQL responses the page loads (`clips_connection`), scrolling at a human pace. Never the
mobile private API: probing it flagged an account.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.adapters.instagram import CANONICAL_BASE, CODE, HANDLE
from thoth_control_plane.acquisition.adapters.threads import _walk
from thoth_control_plane.acquisition.discovery import MAX_CAPTION, _empty
from thoth_control_plane.acquisition.instagram_discovery import rank_videos
from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.normalize import numeric_id

logger = logging.getLogger(__name__)
INSTAGRAM_EPOCH_MS = 1_314_220_021_721  # media ids carry their creation time above bit 23
REELS_KEY = "clips_connection"
GRAPHQL_PATH = "/graphql/query"
FIRST_WAIT_MS = 5_000
# Operator account safety (2026-10-13): a few scrolls, each after a human pause.
MAX_SCROLLS = 4
PAUSE_MS = (5_000, 7_000)
TIMEOUT_MS = 90_000
LOGIN_PATH = "/accounts/login"


def published_from_pk(pk: object) -> str | None:
    number = numeric_id(pk)
    if number is None:
        return None
    millis = (int(number) >> 23) + INSTAGRAM_EPOCH_MS
    return datetime.fromtimestamp(millis / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _media(roots: Iterable[object]) -> Iterable[dict[str, Any]]:
    for root in roots:
        for node in _walk(root):
            connection = node.get(REELS_KEY)
            if not isinstance(connection, dict):
                continue
            for edge in connection.get("edges") or []:
                media = (edge.get("node") or {}).get("media") if isinstance(edge, dict) else None
                if isinstance(media, dict):
                    yield media


def _video(media: dict[str, Any], handle: str) -> DiscoveredVideo | None:
    owner = (media.get("user") or {}).get("username")
    code = media.get("code")
    pk = numeric_id(media.get("pk"))
    if (
        not isinstance(owner, str)
        or owner.lower() != handle.lower()
        or not HANDLE.fullmatch(owner)
        or not isinstance(code, str)
        or CODE.fullmatch(code) is None
        or pk is None
    ):
        return None
    counts = {"comment": media.get("comment_count")}
    if not media.get("like_and_view_counts_disabled"):
        counts |= {"play": media.get("play_count"), "like": media.get("like_count")}
    engagement = {k: int(v) for k, v in counts.items() if isinstance(v, int) and v >= 0}
    caption = media.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else None
    try:
        return DiscoveredVideo(
            post_id=pk,
            owner_handle=owner,
            canonical_url=f"{CANONICAL_BASE}/p/{code}/",
            caption=text[:MAX_CAPTION] if isinstance(text, str) else "",
            published_at=published_from_pk(pk),
            engagement=engagement,
        )
    except ValueError:
        return None


def parse_reels(bodies: Iterable[bytes], handle: str) -> list[DiscoveredVideo]:
    """The account's own reels in the captured responses, once each; collaborators' are not."""
    roots: list[object] = []
    for body in bodies:
        try:
            roots.append(json.loads(body))
        except ValueError:
            continue
    videos: dict[str, DiscoveredVideo] = {}
    for media in _media(roots):
        video = _video(media, handle)
        if video is not None:
            videos.setdefault(video.post_id, video)
    return list(videos.values())


def _default_session_factory(**kwargs: Any) -> Any:
    from scrapling.fetchers import AsyncStealthySession

    return AsyncStealthySession(**kwargs)


class InstagramReelsDiscovery:
    def __init__(
        self,
        access: SessionAccess,
        *,
        session_factory: Callable[..., Any] | None = None,
        pause: Callable[[], int] = lambda: random.randint(*PAUSE_MS),
    ) -> None:
        self._access = access
        self._session_factory = session_factory or _default_session_factory
        self._pause = pause

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        responses: list[Any] = []
        bodies: list[bytes] = []

        async def setup(page: Any) -> None:
            responses.clear()
            page.on(
                "response",
                lambda response: (
                    responses.append(response) if GRAPHQL_PATH in response.url else None
                ),
            )

        async def collect() -> int:
            while len(bodies) < len(responses):
                try:
                    bodies.append(await responses[len(bodies)].body())
                except Exception:
                    bodies.append(b"")
            return len(parse_reels(bodies, request.handle))

        async def action(page: Any) -> Any:
            await page.wait_for_timeout(FIRST_WAIT_MS)
            for _ in range(MAX_SCROLLS):
                if await collect() >= request.limit:
                    break
                await page.mouse.wheel(0, 2200)
                await page.wait_for_timeout(self._pause())
            await collect()
            return page

        session = self._session_factory(headless=True, max_pages=1, **self._access.browser_kwargs())
        active = await session.__aenter__()
        try:
            page = await active.fetch(
                f"{CANONICAL_BASE}/{request.handle}/reels/",
                page_setup=setup,
                page_action=action,
                timeout=TIMEOUT_MS,
            )
        finally:
            await session.__aexit__(None, None, None)
        if LOGIN_PATH in str(getattr(page, "url", "")):
            return _empty("profile", DiscoveryReason.BLOCKED)
        videos = parse_reels(bodies, request.handle)
        logger.info("instagram reels discovery finished videos=%d", len(videos))
        if not videos:
            return _empty("profile", DiscoveryReason.NO_DATA)
        return DiscoveryResult(
            kind="profile",
            videos=rank_videos(videos)[: request.limit],
            pages=sum(1 for body in bodies if REELS_KEY.encode() in body),
            exhausted=False,
            drops=DiscoveryDrops(),
        )
