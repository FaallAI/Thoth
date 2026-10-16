"""Scrapling stealthy-headless browser adapter for single-post TikTok acquisition.

This module is the sole boundary where raw browser state (HTML, captured XHR
bodies, cookies, headers, signed URLs) is inspected. Only validated scalar
fields and media URLs, reduced into a `BrowserSnapshot`, ever cross back out.
Scrapling/Patchright are imported lazily so importing this module (and the
rest of the control plane) never requires the optional `acquisition` extra.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import SecretStr, ValidationError

from thoth_control_plane.acquisition.adapters.tiktok import (
    TikTokPostIdentity,
    TikTokUrlError,
    canonicalize_tiktok_post_url,
)
from thoth_control_plane.acquisition.browser_loop import LoopBoundSession
from thoth_control_plane.acquisition.models import (
    MAX_COMMENTS,
    AcquisitionReason,
    BrowserSnapshot,
    MediaRequestContext,
    ResolvedMedia,
    TikTokComment,
    TikTokPost,
)
from thoth_control_plane.acquisition.normalize import normalize_engagement, published_at_from_epoch

CAPTURE_XHR_PATTERN = r"https://[^\s]+"
EMBEDDED_DATA_SELECTOR = "script#__UNIVERSAL_DATA_FOR_REHYDRATION__::text"
MEDIA_REFERER = "https://www.tiktok.com/"
FETCH_TIMEOUT_MS = 45_000
FETCH_WAIT_MS = 1_000
# Page-load options shared by every TikTok page visit (post and discovery).
FETCH_OPTIONS: dict[str, Any] = {
    "timeout": FETCH_TIMEOUT_MS,
    "network_idle": True,
    "disable_resources": False,
    "google_search": False,
    "wait": FETCH_WAIT_MS,
}
MAX_COMMENT_PAGES = 5
# Same-origin fetch from the loaded post page: it rides the browser's own network
# stack and cookies, needs no request signature, and never opens the comment panel
# (clicking the panel is what raises TikTok's captcha in headless). Only the four
# fields the snapshot keeps cross back into Python.
COMMENT_PAGE_JS = """async ([awemeId, cursor]) => {
  const r = await fetch(`/api/comment/list/?aid=1988&aweme_id=${awemeId}&count=20&cursor=${cursor}`,
                        {credentials: 'include'});
  const d = JSON.parse(await r.text());
  return {has_more: d.has_more, cursor: d.cursor,
          comments: (d.comments || []).map(c => ({cid: c.cid, text: c.text,
            digg_count: c.digg_count, unique_id: c.user && c.user.unique_id}))};
}"""
# TikTok's own comment and profile-grid XHRs carry signatures that headless sessions
# fail, and the failure raises a captcha modal over the page. The comment API does not
# enforce the signature, so its request is rerouted unsigned; the profile grid is not
# needed for the header card, so it is answered empty.
COMMENT_LIST_ROUTE = "**/api/comment/list/**"
ITEM_LIST_ROUTE = "**/api/post/item_list/**"
UNSIGNED_COMMENT_PARAMS = frozenset({"aid", "aweme_id", "count", "cursor"})
EMPTY_ITEM_LIST = '{"statusCode":0,"itemList":[],"hasMore":false,"cursor":"0"}'
COMMENT_SELECTOR = '[data-e2e="comment-level-1"]'
COMMENT_ICON_SELECTOR = '[data-e2e="comment-icon"]'
MAX_COMMENT_CARDS = 12  # Scout's `--max` default
# A "[Sticker]"/"[Stiker]"-only comment carries no text to ground a narration on, and its
# card is only the sticker image; both are dropped before any cap (Scout's `isStickerOnly`).
STICKER_ONLY = re.compile(r"\[\s*sti?c?ker\s*\]", re.IGNORECASE)
CARD_WAIT_S = 15
# Tag each rendered comment's card: the smallest ancestor holding the username and the
# avatar (Scout's climb). Returns [tag, text] per card; text keys the API comment.
COMMENT_CARDS_JS = """() => [...document.querySelectorAll('[data-e2e="comment-level-1"]')]
  .map((t, i) => {
    let w = t;
    for (let k = 0; k < 10 && w.parentElement; k++) {
      w = w.parentElement;
      if (w.querySelectorAll('[data-e2e="comment-level-1"]').length > 1) return null;
      if (w.querySelector('[data-e2e="comment-username-1"]') && w.querySelector('img')) {
        w.setAttribute('data-thoth-card', String(i));
        return [i, t.innerText];
      }
    }
    return null;
  }).filter(Boolean)"""
# Profile header card: avatar, name row and the three counts with their labels. Rows
# below the counts (buttons, bio) are hidden; the state is kept for the check below.
PROFILE_CARD_JS = """() => {
  const q = k => document.querySelector(`[data-e2e="${k}"]`);
  const av = q('user-avatar'), title = q('user-title');
  if (!av || !title) return null;
  const parts = [...title.parentElement.children];
  ['following-count', 'followers-count', 'likes-count'].forEach(k => {
    const e = q(k); if (e) parts.push(e.parentElement);
  });
  const rects = parts.map(e => e.getBoundingClientRect()).filter(r => r.width && r.height);
  const keepBottom = Math.max(...rects.map(r => r.bottom));
  let col = title;
  while (col.parentElement && !col.parentElement.contains(av)) col = col.parentElement;
  [...col.children].forEach(c => {
    if (c.getBoundingClientRect().top >= keepBottom) c.style.visibility = 'hidden';
  });
  window.__thothCard = {title, col, keepBottom};
  rects.push(av.getBoundingClientRect());
  const x1 = Math.min(...rects.map(r => r.left)), y1 = Math.min(...rects.map(r => r.top));
  const x2 = Math.max(...rects.map(r => r.right)), y2 = Math.max(...rects.map(r => r.bottom));
  const p = 18;
  return {x: Math.max(0, x1 + scrollX - p), y: Math.max(0, y1 + scrollY - p),
          width: x2 - x1 + 2 * p, height: y2 - y1 + 2 * p};
}"""
# TikTok first paints a preview header (grey label bars, *Placeholder buttons) that
# passes every text check, and React may re-show hidden rows; checked before and after
# the screenshot so only a final, fully rendered header is kept.
PROFILE_CARD_CHECK_JS = r"""() => {
  const q = k => document.querySelector(`[data-e2e="${k}"]`);
  const s = window.__thothCard;
  if (document.querySelector('[class*="ButtonPlaceholder"], [class*="TabsPlaceholder"]')) {
    return false;
  }
  if (!s || !s.title.isConnected || !s.col.isConnected) return false;
  const labelled = ['following-count', 'followers-count', 'likes-count'].every(k => {
    const e = q(k);
    return e && /\p{L}/u.test(e.parentElement.innerText.replace(e.innerText, ''));
  });
  const img = q('user-avatar') && q('user-avatar').querySelector('img');
  if (!labelled || !img || !img.complete || !img.naturalWidth) return false;
  return ![...s.col.querySelectorAll('*')].some(e => {
    const r = e.getBoundingClientRect();
    return r.height > 0 && r.top >= s.keepBottom && e.checkVisibility({visibilityProperty: true});
  });
}"""

_active_session_count = 0


class HeadlessBrowserError(RuntimeError):
    """Raised when the headless browser cannot produce a usable snapshot.

    Carries only a taxonomy `AcquisitionReason`; never the underlying
    exception, response, or browser state.
    """

    def __init__(self, reason: AcquisitionReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True, slots=True)
class ScraplingCapability:
    """Result of probing whether the optional Scrapling/Patchright stack is usable."""

    available: bool
    code: str | None = None


class HeadlessBrowser(Protocol):
    """Interface a headless browser adapter must satisfy for acquisition."""

    async def fetch(self, url: str) -> BrowserSnapshot: ...

    async def close(self) -> None: ...


def active_scrapling_session_count() -> int:
    """Return the number of currently-open Scrapling sessions (for lifecycle tests)."""
    return _active_session_count


def _increment_active_sessions() -> None:
    global _active_session_count
    _active_session_count += 1


def _decrement_active_sessions() -> None:
    global _active_session_count
    _active_session_count = max(0, _active_session_count - 1)


def _stealthy_session(**kwargs: Any) -> Any:
    from scrapling.fetchers import AsyncStealthySession

    return AsyncStealthySession(**kwargs)


def _default_session_factory(**kwargs: Any) -> Any:
    return LoopBoundSession(_stealthy_session, **kwargs)


def _item_struct(
    captured_xhr: list[dict[str, Any]], embedded_data: dict[str, Any] | None, post_id: str
) -> dict[str, Any] | None:
    """Return the `itemStruct` of `post_id`, from captured XHR bodies first, then from the
    page's embedded rehydration data (a direct post load embeds it; no item XHR fires)."""
    bodies = [
        entry.get("body")
        for entry in captured_xhr
        if isinstance(entry, dict) and entry.get("status") == 200
    ]
    scope = embedded_data.get("__DEFAULT_SCOPE__") if isinstance(embedded_data, dict) else None
    if isinstance(scope, dict):
        bodies.append(scope.get("webapp.video-detail"))
    for body in bodies:
        item_info = body.get("itemInfo") if isinstance(body, dict) else None
        item_struct = item_info.get("itemStruct") if isinstance(item_info, dict) else None
        if isinstance(item_struct, dict) and str(item_struct.get("id")) == post_id:
            return item_struct
    return None


def _xhr_media_urls(item_struct: dict[str, Any] | None) -> list[str]:
    if item_struct is None:
        return []
    video = item_struct.get("video")
    if not isinstance(video, dict):
        return []
    urls = []
    for key in ("playAddr", "downloadAddr"):
        value = video.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    return urls


def _parse_captured_xhr(raw_entries: list[Any]) -> list[dict[str, Any]]:
    """Normalize captured XHR entries (already-parsed dicts, or Scrapling `Response`
    objects exposing `.status` and a synchronous `.json()`) into plain dicts.

    Anything that cannot be safely parsed is silently dropped; raw bodies never
    propagate past this function.
    """
    parsed: list[dict[str, Any]] = []
    for entry in raw_entries:
        if isinstance(entry, dict):
            parsed.append(entry)
            continue
        status = getattr(entry, "status", None)
        json_method = getattr(entry, "json", None)
        if status is None or not callable(json_method):
            continue
        try:
            body = json_method()
        except Exception:
            continue
        if isinstance(body, dict):
            parsed.append({"status": status, "body": body})
    return parsed


def _sticker_only(text: object) -> bool:
    return isinstance(text, str) and STICKER_ONLY.fullmatch(text.strip()) is not None


def _reduce_comments(
    comment_pages: list[Any], comment_cards: list[tuple[str, bytes]]
) -> list[TikTokComment]:
    """First `MAX_COMMENTS` valid, distinct comments; malformed and sticker-only records are
    dropped.

    A card crop attaches to the first comment whose text matches its rendered text;
    a comment without a matching crop simply has none.
    """
    cards: dict[str, bytes] = {}
    for text, png in comment_cards:
        cards.setdefault(text.strip(), png)
    comments: dict[str, TikTokComment] = {}
    for page in comment_pages:
        raw = page.get("comments") if isinstance(page, dict) else None
        for entry in raw if isinstance(raw, list) else ():
            if (
                not isinstance(entry, dict)
                or str(entry.get("cid")) in comments
                or _sticker_only(entry.get("text"))
            ):
                continue
            likes = entry.get("digg_count")
            try:
                comment = TikTokComment(
                    comment_id=str(entry.get("cid")),
                    author=entry.get("unique_id"),
                    text=entry.get("text"),
                    likes=likes if isinstance(likes, int) and likes >= 0 else 0,
                    card_png=cards.pop(str(entry.get("text")).strip(), None),
                )
            except ValidationError:
                continue
            comments[comment.comment_id] = comment
            if len(comments) == MAX_COMMENTS:
                return list(comments.values())
    return list(comments.values())


def _unsigned_comment_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in UNSIGNED_COMMENT_PARAMS]
    return parts._replace(query=urlencode(query)).geturl()


async def _route_unsigned_comments(route: Any) -> None:
    await route.continue_(url=_unsigned_comment_url(route.request.url))


async def _route_empty_item_list(route: Any) -> None:
    await route.fulfill(status=200, content_type="application/json", body=EMPTY_ITEM_LIST)


async def _page_setup(page: Any) -> None:
    await page.context.route(COMMENT_LIST_ROUTE, _route_unsigned_comments)
    await page.context.route(ITEM_LIST_ROUTE, _route_empty_item_list)


@dataclass(slots=True)
class _Visit:
    """What the in-page action collects during the one headless post visit."""

    comment_pages: list[Any] = field(default_factory=list)
    comment_cards: list[tuple[str, bytes]] = field(default_factory=list)
    profile_card: bytes | None = None


async def _wait_for(page: Any, selector: str) -> bool:
    for _ in range(CARD_WAIT_S):
        if await page.locator(selector).count():
            return True
        await page.wait_for_timeout(1_000)
    return False


async def _crop_comment_cards(page: Any, cards: list[tuple[str, bytes]]) -> None:
    if not await _wait_for(page, COMMENT_SELECTOR):
        await page.locator(COMMENT_ICON_SELECTOR).first.click(timeout=5_000)
        if not await _wait_for(page, COMMENT_SELECTOR):
            return
    tagged = await page.evaluate(COMMENT_CARDS_JS)
    tagged = [(tag, text) for tag, text in tagged if not _sticker_only(text)]
    for tag, text in tagged[:MAX_COMMENT_CARDS]:
        with contextlib.suppress(Exception):
            card = page.locator(f'[data-thoth-card="{tag}"]')
            await card.scroll_into_view_if_needed(timeout=5_000)
            cards.append((str(text), await card.screenshot(timeout=10_000)))


async def _crop_profile_card(page: Any, handle: str) -> bytes | None:
    # A separate tab: Scrapling builds the response from the post tab after the action.
    tab = await page.context.new_page()
    try:
        await tab.goto(
            f"https://www.tiktok.com/@{handle}",
            wait_until="domcontentloaded",
            timeout=FETCH_TIMEOUT_MS,
        )
        for _ in range(CARD_WAIT_S):
            rect = await tab.evaluate(PROFILE_CARD_JS)
            if rect and await tab.evaluate(PROFILE_CARD_CHECK_JS):
                png = await tab.screenshot(clip=rect)
                if await tab.evaluate(PROFILE_CARD_CHECK_JS):
                    return png
            await tab.wait_for_timeout(1_000)
        return None
    finally:
        await tab.close()


def _visit_action(identity: TikTokPostIdentity, visit: _Visit) -> Callable[[Any], Any]:
    """Scrapling `page_action`: page comments by cursor, then crop real TikTok cards.

    Best effort: each step fails on its own (captcha body, non-JSON, missing element,
    navigation) and only loses its own output, so none can fail the acquisition. There
    is no synthetic card fallback; a card that cannot be cropped is simply absent.
    """

    async def collect(page: Any) -> None:
        cursor: Any = 0
        with contextlib.suppress(Exception):
            for _ in range(MAX_COMMENT_PAGES):
                result = await page.evaluate(COMMENT_PAGE_JS, [identity.post_id, cursor])
                visit.comment_pages.append(result)
                if (
                    not isinstance(result, dict)
                    or not result.get("has_more")
                    or sum(len(p.get("comments") or []) for p in visit.comment_pages)
                    >= MAX_COMMENTS
                ):
                    break
                cursor = result.get("cursor")
        with contextlib.suppress(Exception):
            await _crop_comment_cards(page, visit.comment_cards)
        with contextlib.suppress(Exception):
            visit.profile_card = await _crop_profile_card(page, identity.owner_handle)

    return collect


def _normalize_handle(value: str) -> str:
    return value.strip().removeprefix("@").casefold()


def extract_browser_snapshot(
    *,
    final_url: str,
    og_title: str | None,
    author: str | None,
    video_sources: list[str],
    captured_xhr: list[dict[str, Any]],
    embedded_data: dict[str, Any] | None = None,
    request_context: MediaRequestContext | None = None,
    comment_pages: list[Any] | None = None,
    comment_cards: list[tuple[str, bytes]] | None = None,
    profile_card: bytes | None = None,
) -> BrowserSnapshot:
    """Reduce raw headless browser output to a sanitized `BrowserSnapshot`.

    `final_url` is validated through Task 2's canonicalization before any
    candidate is accepted. Raw XHR bodies are inspected only long enough to
    pull out `id`/`desc`/`author.uniqueId`, `createTime`, and the `stats`/`statsV2`
    counters; nothing raw is retained.

    Owner-handle cross-check precedence: the XHR `uniqueId` is an
    authoritative signal straight from TikTok's own item data, so when it is
    present it alone decides the match. The `meta[name="author"]` tag is a
    page-rendering artifact (can be absent, differently formatted, or a
    display name) and is only consulted as a fallback when the XHR signal is
    absent. Either signal fails safe: a mismatch downgrades to no candidate.

    Caption precedence: the XHR `desc` is the only caption source. `og_title`
    is TikTok's page title ("<display name> on TikTok") on every post measured,
    including posts that carry a long caption, so it holds no caption
    information and must never stand in for one -- an empty caption is a valid
    result, while a fabricated one would poison downstream narration grounding.

    Media candidates are https only (the player's `blob:` src is unfetchable)
    and come only from the item of this post, never from another video's.
    """
    identity = canonicalize_tiktok_post_url(final_url)
    canonical_handle = _normalize_handle(identity.owner_handle)

    item_struct = _item_struct(captured_xhr, embedded_data, identity.post_id)
    caption = ""
    published_at: str | None = None
    engagement: dict[str, int] = {}
    xhr_unique_id: str | None = None
    if item_struct is not None:
        published_at = published_at_from_epoch(item_struct.get("createTime"))
        engagement = normalize_engagement(item_struct.get("stats"), item_struct.get("statsV2"))
        xhr_desc = item_struct.get("desc")
        if isinstance(xhr_desc, str):
            caption = xhr_desc
        xhr_author = item_struct.get("author")
        if isinstance(xhr_author, dict):
            unique_id = xhr_author.get("uniqueId")
            if isinstance(unique_id, str) and unique_id:
                xhr_unique_id = unique_id

    if xhr_unique_id is not None:
        owner_matches = _normalize_handle(xhr_unique_id) == canonical_handle
    else:
        owner_matches = author is None or _normalize_handle(author) == canonical_handle

    post_candidates: list[TikTokPost] = []
    if owner_matches:
        post_candidates.append(
            TikTokPost(
                post_id=identity.post_id,
                owner_handle=identity.owner_handle,
                caption=caption[:10_000],
                published_at=published_at,
                engagement=engagement,
            )
        )

    media_urls = list(dict.fromkeys([*video_sources, *_xhr_media_urls(item_struct)]))
    media_candidates = [
        ResolvedMedia(ephemeral_url=SecretStr(url), request_context=request_context)
        for url in media_urls
        if url.startswith("https://")
    ]

    return BrowserSnapshot(
        final_url=identity.canonical_url,
        post_candidates=post_candidates,
        media_candidates=media_candidates,
        comments=_reduce_comments(comment_pages or [], comment_cards or []),
        profile_card_png=profile_card,
    )


def _extract_from_response(response: Any, visit: _Visit | None = None) -> BrowserSnapshot:
    visit = visit or _Visit()
    og_title = response.css('meta[property="og:title"]::attr(content)').get()
    author = response.css('meta[name="author"]::attr(content)').get()
    video_sources = response.css("video::attr(src)").getall()
    captured_xhr = _parse_captured_xhr(getattr(response, "captured_xhr", []))
    embedded_data: Any = None
    with contextlib.suppress(ValueError):
        embedded_data = json.loads(response.css(EMBEDDED_DATA_SELECTOR).get() or "null")
    return extract_browser_snapshot(
        final_url=str(response.url),
        og_title=og_title,
        author=author,
        video_sources=list(video_sources),
        captured_xhr=captured_xhr,
        embedded_data=embedded_data if isinstance(embedded_data, dict) else None,
        request_context=_media_request_context(response),
        comment_pages=visit.comment_pages,
        comment_cards=visit.comment_cards,
        profile_card=visit.profile_card,
    )


def _media_request_context(response: Any) -> MediaRequestContext:
    """Capture the session TikTok binds its signed media URLs to (context cookies + UA)."""
    headers = getattr(response, "request_headers", None)
    user_agent = None
    if isinstance(headers, dict):
        user_agent = next(
            (str(v) for k, v in headers.items() if str(k).lower() == "user-agent"), None
        )
    raw_cookies = getattr(response, "cookies", None)
    cookies = [
        (str(c.get("domain") or ""), str(c["name"]), SecretStr(str(c.get("value") or "")))
        for c in (raw_cookies if isinstance(raw_cookies, (list, tuple)) else ())
        if isinstance(c, dict) and c.get("name") and c.get("domain")
    ]
    return MediaRequestContext(user_agent=user_agent, referer=MEDIA_REFERER, cookies=cookies)


def _is_timeout(error: Exception) -> bool:
    # Playwright and asyncio name their timeout errors differently; both say "timeout".
    return "timeout" in type(error).__name__.lower()


def _classify_fetch_error(error: Exception) -> AcquisitionReason:
    if _is_timeout(error):
        return AcquisitionReason.HEADLESS_TIMEOUT
    return AcquisitionReason.HEADLESS_BLOCKED


class ScraplingHeadlessBrowser:
    """Primary TikTok acquisition strategy: a stealthy headless browser session."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None

    async def fetch(self, url: str) -> BrowserSnapshot:
        session = self._session_factory(headless=True, max_pages=1, capture_xhr=CAPTURE_XHR_PATTERN)
        try:
            active = await session.__aenter__()
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None

        self._session = session
        _increment_active_sessions()
        visit = _Visit()
        try:
            identity = canonicalize_tiktok_post_url(url)
            response = await active.fetch(
                url,
                page_setup=_page_setup,
                page_action=_visit_action(identity, visit),
                **FETCH_OPTIONS,
            )
            snapshot = _extract_from_response(response, visit)
        except TikTokUrlError:
            await self.close()
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED) from None
        except Exception as error:
            await self.close()
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None
        except BaseException:
            # Cancellation and other non-Exception signals: still close, then
            # propagate unchanged (never reclassified as an acquisition reason).
            await self.close()
            raise

        # An incomplete snapshot (no post or no media candidate) is returned, not
        # raised: the service classifies it as `headless_incomplete` and keeps the
        # comments and cards the visit already collected through a TikWM rescue.
        return snapshot

    async def close(self) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        try:
            await session.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            _decrement_active_sessions()


async def check_scrapling_capability() -> ScraplingCapability:
    """Probe whether the optional Scrapling/Patchright browser stack is usable.

    Never raises and never retains the underlying exception; a missing
    optional extra or an unusable browser binary both report the same safe
    `acquisition_dependency_unavailable` code.
    """
    try:
        from patchright.async_api import async_playwright
        from scrapling.fetchers import AsyncStealthySession  # noqa: F401
    except ImportError:
        return ScraplingCapability(available=False, code="acquisition_dependency_unavailable")

    playwright = None
    try:
        playwright = await async_playwright().start()
        executable_path = Path(playwright.chromium.executable_path)
        if not executable_path.is_file():
            return ScraplingCapability(available=False, code="acquisition_dependency_unavailable")
        return ScraplingCapability(available=True, code=None)
    except Exception:
        return ScraplingCapability(available=False, code="acquisition_dependency_unavailable")
    finally:
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()
