"""X single-post acquisition: the syndication JSON core, FxEmbed as a best-effort enrichment
(every video, first-page replies, views, reposts, long text), and headless cards.

Content is `request` by construction. X's signed-out pages stopped embedding tweet JSON in
October 2026, so the enrichment reads FxEmbed (spec 2026-10-23); the cards are still cropped
from the real X pages. There is no runtime fallback between methods; the legacy fallback lives
in the workflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition import card_browser
from thoth_control_plane.acquisition.adapters.fxembed import fx_page
from thoth_control_plane.acquisition.adapters.x import (
    CANONICAL_BASE,
    XPageParse,
    XPostIdentity,
    XUrlError,
    canonicalize_x_post_url,
    parse_syndication,
    post_url,
    with_page,
)
from thoth_control_plane.acquisition.browser import (
    HeadlessBrowserError,
    _default_session_factory,
    _is_timeout,
)
from thoth_control_plane.acquisition.card_browser import (
    CardBrowser,
    CardLayout,
    Cards,
    CommentTarget,
    _crop,
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
    ReportComment,
    ReportSource,
    SourceReport,
    failure_code,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)
from thoth_control_plane.acquisition.substance import is_substantive
from thoth_control_plane.acquisition.threads_service import (
    _STRATEGIES,
    REQUEST_OPTIONS,
    RequestFetchError,
    _scrapling_get,
    materialize_media,
)
from thoth_control_plane.acquisition.x_fxembed import FxEmbedClient

logger = logging.getLogger(__name__)

CONTENT_METHOD: Literal["request"] = "request"
# Any token is accepted (Stage 3c probe); the id names the tweet.
SYNDICATION_URL = "https://cdn.syndication.twimg.com/tweet-result?id={post_id}&token=0&lang=en"
LOGIN_PATHS = ("/i/flow/login", "/login", "/account/access")
# A sign-in page means no usable session; `/account/access` means the account was flagged.
SIGN_IN_PATHS = ("/i/flow/login", "/login")
# From the Stage 3c capture survey. The post's own article links to its status; on a reply's
# page the parent tweet's article comes first. The profile card is the block holding the
# avatar, name, and bio, directly under the banner.
# Both fail closed: a shifted layout matches nothing rather than the wrong block.
POST_CARD_SELECTOR = 'article:has(a[href$="/status/{post_id}"])'
# The 2026 X DOM has no test ids and moves its blocks around, so the profile header is found by
# shape (spec 2026-10-23 G5): the tallest full-width block above the first post that names the
# owner. The script tags it; the crop then uses the tag.
PROFILE_CARD_SELECTOR = '[data-thoth-profile-card="1"]'
# A signed-out page lays fixed and sticky bars over its posts: the "Continue to X" bar at the
# bottom (an <aside class="fixed bottom-0">) and the column's sticky header. An element
# screenshot paints whatever covers the element, so one comment card came out as a picture of
# that button (live check 2026-10-23). Every such layer that holds no post is hidden first.
HIDE_OVERLAYS_JS = """() => {
  for (const el of document.querySelectorAll('body *')) {
    const position = getComputedStyle(el).position;
    if ((position === 'fixed' || position === 'sticky')
        && !el.closest('article') && !el.querySelector('article')) {
      el.style.visibility = 'hidden';
    }
  }
}"""
TAG_PROFILE_JS = """(owner) => {
  document.querySelectorAll('[data-thoth-profile-card]')
    .forEach((el) => el.removeAttribute('data-thoth-profile-card'));
  const main = document.querySelector('main');
  if (!main) return false;
  const first = main.querySelector('article');
  const limit = first ? first.getBoundingClientRect().top + 1 : Infinity;
  const width = main.getBoundingClientRect().width;
  // The whole handle: "@bbc" must not match "@bbcnews" (handles are [A-Za-z0-9_] only).
  const handle = new RegExp('@' + owner + '(?![A-Za-z0-9_])', 'i');
  let best = null;
  let tallest = 0;
  for (const el of main.querySelectorAll('*')) {
    if (el.tagName === 'ARTICLE' || el.querySelector('article')) continue;
    const box = el.getBoundingClientRect();
    if (box.height <= 0 || box.bottom > limit || box.width < 0.9 * width) continue;
    if (!handle.test(el.innerText || '')) continue;
    if (box.height > tallest) {
      best = el;
      tallest = box.height;
    }
  }
  if (!best) return false;
  best.setAttribute('data-thoth-profile-card', '1');
  return true;
}"""
# The profile page card (spec 5c-2): X lists posts, not a grid, so the header and the first
# post. Checked against the page recorded on 2026-10-22, whose 2026 DOM has no test ids.
PROFILE_PAGE_ITEMS = "main article"
# A tag no page uses: an unreadable URL crops nothing.
NO_MATCH = "thoth-no-card"
# Spec 2026-10-24 D3: a signed-out post page shows only a few top replies, then a "See all the
# replies" gate. X's own embed widget renders any reply, dark and without its parent; it is a
# real X render, so it may stand in for a page card. Its host is not x.com, so the 30 s page
# gap does not apply between embeds.
EMBED_URL = (
    "https://platform.twitter.com/embed/Tweet.html?id={comment_id}"
    "&theme=dark&hideThread=true&dnt=true&lang=en"
)
MAX_EMBED_CARDS = 6
# The first embed keeps the x.com page gap (`card_browser.PAGE_SPACING_SECONDS`) from the last
# page visit; later embeds are this far apart (cost research 2026-10-24, operator-approved).
EMBED_SPACING_SECONDS = 10.0
EMBED_FETCH_TIMEOUT_MS = 15_000
EMBED_WAIT_MS = 5_000
# The source activity has 5 minutes (`workflows/source_investigation.py`); the operator's X run
# spent about 130 s before any embed. No embed starts once the card step has used this much.
CARD_STEP_BUDGET_SECONDS = 180.0
# Hosts the x.com card pages never load: fonts, analytics, and ads (cost research 2026-10-24).
# Video segments stay: blocking `video.twimg.com` left the post card's video tiles on a spinner
# and "The media could not be played" (live gate 2026-10-24). Embeds keep every host.
X_BLOCKED_DOMAINS = frozenset(
    {
        "fonts.gstatic.com",
        "fonts.googleapis.com",
        "analytics.twitter.com",
        "static.ads-twitter.com",
        "ads-twitter.com",
    }
)
# The embed is the reply when its article links to the reply's status, or shows its text.
EMBED_MATCH_JS = r"""
([id, prefix]) => {
  const article = document.querySelector("article");
  if (!article) return false;
  const status = new RegExp("/status/" + id + "(?:[/?#]|$)");
  const linked = Array.from(article.querySelectorAll('a[href*="/status/"]')).some(
    (a) => status.test(a.getAttribute("href") || "")
  );
  const squash = (text) => (text || "").replace(/\s+/g, " ").trim().toLowerCase();
  return linked || (prefix.length > 0 && squash(article.innerText).includes(squash(prefix)));
}
"""
STATUS_ID = re.compile(r"/status/([0-9]{1,19})")
PROFILE_OWNER = re.compile(r"^/([A-Za-z0-9_]{1,15})/?$")
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
    // A row linking to the reply's own status is exact; text matching is the fallback.
    const linked = rows.find((article) => !article.hasAttribute("data-thoth-comment")
      && article.querySelector('a[href$="/status/' + target.comment_id + '"]'));
    const handle = "@" + target.author.toLowerCase();
    const row = linked || rows.find((article) => {
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
        measure_media=True,
        page_items=PROFILE_PAGE_ITEMS,
        page_rows=1,
        hide_js=HIDE_OVERLAYS_JS,
        blocked_domains=X_BLOCKED_DOMAINS,
    )


def _text(response: Any) -> str:
    body = getattr(response, "body", b"")
    return body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)


class XRequestFetcher:
    """Plain impersonated HTTP GETs of the syndication JSON."""

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
        if is_login_path(response.url, SIGN_IN_PATHS):
            raise RequestFetchError(AcquisitionReason.LOGIN_WALL)
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


def embed_candidates(comments: list[ReportComment]) -> list[CommentTarget]:
    """Meaningful replies, most liked first: the ones worth an embed card (spec D1, D3)."""
    ranked = sorted(
        (comment for comment in comments if is_substantive(comment.text)),
        key=lambda comment: -comment.likes,
    )
    return comment_targets(ranked)


class XHeadlessBrowser(CardBrowser):
    """The X card session: post, reply, and profile cards; never content."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        super().__init__(x_layout(), session_factory)

    async def cards(
        self,
        post_url: str,
        profile_url: str,
        *,
        want_post: bool,
        targets: list[CommentTarget],
        embeds: list[CommentTarget] | None = None,
    ) -> Cards:
        """The post's own article (never the parent above it); the owner's profile block; then
        embed cards for the meaningful replies the page did not show (spec 2026-10-24, D3)."""
        status = STATUS_ID.search(post_url)
        owner = PROFILE_OWNER.match(urlsplit(profile_url).path)
        self._layout = replace(
            self._layout,
            post_selector=(
                POST_CARD_SELECTOR.format(post_id=status.group(1)) if status else NO_MATCH
            ),
            profile_selector=PROFILE_CARD_SELECTOR if owner else NO_MATCH,
            profile_tag_js=(f"({TAG_PROFILE_JS})({json.dumps(owner.group(1))})" if owner else None),
        )
        started = time.monotonic()
        cards = await super().cards(post_url, profile_url, want_post=want_post, targets=targets)
        missing = [target for target in embeds or [] if target.comment_id not in cards.comment_pngs]
        wanted = missing[:MAX_EMBED_CARDS]
        tried: list[CommentTarget] = []
        for index, target in enumerate(wanted):
            gap = card_browser.PAGE_SPACING_SECONDS if index == 0 else EMBED_SPACING_SECONDS
            if time.monotonic() - started + gap > CARD_STEP_BUDGET_SECONDS:
                break
            await asyncio.sleep(gap)
            await self._embed(target, cards)
            tried.append(target)
        if wanted:
            kept = sum(target.comment_id in cards.comment_pngs for target in tried)
            logger.info(
                "x embed cards tried=%d kept=%d skipped=%d",
                len(tried),
                kept,
                len(wanted) - len(tried),
            )
        return cards

    async def _embed(self, target: CommentTarget, cards: Cards) -> None:
        async def action(page: Any) -> None:
            with contextlib.suppress(Exception):
                await page.wait_for_selector("article", timeout=EMBED_WAIT_MS)
            matched = False
            with contextlib.suppress(Exception):
                matched = await page.evaluate(EMBED_MATCH_JS, [target.comment_id, target.prefix])
            if matched is True:
                png = await _crop(page, "article")
                if png is not None:
                    cards.comment_pngs[target.comment_id] = png

        try:
            await self._visit(
                EMBED_URL.format(comment_id=target.comment_id),
                action,
                timeout=EMBED_FETCH_TIMEOUT_MS,
            )
        except HeadlessBrowserError as error:
            cards.problems.append(error.reason.value)


class XAcquirer:
    """One X post: the syndication core, the page enrichment, media in order, and cards."""

    def __init__(
        self,
        request_fetcher: XRequestFetcher,
        headless: XHeadlessBrowser,
        materializer: MediaMaterializer,
        fxembed: FxEmbedClient,
    ) -> None:
        self._request = request_fetcher
        self._headless = headless
        self._materializer = materializer
        self._fxembed = fxembed

    async def _enrich(self, identity: XPostIdentity) -> XPageParse:
        """Videos, counters, long text and replies from FxEmbed (X's signed-out pages stopped
        embedding tweet JSON in October 2026). Best effort: any failure is today's syndication-
        only result plus a warning, never a failed acquisition."""
        try:
            status = await self._fxembed.status(identity.post_id)
            replies: list[dict[str, Any]] = []
            if status is not None:
                try:
                    replies = await self._fxembed.replies(identity.post_id)
                except RequestFetchError as error:
                    # The status alone still carries every video and the counters.
                    logger.warning("x fxembed replies unavailable reason=%s", error.reason.value)
            page = fx_page(status, replies, identity.post_id)
        except RequestFetchError as error:
            logger.warning("x fxembed enrichment unavailable reason=%s", error.reason.value)
            return XPageParse()
        except Exception:
            # Defense in depth: an unforeseen answer shape never fails the acquisition.
            logger.warning("x fxembed enrichment unreadable")
            return XPageParse()
        if status is None:
            logger.warning("x fxembed enrichment unavailable reason=no_status")
        logger.info(
            "x fxembed post videos=%d replies=%d dropped=%d",
            len(page.videos),
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
            page = await self._enrich(identity) if data is not None else XPageParse()
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
                code = failure_code(reason or AcquisitionReason.REQUEST_INCOMPLETE)
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=code, retryable=code in RETRYABLE_FAILURES, attempts=[attempt]
                    )
                )
            owner = parsed.post.owner_handle
            canonical = post_url(owner, identity.post_id)
            # Every post gets its card, video posts too: style A shows it (spec 5c-2, G1).
            cards = await self._headless.cards(
                canonical,
                f"{CANONICAL_BASE}/{owner}",
                want_post=True,
                targets=comment_targets(page.comments),
                embeds=embed_candidates(page.comments),
            )
            saved = await asyncio.to_thread(
                persist_cards, cards, page.comments, workflow_id, artifact_root
            )
            comments = saved.comments
            log_outcome(
                "x",
                CONTENT_METHOD,
                len(media),
                comments,
                saved.post_card,
                saved.profile_card,
                want_post=True,
                problems=cards.problems,
                dropped=page.dropped_comments,
                profile_page=saved.profile_page,
                want_page=True,
            )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="x", canonical_url=canonical),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    comments=comments,
                    post_card=saved.post_card,
                    profile_card=saved.profile_card,
                    profile_page=saved.profile_page,
                )
            )
        finally:
            # Same shielded close as Instagram: a second cancellation must not interrupt
            # browser cleanup partway through.
            await asyncio.shield(self._headless.close())
