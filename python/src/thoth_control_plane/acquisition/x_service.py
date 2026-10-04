"""X single-post acquisition: the syndication JSON core, the page's seroval data as a
best-effort enrichment (first-page replies, views, reposts), and headless cards.

Content is `request` by construction: logged-out pages serve a browser no content data
(no GraphQL traffic, and the seroval table is dropped after hydration). There is no runtime
fallback between methods; the legacy fallback lives in the workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from thoth_control_plane.acquisition.adapters.seroval import decode_scripts
from thoth_control_plane.acquisition.adapters.x import (
    CANONICAL_BASE,
    XPageParse,
    XPostIdentity,
    XUrlError,
    canonicalize_x_post_url,
    parse_page,
    parse_syndication,
    post_url,
    syndication_author,
    with_page,
)
from thoth_control_plane.acquisition.browser import _default_session_factory, _is_timeout
from thoth_control_plane.acquisition.card_browser import (
    CardBrowser,
    CardLayout,
    comment_targets,
    is_login_path,
    log_outcome,
    persist_cards,
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
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)
from thoth_control_plane.acquisition.threads_service import (
    _STRATEGIES,
    REQUEST_OPTIONS,
    RequestFetchError,
    _scrapling_get,
    materialize_media,
)

logger = logging.getLogger(__name__)

CONTENT_METHOD: Literal["request"] = "request"
# Any token is accepted (Stage 3c probe); the id names the tweet.
SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=0&lang=en"
LOGIN_PATHS = ("/i/flow/login", "/login", "/account/access")
# Provisional until the Stage 3c capture fixes them (Task 9).
POST_CARD_SELECTOR = "article"
PROFILE_CARD_SELECTOR = "main"
# Tags each matched reply row; targets arrive as the evaluate argument, never interpolated.
# A row is a top-level article (never a nested quote) whose own text mentions `@author` as a
# whole handle and holds the reply's text prefix.
TAG_REPLIES_JS = """
(targets) => {
  const tagged = [];
  const rows = Array.from(document.querySelectorAll("article")).filter(
    (article) => !article.parentElement || !article.parentElement.closest("article")
  );
  const own = (article) => {
    let text = article.innerText || "";
    for (const quote of article.querySelectorAll("article")) {
      text = text.replace(quote.innerText || "", " ");
    }
    return text;
  };
  const mentions = (text, handle) => {
    for (let at = text.indexOf(handle); at !== -1; at = text.indexOf(handle, at + 1)) {
      if (!/[a-z0-9_]/.test(text.charAt(at + handle.length))) return true;
    }
    return false;
  };
  for (const target of targets) {
    const handle = "@" + target.author.toLowerCase();
    const row = rows.find((article) => {
      const text = own(article);
      return !article.hasAttribute("data-thoth-comment")
        && mentions(text.toLowerCase(), handle)
        && text.includes(target.prefix);
    });
    if (!row) continue;
    row.setAttribute("data-thoth-comment", target.comment_id);
    tagged.push(target.comment_id);
  }
  return tagged;
}
"""


def x_layout() -> CardLayout:
    """Read the selectors at call time, so the capture's ruling is one constant change."""
    return CardLayout(
        post_selector=POST_CARD_SELECTOR,
        profile_selector=PROFILE_CARD_SELECTOR,
        tag_js=TAG_REPLIES_JS,
        login_paths=LOGIN_PATHS,
    )


def _text(response: Any) -> str:
    body = getattr(response, "body", b"")
    return body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)


class XRequestFetcher:
    """Plain impersonated HTTP GETs: the syndication JSON and the post or profile page."""

    def __init__(self, get: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._get = get or _scrapling_get

    async def _response(self, url: str, *, missing_ok: bool = False) -> Any | None:
        try:
            response = await self._get(url, **REQUEST_OPTIONS)
        except Exception as error:
            reason = (
                AcquisitionReason.REQUEST_TIMEOUT
                if _is_timeout(error)
                else AcquisitionReason.REQUEST_BLOCKED
            )
            raise RequestFetchError(reason) from None
        status = getattr(response, "status", None)
        if missing_ok and status == 404:
            return None
        if status != 200 or is_login_path(response.url, LOGIN_PATHS):
            raise RequestFetchError(AcquisitionReason.REQUEST_BLOCKED)
        return response

    async def syndication(self, post_id: str) -> object:
        """The tweet's JSON; None when X has no such tweet (404) or the body is not JSON."""
        response = await self._response(SYNDICATION_URL.format(post_id=post_id), missing_ok=True)
        if response is None:
            return None
        try:
            return json.loads(_text(response))
        except ValueError:
            return None

    async def page(self, url: str) -> str:
        return _text(await self._response(url))


class XHeadlessBrowser(CardBrowser):
    """The X card session: post, reply, and profile cards; never content."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        super().__init__(x_layout(), session_factory)


class XAcquirer:
    """One X post: the syndication core, the page enrichment, media in order, and cards."""

    def __init__(
        self,
        request_fetcher: XRequestFetcher,
        headless: XHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._request = request_fetcher
        self._headless = headless
        self._materializer = materializer

    async def _page(self, url: str, identity: XPostIdentity) -> XPageParse:
        """Best effort: a failed fetch or an unreadable page gives an empty parse."""
        try:
            html = await self._request.page(url)
        except RequestFetchError as error:
            logger.warning("x page enrichment unavailable reason=%s", error.reason.value)
            return XPageParse()
        page = parse_page(decode_scripts(html), identity)
        if not page.engagement:
            logger.warning(
                "x page enrichment found no post replies=%d dropped=%d",
                len(page.comments),
                page.dropped_comments,
            )
        return page

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = _STRATEGIES[CONTENT_METHOD]
        try:
            try:
                identity = canonicalize_x_post_url(source_url)
            except XUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            start = time.monotonic()
            reason: AcquisitionReason | None = None
            try:
                data = await self._request.syndication(identity.post_id)
            except RequestFetchError as error:
                data, reason = None, error.reason
            author = syndication_author(data)
            page = (
                await self._page(post_url(author, identity.post_id), identity)
                if author is not None
                else XPageParse()
            )
            parsed = parse_syndication(data, identity, page.videos)
            if parsed is None and reason is None:
                reason = AcquisitionReason.REQUEST_INCOMPLETE
            media: list[MaterializedMedia] = []
            if parsed is not None:
                parsed = with_page(parsed, page)
                if not parsed.post.text.strip() and not parsed.media:
                    attempt = _make_attempt(strategy, None, _elapsed_ms(start))
                    return AcquisitionResult(
                        failure=AcquisitionFailure(
                            code="no_content", retryable=False, attempts=[attempt]
                        )
                    )
                try:
                    media = await materialize_media(
                        self._materializer,
                        parsed.media,
                        f"x-{identity.post_id}",
                        workflow_id,
                        strategy,
                        artifact_root,
                    )
                except MediaMaterializationError:
                    reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
            attempt = _make_attempt(strategy, reason, _elapsed_ms(start))
            if reason is not None or parsed is None:
                code = (reason or AcquisitionReason.REQUEST_INCOMPLETE).value
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=code, retryable=code in RETRYABLE_FAILURES, attempts=[attempt]
                    )
                )
            owner = parsed.post.owner_handle
            canonical = post_url(owner, identity.post_id)
            want_post = not any(item.kind == "video" for item in media)
            cards = await self._headless.cards(
                canonical,
                f"{CANONICAL_BASE}/{owner}",
                want_post=want_post,
                targets=comment_targets(page.comments),
            )
            post_card, comments, profile_card = await asyncio.to_thread(
                persist_cards, cards, page.comments, workflow_id, artifact_root
            )
            log_outcome(
                "x",
                CONTENT_METHOD,
                len(media),
                comments,
                post_card,
                profile_card,
                want_post=want_post,
                problems=cards.problems,
                dropped=page.dropped_comments,
            )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="x", canonical_url=canonical),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    comments=comments,
                    post_card=post_card,
                    profile_card=profile_card,
                )
            )
        finally:
            # Same shielded close as Instagram: a second cancellation must not interrupt
            # browser cleanup partway through.
            await asyncio.shield(self._headless.close())
