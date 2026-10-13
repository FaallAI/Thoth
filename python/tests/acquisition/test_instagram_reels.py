"""Instagram reels listed in a signed-in browser (plan Task 16, spec 5.9)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
from thoth_control_plane.acquisition.instagram_reels import (
    InstagramReelsDiscovery,
    parse_reels,
    published_from_pk,
)
from thoth_control_plane.acquisition.models import DiscoveryReason, ProfileDiscovery

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "instagram_reels" / "reels_tab.json").read_text(
        encoding="utf-8"
    )
)
HANDLE = FIXTURE["handle"]
BODIES = [json.dumps(body).encode() for body in FIXTURE["bodies"]]
GRAPHQL = "https://www.instagram.com/graphql/query"
ACCESS = SessionAccess(
    parse_cookies(
        "instagram",
        "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", "s"]) + "\n",
        now=datetime(2026, 10, 13, tzinfo=UTC),
    )
)


def test_the_upload_time_is_read_from_the_media_id() -> None:
    # DeWlWJmyKxP: published 2026-10-11T11:47:13Z; its id was minted a minute earlier.
    assert published_from_pk("4005553168456395855") == "2026-10-11T11:46:09Z"
    assert published_from_pk("not-a-number") is None


def test_only_the_accounts_own_reels_are_kept_once_each() -> None:
    videos = parse_reels([*BODIES, BODIES[0]], HANDLE)

    owners = {video.owner_handle for video in videos}
    assert owners == {HANDLE}  # a collaborator's reel on the tab is not the account's own
    assert len(videos) == len({video.post_id for video in videos}) == 16
    first = videos[0]
    assert set(first.engagement) == {"play", "like", "comment"}
    assert first.published_at is not None
    assert str(first.canonical_url).startswith("https://www.instagram.com/p/")


def test_hidden_counts_are_left_out() -> None:
    body = json.loads(BODIES[1])
    media = body["data"]["fetch__XDTUserDict"]["clips_connection"]["edges"][0]["node"]["media"]
    media["like_and_view_counts_disabled"] = True
    media["user"]["username"] = HANDLE

    videos = {v.post_id: v for v in parse_reels([json.dumps(body).encode()], HANDLE)}

    assert set(videos[str(media["pk"])].engagement) == {"comment"}


class _Response:
    def __init__(self, url: str, body: bytes) -> None:
        self.url = url
        self._body = body

    async def body(self) -> bytes:
        return self._body


class _Page:
    def __init__(self, bodies: list[bytes]) -> None:
        self.pending = list(bodies)
        self.handlers: list[Any] = []
        self.scrolls = 0
        self.waits: list[int] = []
        self.mouse = SimpleNamespace(wheel=self._wheel)

    def on(self, event: str, handler: Any) -> None:
        assert event == "response"
        self.handlers.append(handler)

    def emit(self) -> None:
        if self.pending:
            body = self.pending.pop(0)
            for handler in self.handlers:
                handler(_Response("https://www.instagram.com/api/graphql", b"{}"))
                handler(_Response(GRAPHQL, body))

    async def _wheel(self, dx: int, dy: int) -> None:
        self.scrolls += 1
        self.emit()

    async def wait_for_timeout(self, timeout: int) -> None:
        self.waits.append(timeout)


class _Session:
    def __init__(
        self, bodies: list[bytes], final_url: str = f"https://www.instagram.com/{HANDLE}/reels/"
    ):
        self.page = _Page(bodies)
        self.final_url = final_url
        self.kwargs: dict[str, Any] = {}
        self.fetched: list[str] = []
        self.exited = False

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.exited = True

    async def fetch(self, url: str, **kwargs: Any) -> SimpleNamespace:
        self.fetched.append(url)
        await kwargs["page_setup"](self.page)
        self.page.emit()
        await kwargs["page_action"](self.page)
        return SimpleNamespace(url=self.final_url)


def _discovery(session: _Session) -> InstagramReelsDiscovery:
    def factory(**kwargs: Any) -> _Session:
        session.kwargs = kwargs
        return session

    return InstagramReelsDiscovery(ACCESS, session_factory=factory)


@pytest.mark.asyncio
async def test_the_reels_tab_is_read_with_the_session_and_paced_scrolls() -> None:
    session = _Session(BODIES)

    result = await _discovery(session).discover(ProfileDiscovery(handle=HANDLE, limit=30))

    assert session.fetched == [f"https://www.instagram.com/{HANDLE}/reels/"]
    assert "cookies" in session.kwargs and session.exited
    assert len(result.videos) == 16 and result.reason is None
    # Human pacing (operator account safety, 2026-10-13): every scroll waits at least 4 s.
    assert session.page.scrolls >= 1 and min(session.page.waits) >= 4000


@pytest.mark.asyncio
async def test_scrolling_stops_once_the_limit_is_reached() -> None:
    session = _Session([BODIES[0]] * 6)

    result = await _discovery(session).discover(ProfileDiscovery(handle=HANDLE, limit=10))

    assert len(result.videos) == 10
    assert session.page.scrolls == 0  # the first page already held 12 own reels


@pytest.mark.asyncio
async def test_a_login_redirect_is_blocked() -> None:
    session = _Session(BODIES, final_url="https://www.instagram.com/accounts/login/?next=x")

    result = await _discovery(session).discover(ProfileDiscovery(handle=HANDLE, limit=30))

    assert (result.videos, result.reason) == ([], DiscoveryReason.BLOCKED)


@pytest.mark.asyncio
async def test_no_reels_response_is_no_data() -> None:
    result = await _discovery(_Session([])).discover(ProfileDiscovery(handle=HANDLE, limit=30))

    assert result.reason == DiscoveryReason.NO_DATA


def test_a_leased_session_lists_reels_and_anonymous_reads_the_grid(tmp_path: Path) -> None:
    from thoth_control_plane.acquisition.instagram_discovery import InstagramProfileDiscovery
    from thoth_control_plane.attribution.adapters.discovery import DEFAULT_FACTORIES

    assert isinstance(DEFAULT_FACTORIES["instagram"](ACCESS, tmp_path), InstagramReelsDiscovery)
    assert isinstance(DEFAULT_FACTORIES["instagram"](None, tmp_path), InstagramProfileDiscovery)
