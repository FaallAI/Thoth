"""Best-effort headless cards shared by the Instagram and X acquirers.

One lazily opened anonymous stealthy session visits a post page (the post card and one card
per tagged comment row) and a profile page (the profile card). Each platform supplies a
`CardLayout`. Every failure lands in `Cards.problems`; only cancellation propagates. A
card is always a real crop, never a synthetic render.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    HeadlessBrowserError,
    _classify_fetch_error,
    _default_session_factory,
    _increment_active_sessions,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    CardArtifact,
    ReportComment,
)
from thoth_control_plane.acquisition.threads_service import exit_session, save_card

logger = logging.getLogger(__name__)

COMMENT_ROW_ATTRIBUTE = "data-thoth-comment"
COMMENT_PREFIX_CHARS = 30
DIALOG_TIMEOUT_MS = 3_000


@dataclass(frozen=True)
class CardLayout:
    """Where one platform's cards live on its logged-out pages."""

    post_selector: str
    profile_selector: str
    # Called with the comment targets; tags rows with COMMENT_ROW_ATTRIBUTE, returns ids.
    tag_js: str
    login_paths: tuple[str, ...]
    dismiss_selector: str | None = None


def is_login_path(url: object, login_paths: tuple[str, ...]) -> bool:
    path = urlsplit(str(url)).path
    return any(path == prefix or path.startswith(prefix + "/") for prefix in login_paths)


@dataclass(frozen=True)
class CommentTarget:
    comment_id: str
    author: str
    prefix: str


def comment_targets(comments: list[ReportComment]) -> list[CommentTarget]:
    targets: list[CommentTarget] = []
    for comment in comments:
        line = next((part.strip() for part in comment.text.splitlines() if part.strip()), "")
        targets.append(
            CommentTarget(comment.comment_id, comment.author, line[:COMMENT_PREFIX_CHARS])
        )
    return targets


@dataclass
class Cards:
    post_png: bytes | None = None
    comment_pngs: dict[str, bytes] = field(default_factory=dict)
    profile_png: bytes | None = None
    problems: list[str] = field(default_factory=list)


async def _dismiss(page: Any, selector: str | None) -> None:
    # A sign-up dialog may cover the page; a missing dialog is fine.
    if selector is None:
        return
    with contextlib.suppress(Exception):
        await page.locator(selector).first.click(timeout=DIALOG_TIMEOUT_MS)


async def _crop(page: Any, selector: str) -> bytes | None:
    with contextlib.suppress(Exception):
        element = page.locator(selector).first
        await element.scroll_into_view_if_needed(timeout=5_000)
        return await element.screenshot(timeout=10_000)
    return None


def _on_post(
    cards: Cards, want_post: bool, targets: list[CommentTarget], layout: CardLayout
) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if is_login_path(page.url, layout.login_paths):
            cards.problems.append(AcquisitionReason.HEADLESS_BLOCKED.value)
            return
        await _dismiss(page, layout.dismiss_selector)
        if want_post:
            cards.post_png = await _crop(page, layout.post_selector)
        if not targets:
            return
        tagged: object = []
        with contextlib.suppress(Exception):
            tagged = await page.evaluate(layout.tag_js, [asdict(t) for t in targets])
        known = {target.comment_id for target in targets}
        for comment_id in tagged if isinstance(tagged, list) else []:
            # Only ids we sent (validated `[A-Za-z0-9_-]`) ever reach a selector.
            if comment_id in known and comment_id not in cards.comment_pngs:
                png = await _crop(page, f'[{COMMENT_ROW_ATTRIBUTE}="{comment_id}"]')
                if png is not None:
                    cards.comment_pngs[comment_id] = png

    return action


def _on_profile(cards: Cards, layout: CardLayout) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if is_login_path(page.url, layout.login_paths):
            cards.problems.append(AcquisitionReason.HEADLESS_BLOCKED.value)
            return
        await _dismiss(page, layout.dismiss_selector)
        cards.profile_png = await _crop(page, layout.profile_selector)

    return action


class CardBrowser:
    """One lazily opened stealthy session for a platform's card crops."""

    def __init__(
        self,
        layout: CardLayout,
        session_factory: Callable[..., Any] = _default_session_factory,
    ) -> None:
        self._layout = layout
        self._session_factory = session_factory
        self._session: Any | None = None
        self._active: Any | None = None

    async def _open(self) -> Any:
        if self._active is None:
            session = self._session_factory(headless=True, max_pages=1)
            try:
                active = await session.__aenter__()
            except Exception as error:
                raise HeadlessBrowserError(_classify_fetch_error(error)) from None
            self._session, self._active = session, active
            _increment_active_sessions()
        return self._active

    async def _visit(self, url: str, action: Callable[[Any], Awaitable[None]] | None = None):
        active = await self._open()
        try:
            return await active.fetch(url, page_action=action, **FETCH_OPTIONS)
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None

    async def _card_visit(
        self, url: str, action: Callable[[Any], Awaitable[None]], cards: Cards
    ) -> None:
        try:
            await self._visit(url, action)
        except HeadlessBrowserError as error:
            cards.problems.append(error.reason.value)

    async def cards(
        self,
        post_url: str,
        profile_url: str,
        *,
        want_post: bool,
        targets: list[CommentTarget],
    ) -> Cards:
        """Best effort: every failure lands in `problems`; only cancellation propagates."""
        cards = Cards()
        if want_post or targets:
            action = _on_post(cards, want_post, targets, self._layout)
            await self._card_visit(post_url, action, cards)
        await self._card_visit(profile_url, _on_profile(cards, self._layout), cards)
        return cards

    async def close(self) -> None:
        session, self._session, self._active = self._session, None, None
        await exit_session(session)


def persist_cards(
    cards: Cards, comments: list[ReportComment], workflow_id: str, artifact_root: Path
) -> tuple[CardArtifact | None, list[ReportComment], CardArtifact | None]:
    base = PurePosixPath("reports") / workflow_id / "cards"

    def save(png: bytes | None, name: str) -> CardArtifact | None:
        return save_card(png, artifact_root, base / name)

    carded = [
        comment.model_copy(
            update={
                "card": save(
                    cards.comment_pngs.get(comment.comment_id),
                    f"comment-{comment.comment_id}.png",
                )
            }
        )
        for comment in comments
    ]
    return save(cards.post_png, "post.png"), carded, save(cards.profile_png, "profile.png")


def log_outcome(
    platform: str,
    method: str,
    media: int,
    comments: list[ReportComment],
    post_card: CardArtifact | None,
    profile_card: CardArtifact | None,
    *,
    want_post: bool,
    problems: list[str],
    dropped: int,
) -> None:
    """Counts and enums only: never a URL, a handle, or text."""
    carded = sum(comment.card is not None for comment in comments)
    logger.info(
        "%s acquisition finished method=%s media=%d comments=%d comment_cards=%d "
        "post_card=%s profile_card=%s",
        platform,
        method,
        media,
        len(comments),
        carded,
        post_card is not None,
        profile_card is not None,
    )
    missing = []
    if want_post and post_card is None:
        missing.append("post")
    if profile_card is None:
        missing.append("profile")
    if carded < len(comments):
        missing.append(f"comments={len(comments) - carded}")
    if missing or problems:
        logger.warning(
            "%s cards missing missing=%s problems=%s",
            platform,
            ",".join(missing) or "none",
            ",".join(problems) or "none",
        )
    if dropped:
        logger.debug("%s comments dropped count=%d", platform, dropped)
