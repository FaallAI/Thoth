"""S1 to S6 of source attribution: is this post the original, and if not, which post is?

`SourceAttributor.identify` reads evidence from the repost, decides the credit, discovers the
credited account's videos, filters them by free metadata, matches frames, and acquires at most a
few finalists, stopping at the first measured match. Every port failure degrades one piece of
evidence or one candidate; `identify` raises only on cancellation.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution import credit
from thoth_control_plane.attribution.candidates import parse_time, shortlist
from thoth_control_plane.attribution.matching import (
    FrameHash,
    TextBox,
    looks_like_burned_in_speech,
    match_share,
)
from thoth_control_plane.attribution.models import (
    MAX_EVIDENCE,
    AttributedPost,
    AttributionEvidence,
    Platform,
    SourceAttribution,
    Verdict,
)
from thoth_control_plane.attribution.ports import (
    AcquiredCandidate,
    CandidateAcquirer,
    CoverReading,
    DecisionModel,
    Discoverer,
    Frame,
    FrameHasher,
    FrameSource,
    TextReader,
    VisionReader,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class Tuning:
    """Provisional until the golden-fixture capture calibrates them (plan Task 11)."""

    hash_fps: float = 1.0
    credit_seconds: float = 3.0
    reaction_frames: int = 10
    max_distance: int = 10
    match_threshold: float = 0.6
    repost_threshold: float = 0.5
    handle_threshold: float = 0.5
    max_finalists: int = 3
    finalist_concurrency: int = 2


DEFAULT_TUNING = Tuning()


@dataclass(frozen=True)
class AttributionPorts:
    frames: FrameSource
    hasher: FrameHasher
    text: TextReader
    discoverer: Discoverer
    acquirer: CandidateAcquirer
    vision: VisionReader | None = None
    decisions: DecisionModel | None = None


@dataclass(frozen=True)
class AttributionOutcome:
    attribution: SourceAttribution
    original: AcquiredCandidate | None = None


@dataclass(frozen=True)
class _Credit:
    handle: str | None
    platform: Platform | None
    repost_probability: float
    by_model: bool
    ambiguous: bool = False


@dataclass
class _Finalist:
    video: DiscoveredVideo
    candidate_id: str
    checked: bool = False
    acquired: AcquiredCandidate | None = None
    share: float | None = None
    rejected: str | None = None


class SourceAttributor:
    def __init__(
        self,
        ports: AttributionPorts,
        tuning: Tuning = DEFAULT_TUNING,
        curated: frozenset[str] = frozenset(),
    ) -> None:
        self._ports = ports
        self._tuning = tuning
        self._curated = curated

    @property
    def ports(self) -> AttributionPorts:
        return self._ports

    async def identify(
        self, workflow_id: str, report: SourceReport, video: Path | None
    ) -> AttributionOutcome:
        frames = await self._frames(video)
        lines: list[str] = []
        for frame in frames:
            if frame.second < self._tuning.credit_seconds:
                lines += [box.text for box in await self._read(frame)]
        cover = await self._cover(frames)
        owner = report.post.owner_handle
        caption_handles = credit.text_handles(report.post.text)
        found_in_frames = credit.frame_handles(lines)
        read_by_vision = credit.vision_handles(cover.handles) if cover is not None else []
        options = credit.credit_options(caption_handles, [*found_in_frames, *read_by_vision], owner)
        evidence = _text_evidence(
            caption_handles, [*found_in_frames, *read_by_vision], owner, cover
        )
        decided = await self._credit(report, options, lines, cover, evidence)

        if decided.handle is None:
            if decided.ambiguous:
                return self._finish(
                    workflow_id, report, "unresolved", evidence, reason="ambiguous_credit"
                )
            repost = decided.repost_probability >= self._tuning.repost_threshold
            return self._finish(
                workflow_id,
                report,
                "unresolved" if repost else "original",
                evidence,
                reason="no_credit" if repost else None,
                confidence="high" if decided.by_model else "low",
            )

        platform: Platform = decided.platform or report.source.platform
        counts: Counter[str] = Counter()
        if not self._ports.discoverer.supports(platform):
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="discovery_unsupported"
            )
        videos = await self._guard(
            self._ports.discoverer.discover(platform, decided.handle), "discovery"
        )
        if videos is None:
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="discovery_failed"
            )
        if not videos:
            # An OCR misread names a profile that does not exist; a near variant the
            # evidence also holds (another frame, the vision reading) may be the real one.
            for variant in credit.near_variants(decided.handle, options):
                found = await self._guard(
                    self._ports.discoverer.discover(platform, variant), "discovery"
                )
                if found:
                    evidence.append(
                        AttributionEvidence(
                            kind="decision", detail=f"credit corrected to @{variant}"
                        )
                    )
                    videos = found
                    break
        counts["discovered"] = len(videos)
        repost_duration = next(
            (m.duration_seconds for m in report.media if m.kind == "video" and m.duration_seconds),
            None,
        )
        kept, dropped = shortlist(
            videos,
            repost_owner=owner,
            curated=self._curated,
            repost_time=parse_time(report.post.published_at),
            repost_duration=repost_duration,
        )
        counts.update(dropped)
        if not kept:
            return self._finish(
                workflow_id,
                report,
                "unresolved",
                evidence,
                reason="no_plausible_candidate",
                counts=counts,
            )

        finalists = [
            _Finalist(video, f"{workflow_id}-c{index}")
            for index, video in enumerate(kept[: self._tuning.max_finalists], start=1)
        ]
        winner = await self._evaluate(finalists, self._hashes(frames))
        for finalist in finalists:
            counts[_outcome(finalist)] += 1
            if finalist is not winner and finalist.acquired is not None:
                await self._guard(self._ports.acquirer.discard(finalist.candidate_id), "discard")
        if winner is None or winner.acquired is None:
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="no_match", counts=counts
            )

        acquired = winner.acquired
        evidence.append(
            AttributionEvidence(
                kind="visual_match",
                detail=f"match_share={winner.share:.2f}"
                if winner.share is not None
                else "match_unmeasured",
                confidence=winner.share,
            )
        )
        source = AttributedPost(
            platform=acquired.report.source.platform,
            canonical_url=acquired.report.source.canonical_url,
            owner_handle=acquired.report.post.owner_handle,
        )
        attribution = self._attribution(
            workflow_id,
            report,
            "replaced",
            evidence,
            source=source,
            confidence="high" if winner.share is not None else "low",
            counts=counts,
        )
        return AttributionOutcome(attribution, original=acquired)

    async def _credit(
        self,
        report: SourceReport,
        options: list[str],
        lines: list[str],
        cover: CoverReading | None,
        evidence: list[AttributionEvidence],
    ) -> _Credit:
        owner_key = credit.normalize(report.post.owner_handle)
        rule = credit.text_rule_credit(report.post.text)
        if rule is not None and credit.normalize(rule[0]) != owner_key:
            handle, platform = rule
            evidence.append(
                AttributionEvidence(kind="text_rule", detail=f"@{handle} on {platform}")
            )
            return _Credit(handle, platform, 1.0, by_model=False)
        if self._ports.decisions is not None:
            state: dict[str, object] = {
                "caption": report.post.text[:2000],
                "frame_text": " | ".join(lines)[:2000],
                "headline": cover.headline if cover else "",
                "scene": cover.scene if cover else "",
                "platform_icon": cover.icon if cover else "",
                "reposting_account": report.post.owner_handle,
                "reposting_platform": report.source.platform,
                "handles_found": list(options),
            }
            decided = await self._guard(self._ports.decisions.decide(state, options), "decision")
            if decided is not None:
                evidence.append(
                    AttributionEvidence(
                        kind="decision",
                        detail=f"repost probability {decided.is_repost:.2f}",
                        confidence=decided.is_repost,
                    )
                )
                handle = (
                    decided.handle
                    if decided.handle_probability >= self._tuning.handle_threshold
                    else None
                )
                if handle is not None:
                    evidence.append(
                        AttributionEvidence(
                            kind="decision",
                            detail=f"credit @{handle}",
                            confidence=decided.handle_probability,
                        )
                    )
                return _Credit(handle, decided.platform, decided.is_repost, by_model=True)
        if len(options) == 1:
            return _Credit(options[0], None, 1.0, by_model=False)
        return _Credit(
            None, None, 1.0 if options else 0.0, by_model=False, ambiguous=len(options) > 1
        )

    async def _evaluate(
        self, finalists: list[_Finalist], repost_hashes: list[FrameHash]
    ) -> _Finalist | None:
        step = max(1, self._tuning.finalist_concurrency)
        for start in range(0, len(finalists), step):
            batch = finalists[start : start + step]
            await asyncio.gather(*(self._check(finalist, repost_hashes) for finalist in batch))
            if any(f.rejected is None and f.share is not None for f in batch):
                break
        accepted = [f for f in finalists if f.checked and f.rejected is None]
        measured = [f for f in accepted if f.share is not None]
        if measured:
            return max(measured, key=lambda f: f.share or 0.0)
        return accepted[0] if accepted else None

    async def _check(self, finalist: _Finalist, repost_hashes: list[FrameHash]) -> None:
        finalist.checked = True
        acquired = await self._guard(
            self._ports.acquirer.acquire(finalist.candidate_id, str(finalist.video.canonical_url)),
            "acquisition",
        )
        if acquired is None:
            finalist.rejected = "acquisition_failed"
            return
        finalist.acquired = acquired
        frames = await self._frames(acquired.video)
        if repost_hashes:
            share = match_share(repost_hashes, self._hashes(frames), self._tuning.max_distance)
            if share is None:
                finalist.rejected = "no_video"
                return
            finalist.share = share
            if share < self._tuning.match_threshold:
                finalist.rejected = "no_match"
                return
        if self._ports.vision is not None and frames:
            kind = await self._guard(self._ports.vision.classify(frames[:3]), "vision")
            if kind == "commentary":
                finalist.rejected = "commentary"
                return
        readings: list[Sequence[TextBox]] = []
        for frame in frames[: self._tuning.reaction_frames]:
            readings.append(await self._read(frame))
        if looks_like_burned_in_speech(readings):
            finalist.rejected = "reaction"

    async def _frames(self, video: Path | None) -> list[Frame]:
        if video is None:
            return []
        frames = await self._guard(
            self._ports.frames.frames(video, fps=self._tuning.hash_fps), "frames"
        )
        return frames or []

    async def _read(self, frame: Frame) -> list[TextBox]:
        return await self._guard(self._ports.text.read(frame), "ocr") or []

    async def _cover(self, frames: list[Frame]) -> CoverReading | None:
        if self._ports.vision is None or not frames:
            return None
        return await self._guard(self._ports.vision.read_cover(frames[:3]), "vision")

    def _hashes(self, frames: list[Frame]) -> list[FrameHash]:
        hashes: list[FrameHash] = []
        for frame in frames:
            try:
                value = self._ports.hasher.hash(frame)
            except Exception:
                logger.warning("source attribution hash unavailable for one frame")
                continue
            if value is not None:
                hashes.append(FrameHash(frame.second, value))
        return hashes

    async def _guard(self, awaitable: Awaitable[T], what: str) -> T | None:
        try:
            return await awaitable
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("source attribution %s unavailable; continuing without it", what)
            return None

    def _attribution(
        self,
        workflow_id: str,
        report: SourceReport,
        verdict: Verdict,
        evidence: list[AttributionEvidence],
        *,
        source: AttributedPost | None = None,
        confidence: Literal["high", "low"] = "low",
        reason: str | None = None,
        counts: Counter[str] | None = None,
    ) -> SourceAttribution:
        return SourceAttribution(
            workflow_id=workflow_id,
            input=AttributedPost(
                platform=report.source.platform,
                canonical_url=report.source.canonical_url,
                owner_handle=report.post.owner_handle,
            ),
            verdict=verdict,
            source=source,
            confidence=confidence,
            reason=reason,
            evidence=evidence[:MAX_EVIDENCE],
            candidates=dict(counts or {}),
        )

    def _finish(
        self,
        workflow_id: str,
        report: SourceReport,
        verdict: Verdict,
        evidence: list[AttributionEvidence],
        **fields: object,
    ) -> AttributionOutcome:
        return AttributionOutcome(
            self._attribution(workflow_id, report, verdict, evidence, **fields)  # type: ignore[arg-type]
        )


def _outcome(finalist: _Finalist) -> str:
    if not finalist.checked:
        return "not_evaluated"
    if finalist.rejected is not None:
        return finalist.rejected
    return "matched" if finalist.share is not None else "unmeasured"


def _text_evidence(
    caption_handles: list[str],
    found_in_frames: list[str],
    owner: str,
    cover: CoverReading | None,
) -> list[AttributionEvidence]:
    owner_key = credit.normalize(owner)
    evidence = [
        AttributionEvidence(kind="caption", detail=f"@{handle}")
        for handle in caption_handles
        if credit.normalize(handle) != owner_key
    ]
    evidence += [
        AttributionEvidence(kind="frame_text", detail=f"@{handle}")
        for handle in found_in_frames
        if credit.normalize(handle) != owner_key
    ]
    if cover is not None:
        for label, text in (("headline", cover.headline), ("icon", cover.icon)):
            if text.strip():
                evidence.append(
                    AttributionEvidence(
                        kind="cover_vision", detail=f"{label}: {text.strip()}"[:300]
                    )
                )
    return evidence
