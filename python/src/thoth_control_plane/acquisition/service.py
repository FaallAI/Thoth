"""Headless-first TikTok acquisition orchestration with a bounded TikWM fallback.

Scrapling headless is always attempted first, unconditionally. TikWM/CDN runs
at most once, and only after a headless attempt that failed, came back
incomplete, was blocked, timed out, or whose media failed to materialize.
This module never imports Temporal or legacy Scout; it is a pure async
module that Task 6 adapts into a Temporal activity.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path, PurePosixPath

from thoth_control_plane.acquisition.adapters.tiktok import (
    TikTokPostIdentity,
    TikTokUrlError,
    canonicalize_tiktok_post_url,
    validate_tiktok_entry_url,
)
from thoth_control_plane.acquisition.adapters.tikwm import TikWmError, TikWmResolver
from thoth_control_plane.acquisition.browser import HeadlessBrowser, HeadlessBrowserError
from thoth_control_plane.acquisition.cards import persist_cards
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
)
from thoth_control_plane.acquisition.models import (
    AcquisitionAttempt,
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    AttemptStatus,
    BrowserSnapshot,
    CardArtifact,
    MaterializedMedia,
    ReportComment,
    ReportSource,
    ResolvedMedia,
    SourcePost,
    SourceReport,
    TikTokPost,
)

RETRYABLE_FAILURES = frozenset(
    {
        "headless_timeout",
        "headless_blocked",
        "headless_incomplete",
        "request_timeout",
        "request_blocked",
        "request_incomplete",
        "cdn_rate_limited",
        "cdn_unavailable",
        "media_validation_failed",
    }
)


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def _make_attempt(
    strategy: AcquisitionStrategy, reason: AcquisitionReason | None, elapsed_ms: int
) -> AcquisitionAttempt:
    if reason is None:
        status = AttemptStatus.SUCCEEDED
    elif reason in (AcquisitionReason.HEADLESS_INCOMPLETE, AcquisitionReason.REQUEST_INCOMPLETE):
        status = AttemptStatus.INCOMPLETE
    else:
        status = AttemptStatus.FAILED
    return AcquisitionAttempt(
        strategy=strategy, status=status, reason=reason, attempt_count=1, elapsed_ms=elapsed_ms
    )


def _derive_identity(
    source_url: str, snapshot: BrowserSnapshot | None
) -> TikTokPostIdentity | None:
    """Canonicalize an identity from the browser's final URL, falling back to
    the (already validated) entry URL when no headless snapshot is available.
    Canonical URL identity is always preferred over a provider-reported id.
    """
    candidate_urls = [str(snapshot.final_url)] if snapshot is not None else []
    candidate_urls.append(source_url)
    for url in candidate_urls:
        try:
            return canonicalize_tiktok_post_url(url)
        except TikTokUrlError:
            continue
    return None


def _merge_post(
    identity: TikTokPostIdentity | None,
    headless_post: TikTokPost | None,
    provider_post: TikTokPost | None,
) -> TikTokPost:
    """Prefer a valid headless caption over a provider caption, while
    canonical URL identity (if derivable) wins all post-id/handle conflicts.
    `published_at` and `engagement` merge per field, headless first.
    """
    caption = ""
    if headless_post is not None and headless_post.caption:
        caption = headless_post.caption
    elif provider_post is not None:
        caption = provider_post.caption

    published_at: str | None = None
    engagement: dict[str, int] = {}
    for post in (headless_post, provider_post):
        if post is not None:
            published_at = published_at or post.published_at
            engagement = engagement or post.engagement

    identity_source = identity or headless_post or provider_post
    if identity_source is None:
        raise AssertionError("post identity must be derivable from at least one source")
    return TikTokPost(
        post_id=identity_source.post_id,
        owner_handle=identity_source.owner_handle,
        caption=caption,
        published_at=published_at,
        engagement=engagement,
    )


def _fallback_canonical_url(post: TikTokPost) -> str:
    return f"https://www.tiktok.com/@{post.owner_handle}/video/{post.post_id}"


def _build_report(
    workflow_id: str,
    identity: TikTokPostIdentity | None,
    post: TikTokPost,
    materialized: MaterializedMedia,
    attempts: list[AcquisitionAttempt],
    comments: list[ReportComment],
    profile_card: CardArtifact | None,
    post_card: CardArtifact | None = None,
) -> SourceReport:
    canonical_url = (
        identity.canonical_url if identity is not None else _fallback_canonical_url(post)
    )
    return SourceReport(
        workflow_id=workflow_id,
        source=ReportSource(platform="tiktok", canonical_url=canonical_url),
        post=SourcePost(
            post_id=post.post_id,
            owner_handle=post.owner_handle,
            text=post.caption,
            published_at=post.published_at,
            engagement=post.engagement,
        ),
        media=[materialized],
        outcome=AcquisitionOutcome(attempts=attempts),
        comments=comments,
        profile_card=profile_card,
        post_card=post_card,
    )


class TikTokAcquisitionService:
    """Orchestrates one public TikTok post through headless-first acquisition."""

    def __init__(
        self,
        browser: HeadlessBrowser,
        resolver: TikWmResolver,
        materializer: MediaMaterializer,
    ) -> None:
        self._browser = browser
        self._resolver = resolver
        self._materializer = materializer

    async def _materialize(
        self,
        candidate: ResolvedMedia,
        workflow_id: str,
        post_id: str,
        strategy: AcquisitionStrategy,
        artifact_root: Path,
    ) -> MaterializedMedia:
        relative_location = (
            PurePosixPath("reports") / workflow_id / "media" / f"tiktok-{post_id}.mp4"
        )
        destination = artifact_root / relative_location
        return await self._materializer.materialize(
            candidate, destination, relative_location, strategy
        )

    async def inspect(
        self, *, workflow_id: str, source_url: str, artifact_root: Path
    ) -> AcquisitionResult:
        try:
            validate_tiktok_entry_url(source_url)
        except TikTokUrlError:
            return AcquisitionResult(
                failure=AcquisitionFailure(code="invalid_tiktok_url", retryable=False)
            )

        attempts: list[AcquisitionAttempt] = []
        snapshot: BrowserSnapshot | None = None
        headless_reason: AcquisitionReason | None = None
        headless_post: TikTokPost | None = None
        identity: TikTokPostIdentity | None = None
        materialized: MaterializedMedia | None = None

        headless_start = time.monotonic()
        try:
            snapshot = await self._browser.fetch(source_url)
        except HeadlessBrowserError as error:
            headless_reason = error.reason
        finally:
            # Browser cleanup runs unconditionally, including on cancellation:
            # `asyncio.CancelledError` derives from `BaseException`, so it is
            # not caught above, but this `finally` still closes the browser
            # before the cancellation propagates. `asyncio.shield` runs
            # close() as an independent task so a *second* cancellation
            # delivered while we are awaiting it cannot also cancel the
            # underlying cleanup partway through.
            await asyncio.shield(self._browser.close())

        if headless_reason is None:
            assert snapshot is not None  # guaranteed: no exception was raised above
            identity = _derive_identity(source_url, snapshot)
            headless_post = snapshot.post_candidates[0] if snapshot.post_candidates else None
            if snapshot.post_candidates and snapshot.media_candidates and identity is not None:
                # Candidates are ordered by preference; one that fails
                # validation must not hide a later one that would pass.
                for candidate in snapshot.media_candidates:
                    try:
                        materialized = await self._materialize(
                            candidate,
                            workflow_id,
                            identity.post_id,
                            AcquisitionStrategy.SCRAPLING_HEADLESS,
                            artifact_root,
                        )
                        break
                    except MediaMaterializationError:
                        continue
                if materialized is None:
                    headless_reason = AcquisitionReason.MEDIA_VALIDATION_FAILED
            else:
                headless_reason = AcquisitionReason.HEADLESS_INCOMPLETE

        attempts.append(
            _make_attempt(
                AcquisitionStrategy.SCRAPLING_HEADLESS,
                None if materialized is not None else headless_reason,
                _elapsed_ms(headless_start),
            )
        )

        if materialized is not None:
            post = _merge_post(identity, headless_post, None)
            comments, profile_card, post_card = await asyncio.to_thread(
                persist_cards, snapshot, workflow_id, artifact_root
            )
            return AcquisitionResult(
                report=_build_report(
                    workflow_id,
                    identity,
                    post,
                    materialized,
                    attempts,
                    comments,
                    profile_card,
                    post_card,
                )
            )

        # Headless did not produce usable, materialized media: this is the
        # single eligible condition under which TikWM may run, and it runs
        # at most once from this point on.
        assert headless_reason is not None

        tikwm_start = time.monotonic()
        try:
            resolution = await self._resolver.resolve(source_url)
        except TikWmError as error:
            reason = AcquisitionReason(error.code)
            attempts.append(
                _make_attempt(AcquisitionStrategy.TIKWM_CDN, reason, _elapsed_ms(tikwm_start))
            )
            return AcquisitionResult(
                failure=AcquisitionFailure(
                    code=reason.value,
                    retryable=reason.value in RETRYABLE_FAILURES,
                    attempts=list(attempts),
                )
            )

        merged_identity = identity if identity is not None else _derive_identity(source_url, None)
        post_id = (
            merged_identity.post_id if merged_identity is not None else resolution.post.post_id
        )

        try:
            materialized = await self._materialize(
                resolution.media, workflow_id, post_id, AcquisitionStrategy.TIKWM_CDN, artifact_root
            )
        except MediaMaterializationError:
            attempts.append(
                _make_attempt(
                    AcquisitionStrategy.TIKWM_CDN,
                    AcquisitionReason.MEDIA_VALIDATION_FAILED,
                    _elapsed_ms(tikwm_start),
                )
            )
            return AcquisitionResult(
                failure=AcquisitionFailure(
                    code="media_validation_failed", retryable=True, attempts=list(attempts)
                )
            )

        attempts.append(
            _make_attempt(AcquisitionStrategy.TIKWM_CDN, None, _elapsed_ms(tikwm_start))
        )
        post = _merge_post(merged_identity, headless_post, resolution.post)
        # Comments come only from the headless visit; TikWM yields none.
        comments, profile_card, post_card = await asyncio.to_thread(
            persist_cards, snapshot, workflow_id, artifact_root
        )
        return AcquisitionResult(
            report=_build_report(
                workflow_id,
                merged_identity,
                post,
                materialized,
                attempts,
                comments,
                profile_card,
                post_card,
            )
        )
