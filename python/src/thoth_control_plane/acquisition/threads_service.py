"""Threads single-post acquisition: one content method, a best-effort headless post card.

`CONTENT_METHOD` is decided once from the Stage 3a golden-fixture comparison (request wins
when it matches or beats headless on every count). There is no runtime fallback between
methods; the legacy fallback lives in the workflow.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from thoth_control_plane.acquisition.adapters.threads import (
    POST_PATH,
    SHARE_PATH,
    ThreadsParse,
    ThreadsPostIdentity,
    ThreadsUrlError,
    canonical_threads_share_url,
    canonicalize_threads_post_url,
    json_roots,
    parse_documents,
)
from thoth_control_plane.acquisition.browser import (
    FETCH_OPTIONS,
    HeadlessBrowserError,
    _classify_fetch_error,
    _decrement_active_sessions,
    _default_session_factory,
    _increment_active_sessions,
    _is_timeout,
    _parse_captured_xhr,
)
from thoth_control_plane.acquisition.cards import CardRejected, write_card
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    MAX_MEDIA_ITEMS,
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    CardArtifact,
    MaterializedMedia,
    ReportSource,
    SourceReport,
)
from thoth_control_plane.acquisition.service import (
    RETRYABLE_FAILURES,
    _elapsed_ms,
    _make_attempt,
)

# Provisional until Task 10 records the comparison; a test pins it to the fixtures.
CONTENT_METHOD: Literal["request", "headless"] = "request"
REQUEST_OPTIONS: dict[str, Any] = {
    "impersonate": "chrome",
    "stealthy_headers": True,
    "follow_redirects": "safe",
    "timeout": 30,
    "retries": 1,
}
THREADS_CAPTURE_XHR = r"https://www\.threads\.(?:com|net)/(?:api/)?graphql.*"
POST_CARD_SELECTOR = 'div[data-pressable-container="true"]'
SCRIPT_SELECTOR = 'script[type="application/json"]::text'
SHARE_RESOLVE_TIMEOUT_MS = 15_000
_STRATEGIES = {
    "request": AcquisitionStrategy.SCRAPLING_REQUEST,
    "headless": AcquisitionStrategy.SCRAPLING_HEADLESS,
}


class RequestFetchError(Exception):
    def __init__(self, reason: AcquisitionReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


async def _scrapling_get(url: str, **kwargs: Any) -> Any:
    from scrapling.fetchers import AsyncFetcher

    return await AsyncFetcher.get(url, **kwargs)


def _blocked(final_url: object) -> bool:
    return urlsplit(str(final_url)).path.startswith("/login")


class ThreadsRequestFetcher:
    """Plain impersonated HTTP GET; returns the page's embedded JSON script texts."""

    def __init__(self, get: Callable[..., Awaitable[Any]] | None = None) -> None:
        self._get = get or _scrapling_get

    async def fetch(self, url: str) -> list[str]:
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
        return [text for text in response.css(SCRIPT_SELECTOR).getall() if text]


@dataclass(frozen=True)
class ThreadsPage:
    xhr_bodies: list[object]
    script_texts: list[str]
    card_png: bytes | None


def _crop_post_card(cards: list[bytes]) -> Callable[[Any], Awaitable[None]]:
    async def crop(page: Any) -> None:
        # Best effort: a card that cannot be cropped is simply absent.
        with contextlib.suppress(Exception):
            card = page.locator(POST_CARD_SELECTOR).first
            await card.scroll_into_view_if_needed(timeout=5_000)
            cards.append(await card.screenshot(timeout=10_000))

    return crop


def _await_post_url(landing: list[str]) -> Callable[[Any], Awaitable[None]]:
    async def wait(page: Any) -> None:
        # A share link redirects client-side; record wherever the page ends up.
        with contextlib.suppress(Exception):
            await page.wait_for_url(
                lambda url: POST_PATH.fullmatch(urlsplit(url).path) is not None,
                timeout=SHARE_RESOLVE_TIMEOUT_MS,
            )
        landing.append(page.url)

    return wait


class ThreadsHeadlessBrowser:
    """A stealthy headless visit: GraphQL bodies, embedded JSON, and a post-card crop."""

    def __init__(self, session_factory: Callable[..., Any] = _default_session_factory) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None

    async def fetch(self, url: str) -> ThreadsPage:
        session = self._session_factory(headless=True, max_pages=1, capture_xhr=THREADS_CAPTURE_XHR)
        try:
            active = await session.__aenter__()
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None

        self._session = session
        _increment_active_sessions()
        cards: list[bytes] = []
        try:
            response = await active.fetch(url, page_action=_crop_post_card(cards), **FETCH_OPTIONS)
            if _blocked(response.url):
                raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
            xhr = _parse_captured_xhr(list(getattr(response, "captured_xhr", None) or []))
            return ThreadsPage(
                xhr_bodies=[entry.get("body") for entry in xhr if entry.get("status") == 200],
                script_texts=[text for text in response.css(SCRIPT_SELECTOR).getall() if text],
                card_png=cards[0] if cards else None,
            )
        except HeadlessBrowserError:
            await self.close()
            raise
        except Exception as error:
            await self.close()
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None
        except BaseException:
            await self.close()
            raise

    async def resolve(self, share_url: str) -> str:
        """Follow a share link in its own short-lived session; return the landing URL."""
        session = self._session_factory(headless=True, max_pages=1)
        try:
            active = await session.__aenter__()
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None
        _increment_active_sessions()
        landing: list[str] = []
        try:
            await active.fetch(share_url, page_action=_await_post_url(landing), **FETCH_OPTIONS)
        except Exception as error:
            raise HeadlessBrowserError(_classify_fetch_error(error)) from None
        finally:
            try:
                await asyncio.shield(session.__aexit__(None, None, None))
            except Exception:
                pass
            finally:
                _decrement_active_sessions()
        if landing and _blocked(landing[0]):
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_BLOCKED)
        if not landing or SHARE_PATH.fullmatch(urlsplit(landing[0]).path):
            # The client-side redirect never happened in time; a retry may still land.
            raise HeadlessBrowserError(AcquisitionReason.HEADLESS_INCOMPLETE)
        return landing[0]

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


async def resolve_threads_identity(
    source_url: str, headless: ThreadsHeadlessBrowser
) -> ThreadsPostIdentity:
    """A post URL is its own identity; a share link is followed once in the browser."""
    try:
        return canonicalize_threads_post_url(source_url)
    except ThreadsUrlError:
        share_url = canonical_threads_share_url(source_url)
    return canonicalize_threads_post_url(await headless.resolve(share_url))


def _persist_post_card(
    card_png: bytes | None, workflow_id: str, artifact_root: Path
) -> CardArtifact | None:
    if card_png is None:
        return None
    location = PurePosixPath("reports") / workflow_id / "cards" / "post.png"
    try:
        return write_card(card_png, artifact_root, location)
    except (CardRejected, OSError):
        return None


class ThreadsAcquirer:
    """One Threads post: content by `CONTENT_METHOD`, media in order, a card for non-video."""

    def __init__(
        self,
        request_fetcher: ThreadsRequestFetcher,
        headless: ThreadsHeadlessBrowser,
        materializer: MediaMaterializer,
    ) -> None:
        self._request = request_fetcher
        self._headless = headless
        self._materializer = materializer

    async def _content(
        self, identity: ThreadsPostIdentity
    ) -> tuple[ThreadsParse | None, AcquisitionReason | None, bytes | None]:
        url = str(identity.canonical_url)
        if CONTENT_METHOD == "request":
            try:
                texts = await self._request.fetch(url)
            except RequestFetchError as error:
                return None, error.reason, None
            parsed = parse_documents(json_roots(texts), identity)
            return parsed, None if parsed else AcquisitionReason.REQUEST_INCOMPLETE, None
        try:
            page = await self._headless.fetch(url)
        except HeadlessBrowserError as error:
            return None, error.reason, None
        parsed = parse_documents([*page.xhr_bodies, *json_roots(page.script_texts)], identity)
        return parsed, None if parsed else AcquisitionReason.HEADLESS_INCOMPLETE, page.card_png

    async def _card_visit(self, identity: ThreadsPostIdentity) -> bytes | None:
        try:
            return (await self._headless.fetch(str(identity.canonical_url))).card_png
        except HeadlessBrowserError:
            return None

    async def _materialize_all(
        self,
        parsed: ThreadsParse,
        workflow_id: str,
        strategy: AcquisitionStrategy,
        artifact_root: Path,
    ) -> list[MaterializedMedia]:
        done: list[MaterializedMedia] = []
        try:
            for index, candidate in enumerate(parsed.media[:MAX_MEDIA_ITEMS], start=1):
                location = (
                    PurePosixPath("reports")
                    / workflow_id
                    / "media"
                    / f"threads-{parsed.post.post_id}-{index}"
                )
                done.append(
                    await self._materializer.materialize(
                        candidate,
                        artifact_root / location,
                        location,
                        strategy,
                        media_id=f"media_{index}",
                        index=index,
                    )
                )
        except BaseException:
            # A partial carousel is never reported; remove what this call wrote.
            for item in done:
                with contextlib.suppress(OSError):
                    (artifact_root / item.location).unlink(missing_ok=True)
            raise
        return done

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        strategy = _STRATEGIES[CONTENT_METHOD]
        try:
            try:
                identity = await resolve_threads_identity(source_url, self._headless)
            except ThreadsUrlError:
                return AcquisitionResult(
                    failure=AcquisitionFailure(code="invalid_source_url", retryable=False)
                )
            except HeadlessBrowserError as error:
                return AcquisitionResult(
                    failure=AcquisitionFailure(
                        code=error.reason.value,
                        retryable=error.reason.value in RETRYABLE_FAILURES,
                    )
                )
            start = time.monotonic()
            parsed, reason, card_png = await self._content(identity)
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
                    media = await self._materialize_all(
                        parsed, workflow_id, strategy, artifact_root
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
            post_card = None
            if not any(item.kind == "video" for item in media):
                if CONTENT_METHOD == "request":
                    card_png = await self._card_visit(identity)
                post_card = await asyncio.to_thread(
                    _persist_post_card, card_png, workflow_id, artifact_root
                )
            return AcquisitionResult(
                report=SourceReport(
                    workflow_id=workflow_id,
                    source=ReportSource(platform="threads", canonical_url=identity.canonical_url),
                    post=parsed.post,
                    media=media,
                    outcome=AcquisitionOutcome(attempts=[attempt]),
                    post_card=post_card,
                )
            )
        finally:
            # Same shielded close as the TikTok service: a second cancellation must not
            # interrupt browser cleanup partway through.
            await asyncio.shield(self._headless.close())
