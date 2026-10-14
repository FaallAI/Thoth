"""Footage for one workflow: queries, search, gates, clip checks, quota (spec 2026-10-14).

Cheap before expensive: text gates and the story gate touch no media; a candidate that passes
them is downloaded as a short window, then checked by OCR, vision, and a duplicate hash. Every
decision is stored as it is made, so a retry resumes instead of starting over.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.assembly.ocr import analyze_main_ocr
from thoth_control_plane.assembly.ports import (
    AssemblyError,
    CaptionJudge,
    DurationProbe,
    FrameSampler,
    RegionTracker,
    TextReader,
)
from thoth_control_plane.attribution.adapters.frames import DurationError, FrameError, ToolMissing
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.attribution.ports import AttributionError
from thoth_control_plane.footage.adapters.embedder import cosine
from thoth_control_plane.footage.frames import clip_window, dhash, is_duplicate, vision_seconds
from thoth_control_plane.footage.gates import MainIdentity, text_gate
from thoth_control_plane.footage.models import (
    AdmittedClip,
    CandidateView,
    FootageObject,
    FootageResult,
    FootageStatus,
    NewCandidate,
    SearchBatch,
)
from thoth_control_plane.footage.ports import (
    ClipDownloader,
    Embedder,
    FootageJudge,
    FootageState,
    QueryModel,
    SearchPort,
)
from thoth_control_plane.footage.queries import footage_objects, query_prompt, top_comments

logger = logging.getLogger(__name__)

MAX_FOOTAGE = 6
PER_QUERY = 2
RESULTS_PER_QUERY = 8
SEARCH_PLATFORMS = ("tiktok", "youtube", "x")
CAROUSEL = "carousel"
VISION_WIDTH = 360
MEDIA_FAILURES = frozenset(
    {"incomplete_frame_coverage", "duration_probe_failed", "main_media_missing"}
)
HEADLINE_PREFIX = "headline: "
DEFAULT_VISUAL = "the scene the post is about"


@dataclass(frozen=True)
class FootagePorts:
    queries: QueryModel
    search: SearchPort
    embedder: Embedder
    downloader: ClipDownloader
    frames: FrameSampler
    probe: DurationProbe
    text: TextReader
    judge: FootageJudge
    store: FootageState
    tracker: RegionTracker | None = None
    captions: CaptionJudge | None = None


@dataclass(frozen=True)
class FootageInputs:
    workflow_id: str
    report: SourceReport
    attribution: SourceAttribution | None
    original: SourceReport | None
    artifact_root: Path


def _main(inputs: FootageInputs) -> SourceReport:
    """The main assembly uses (5a A2): the original when attribution replaced the post."""
    verdict = inputs.attribution.verdict if inputs.attribution is not None else "none"
    if verdict == "replaced" and inputs.original is not None:
        return inputs.original
    return inputs.report


def _headline(attribution: SourceAttribution | None) -> str:
    for item in attribution.evidence if attribution is not None else []:
        if item.kind == "cover_vision" and item.detail.startswith(HEADLINE_PREFIX):
            return item.detail[len(HEADLINE_PREFIX) :]
    return ""


def _storable(obj: FootageObject) -> bool:
    """PostgreSQL text and jsonb refuse NUL, and the search contract refuses any control
    character; such an object is dropped before the run stores it."""
    return not any(unicodedata.category(char) == "Cc" for char in obj.query + obj.visual)


def _carousel(main: SourceReport) -> dict[str, PurePosixPath]:
    """Spec F2: an Instagram /p/ post with at least two videos; the first video is the main."""
    url = str(main.source.canonical_url)
    videos = [media for media in main.media if media.kind == "video"]
    if main.source.platform != "instagram" or "/p/" not in url or len(videos) < 2:
        return {}
    return {f"{url}#slide{media.index}": media.location for media in videos[1 : MAX_FOOTAGE + 1]}


def select_batch(
    queues: dict[str, list[CandidateView]],
    admitted: Counter[str],
    total: int,
    size: int,
    per_query: int = PER_QUERY,
) -> list[CandidateView]:
    """Up to `size` candidates in rounds across queries, within the per-query and total caps."""
    batch: list[CandidateView] = []
    taken: Counter[str] = Counter()
    progress = True
    while progress and len(batch) < size and total + len(batch) < MAX_FOOTAGE:
        progress = False
        for query, queue in queues.items():
            if len(batch) >= size or total + len(batch) >= MAX_FOOTAGE:
                break
            if queue and admitted[query] + taken[query] < per_query:
                batch.append(queue.pop(0))
                taken[query] += 1
                progress = True
    return batch


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()


class FootageBuilder:
    def __init__(
        self,
        ports: FootagePorts,
        *,
        aggregators: frozenset[str],
        story_min: float,
        max_frames: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        deadline_seconds: float = 720.0,
        per_candidate_seconds: float = 90.0,
        concurrency: int = 3,
    ) -> None:
        self._ports = ports
        self._store = ports.store
        self._aggregators = aggregators
        self._story_min = story_min
        self._max_frames = max_frames
        self._clock = clock
        self._deadline = deadline_seconds
        self._per_candidate = per_candidate_seconds
        self._concurrency = concurrency
        self._position = 0

    async def build(self, inputs: FootageInputs) -> FootageResult:
        started = time.monotonic()
        workflow = inputs.workflow_id
        main = _main(inputs)
        run = await asyncio.to_thread(self._store.run, workflow)
        if run is not None and run.status == "done":
            return await self._result(workflow, run.footage_status or "unavailable")
        self._clean_parts(inputs.artifact_root, workflow)

        slides = _carousel(main)
        if slides:
            await asyncio.to_thread(self._store.start_run, workflow, [])
            await asyncio.to_thread(
                self._store.add_candidates,
                workflow,
                [
                    NewCandidate(
                        url=url,
                        platform="instagram",
                        source="carousel",
                        query=CAROUSEL,
                        visual="",
                        owner_handle=main.post.owner_handle,
                        caption=main.post.text[:2000],
                    )
                    for url in slides
                ],
            )
            return await self._check_all(inputs, main, started, [CAROUSEL], slides)

        if run is None:
            found = await self._objects(main, inputs.attribution)
            if found is None:
                await asyncio.to_thread(self._store.start_run, workflow, [])
                await asyncio.to_thread(self._store.finish_run, workflow, "unavailable")
                return FootageResult(status="unavailable")
            run = await asyncio.to_thread(self._store.start_run, workflow, found)
        objects = run.objects
        if not objects:
            await asyncio.to_thread(self._store.finish_run, workflow, "none")
            return FootageResult(status="none")

        hits, failed = await self._search(objects)
        if failed:
            await asyncio.to_thread(self._store.finish_run, workflow, "unavailable")
            return await self._result(workflow, "unavailable")
        identity = MainIdentity.of(
            str(main.source.canonical_url),
            [str(inputs.report.source.canonical_url)],
            main.post.text,
        )
        await self._gate(workflow, identity, objects, hits)
        await self._story(workflow, main)
        return await self._check_all(inputs, main, started, [obj.query for obj in objects], {})

    async def _objects(
        self, main: SourceReport, attribution: SourceAttribution | None
    ) -> list[FootageObject] | None:
        comments = top_comments((comment.text, comment.likes) for comment in main.comments)
        prompt = query_prompt(main.post.text, _headline(attribution), comments)
        if prompt is None:
            return []
        for _ in range(2):  # spec F3: one retry
            answer = await self._ports.queries.read(prompt)
            if answer is not None:
                return [obj for obj in footage_objects(answer) if _storable(obj)]
        return None

    async def _search(
        self, objects: Sequence[FootageObject]
    ) -> tuple[dict[str, list[tuple[str, DiscoveredVideo]]], bool]:
        async def platform(name: str) -> dict[str, list[DiscoveredVideo]] | None:
            found: dict[str, list[DiscoveredVideo]] = {}
            missing: list[str] = []
            for obj in objects:
                cached = await asyncio.to_thread(self._store.cached_search, name, obj.query)
                if cached is None:
                    missing.append(obj.query)
                else:
                    found[obj.query] = list(cached)
            if not missing:
                return found
            # One call per platform: X serves every query from one lease (option A).
            try:
                batch = await self._ports.search.search(name, missing, RESULTS_PER_QUERY)
            except ToolMissing:
                raise
            except Exception:
                logger.warning("footage search failed platform=%s", name)
                batch = SearchBatch(found={}, failed=True)
            for query, videos in batch.found.items():
                await asyncio.to_thread(self._store.save_search, name, query, videos)
                found[query] = list(videos)
            if batch.failed and not found:
                return None
            if batch.failed:
                logger.warning("footage search partial platform=%s", name)
            return found

        results = await asyncio.gather(*(platform(name) for name in SEARCH_PLATFORMS))
        merged: dict[str, list[tuple[str, DiscoveredVideo]]] = {obj.query: [] for obj in objects}
        for name, result in zip(SEARCH_PLATFORMS, results, strict=True):
            for query, videos in (result or {}).items():
                merged[query].extend((name, video) for video in videos)
        logger.info(
            "footage search done platforms_failed=%d hits=%d",
            sum(1 for result in results if result is None),
            sum(len(items) for items in merged.values()),
        )
        return merged, all(result is None for result in results)

    async def _gate(
        self,
        workflow: str,
        identity: MainIdentity,
        objects: Sequence[FootageObject],
        hits: dict[str, list[tuple[str, DiscoveredVideo]]],
    ) -> None:
        known = {c.url for c in await asyncio.to_thread(self._store.candidates, workflow)}
        new: list[NewCandidate] = []
        for obj in objects:
            for platform, video in hits.get(obj.query, []):
                url = str(video.canonical_url)
                if url in known:  # the same post from another platform or query
                    continue
                known.add(url)
                reason = text_gate(url, video, identity, self._aggregators)
                new.append(
                    NewCandidate(
                        url=url,
                        platform=platform,
                        source="search",
                        query=obj.query,
                        visual=obj.visual,
                        owner_handle=video.owner_handle,
                        caption=video.caption[:2000],
                        published_at=video.published_at,
                        engagement=dict(video.engagement),
                        source_duration=video.duration_seconds,
                        status="rejected" if reason else "pending",
                        reason=reason,
                    )
                )
        await asyncio.to_thread(self._store.add_candidates, workflow, new)

    async def _story(self, workflow: str, main: SourceReport) -> None:
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        unscored = [c for c in candidates if c.status == "pending" and c.story_score is None]
        if not unscored:
            return
        text = main.post.text
        story = f"{text[:120]}. {text}".strip()
        vectors = await self._ports.embedder.embed([story, *(c.caption for c in unscored)])
        for candidate, vector in zip(unscored, vectors[1:], strict=True):
            score = 0.0
            if candidate.caption.strip():
                score = max(0.0, min(1.0, cosine(vectors[0], vector)))
            if score < self._story_min:
                await asyncio.to_thread(
                    self._store.reject, workflow, candidate.url, "story", story_score=score
                )
            else:
                await asyncio.to_thread(self._store.score, workflow, candidate.url, score)

    async def _check_all(
        self,
        inputs: FootageInputs,
        main: SourceReport,
        started: float,
        queries: list[str],
        carousel: dict[str, PurePosixPath],
    ) -> FootageResult:
        workflow, root = inputs.workflow_id, inputs.artifact_root
        admitted_hashes = await self._verify_admitted(workflow, root)
        main_hashes = await self._main_hashes(main, root)
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        pending = [c for c in candidates if c.status == "pending"]
        admitted = Counter(c.query for c in candidates if c.status == "admitted")
        positions = [c.position for c in candidates if c.position is not None]
        self._position = max(positions, default=-1) + 1
        queues = {
            query: sorted(
                (c for c in pending if c.query == query), key=lambda c: -(c.story_score or 0.0)
            )
            for query in queries
        }
        per_query = MAX_FOOTAGE if carousel else PER_QUERY
        total = sum(admitted.values())
        while total < MAX_FOOTAGE and time.monotonic() - started < self._deadline:
            batch = select_batch(queues, admitted, total, self._concurrency, per_query)
            if not batch:
                break
            outcomes = await asyncio.gather(
                *(
                    self._timed(
                        workflow, root, c, carousel.get(c.url), main_hashes, admitted_hashes
                    )
                    for c in batch
                )
            )
            for candidate, ok in zip(batch, outcomes, strict=True):
                if ok:
                    admitted[candidate.query] += 1
                    total += 1
        status: FootageStatus = "ok" if total else "none"
        await asyncio.to_thread(self._store.finish_run, workflow, status)
        return await self._result(workflow, status)

    async def _timed(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        existing: PurePosixPath | None,
        main_hashes: list[int],
        admitted_hashes: list[list[int]],
    ) -> bool:
        owned = existing is None
        name = hashlib.sha256(candidate.url.encode()).hexdigest()[:20] + ".mp4"
        location = existing or PurePosixPath("reports") / workflow / "footage" / name
        try:
            return await asyncio.wait_for(
                self._check(
                    workflow, root, candidate, location, owned, main_hashes, admitted_hashes
                ),
                self._per_candidate,
            )
        except TimeoutError:
            return await self._reject(workflow, root, candidate, location, owned, "media_failed")

    async def _check(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        location: PurePosixPath,
        owned: bool,
        main_hashes: list[int],
        admitted_hashes: list[list[int]],
    ) -> bool:
        path = root / location
        window = clip_window(candidate.source_duration) if owned else None
        if owned:
            try:
                await self._ports.downloader.download(candidate.url, window, path)
            except ToolMissing:
                raise
            except Exception:
                return await self._reject(
                    workflow, root, candidate, location, owned, "media_failed"
                )
        try:
            ocr = await analyze_main_ocr(
                path,
                None,
                frames=self._ports.frames,
                probe=self._ports.probe,
                text=self._ports.text,
                max_frames=self._max_frames,
                now=self._clock(),
                trim_allowed=True,
                tracker=self._ports.tracker,
                judge=self._ports.captions,
            )
            if ocr.outcome == "subtitle":
                return await self._reject(workflow, root, candidate, location, owned, "subtitle")
            duration = await self._ports.probe.duration(path)
            frames = [
                await self._ports.frames.frame_at(path, second, width=VISION_WIDTH)
                for second in vision_seconds(ocr.trim_start, duration)
            ]
        except AssemblyError as error:
            if error.code in MEDIA_FAILURES:
                return await self._reject(
                    workflow, root, candidate, location, owned, "media_failed"
                )
            raise  # a missing tool is an explicit error
        except (FrameError, DurationError):
            return await self._reject(workflow, root, candidate, location, owned, "media_failed")
        try:
            answer = await self._ports.judge.judge(frames, candidate.visual or DEFAULT_VISUAL)
        except AttributionError:
            return await self._reject(
                workflow, root, candidate, location, owned, "vision_unavailable"
            )
        seen = {
            "kind": answer.kind,
            "shows_object": answer.shows_object,
            "description": answer.description,
        }
        if answer.kind == "commentary":
            return await self._reject(
                workflow, root, candidate, location, owned, "commentary", **seen
            )
        if answer.shows_object == "no":
            return await self._reject(
                workflow, root, candidate, location, owned, "object_absent", **seen
            )
        hashes = [dhash(frame.jpeg) for frame in frames]
        if is_duplicate(hashes, [main_hashes, *admitted_hashes]):
            return await self._reject(
                workflow, root, candidate, location, owned, "duplicate", **seen
            )
        admitted_hashes.append(hashes)
        position, self._position = self._position, self._position + 1
        clip = AdmittedClip(
            kind=answer.kind,
            shows_object=answer.shows_object,
            description=answer.description,
            media_location=location.as_posix(),
            media_checksum=_sha256(path),
            media_bytes=path.stat().st_size,
            clip_duration=duration,
            clip_start=window[0] if window else 0.0,
            ocr=ocr.model_dump(mode="json"),
            position=position,
        )
        await asyncio.to_thread(self._store.admit, workflow, candidate.url, clip)
        if candidate.source == "carousel":
            await asyncio.to_thread(self._store.score, workflow, candidate.url, 1.0)
        return True

    async def _reject(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        location: PurePosixPath,
        owned: bool,
        reason: str,
        **seen: str,
    ) -> bool:
        if owned:  # a carousel slide is the acquisition's file, never deleted here
            (root / location).unlink(missing_ok=True)
        await asyncio.to_thread(self._store.reject, workflow, candidate.url, reason, **seen)
        return False

    async def _verify_admitted(self, workflow: str, root: Path) -> list[list[int]]:
        hashes: list[list[int]] = []
        for candidate in await asyncio.to_thread(self._store.admitted, workflow):
            path = root / (candidate.media_location or "")
            if not path.is_file() or _sha256(path) != candidate.media_checksum:
                await asyncio.to_thread(self._store.reopen, workflow, candidate.url)
                continue
            hashes.append(await self._hashes(path, candidate.clip_duration or 0.0))
        return hashes

    async def _main_hashes(self, main: SourceReport, root: Path) -> list[int]:
        videos = [media for media in main.media if media.kind == "video"]
        if not videos:
            return []
        path = root / videos[0].location
        if not path.is_file():
            return []
        try:
            duration = videos[0].duration_seconds or await self._ports.probe.duration(path)
        except DurationError:
            return []
        return await self._hashes(path, duration)

    async def _hashes(self, path: Path, duration: float) -> list[int]:
        try:
            frames = [
                await self._ports.frames.frame_at(path, second, width=VISION_WIDTH)
                for second in vision_seconds(0.0, duration)
            ]
        except FrameError:
            return []
        return [dhash(frame.jpeg) for frame in frames]

    async def _result(self, workflow: str, status: str) -> FootageResult:
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        reasons = Counter(c.reason for c in candidates if c.reason)
        admitted = sum(1 for c in candidates if c.status == "admitted")
        logger.info(
            "footage finished status=%s admitted=%d rejected=%s", status, admitted, dict(reasons)
        )
        return FootageResult(status=status, admitted=admitted, rejected=dict(reasons))  # type: ignore[arg-type]

    @staticmethod
    def _clean_parts(root: Path, workflow: str) -> None:
        for part in (root / "reports" / workflow / "footage").glob("*.part"):
            part.unlink(missing_ok=True)
