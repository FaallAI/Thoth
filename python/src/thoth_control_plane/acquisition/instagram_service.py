"""Instagram single-post acquisition: content by one method, first-page comments, and
best-effort headless cards (post, one per comment, profile).

`CONTENT_METHOD` and `SHARE_RESOLUTION_METHOD` are decided once from the Stage 3b
golden-fixture comparison. There is no runtime fallback between methods; the legacy
fallback lives in the workflow. Cards always come from one anonymous headless session.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
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
    HeadlessBrowserError,
    _default_session_factory,
    _is_timeout,
)
from thoth_control_plane.acquisition.card_browser import (
    COMMENT_ROW_ATTRIBUTE as COMMENT_ROW_ATTRIBUTE,
)
from thoth_control_plane.acquisition.card_browser import (
    CardBrowser,
    CardLayout,
    Cards,
    comment_targets,
    is_login_path,
    log_outcome,
    persist_cards,
)
from thoth_control_plane.acquisition.card_browser import (
    CommentTarget as CommentTarget,
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
    MaterializedMedia,
    ReportSource,
    SourceReport,
    failure_code,
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
    materialize_media,
)

logger = logging.getLogger(__name__)

# Provisional until the Stage 3b capture decides them (restricted evidence in the checkpoint).
CONTENT_METHOD: Literal["request", "headless"] = "request"
SHARE_RESOLUTION_METHOD: Literal["request", "headless"] = "request"
DIALOG_CLOSE_SELECTOR = 'div[role=dialog] svg[aria-label="Close"]'
POST_CARD_SELECTOR = "main > div > div"
PROFILE_CARD_SELECTOR = "header"
LOGIN_PATHS = ("/accounts/login", "/login", "/challenge")
# A sign-in page means no usable session; a challenge means the session was flagged.
SIGN_IN_PATHS = ("/accounts/login", "/login")
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


INSTAGRAM_LAYOUT = CardLayout(
    post_selector=POST_CARD_SELECTOR,
    profile_selector=PROFILE_CARD_SELECTOR,
    tag_js=TAG_COMMENTS_JS,
    login_paths=LOGIN_PATHS,
    dismiss_selector=DIALOG_CLOSE_SELECTOR,
)
# Kept under its Stage 3b name for the Instagram callers and tests.
InstagramCards = Cards


def _blocked(url: object) -> bool:
    return is_login_path(url, LOGIN_PATHS)


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
        if is_login_path(response.url, SIGN_IN_PATHS):
            raise RequestFetchError(AcquisitionReason.LOGIN_WALL)
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


class InstagramHeadlessBrowser(CardBrowser):
    """The Instagram card session, plus share resolution and page JSON in the same session."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        super().__init__(INSTAGRAM_LAYOUT, session_factory)

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
        incomplete = (
            AcquisitionReason.REQUEST_INCOMPLETE
            if CONTENT_METHOD == "request"
            else AcquisitionReason.HEADLESS_INCOMPLETE
        )
        try:
            if CONTENT_METHOD == "request":
                texts = await self._request.fetch(url)
            else:
                texts = await self._headless.scripts(url)
        except (RequestFetchError, HeadlessBrowserError) as error:
            return None, error.reason
        roots = json_roots(texts)
        if login_required(roots):
            return None, AcquisitionReason.LOGIN_WALL
        parsed = parse_post(roots, identity)
        return parsed, None if parsed else incomplete

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = _STRATEGIES[CONTENT_METHOD]
        try:
            start = time.monotonic()
            try:
                identity = await resolve_instagram_identity(
                    source_url, self._request, self._headless
                )
            except InstagramUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            except (RequestFetchError, HeadlessBrowserError) as error:
                attempt = _make_attempt(
                    _STRATEGIES[SHARE_RESOLUTION_METHOD], error.reason, _elapsed_ms(start)
                )
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=failure_code(error.reason),
                        retryable=failure_code(error.reason) in RETRYABLE_FAILURES,
                        attempts=[attempt],
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
                        code=failure_code(reason),
                        retryable=failure_code(reason) in RETRYABLE_FAILURES,
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
                persist_cards, cards, parsed.comments, workflow_id, artifact_root
            )
            log_outcome(
                "instagram",
                CONTENT_METHOD,
                len(media),
                comments,
                post_card,
                profile_card,
                want_post=want_post,
                problems=cards.problems,
                dropped=parsed.dropped_comments,
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
