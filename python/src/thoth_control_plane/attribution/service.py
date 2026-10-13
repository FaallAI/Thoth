"""S1 to S6 of source attribution: is this post the original, and if not, which post is?

`SourceAttributor.identify` reads evidence from the repost, decides the credit, discovers the
credited account's videos, filters them by free metadata, matches frames, and acquires at most a
few finalists, stopping at the first measured match. A failure about external content degrades
one piece of evidence or one candidate; a required tool, model, or provider that cannot work
raises `AttributionError` (operator, 2026-10-13).
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
from thoth_control_plane.attribution.adapters.frames import ToolMissing
from thoth_control_plane.attribution.candidates import parse_time, shortlist
from thoth_control_plane.attribution.matching import (
    TextBox,
    looks_like_burned_in_speech,
    summarize_matches,
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
    AttributionError,
    CandidateAcquirer,
    CoverReading,
    DecisionModel,
    Diarizer,
    Discoverer,
    Frame,
    FrameSource,
    SceneDetector,
    TextReader,
    Transcriber,
    VisionReader,
    VisualMatcher,
)
from thoth_control_plane.attribution.reaction import engagement_ratio, judge, split_speech
from thoth_control_plane.attribution.scenes import Shot, label, shots, vision_frames

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class Tuning:
    """Calibrated on the live golden captures of 2026-10-10 and 2026-10-11."""

    frame_fps: float = 1.0
    # A candidate is sampled up to here: a long upload would cost minutes of ffmpeg and ORB.
    candidate_seconds: float = 600.0
    credit_seconds: float = 3.0
    reaction_frames: int = 10
    # A repost frame holds a candidate frame at this many RANSAC inliers. Live captures
    # (2026-10-10): true originals 124 to 418, unrelated videos at most 16; 40 also stays
    # above a logo or an end card the account stamps on every video.
    min_inliers: int = 40
    # At 3000 ORB features a text label can line up with another label in one frame
    # (2026-10-11: 45 inliers, unrelated pair); every true original held at least 5 frames.
    min_matched_frames: int = 2
    repost_threshold: float = 0.5
    handle_threshold: float = 0.5
    max_finalists: int = 3
    finalist_concurrency: int = 2
    # Reactions (spec 2026-10-13): only the first minutes are transcribed; the thresholds are
    # calibrated on the reaction goldens.
    transcript_seconds: float = 180.0
    reaction_contribution: float = 0.5
    reaction_discussion: float = 0.5
    reaction_engagement: float = 1.0


DEFAULT_TUNING = Tuning()


@dataclass(frozen=True)
class AttributionPorts:
    frames: FrameSource
    matcher: VisualMatcher
    text: TextReader
    discoverer: Discoverer
    acquirer: CandidateAcquirer
    vision: VisionReader
    decisions: DecisionModel
    scenes: SceneDetector
    transcriber: Transcriber
    diarizer: Diarizer


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


@dataclass
class _Finalist:
    video: DiscoveredVideo
    candidate_id: str
    checked: bool = False
    acquired: AcquiredCandidate | None = None
    matched_frames: int = 0
    inliers: int | None = None
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
        if video is not None and not frames:
            # The video exists but sampling failed: no evidence, so no verdict on the source.
            return self._finish(workflow_id, report, "unresolved", [], reason="frames_failed")
        lines: list[str] = []
        for frame in frames:
            if frame.second < self._tuning.credit_seconds:
                lines += [box.text for box in await self._read(frame)]
        cover, labelled = await self._cover(frames, video)
        owner = report.post.owner_handle
        caption_handles = credit.text_handles(report.post.text)
        found_in_frames = credit.frame_handles(lines)
        read_by_vision = credit.vision_handles(cover.handles) if cover is not None else []
        options = credit.credit_options(caption_handles, [*found_in_frames, *read_by_vision], owner)
        evidence = _text_evidence(caption_handles, found_in_frames, read_by_vision, owner, cover)
        if (
            cover is not None
            and video is not None
            and cover.reaction_shape != "none"
            and await self._reaction(report, video, cover, labelled, lines, evidence)
        ):
            return self._finish(workflow_id, report, "original", evidence, confidence="high")
        decided = await self._credit(report, options, lines, cover, evidence)

        if decided.handle is None:
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
        kept, dropped = shortlist(
            videos,
            repost_owner=owner,
            curated=self._curated,
            repost_time=parse_time(report.post.published_at),
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
        winner: _Finalist | None = None
        try:
            winner = await self._evaluate(finalists, await self._prepare(frames))
        finally:
            # Also on cancellation: an acquired finalist is a directory of media on disk.
            for finalist in finalists:
                if finalist is not winner and finalist.acquired is not None:
                    await self._guard(
                        self._ports.acquirer.discard(finalist.candidate_id), "discard"
                    )
        for finalist in finalists:
            counts[_outcome(finalist)] += 1
        if winner is None or winner.acquired is None:
            return self._finish(
                workflow_id, report, "unresolved", evidence, reason="no_match", counts=counts
            )

        acquired = winner.acquired
        evidence.append(
            AttributionEvidence(
                kind="visual_match",
                detail=(
                    f"{winner.matched_frames} repost frames hold it, up to {winner.inliers} inliers"
                )
                if winner.inliers is not None
                else "match_unmeasured",
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
            confidence="high" if winner.inliers is not None else "low",
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
        decided = await self._ports.decisions.decide(state, options)
        evidence.append(
            AttributionEvidence(
                kind="decision",
                detail=f"repost probability {decided.is_repost:.2f}",
                confidence=decided.is_repost,
            )
        )
        handle = (
            decided.handle if decided.handle_probability >= self._tuning.handle_threshold else None
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

    async def _reaction(
        self,
        report: SourceReport,
        video: Path,
        cover: CoverReading,
        labelled: list[Shot],
        lines: list[str],
        evidence: list[AttributionEvidence],
    ) -> bool:
        """Spec 2026-10-13: is this reaction an original? Unmeasured parts keep it a repost."""
        shape = cover.reaction_shape
        if cover.subject_media in ("text", "image"):
            evidence.append(
                AttributionEvidence(
                    kind="reaction", detail=f"{shape} reaction to a {cover.subject_media} post"
                )
            )
            return True
        seconds = self._tuning.transcript_seconds
        transcript = await self._ports.transcriber.transcribe(video, seconds=seconds)
        turns = await self._ports.diarizer.turns(video, seconds=seconds)
        speech = split_speech(transcript, turns, labelled)
        comments = [comment.text for comment in report.comments][:12]
        assessment = await self._ports.decisions.assess(
            {
                "caption": report.post.text[:2000],
                "frame_text": " | ".join(lines)[:2000],
                "headline": cover.headline,
                "scene": cover.scene,
                "reaction_shape": shape,
                "creator_speech": speech.creator[:6000],
                "subject_speech": speech.subject[:6000],
                "comments": comments,
            },
            with_comments=bool(comments),
        )
        platform = report.source.platform
        videos = (
            await self._guard(
                self._ports.discoverer.discover(platform, report.post.owner_handle), "baseline"
            )
            if self._ports.discoverer.supports(platform)
            else None
        )
        ratio = engagement_ratio(report.post.post_id, report.post.engagement, videos or [])
        call = judge(
            assessment,
            ratio,
            contribution=self._tuning.reaction_contribution,
            discussion=self._tuning.reaction_discussion,
            engagement=self._tuning.reaction_engagement,
        )
        discussion = "-" if assessment.discussion is None else f"{assessment.discussion:.2f}"
        engagement = "-" if ratio is None else f"{ratio:.1f}x"
        evidence.append(
            AttributionEvidence(
                kind="reaction",
                detail=(
                    f"{shape}, {cover.subject_media} subject, contribution "
                    f"{assessment.contribution:.2f}, discussion {discussion}, engagement "
                    f"{engagement}: {call.reason}"
                )[:300],
                confidence=assessment.contribution,
            )
        )
        return call.original

    async def _evaluate(self, finalists: list[_Finalist], repost: object) -> _Finalist | None:
        step = max(1, self._tuning.finalist_concurrency)
        for start in range(0, len(finalists), step):
            batch = finalists[start : start + step]
            await asyncio.gather(*(self._check(finalist, repost) for finalist in batch))
            if any(f.rejected is None and f.inliers is not None for f in batch):
                break
        accepted = [f for f in finalists if f.checked and f.rejected is None]
        measured = [f for f in accepted if f.inliers is not None]
        if measured:
            return max(measured, key=lambda f: f.inliers or 0)
        return accepted[0] if accepted else None

    async def _check(self, finalist: _Finalist, repost: object) -> None:
        finalist.checked = True
        acquired = await self._guard(
            self._ports.acquirer.acquire(finalist.candidate_id, str(finalist.video.canonical_url)),
            "acquisition",
        )
        if acquired is None:
            finalist.rejected = "acquisition_failed"
            return
        finalist.acquired = acquired
        frames = await self._frames(acquired.video, self._tuning.candidate_seconds)
        if acquired.video is not None and not frames:
            finalist.rejected = "frames_failed"
            return
        if repost:
            candidate = await self._prepare(frames)
            scores = (
                await self._guard(self._ports.matcher.compare(repost, candidate), "match")
                if candidate
                else None
            )
            summary = summarize_matches(scores or [], min_inliers=self._tuning.min_inliers)
            if summary is None:
                finalist.rejected = "no_video"
                return
            finalist.matched_frames, finalist.inliers = summary
            if finalist.matched_frames < self._tuning.min_matched_frames:
                finalist.rejected = "no_match"
            # Matched footage is the source whatever its genre: vision calls talking-head
            # originals "commentary", so the genre checks below run only when unmeasured.
            return
        if frames:
            kind = await self._ports.vision.classify(frames[:3])
            if kind == "commentary":
                finalist.rejected = "commentary"
                return
        readings: list[Sequence[TextBox]] = []
        for frame in frames[: self._tuning.reaction_frames]:
            readings.append(await self._read(frame))
        if looks_like_burned_in_speech(readings):
            finalist.rejected = "reaction"

    async def _frames(self, video: Path | None, seconds: float | None = None) -> list[Frame]:
        if video is None:
            return []
        frames = await self._guard(
            self._ports.frames.frames(video, fps=self._tuning.frame_fps, seconds=seconds), "frames"
        )
        return frames or []

    async def _read(self, frame: Frame) -> list[TextBox]:
        return await self._guard(self._ports.text.read(frame), "ocr") or []

    async def _cover(
        self, frames: list[Frame], video: Path | None
    ) -> tuple[CoverReading | None, list[Shot]]:
        """The cover reading from the cover and the longest shots, and each shot's label."""
        if not frames or video is None:
            return None, []
        end = frames[-1].second + 1.0 / self._tuning.frame_fps
        cut = shots(await self._guard_tool(self._ports.scenes.cuts(video)), end)
        sent = vision_frames(frames, cut)
        cover = await self._ports.vision.read_cover(sent)
        return cover, label(cut, sent, cover.shows)

    async def _guard_tool(self, awaitable: Awaitable[T]) -> T:
        """A required local tool: a missing binary is its own code, never a degraded verdict."""
        try:
            return await awaitable
        except ToolMissing as missing:
            raise AttributionError(missing.code) from missing

    async def _prepare(self, frames: list[Frame]) -> object:
        """Matcher features for a video's frames; falsy when nothing can be matched."""
        if not frames:
            return None
        return await self._guard(self._ports.matcher.prepare(frames), "match")

    async def _guard(self, awaitable: Awaitable[T], what: str) -> T | None:
        try:
            return await awaitable
        except (asyncio.CancelledError, AttributionError):
            raise
        except ToolMissing as missing:
            raise AttributionError(missing.code) from missing
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
    return "matched" if finalist.inliers is not None else "unmeasured"


def _text_evidence(
    caption_handles: list[str],
    found_in_frames: list[str],
    read_by_vision: list[str],
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
    evidence += [
        AttributionEvidence(kind="cover_vision", detail=f"handle: @{handle}")
        for handle in read_by_vision
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
