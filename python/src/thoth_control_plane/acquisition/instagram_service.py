"""Instagram single-post acquisition: content by one method, first-page comments, and
best-effort headless cards (post, one per comment, profile).

`CONTENT_METHOD` and `SHARE_RESOLUTION_METHOD` are decided once from the Stage 3b
golden-fixture comparison. There is no runtime fallback between methods; the legacy
fallback lives in the workflow. Cards always come from one anonymous headless session.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.adapters.instagram import (
    CANONICAL_BASE,
    POST_PATH,
    SHARE_PATH,
    InstagramParse,
    InstagramPostIdentity,
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
    login_required,
    parse_post,
)
from thoth_control_plane.acquisition.adapters.threads import json_roots
from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    HeadlessBrowserError,
    _classify_fetch_error,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
)
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    CardArtifact,
    MaterializedMedia,
    ReportComment,
    ReportSource,
    SourceReport,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)
from thoth_control_plane.acquisition.threads_service import (
    _STRATEGIES,
    REQUEST_OPTIONS,
    SCRIPT_SELECTOR,
    RequestFetchError,
    _await_post_url,
    _scrapling_get,
    exit_session,
    materialize_media,
    save_card,
)

logger = logging.getLogger(__name__)

# Provisional until the Stage 3b capture decides them (restricted evidence in the checkpoint).
CONTENT_METHOD: Literal["request", "headless"] = "request"
SHARE_RESOLUTION_METHOD: Literal["request", "headless"] = "request"
DIALOG_CLOSE_SELECTOR = 'div[role=dialog] svg[aria-label="Close"]'
POST_CARD_SELECTOR = "main > div > div"
PROFILE_CARD_SELECTOR = "header"
COMMENT_ROW_ATTRIBUTE = "data-thoth-comment"
COMMENT_PREFIX_CHARS = 30
DIALOG_TIMEOUT_MS = 3_000
LOGIN_PATHS = ("/accounts/login", "/login", "/challenge")
# Tags each matched comment row; targets arrive as the evaluate argument, never interpolated.
TAG_COMMENTS_JS = """
(targets) => {
  const tagged = [];
  const spans = Array.from(document.querySelectorAll("span"));
  for (const target of targets) {
    const link = `a[href="/${CSS.escape(target.author)}/"]`;
    for (const span of spans) {
      if (!(span.textContent || "").trim().startsWith(target.prefix)) continue;
      // A span inside an already tagged row belongs to another comment.
      if (span.closest("[data-thoth-comment]")) continue;
      // The row is the smallest ancestor holding an avatar, and it must hold this author:
      // climbing further would reach the whole comment list.
      let row = span;
      while (row && row !== document.body && !row.querySelector("img")) {
        row = row.parentElement;
      }
      if (!row || row === document.body || !row.querySelector(link)) continue;
      row.setAttribute("data-thoth-comment", target.comment_id);
      tagged.push(target.comment_id);
      break;
    }
  }
  return tagged;
}
"""


def _blocked(url: object) -> bool:
    path = urlsplit(str(url)).path
    return any(path == prefix or path.startswith(prefix + "/") for prefix in LOGIN_PATHS)


class InstagramRequestFetcher:
    """Plain impersonated HTTP GET; returns embedded JSON script texts or a landing URL."""

    def __init__(self, get: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._get = get or _scrapling_get

    async def _response(self, url: str) -> Any:
        try:
            response = await self._get(url, **REQUEST_OPTIONS)
        except Exception as error:
            reason = (
                AcquisitionReason.REQUEST_TIMEOUT
                if _is_timeout(error)
                else AcquisitionReason.REQUEST_BLOCKED
            )
            raise RequestFetchError(reason) from None
        if getattr(response, "status", None) != 200 or _blocked(response.url):
            raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
        return response

    async def fetch(self, url: str) -> list[str]:
        response = await self._response(url)
        return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]

    async def landing(self, share_url: str) -> str:
        """Follow a share link's safe redirects; return where the request ended up."""
        return str((await self._response(share_url)).url)


async def resolve_instagram_identity(
    source_url: str, request: Any, headless: Any
) -> InstagramPostIdentity:
    """A post URL is its own identity; a share link is followed once by the chosen method."""
    try:
        return canonicalize_instagram_post_url(source_url)
    except InstagramUrlError:
        share_url = canonical_instagram_share_url(source_url)
    if SHARE_RESOLUTION_METHOD == "request":
        landing = await request.landing(share_url)
    else:
        landing = await headless.resolve(share_url)
    return canonicalize_instagram_post_url(landing)


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
class InstagramCards:
    post_png: bytes | None = None
    comment_pngs: dict[str, bytes] = field(default_factory=dict)
    profile_png: bytes | None = None
    problems: list[str] = field(default_factory=list)


async def _dismiss(page: Any) -> None:
    # The anonymous sign-up dialog covers the page; a missing dialog is fine.
    with contextlib.suppress(Exception):
        await page.locator(DIALOG_CLOSE_SELECTOR).first.click(timeout=DIALOG_TIMEOUT_MS)


async def _crop(page: Any, selector: str) -> bytes | None:
    with contextlib.suppress(Exception):
        element = page.locator(selector).first
        await element.scroll_into_view_if_needed(timeout=5_000)
        return await element.screenshot(timeout=10_000)
    return None


def _on_post(
    cards: InstagramCards, want_post: bool, targets: list[CommentTarget]
) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if _blocked(page.url):
            cards.problems.append(AcquisitionReason.HEADLESS_BLOCKED.value)
            return
        await _dismiss(page)
        if want_post:
            cards.post_png = await _crop(page, POST_CARD_SELECTOR)
        if not targets:
            return
        tagged: object = []
        with contextlib.suppress(Exception):
            tagged = await page.evaluate(TAG_COMMENTS_JS, [asdict(t) for t in targets])
        known = {target.comment_id for target in targets}
        for comment_id in tagged if isinstance(tagged, list) else []:
            # Only ids we sent (validated numeric) ever reach a selector.
            if comment_id in known and comment_id not in cards.comment_pngs:
                png = await _crop(page, f'[{COMMENT_ROW_ATTRIBUTE}="{comment_id}"]')
                if png is not None:
                    cards.comment_pngs[comment_id] = png

    return action


def _on_profile(cards: InstagramCards) -> Callable[[Any], Awaitable[None]]:
    async def action(page: Any) -> None:
        if _blocked(page.url):
            cards.problems.append(AcquisitionReason.HEADLESS_BLOCKED.value)
            return
        await _dismiss(page)
        cards.profile_png = await _crop(page, PROFILE_CARD_SELECTOR)

    return action


class InstagramHeadlessBrowser:
    """One lazily opened stealthy session for share resolution, page JSON, and card crops."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
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

    async def scripts(self, url: str) -> list[str]:
        response = await self._visit(url)
        if _blocked(response.url):
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
        return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]

    async def resolve(self, share_url: str) -> str:
        landing: list[str] = []
        await self._visit(share_url, _await_post_url(landing, POST_PATH))
        if landing and _blocked(landing[0]):
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
        if not landing or SHARE_PATH.fullmatch(urlsplit(landing[0]).path):
            # The client-side redirect never happened in time; a retry may still land.
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_INCOMPLETE)
        return landing[0]

    async def _card_visit(
        self, url: str, action: Callable[[Any], Awaitable[None]], cards: InstagramCards
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
    ) -> InstagramCards:
        """Best effort: every failure lands in `problems`; only cancellation propagates."""
        cards = InstagramCards()
        if want_post or targets:
            await self._card_visit(post_url, _on_post(cards, want_post, targets), cards)
        await self._card_visit(profile_url, _on_profile(cards), cards)
        return cards

    async def close(self) -> None:
        session, self._session, self._active = self._session, None, None
        await exit_session(session)


def _persist_cards(
    cards: InstagramCards, comments: list[ReportComment], workflow_id: str, artifact_root: Path
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


def _log_outcome(
    parsed: InstagramParse,
    media: list[MaterializedMedia],
    comments: list[ReportComment],
    post_card: CardArtifact | None,
    profile_card: CardArtifact | None,
    want_post: bool,
    problems: list[str],
) -> None:
    carded = sum(comment.card is not None for comment in comments)
    logger.info(
        "instagram acquisition finished method=%s media=%d comments=%d comment_cards=%d "
        "post_card=%s profile_card=%s",
        CONTENT_METHOD,
        len(media),
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
            "instagram cards missing missing=%s problems=%s",
            ",".join(missing) or "none",
            ",".join(problems) or "none",
        )
    if parsed.dropped_comments:
        logger.debug("instagram comments dropped count=%d", parsed.dropped_comments)


class InstagramAcquirer:
    """One Instagram post: content by `CONTENT_METHOD`, media in order, comments, and cards."""

    def __init__(
        self,
        request_fetcher: InstagramRequestFetcher,
        headless: InstagramHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._request = request_fetcher
        self._headless = headless
        self._materializer = materializer

    async def _content(
        self, identity: InstagramPostIdentity
    ) -> tuple[InstagramParse | None, AcquisitionReason | None]:
        url = str(identity.canonical_url)
        if CONTENT_METHOD == "request":
            blocked = AcquisitionReason.REQUEST_BLOCKED
            incomplete = AcquisitionReason.REQUEST_INCOMPLETE
        else:
            blocked = AcquisitionReason.HEADLESS_BLOCKED
            incomplete = AcquisitionReason.HEADLESS_INCOMPLETE
        try:
            if CONTENT_METHOD == "request":
                texts = await self._request.fetch(url)
            else:
                texts = await self._headless.scripts(url)
        except (RequestFetchError, HeadlessBrowserError) as error:
            return None, error.reason
        roots = json_roots(texts)
        if login_required(roots):
            return None, blocked
        parsed = parse_post(roots, identity)
        return parsed, None if parsed else incomplete

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = _STRATEGIES[CONTENT_METHOD]
        try:
            try:
                identity = await resolve_instagram_identity(
                    source_url, self._request, self._headless
                )
            except InstagramUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            except (RequestFetchError, HeadlessBrowserError) as error:
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=error.reason.value,
                        retryable=error.reason.value in RETRYABLE_FAILURES,
                    )
                )
            start = time.monotonic()
            parsed, reason = await self._content(identity)
            if parsed is not None and not parsed.post.text.strip() and not parsed.media:
                attempt = _make_attempt(strategy, None, _elapsed_ms(start))
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code="no_content", retryable=False, attempts=[attempt]
                    )
                )
            media: list[MaterializedMedia] = []
            if parsed is not None:
                try:
                    media = await materialize_media(
                        self._materializer,
                        parsed.media,
                        f"instagram-{identity.post_id}",
                        workflow_id,
                        strategy,
                        artifact_root,
                    )
                except MediaMaterializationError:
                    reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
            attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
            if reason is not None:
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=reason.value,
                        retryable=reason.value in RETRYABLE_FAILURES,
                        attempts=[attempt],
                    )
                )
            assert parsed is not None  # a None parse always carries a reason
            want_post = not any(item.kind == "video" for item in media)
            cards = await self._headless.cards(
                str(identity.canonical_url),
                f"{CANONICAL_BASE}/{parsed.post.owner_handle}/",
                want_post=want_post,
                targets=comment_targets(parsed.comments),
            )
            post_card, comments, profile_card = await asyncio.to_thread(
                _persist_cards, cards, parsed.comments, workflow_id, artifact_root
            )
            _log_outcome(
                parsed, media, comments, post_card, profile_card, want_post, cards.problems
            )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="instagram", canonical_url=identity.canonical_url),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    comments=comments,
                    post_card=post_card,
                    profile_card=profile_card,
                )
            )
        finally:
            # Same shielded close as Threads: a second cancellation must not interrupt
            # browser cleanup partway through.
            await asyncio.shield(self._headless.close())
