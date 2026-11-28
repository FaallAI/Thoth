"""Footage for one workflow: queries, search, gates, clip checks, quota (spec 2026-10-14).

Cheap before expensive: text gates and the story gate touch no media; a candidate that passes
them is downloaded as a short window, then checked by OCR, vision, and a duplicate hash. Every
decision is stored as it is made, so a retry resumes instead of starting over.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import shutil
import time
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar

from thoth_control_plane import progress
from thoth_control_plane.acquisition.cards import CardRejected, write_card
from thoth_control_plane.acquisition.models import (
    DiscoveredPhoto,
    DiscoveredVideo,
    SourceReport,
)
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
from thoth_control_plane.attribution.credit import normalize
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.attribution.ports import AttributionError, Frame
from thoth_control_plane.footage.adapters.downloader import ClipError
from thoth_control_plane.footage.adapters.embedder import cosine
from thoth_control_plane.footage.adapters.photos import PhotoError
from thoth_control_plane.footage.adapters.vision import FootageAnswer
from thoth_control_plane.footage.context import (
    CARD_PROMPT,
    PERSON_VISUAL,
    PERSON_WINDOW,
    REFINE_PROMPT,
    WINDOW_BEFORE,
    CardModel,
    ContextCard,
    card_material,
    card_names,
    card_objects,
    context_objects,
    context_reason,
    discussed_names,
    event_terms,
    has_event_term,
    in_window,
    names_discussed_with_context,
    names_subject,
    related_terms,
    same_event,
    subject_names,
)
from thoth_control_plane.footage.creator import (
    CREATOR_LISTING,
    MAX_PHOTOS,
    closest,
    creator_query,
    enriched_text,
    verdict,
)
from thoth_control_plane.footage.frames import clip_window, dhash, is_duplicate, vision_seconds
from thoth_control_plane.footage.gates import (
    MAX_SECONDS,
    MainIdentity,
    mentions,
    norm,
    same_as_main,
    text_gate,
)
from thoth_control_plane.footage.models import (
    AdmittedClip,
    CandidateView,
    FootageObject,
    FootageResult,
    FootageStatus,
    LibraryClip,
    NewCandidate,
    RejectReason,
    RunView,
    SearchBatch,
)
from thoth_control_plane.footage.moments import (
    SECTION_SECONDS,
    CaptionPort,
    Discussion,
    LongVideoHints,
    parse_json3,
    pick_discussions,
    section,
)
from thoth_control_plane.footage.ports import (
    ClipDownloader,
    CreatorPort,
    Embedder,
    FootageJudge,
    FootageState,
    PhotoFetcher,
    QueryModel,
    SearchPort,
)
from thoth_control_plane.footage.queries import footage_objects, query_prompt, top_comments
from thoth_control_plane.footage.recording import (
    CopyFacts,
    clean_original,
    is_copy,
    keep_first,
    text_share,
    triggered,
)
from thoth_control_plane.footage.reposts import (
    CreditRef,
    credited_source,
    frame_credited_source,
    is_own_account,
)

logger = logging.getLogger(__name__)

MAX_FOOTAGE = 8  # spec 10.6
MAX_OLD = 2  # clips older than 30 days per run (spec 10.12, revision 5)
MAX_DISCUSSES = 1  # clips that talk about the subject without showing them (10.12)
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
SCRATCH_GLOB = "thoth-footage-*"  # the clip downloader's scratch directories
# Spec 5c-2: profile listings exist for these; photo posts come from all but YouTube. TikTok is
# back (operator, 2026-10-22): its listing page now solves the drag captchas TikTok raises over
# the grid (`acquisition/captcha.py`), so a main lists its creator like the other platforms.
CREATOR_PLATFORMS = frozenset({"tiktok", "instagram", "x", "youtube"})
PHOTO_PLATFORMS = frozenset({"tiktok", "instagram", "x"})
PAGE_CARD = "profile-page.png"
# The context path (footage library spec 2026-11-15): queries per round, titles round two reads.
REFINE_QUERIES = 3
REFINE_TITLES = 15
OWN_SCORE = 1.0  # own accounts are screened first
PASS_SCORE = 0.5
REFINED = "refined"  # set in the stored card once round two ran
# Every long video a run finds gets its captions (live wf_4ac021d9: the podcast was 5th of
# 6 and never cut), a few seconds apart so YouTube does not answer 429.
MAX_LONG_VIDEOS = 6
CAPTION_SPACING = 3.0
CAPTION_LANGUAGE = "id"
SECTION_MARK = "#t="
LIBRARY = "library"  # the query library clips are counted under
# Long-video sections have a quota of their own: under their parent's query, the search clips
# that query found filled it first and the discussion was never screened (live wf_a91d3f0f).
SECTIONS = "sections"
# A YouTube video past 3 minutes is cut at its moments; one past MAX_SECONDS has no plain clip
# (spec 2026-11-27 ocr video credit, 3.5).
LONG_SECTION_SECONDS = 180.0
# Credits burned into rejected subtitled reposts (spec 2026-11-27 ocr video credit, 3.3): a few
# accounts per run, whose originals and sections get a queue and a quota of their own.
MAX_OCR_TRACES = 3
OCR_TRACED = "ocr_trace"
MAX_TRACE_QUERY = 80
MAX_TRACE_LISTINGS = 3  # creator listings are browser work; a run traces few accounts
COPY_SHARES = (0.2, 0.5, 0.8)  # the frames a copy is first tried on, and read for text
ORIGINAL_SOURCES = ("creator", "trace", OCR_TRACED)

T = TypeVar("T")

# Tasks that ignored their cancellation: held so they are not collected mid-flight.
_ABANDONED: set[asyncio.Task[Any]] = set()


def _abandon(task: asyncio.Task[Any]) -> None:
    _ABANDONED.add(task)
    task.add_done_callback(_ABANDONED.discard)
    task.add_done_callback(lambda done: done.cancelled() or done.exception())  # never re-raised


@dataclass
class _Build:
    """One build's check state; a builder may serve several builds at once."""

    positions: Iterator[int] = field(default_factory=itertools.count)
    steps: dict[str, str] = field(default_factory=dict)  # candidate URL -> current step
    closed: set[str] = field(default_factory=set)  # decided elsewhere: the check writes nothing
    phase: str = "search"
    over: bool = False
    # The context path (spec 2026-11-15): the card admits are tagged with, and the library's
    # workspace; None on the object path or for a run without a project.
    card: ContextCard | None = None
    workspace: str | None = None
    # One copy of a recording (spec 2026-11-15, 9.4 and 9.9): the main's 1 fps features, every
    # kept clip's, the queries of clips a cleaner copy displaced, and the lock that makes the
    # copy decision and the admit one step.
    main_recording: list[Any] | None = None
    # Spec 10.5/10.12: one frame of the main the vision call compares a clip with; None without
    # a card, so the object path asks no same-event question.
    reference: Frame | None = None
    main_published: str | None = None
    # Spec 10.6 and 10.12: the one same-event clip kept, and the old clips kept.
    same_event: _Recording | None = None
    old: set[str] = field(default_factory=set)
    # Spec 10.12: the subject's face template (None: no face check), and the clips kept that
    # only discuss the subject.
    subject: Any = None
    discussing: set[str] = field(default_factory=set)
    media_causes: Counter[str] = field(default_factory=Counter)  # spec 10.8
    recordings: dict[str, _Recording] = field(default_factory=dict)
    displaced: list[str] = field(default_factory=list)
    copy_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Spec 2026-11-27 ocr video credit, 3.3 and 3.5: the accounts traced (from captions or
    # frames), the frame credits waiting for the next batch, how many accounts frames traced,
    # and the long videos whose captions were read.
    traced_keys: set[tuple[str, str]] = field(default_factory=set)
    ocr_credits: list[tuple[CandidateView, CreditRef]] = field(default_factory=list)
    ocr_traced_count: int = 0
    sectioned: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _Evidence:
    features: list[Any]
    facts: CopyFacts
    source: str
    copies_main: bool


@dataclass
class _Recording:
    url: str
    source: str  # the address before a section's `#t=`
    query: str  # its quota key (`quota_key`)
    frames: list[Any]  # 1 fps features
    facts: CopyFacts
    hashes: list[int]


async def _together(work: Iterable[Coroutine[Any, Any, T]]) -> list[T]:
    """Run concurrently; the first failure cancels the others and is raised as itself."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(item) for item in work]
    except BaseExceptionGroup as failed:
        raise failed.exceptions[0] from None
    return [task.result() for task in tasks]


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
    creator: CreatorPort | None = None
    photos: PhotoFetcher | None = None
    # Footage library (spec 2026-11-15): the card model, long videos' captions, and a copy of a
    # library clip's stored media into this run.
    card: CardModel | None = None
    captions_text: CaptionPort | None = None
    library_media: Callable[[str, Path], Awaitable[None]] | None = None
    # One copy of a recording (spec 2026-11-15, 9.9): 1 fps frames at 480 px and ORB features;
    # without both, the copy check is skipped.
    recording_frames: Any | None = None
    matcher: Any | None = None
    # The story's subject by face (spec 10.12): `FaceReader`; the check runs only when the
    # workflow sends a subject.
    faces: Any | None = None


@dataclass(frozen=True)
class FootageInputs:
    workflow_id: str
    report: SourceReport
    attribution: SourceAttribution | None
    original: SourceReport | None
    artifact_root: Path
    # Uploads the admitted clips (spec 2026-10-17). It runs before the run is marked done:
    # a failed upload leaves the run open, so the retry reopens the clips it cannot find.
    publish: Callable[[list[str]], Awaitable[None]] | None = None
    # What the context card reads besides the post (spec 2026-11-15, 4.1); empty when unknown.
    figures: list[dict[str, Any]] = field(default_factory=list)
    transcript: str = ""
    # Spec 10.12: the story's subject by face, the template of the main's chosen face group;
    # None with `face_check` off (no faces, the operator chose none of them, or disabled).
    subject: Any = None
    face_check: bool = False


def main_report(inputs: FootageInputs) -> SourceReport:
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
    """Spec F2: an Instagram /p/ post or an X post (spec 2026-10-23 G6) with at least two videos;
    the first video is the main, the others are its footage."""
    url = str(main.source.canonical_url)
    videos = [media for media in main.media if media.kind == "video"]
    platform = main.source.platform
    shaped = platform == "x" or (platform == "instagram" and "/p/" in url)
    if not shaped or len(videos) < 2:
        return {}
    return {f"{url}#slide{media.index}": media.location for media in videos[1 : MAX_FOOTAGE + 1]}


Relation = Literal["related", "same_event", "discusses", "unknown"]


def relation_of(answer: FootageAnswer, asked: bool) -> Relation:
    """How a clip relates to the main's incident (spec 10.3): unknown when no scene was asked."""
    if not asked:
        return "unknown"
    return "same_event" if answer.same_event == "yes" else "related"


def quota_key(candidate: CandidateView) -> str:
    """The queue a candidate is screened and counted under: a section and a frame-traced clip
    each have their own, and a section of a frame-traced video stays with it."""
    if candidate.source == "section":
        return OCR_TRACED if candidate.query == OCR_TRACED else SECTIONS
    if candidate.source == OCR_TRACED:
        return OCR_TRACED
    return candidate.query


def select_batch(
    queues: dict[str, list[CandidateView]],
    admitted: Counter[str],
    total: int,
    size: int,
    per_query: int = PER_QUERY,
) -> list[CandidateView]:
    """Up to `size` candidates within the per-query and total caps (spec F6): each pick goes to
    the least-served query (admitted plus taken; ties in object order), so every query gets its
    first turn before any gets a second, across batches too."""
    batch: list[CandidateView] = []
    taken: Counter[str] = Counter()
    while len(batch) < size and total + len(batch) < MAX_FOOTAGE:
        open_queries = [
            query
            for query, queue in queues.items()
            if queue and admitted[query] + taken[query] < per_query
        ]
        if not open_queries:
            break
        query = min(open_queries, key=lambda q: admitted[q] + taken[q])
        batch.append(queues[query].pop(0))
        taken[query] += 1
    return batch


def _when(value: str | None) -> datetime | None:
    """A stored ISO-8601 UTC time, or None when it is missing or unreadable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()


def trace_query(display: str, card: ContextCard) -> str:
    """A YouTube search for a credited channel (spec 2026-11-27, 4.2): its name, the card person
    the video is about, and up to three event words in the event's order, at most 80 characters."""
    people = card.people[1:] if card.main_kind == "commentary" else card.people[:1]
    named = {word for name in card_names(card) for word in name.split()}
    terms = set(event_terms(card)) - named
    words = dict.fromkeys(
        word
        for word in (token.strip(".,;:!?()\"'").lower() for token in card.event.split())
        if word in terms
    )
    parts = [display.strip(), *(person.name for person in people[:1]), *list(words)[:3]]
    query = ""
    for part in parts:
        if part and len(f"{query} {part}".strip()) <= MAX_TRACE_QUERY:
            query = f"{query} {part}".strip()
    return query


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
        grace_seconds: float = 10.0,
        overrun_seconds: float = 120.0,
        caption_spacing: float = CAPTION_SPACING,
        context_enabled: bool = False,
    ) -> None:
        self._ports = ports
        self._context_enabled = context_enabled
        self._store = ports.store
        self._aggregators = aggregators
        self._story_min = story_min
        self._max_frames = max_frames
        self._clock = clock
        self._deadline = deadline_seconds
        self._per_candidate = per_candidate_seconds
        self._concurrency = concurrency
        self._grace = grace_seconds
        self._overrun = overrun_seconds
        self._caption_spacing = caption_spacing

    async def build(self, inputs: FootageInputs) -> FootageResult:
        """The body under a hard deadline: a step that ignores cancellation cannot hold the
        activity past it; the run finishes with what was admitted."""
        state = _Build()
        if inputs.face_check and inputs.subject is not None:
            if self._ports.faces is None:
                raise AssemblyError("face_model_missing")  # a required tool fails loud
            state.subject = inputs.subject
        body = asyncio.create_task(self._build(inputs, state))
        if await self._bounded(body, self._deadline + self._overrun) and not body.cancelled():
            return body.result()
        state.over = True
        state.closed.update(state.steps)  # stragglers write nothing more
        workflow = inputs.workflow_id
        logger.warning("footage deadline reached phase=%s", state.phase)
        status: FootageStatus = "unavailable"
        if state.phase == "checks":
            admitted = await asyncio.to_thread(self._store.admitted, workflow)
            status = "ok" if admitted else "none"
        await asyncio.to_thread(self._store.start_run, workflow, [])  # no-op once it exists
        if inputs.publish is not None:
            await self._publish(workflow, inputs.publish)
        await asyncio.to_thread(self._store.finish_run, workflow, status)
        return await self._result(workflow, status)

    async def _publish(
        self, workflow: str, publish: Callable[[list[str]], Awaitable[None]]
    ) -> None:
        """Hand over the admitted clips and photos and the page card only: a rejected or
        abandoned download stays local."""
        admitted = await asyncio.to_thread(self._store.admitted, workflow)
        photos = await asyncio.to_thread(self._store.admitted, workflow, "image")
        locations = [str(c.media_location) for c in [*admitted, *photos] if c.media_location]
        run = await asyncio.to_thread(self._store.run, workflow)
        if run is not None and run.profile_page is not None:
            locations.append(str(run.profile_page["location"]))
        await publish(locations)

    async def _bounded(self, task: asyncio.Task[Any], seconds: float) -> bool:
        """Wait up to `seconds`, then cancel and allow the grace. False: the task ignored its
        cancellation and is abandoned. Cancelled itself, it cancels the task the same way."""
        # An errored task nobody awaits must not log a traceback (it can carry a URL).
        task.add_done_callback(lambda done: done.cancelled() or done.exception())
        try:
            await asyncio.wait({task}, timeout=seconds)
            if not task.done():
                task.cancel()
                await asyncio.wait({task}, timeout=self._grace)
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.wait({task}, timeout=self._grace)
            if not task.done():
                _abandon(task)
            raise
        if not task.done():
            _abandon(task)
        return task.done()

    async def _build(self, inputs: FootageInputs, state: _Build) -> FootageResult:
        started = time.monotonic()
        workflow = inputs.workflow_id
        main = main_report(inputs)
        run = await asyncio.to_thread(self._store.run, workflow)
        if run is not None and run.status == "done":
            return await self._result(workflow, run.footage_status or "unavailable")
        self._clean_parts(inputs.artifact_root, workflow)

        slides = _carousel(main)
        if slides:
            await progress.step("footage.plan_queries", params={"count": 1})
            await asyncio.to_thread(self._store.start_run, workflow, [])
            await asyncio.to_thread(
                self._store.add_candidates,
                workflow,
                [
                    NewCandidate(
                        url=url,
                        platform=main.source.platform,
                        source="carousel",
                        query=CAROUSEL,
                        visual="",
                        owner_handle=main.post.owner_handle,
                        caption=main.post.text[:2000],
                    )
                    for url in slides
                ],
            )
            return await self._check_all(inputs, main, started, state, [CAROUSEL], slides)

        card = ContextCard.model_validate(run.context) if run and run.context else None
        begun = None
        if run is None and self._context_enabled and self._ports.card is not None:
            begun = await self._start_context(workflow, main, inputs)
            if state.over:  # a card model that ignored its cancellation came back late
                raise asyncio.CancelledError
            if begun is not None:
                card, run = begun
        if run is None:
            found = await self._objects(main, inputs.attribution)
            if state.over:  # a query model that ignored its cancellation came back late
                raise asyncio.CancelledError
            if found is None:
                await asyncio.to_thread(self._store.start_run, workflow, [])
                await asyncio.to_thread(self._store.finish_run, workflow, "unavailable")
                return FootageResult(status="unavailable")
            await progress.step("footage.plan_queries", params={"count": len(found)})
            run = await asyncio.to_thread(self._store.start_run, workflow, found)
        objects = run.objects
        if not objects:
            await asyncio.to_thread(self._store.finish_run, workflow, "none")
            return FootageResult(status="none")
        if card is not None:
            state.card = card
            state.workspace = await asyncio.to_thread(self._store.workspace_of, workflow)
            if begun is not None:
                await self._from_library(inputs, main, card, state)

        hits, failed = await self._search(objects)
        identity = MainIdentity.of(
            str(main.source.canonical_url),
            [str(inputs.report.source.canonical_url)],
            main.post.text,
        )
        creators = await self._creator(inputs, main, identity, objects, card)
        reused = await asyncio.to_thread(self._store.admitted, workflow)
        if failed and not creators and not reused:
            await asyncio.to_thread(self._store.finish_run, workflow, "unavailable")
            return await self._result(workflow, "unavailable")
        if failed:
            # The run keeps the creator's material, but the outage must stay visible.
            logger.warning("footage search unavailable; creator material only")
        if not failed:
            await self._gate(workflow, identity, objects, hits, card)
        if card is None:
            await self._story(workflow, main)
        else:
            await self._rounds(workflow, main, identity, card, run.context or {})
            current = await asyncio.to_thread(self._store.run, workflow)
            if current is not None and current.context:
                card = ContextCard.model_validate(current.context)
                state.card = card
            await self._trace(workflow, main, identity, card, state)
            await self._sections(workflow, card, state.sectioned)
            objects = current.objects if current is not None else objects
        if state.over:  # likewise an embedder
            raise asyncio.CancelledError
        people = frozenset(obj.query for obj in objects if obj.person)
        queries = [obj.query for obj in objects]
        if creators:
            queries.append(creator_query(main.post.owner_handle))
        return await self._check_all(inputs, main, started, state, queries, {}, people, identity)

    async def _creator(
        self,
        inputs: FootageInputs,
        main: SourceReport,
        identity: MainIdentity,
        objects: Sequence[FootageObject],
        card: ContextCard | None = None,
    ) -> int:
        """The creator's own videos and photos (spec 5c-2, G3, G3a, G4); how many are live.

        Listed once per workflow: a retry finds the creator rows and only counts them.
        """
        workflow, root = inputs.workflow_id, inputs.artifact_root
        platform, handle = main.source.platform, main.post.owner_handle
        if self._ports.creator is None or platform not in CREATOR_PLATFORMS:
            return 0
        known = await asyncio.to_thread(self._store.candidates, workflow)
        if any(c.source == "creator" for c in known):
            return sum(1 for c in known if c.source == "creator" and c.status != "rejected")
        await progress.step("footage.creator_listing")
        try:
            listing = await self._ports.creator.listing_of(platform, handle, CREATOR_LISTING)
        except ToolMissing:
            raise
        except Exception as error:
            logger.warning("footage creator listing failed error=%s", type(error).__name__)
            listing = None
        if listing is None:
            logger.warning("footage creator listing unavailable platform=%s", platform)
            return 0
        if listing.page_png is not None:
            await self._page_card(workflow, root, listing.page_png)
        visual = "; ".join(obj.visual for obj in objects if obj.visual)[:300] or DEFAULT_VISUAL
        query = creator_query(handle)
        seen = {c.url for c in known}
        videos = [v for v in listing.videos if str(v.canonical_url) not in seen]
        photos = [p for p in listing.photos if str(p.canonical_url) not in seen]
        if platform not in PHOTO_PLATFORMS:
            photos = []
        posts: list[DiscoveredVideo | DiscoveredPhoto] = [*videos, *photos]
        texts = [enriched_text(post.caption, post.hashtags) for post in posts]
        if card is None:
            scores = await self._scores(main, texts)
        else:  # spec 2026-11-15, 4.3.6: the creator's posts pass the context gate too
            scores = [
                0.0 if self._off_story(text, post.published_at, main, card) else OWN_SCORE
                for text, post in zip(texts, posts, strict=True)
            ]
        main_day = _when(main.post.published_at)
        rows: list[NewCandidate] = []
        undecided: list[int] = []
        verdicts: dict[int, str] = {}
        for index, post in enumerate(posts):
            url = str(post.canonical_url)
            if isinstance(post, DiscoveredVideo):
                reason = text_gate(url, post, identity, self._aggregators)
            else:
                reason = "main" if url in identity.urls else None
            if reason is None and card is not None:
                reason = "story" if scores[index] == 0.0 else None
            elif reason is None:
                decided = verdict(scores[index], post.caption, self._story_min)
                if decided == "undecided":
                    undecided.append(index)
                reason = "story" if decided == "reject" else None
            verdicts[index] = reason or "pending"
        kept, dropped = closest(undecided, lambda i: _when(posts[i].published_at), main_day)
        for index in dropped:
            verdicts[index] = "story"
        for index, post in enumerate(posts):
            reason = verdicts[index]
            photo = isinstance(post, DiscoveredPhoto)
            rows.append(
                NewCandidate(
                    url=str(post.canonical_url),
                    platform=platform,
                    source="creator",
                    query=query,
                    visual=visual,
                    owner_handle=post.owner_handle,
                    caption=post.caption[:2000],
                    published_at=post.published_at,
                    engagement={} if photo else dict(post.engagement),
                    source_duration=None if photo else post.duration_seconds,
                    status="pending" if reason == "pending" else "rejected",
                    reason=None if reason == "pending" else reason,
                    media_kind="image" if photo else "video",
                )
            )
        await asyncio.to_thread(self._store.add_candidates, workflow, rows)
        for index, row in enumerate(rows):
            if row.status == "pending":
                await asyncio.to_thread(self._store.score, workflow, row.url, scores[index])
        live_photos = sorted(
            (i for i in range(len(videos), len(posts)) if rows[i].status == "pending"),
            key=lambda i: -scores[i],
        )
        admitted_photos = await self._check_photos(
            workflow, root, [posts[i] for i in live_photos], visual
        )
        if inputs.publish is not None and (admitted_photos or listing.page_png is not None):
            # Stored now: the photo links cannot be fetched again after a crash in the clip
            # checks, which would otherwise leave admitted rows without their files.
            await self._publish(workflow, inputs.publish)
        live_videos = sum(1 for row in rows[: len(videos)] if row.status == "pending")
        logger.info(
            "footage creator listed=%d passed=%d undecided=%d kept_close=%d videos=%d photos=%d",
            len(posts),
            sum(1 for i in range(len(posts)) if verdicts[i] == "pending") - len(kept),
            len(undecided),
            len(kept),
            live_videos,
            admitted_photos,
        )
        return live_videos + admitted_photos

    async def _start_context(
        self, workflow: str, main: SourceReport, inputs: FootageInputs
    ) -> tuple[ContextCard, RunView] | None:
        """The context card and the run's first queries; None falls back to the object path."""
        assert self._ports.card is not None
        material = card_material(main, inputs.figures, inputs.transcript)
        card = await self._ports.card.card(CARD_PROMPT, material)
        if card is None or not card_names(card):
            logger.warning("footage context card unavailable; object queries")
            return None
        objects = [o for o in card_objects(card) if _storable(o)]
        if not objects:
            logger.warning("footage context card has no queries; object queries")
            return None
        await progress.step("footage.plan_queries", params={"count": len(objects)})
        run = await asyncio.to_thread(self._store.start_run, workflow, objects)
        await asyncio.to_thread(self._store.set_context, workflow, card.model_dump())
        logger.info("footage context card people=%d queries=%d", len(card.people), len(objects))
        return card, run

    def _off_story(
        self, text: str, published_at: str | None, main: SourceReport, card: ContextCard
    ) -> bool:
        # Spec 10.5/10.12: naming the subject opens two years; event words alone keep 30 days.
        # A commentary's discussed figure with a context word opens two years too (2026-11-26).
        said = norm(text)
        if names_subject(said, card) or names_discussed_with_context(said, card):
            return not in_window(
                published_at, main.post.published_at, self._clock(), before=PERSON_WINDOW
            )
        return not in_window(published_at, main.post.published_at, self._clock()) or (
            context_reason(text, card) is not None
        )

    async def _context_gate(self, workflow: str, main: SourceReport, card: ContextCard) -> int:
        """Decide every undecided candidate by the card, own accounts first; the passing count."""
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        passing = 0
        for c in candidates:
            if c.status != "pending" or c.media_kind != "video":
                continue
            if c.story_score is not None:
                passing += 1
                continue
            if self._off_story(f"{c.caption} {c.owner_handle}", c.published_at, main, card):
                await asyncio.to_thread(self._store.reject, workflow, c.url, "story")
                continue
            score = OWN_SCORE if is_own_account(c.owner_handle, card) else PASS_SCORE
            await asyncio.to_thread(self._store.score, workflow, c.url, score)
            passing += 1
        return passing

    async def _rounds(
        self,
        workflow: str,
        main: SourceReport,
        identity: MainIdentity,
        card: ContextCard,
        stored: dict[str, Any],
    ) -> None:
        """Round one's gate, then round two: the titles teach the card aliases and corrections,
        its new queries are searched, and round one's story rejects are judged again."""
        await self._context_gate(workflow, main, card)
        # Round two always runs once (spec 10.4): skipped on a full round one, the card never
        # learned the subject's real name (live Mutant runs, `refined` false).
        if stored.get(REFINED) or self._ports.card is None:
            return
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        titles = [
            {"title": c.caption[:200], "channel": c.owner_handle, "platform": c.platform}
            for c in candidates
            if c.source == "search"
        ][:REFINE_TITLES]
        material = json.dumps({"card": card.model_dump(), "results": titles}, ensure_ascii=False)
        refined = await self._ports.card.card(REFINE_PROMPT, material)
        if refined is not None:
            # Round two sees titles only, never the main: the kind stays round one's.
            refined = refined.model_copy(update={"main_kind": card.main_kind})
        if refined is None or not card_names(refined):
            await asyncio.to_thread(
                self._store.set_context, workflow, {**card.model_dump(), REFINED: True}
            )
            return
        run = await asyncio.to_thread(self._store.run, workflow)
        known = {norm(o.query) for o in (run.objects if run is not None else [])}
        fresh = [q for q in refined.queries if norm(q) and norm(q) not in known][:REFINE_QUERIES]
        related = [r for r in refined.related if norm(r.query) not in known][:REFINE_QUERIES]
        objects = [o for o in context_objects(refined, fresh, related) if _storable(o)]
        await asyncio.to_thread(
            self._store.set_context, workflow, {**refined.model_dump(), REFINED: True}
        )
        if objects:
            await asyncio.to_thread(self._store.add_objects, workflow, objects)
            hits, failed = await self._search(objects)
            if not failed:
                await self._gate(workflow, identity, objects, hits, refined)
        for c in await asyncio.to_thread(self._store.candidates, workflow):
            story = c.status == "rejected" and c.reason == "story" and c.media_kind == "video"
            text = f"{c.caption} {c.owner_handle}"
            if story and not self._off_story(text, c.published_at, main, refined):
                await asyncio.to_thread(self._store.reopen, workflow, c.url)
        await self._context_gate(workflow, main, refined)
        logger.info("footage context round two queries=%d", len(objects))

    async def _trace(
        self,
        workflow: str,
        main: SourceReport,
        identity: MainIdentity,
        card: ContextCard,
        state: _Build | None = None,
    ) -> None:
        """A repost that credits another account is replaced by that account's original, when
        its listing holds one on the story (spec 2026-11-15, 4.5). The accounts listed join
        `state.traced_keys`, so a frame credit never lists them again."""
        if self._ports.creator is None:
            return
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        known = {c.url for c in candidates}
        kept = sum(1 for c in candidates if c.status in ("admitted", "pending"))
        # Plenty to screen already: only a YouTube original still earns a trace, since a long
        # video is cut at its moments and a repost is often subtitled (spec 2026-11-27, 4.2).
        full = kept >= MAX_FOOTAGE * 2
        listings: dict[tuple[str, str], list[DiscoveredVideo]] = {}
        searched: set[tuple[str, str]] = set()
        for c in candidates:
            if c.status != "pending" or c.source != "search" or c.media_kind != "video":
                continue
            ref = credited_source(c.caption)
            if ref is None or normalize(ref.account) == normalize(c.owner_handle):
                continue
            # An own clip tagging someone is the original, unless it names the source platform.
            if ref.platform is None and is_own_account(c.owner_handle, card):
                continue
            platform = ref.platform or ("youtube" if "youtube" in c.caption.lower() else c.platform)
            if platform not in CREATOR_PLATFORMS or (full and platform != "youtube"):
                continue
            key = (platform, normalize(ref.account))
            if key not in listings and len(listings) >= MAX_TRACE_LISTINGS:
                continue
            if key not in listings:
                listings[key] = await self._trace_listing(platform, ref.account)
                if state is not None:
                    state.traced_keys.add(key)
            rows = self._trace_rows(c, platform, listings[key], known, identity, main, card)
            if (
                platform == "youtube"
                and key not in searched
                and not any(row.status == "pending" for row in rows)
            ):
                # A channel name is rarely its handle: one targeted search instead.
                searched.add(key)
                found = await self._trace_search(trace_query(ref.display, card))
                listings[key] = [*listings[key], *found]
                rows += self._trace_rows(c, platform, found, known, identity, main, card)
            if not rows:
                continue
            await asyncio.to_thread(self._store.add_candidates, workflow, rows)
            originals = [row for row in rows if row.status == "pending"]
            for row in originals:
                await asyncio.to_thread(self._store.score, workflow, row.url, OWN_SCORE)
            if originals:
                await asyncio.to_thread(self._store.reject, workflow, c.url, "repost")
        logger.info("footage trace credited_accounts=%d", len(listings))

    def _trace_rows(
        self,
        repost: CandidateView,
        platform: str,
        videos: Sequence[DiscoveredVideo],
        known: set[str],
        identity: MainIdentity,
        main: SourceReport,
        card: ContextCard,
        *,
        source: str = "trace",
        query: str | None = None,
    ) -> list[NewCandidate]:
        """The new candidates a credited account offers: gate rejections kept, off-story
        videos dropped; `known` grows with each. They take the repost's query unless given
        one."""
        rows: list[NewCandidate] = []
        for video in videos:
            url = str(video.canonical_url)
            if url in known:
                continue
            reason = text_gate(
                url, video, identity, self._aggregators, long_ok=platform == "youtube"
            )
            text = f"{video.caption} {video.owner_handle}"
            if reason is None and self._off_story(text, video.published_at, main, card):
                continue
            known.add(url)
            rows.append(
                NewCandidate(
                    url=url,
                    platform=platform,
                    source=source,
                    query=query or repost.query,
                    visual=repost.visual,
                    owner_handle=video.owner_handle,
                    caption=video.caption[:2000],
                    published_at=video.published_at,
                    engagement=dict(video.engagement),
                    source_duration=video.duration_seconds,
                    status="rejected" if reason else "pending",
                    reason=reason,
                )
            )
        return rows

    async def _trace_listing(self, platform: str, account: str) -> list[DiscoveredVideo]:
        assert self._ports.creator is not None
        try:
            listing = await self._ports.creator.listing_of(platform, account, CREATOR_LISTING)
        except ToolMissing:
            raise
        except Exception as error:
            logger.warning("footage trace listing failed error=%s", type(error).__name__)
            return []
        return list(listing.videos) if listing else []

    async def _trace_search(self, query: str) -> list[DiscoveredVideo]:
        """One YouTube search for a credited channel, cached like every footage search."""
        cached = await asyncio.to_thread(self._store.cached_search, "youtube", query)
        if cached is not None:
            return list(cached)
        try:
            batch = await self._ports.search.search("youtube", [query], RESULTS_PER_QUERY)
        except ToolMissing:
            raise
        except Exception as error:
            logger.warning("footage trace search failed error=%s", type(error).__name__)
            return []
        if query not in batch.found:
            return []
        videos = list(batch.found[query])
        await asyncio.to_thread(self._store.save_search, "youtube", query, videos)
        return videos

    async def _sections(
        self,
        workflow: str,
        card: ContextCard,
        sectioned: set[str] | None = None,
        only: set[str] | None = None,
    ) -> None:
        """A YouTube video past 3 minutes is cut at the caption lines naming a card person, and
        is then rejected `duration`. One past MAX_SECONDS is rejected even with no moment, so
        nothing is downloaded; a shorter one with no moment stays pending for a plain clip.
        `sectioned` holds the videos already read, so a second call reads only new ones; `only`
        limits a call to the given videos (spec 2026-11-27 ocr video credit, 3.5)."""
        already = sectioned if sectioned is not None else set()
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        known = {c.url for c in candidates}
        handled = 0
        eligible = [
            c
            for c in candidates
            if c.status == "pending"
            and c.platform == "youtube"
            and (c.source_duration or 0.0) > LONG_SECTION_SECONDS
            and SECTION_MARK not in c.url
            and c.url not in already
            and (only is None or c.url in only)
        ]
        # Own accounts and traced originals first, then a video past MAX_SECONDS before a medium
        # one (it has no plain clip): the caption fetches are capped.
        for c in sorted(
            eligible,
            key=lambda c: (-(c.story_score or 0.0), (c.source_duration or 0.0) <= MAX_SECONDS),
        ):
            found: list[Discussion] = []
            if self._ports.captions_text is not None and handled < MAX_LONG_VIDEOS:
                if handled:
                    await asyncio.sleep(self._caption_spacing)
                handled += 1
                already.add(c.url)
                port = self._ports.captions_text
                if hasattr(port, "hints"):  # chapters and heatmap from the same metadata call
                    hints = await port.hints(c.url, CAPTION_LANGUAGE)
                else:
                    hints = LongVideoHints(await port.captions(c.url, CAPTION_LANGUAGE))
                if hints.captions or hints.chapters:
                    subject = subject_names(card)
                    others = [name for name in card_names(card) if name not in subject]
                    # A name is never a discussion word: "Denny" from the event is a person.
                    named = {word for name in card_names(card) for word in name.split()}
                    terms = set(event_terms(card))
                    if card.main_kind == "commentary":
                        # The video discusses the event, not the commentator (2026-11-26, 3.4).
                        subject, others = [], card_names(card)
                        terms |= related_terms(card)
                    words = [*card.spoken, *sorted(t for t in terms if t not in named)]
                    lines = parse_json3(hints.captions) if hints.captions else []
                    found = pick_discussions(
                        lines,
                        subject,
                        others,
                        words,
                        chapters=hints.chapters,
                        heatmap=hints.heatmap,
                    )
            rows = [
                NewCandidate(
                    url=f"{c.url}{SECTION_MARK}{discussion.moment:.1f}",
                    platform=c.platform,
                    source="section",
                    query=c.query,
                    # A person talking, named nowhere (spec 10.12); a chapter cut has no words
                    # said, so it shows what the long video was searched for.
                    visual=PERSON_VISUAL if discussion.said else (c.visual or PERSON_VISUAL),
                    owner_handle=c.owner_handle,
                    caption=c.caption,
                    published_at=c.published_at,
                    engagement=dict(c.engagement),
                    source_duration=SECTION_SECONDS,
                    said=discussion.said,
                )
                for discussion in found
                if f"{c.url}{SECTION_MARK}{discussion.moment:.1f}" not in known
            ]
            if rows:
                await asyncio.to_thread(self._store.add_candidates, workflow, rows)
                for row in rows:
                    await asyncio.to_thread(
                        self._store.score, workflow, row.url, c.story_score or PASS_SCORE
                    )
            if rows or (c.source_duration or 0.0) > MAX_SECONDS:
                await asyncio.to_thread(self._store.reject, workflow, c.url, "duration")
            logger.info("footage long video sections=%d", len(rows))

    async def _trace_ocr_credits(
        self,
        workflow: str,
        main: SourceReport,
        identity: MainIdentity,
        state: _Build,
        queues: dict[str, list[CandidateView]],
        queued: set[str],
    ) -> int:
        """The credits burned into rejected subtitled reposts (spec 2026-11-27 ocr video
        credit, 3.3): up to MAX_OCR_TRACES accounts per run are traced like a caption credit,
        a long original is cut, and the new pending clips join the screening at the head of
        their queue. Returns how many joined."""
        credits = sorted(state.ocr_credits, key=lambda item: item[1].platform != "youtube")
        state.ocr_credits.clear()
        card = state.card
        if card is None or self._ports.creator is None:
            return 0
        known = {c.url for c in await asyncio.to_thread(self._store.candidates, workflow)}
        traced = 0
        long_originals: set[str] = set()
        for repost, ref in credits:
            if state.ocr_traced_count >= MAX_OCR_TRACES:
                break
            account = normalize(ref.account)
            platform = ref.platform or (
                "youtube" if "youtube" in ref.display.lower() else repost.platform
            )
            key = (platform, account)
            if (
                platform not in CREATOR_PLATFORMS
                or account == normalize(repost.owner_handle)
                or key in state.traced_keys
            ):
                continue
            state.traced_keys.add(key)
            state.ocr_traced_count += 1
            traced += 1
            listing = await self._trace_listing(platform, ref.account)
            rows = self._trace_rows(
                repost,
                platform,
                listing,
                known,
                identity,
                main,
                card,
                source=OCR_TRACED,
                query=OCR_TRACED,
            )
            if platform == "youtube" and not any(row.status == "pending" for row in rows):
                found = await self._trace_search(trace_query(ref.display, card))
                rows += self._trace_rows(
                    repost,
                    platform,
                    found,
                    known,
                    identity,
                    main,
                    card,
                    source=OCR_TRACED,
                    query=OCR_TRACED,
                )
            if not rows:
                continue
            await asyncio.to_thread(self._store.add_candidates, workflow, rows)
            for row in rows:
                if row.status != "pending":
                    continue
                await asyncio.to_thread(self._store.score, workflow, row.url, OWN_SCORE)
                if platform == "youtube" and (row.source_duration or 0.0) > LONG_SECTION_SECONDS:
                    long_originals.add(row.url)
        if long_originals:
            # Only these originals: the long videos the first call left unread stay as they are.
            await self._sections(workflow, card, state.sectioned, long_originals)
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        # A medium video cut just now is no longer pending: it leaves its queue.
        open_now = {c.url for c in candidates if c.status == "pending"}
        for queue in queues.values():
            queue[:] = [c for c in queue if c.url in open_now]
        joined = [
            c
            for c in candidates
            if c.status == "pending" and c.media_kind == "video" and c.url not in queued
        ]
        for c in sorted(joined, key=lambda c: c.story_score or 0.0):
            queues.setdefault(quota_key(c), []).insert(0, c)
        queued.update(c.url for c in joined)
        logger.info("footage ocr trace credits=%d added=%d", traced, len(joined))
        return len(joined)

    async def _scores(self, main: SourceReport, texts: list[str]) -> list[float]:
        if not texts:
            return []
        text = main.post.text
        story = f"{text[:120]}. {text}".strip()
        vectors = await self._ports.embedder.embed([story, *texts])
        return [
            max(0.0, min(1.0, cosine(vectors[0], vector))) if caption.strip() else 0.0
            for caption, vector in zip(texts, vectors[1:], strict=True)
        ]

    async def _page_card(self, workflow: str, root: Path, png: bytes) -> None:
        location = PurePosixPath("reports") / workflow / "cards" / PAGE_CARD
        try:
            card = await asyncio.to_thread(write_card, png, root, location)
        except (CardRejected, OSError):
            logger.warning("footage creator page card rejected")
            return
        await asyncio.to_thread(
            self._store.set_profile_page, workflow, card.model_dump(mode="json")
        )

    async def _check_photos(
        self, workflow: str, root: Path, photos: list[DiscoveredPhoto], visual: str
    ) -> int:
        """Up to MAX_PHOTOS photos, best story score first, each judged on itself."""
        if self._ports.photos is None:
            return 0
        admitted = 0
        for photo in photos:
            if admitted >= MAX_PHOTOS:
                break
            url = str(photo.canonical_url)
            target = root / "reports" / workflow / "footage" / f"photo-{photo.post_id}"
            try:
                path = await self._ports.photos.fetch(str(photo.image_urls[0]), target)
            except PhotoError:
                await asyncio.to_thread(self._store.reject, workflow, url, "media_failed")
                continue
            try:
                frame = await self._ports.frames.frame_at(path, 0.0, width=VISION_WIDTH)
                answer = await self._ports.judge.judge([frame], visual)
            except FrameError:
                reason, seen = "media_failed", {}
            except AttributionError:
                reason, seen = "vision_unavailable", {}
            else:
                seen = {
                    "kind": answer.kind,
                    "shows_object": answer.shows_object,
                    "description": answer.description,
                }
                reason = (
                    "commentary"
                    if answer.kind == "commentary"
                    else "object_absent"
                    if answer.shows_object == "no"
                    else ""
                )
            if reason:
                path.unlink(missing_ok=True)
                await asyncio.to_thread(self._store.reject, workflow, url, reason, **seen)
                continue
            clip = AdmittedClip(
                kind=answer.kind,
                shows_object=answer.shows_object,
                description=answer.description,
                media_location=path.relative_to(root).as_posix(),
                media_checksum=_sha256(path),
                media_bytes=path.stat().st_size,
                clip_duration=0.0,
                clip_start=0.0,
                ocr={},
                position=admitted,
            )
            await asyncio.to_thread(self._store.admit, workflow, url, clip)
            admitted += 1
        return admitted

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
        searched = 0

        async def platform(name: str) -> dict[str, list[DiscoveredVideo]] | None:
            found: dict[str, list[DiscoveredVideo]] = {}
            missing: list[str] = []
            for obj in objects:
                cached = await asyncio.to_thread(self._store.cached_search, name, obj.query)
                if cached is None:
                    missing.append(obj.query)
                else:
                    found[obj.query] = list(cached)
            failed = False
            if missing:
                # One call per platform: X serves every query from one lease (option A).
                try:
                    batch = await self._ports.search.search(name, missing, RESULTS_PER_QUERY)
                except ToolMissing:
                    raise
                except Exception as error:
                    logger.warning(
                        "footage search failed platform=%s error=%s", name, type(error).__name__
                    )
                    batch = SearchBatch(found={}, failed=True)
                for query, videos in batch.found.items():
                    await asyncio.to_thread(self._store.save_search, name, query, videos)
                    found[query] = list(videos)
                failed = batch.failed
            logger.info(
                "footage search platform=%s hits=%d failed=%s",
                name,
                sum(len(videos) for videos in found.values()),
                failed,
            )
            # A completion count, not the platform index: the searches run concurrently,
            # so the last platform to finish reports the total, whichever it is.
            nonlocal searched
            searched += 1
            await progress.step(
                "footage.search_platforms",
                n=searched,
                total=len(SEARCH_PLATFORMS),
                params={"platform": name},
            )
            if failed and not found:
                return None
            return found

        results = await _together(platform(name) for name in SEARCH_PLATFORMS)
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
        card: ContextCard | None = None,
    ) -> None:
        known = {c.url for c in await asyncio.to_thread(self._store.candidates, workflow)}
        new: list[NewCandidate] = []
        for obj in objects:
            for platform, video in hits.get(obj.query, []):
                url = str(video.canonical_url)
                if url in known:  # the same post from another platform or query
                    continue
                known.add(url)
                long_ok = card is not None and platform == "youtube"
                reason = text_gate(url, video, identity, self._aggregators, long_ok=long_ok)
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
        state: _Build,
        queries: list[str],
        carousel: dict[str, PurePosixPath],
        people: frozenset[str] = frozenset(),
        identity: MainIdentity | None = None,
    ) -> FootageResult:
        state.phase = "checks"
        workflow, root = inputs.workflow_id, inputs.artifact_root
        state.main_published = main.post.published_at
        admitted_hashes = await self._verify_admitted(workflow, root, state)
        main_hashes = await self._main_hashes(main, root)
        await self._main_recording(main, root, state)
        if state.card is not None:
            state.reference = await self._reference(main, root)
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        clips = [c for c in candidates if c.media_kind == "video"]  # photos are checked apart
        pending = [c for c in clips if c.status == "pending"]
        admitted = Counter(quota_key(c) for c in clips if c.status == "admitted")
        used = [c.position for c in candidates if c.position is not None]
        state.positions = itertools.count(max(used, default=-1) + 1)
        queues = {
            query: sorted(
                (c for c in pending if quota_key(c) == query),
                key=lambda c: -(c.story_score or 0.0),
            )
            for query in [*queries, SECTIONS, OCR_TRACED]
        }
        queued = {c.url for c in pending}
        total_pending = len(pending)  # grows when frame credits bring originals mid-run
        per_query = MAX_FOOTAGE if carousel else PER_QUERY
        total = sum(admitted.values())
        screened = 0
        while total < MAX_FOOTAGE and time.monotonic() - started < self._deadline:
            batch = select_batch(queues, admitted, total, self._concurrency, per_query)
            if not batch:
                break
            # A failure (a missing tool) cancels the siblings, so none decides during a retry.
            outcomes = await _together(
                self._timed(
                    workflow,
                    root,
                    c,
                    carousel.get(c.url),
                    main_hashes,
                    admitted_hashes,
                    state,
                    c.query in people or c.source == "section",
                )
                for c in batch
            )
            for candidate, ok in zip(batch, outcomes, strict=True):
                if ok:
                    admitted[quota_key(candidate)] += 1
                    total += 1
                screened += 1
                await progress.step("footage.screen_clips", n=screened, total=total_pending)
            for query in state.displaced:  # a cleaner copy took its place (spec 9.4)
                admitted[query] -= 1
                total -= 1
            state.displaced.clear()
            if (
                state.ocr_credits
                and identity is not None
                and total < MAX_FOOTAGE
                and time.monotonic() - started < self._deadline
            ):
                total_pending += await self._trace_ocr_credits(
                    workflow, main, identity, state, queues, queued
                )
        photos = await asyncio.to_thread(self._store.admitted, workflow, "image")
        status: FootageStatus = "ok" if total or photos else "none"
        if inputs.publish is not None:
            await self._publish(workflow, inputs.publish)
        await asyncio.to_thread(self._store.finish_run, workflow, status)
        return await self._result(workflow, status, state.media_causes)

    async def _timed(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        existing: PurePosixPath | None,
        main_hashes: list[int],
        admitted_hashes: list[list[int]],
        state: _Build,
        person: bool,
    ) -> bool:
        owned = existing is None
        name = hashlib.sha256(candidate.url.encode()).hexdigest()[:20] + ".mp4"
        location = existing or PurePosixPath("reports") / workflow / "footage" / name
        state.steps[candidate.url] = "download" if owned else "ocr"
        check = asyncio.create_task(
            self._check(
                workflow,
                root,
                candidate,
                location,
                owned,
                main_hashes,
                admitted_hashes,
                state,
                person,
            )
        )
        try:
            finished = await self._bounded(check, self._per_candidate)
        except asyncio.CancelledError:
            # Cancelled before a decision: drop the window; the candidate stays pending, so a
            # retry redoes it. (After an admit landed, a retry finds no file and reopens it.)
            state.closed.add(candidate.url)
            if owned:
                (root / location).unlink(missing_ok=True)
            raise
        if finished and not check.cancelled():
            return check.result()  # a decision, or a missing tool raised
        state.closed.add(candidate.url)  # before the reject: a straggler can no longer write
        logger.warning(
            "footage check timed out platform=%s step=%s abandoned=%s",
            candidate.platform,
            state.steps[candidate.url],
            not finished,
        )
        if owned:
            (root / location).unlink(missing_ok=True)
        self._media_failed(candidate, "timeout", state)
        await asyncio.to_thread(self._store.reject, workflow, candidate.url, "media_failed")
        return False

    async def _check(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        location: PurePosixPath,
        owned: bool,
        main_hashes: list[int],
        admitted_hashes: list[list[int]],
        state: _Build,
        person: bool,
    ) -> bool:
        steps = state.steps
        path = root / location
        source, _, moment = candidate.url.partition(SECTION_MARK)
        window = clip_window(candidate.source_duration) if owned else None
        if owned and moment:  # a long video's caption moment (spec 2026-11-15, 4.4)
            window = section(float(moment))
        if owned:
            try:
                await self._ports.downloader.download(source, window, path)
            except ClipError as error:
                self._media_failed(candidate, f"ClipError({error})", state)
                return await self._reject(
                    workflow, root, candidate, location, owned, "media_failed", state
                )
        try:
            steps[candidate.url] = "ocr"
            # The text already read on each frame, for a burned-in credit (spec 2026-11-27 ocr
            # video credit, 3.3); a carousel slide is the main's own.
            ocr_frames: list[list[str]] | None = (
                [] if state.card is not None and candidate.source != "carousel" else None
            )
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
                follow=False,  # a captioned candidate is rejected; it needs no windows
                collected_frames=ocr_frames,
            )
            # An overlay band is rejected too: the renderer blurs bands on the main only.
            if ocr.outcome in ("subtitle", "overlay"):
                # Its credit is traced between batches: no network inside the check's budget.
                ref = frame_credited_source(ocr_frames) if ocr_frames else None
                if ref is not None and normalize(ref.account) != normalize(candidate.owner_handle):
                    state.ocr_credits.append((candidate, ref))
                return await self._reject(
                    workflow, root, candidate, location, owned, "subtitle", state
                )
            steps[candidate.url] = "frames"
            duration = await self._ports.probe.duration(path)
            frames = [
                await self._ports.frames.frame_at(path, second, width=VISION_WIDTH)
                for second in vision_seconds(ocr.trim_start, duration)
            ]
        except AssemblyError as error:
            if error.code in MEDIA_FAILURES:
                self._media_failed(candidate, error.code, state)
                return await self._reject(
                    workflow, root, candidate, location, owned, "media_failed", state
                )
            raise  # a missing tool is an explicit error
        except (FrameError, DurationError) as error:
            self._media_failed(candidate, type(error).__name__, state)
            return await self._reject(
                workflow, root, candidate, location, owned, "media_failed", state
            )
        shown = True
        if self._needs_subject_face(candidate, state):
            # Spec 10.12: before the paid call, so a clip without the subject costs nothing.
            steps[candidate.url] = "faces"
            shown = await self._shows_subject(path, state)
            if not shown and not self._may_discuss(candidate, state):
                return await self._reject(
                    workflow, root, candidate, location, owned, "subject_absent", state
                )
        steps[candidate.url] = "vision"
        try:
            answer = await self._ports.judge.judge(
                frames,
                candidate.visual or DEFAULT_VISUAL,
                person=person,
                reference=state.reference,
            )
        except AttributionError:
            return await self._reject(
                workflow, root, candidate, location, owned, "vision_unavailable", state
            )
        seen = {
            "kind": answer.kind,
            "shows_object": answer.shows_object,
            "description": answer.description,
        }
        relation = relation_of(answer, state.reference is not None)
        if not shown:
            # One clip may talk about the subject without showing them; never the incident.
            if relation == "same_event":
                return await self._reject(
                    workflow, root, candidate, location, owned, "subject_absent", state
                )
            relation = "discusses"
        # A section is a person talking (spec 10.5): it is never rejected as commentary.
        if answer.kind == "commentary" and candidate.source != "section":
            return await self._reject(
                workflow, root, candidate, location, owned, "commentary", state, **seen
            )
        if answer.shows_object == "no":
            return await self._reject(
                workflow, root, candidate, location, owned, "object_absent", state, **seen
            )
        steps[candidate.url] = "hash"
        hashes = [dhash(frame.jpeg) for frame in frames]
        if is_duplicate(hashes, [main_hashes, *admitted_hashes]):
            return await self._reject(
                workflow, root, candidate, location, owned, "duplicate", state, **seen
            )
        steps[candidate.url] = "copy"
        # The heavy reads (frames, ORB, OCR, the main) run before the lock (final review, 3).
        evidence = await self._evidence(candidate, path, state)
        if evidence is not None and evidence.copies_main:
            return await self._reject(
                workflow, root, candidate, location, owned, "duplicate", state, **seen
            )
        async with state.copy_lock:  # the copy decision and the admit are one step
            losers: list[_Recording] = []
            if evidence is not None:
                found = await self._losers(
                    evidence.features, evidence.facts, evidence.source, state
                )
                if found is None:
                    return await self._reject(
                        workflow, root, candidate, location, owned, "duplicate", state, **seen
                    )
                losers = found
            facts = (
                evidence.facts
                if evidence is not None
                else CopyFacts(
                    candidate.url, self._original(candidate, state), 0.0, candidate.published_at
                )
            )
            held = state.same_event
            if relation == "same_event" and (
                not clean_original(facts) or (held is not None and keep_first(held.facts, facts))
            ):
                return await self._reject(
                    workflow, root, candidate, location, owned, "same_event", state, **seen
                )
            if relation == "discusses" and len(state.discussing) >= MAX_DISCUSSES:
                return await self._reject(
                    workflow, root, candidate, location, owned, "subject_absent", state, **seen
                )
            old = self._old(candidate, state)
            if old and len(state.old) >= MAX_OLD:
                return await self._reject(
                    workflow, root, candidate, location, owned, "too_old", state, **seen
                )
            steps[candidate.url] = "store"
            if candidate.url in state.closed:  # abandoned: its media_failed is recorded
                return False
            admitted_hashes.append(hashes)
            position = next(state.positions)
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
                relation=relation,
            )
            if candidate.source == "carousel":  # scored first: an admitted slide always has its 1.0
                await asyncio.to_thread(self._store.score, workflow, candidate.url, 1.0)
            if candidate.url in state.closed:
                return False
            await asyncio.to_thread(self._store.admit, workflow, candidate.url, clip)
            # Only an admit that landed displaces a kept copy (final review, 1).
            await self._settle(
                workflow, candidate, evidence, losers, hashes, admitted_hashes, state
            )
            if old:
                state.old.add(candidate.url)
            if relation == "discusses":
                state.discussing.add(candidate.url)
            if relation == "same_event":
                # A holder beaten as a copy in `_settle` is gone already (final review, 1).
                if held is not None and state.same_event is held:
                    await self._displace(workflow, held, admitted_hashes, state, "same_event")
                state.same_event = _Recording(
                    candidate.url,
                    candidate.url.partition(SECTION_MARK)[0],
                    quota_key(candidate),
                    [],
                    facts,
                    hashes,
                )
            if state.card is not None and state.workspace is not None:
                await self._remember(workflow, candidate, clip, window, hashes, state)
            return True

    async def _recording(self, path: Path) -> tuple[list[Frame], list[Any]]:
        """A clip's 1 fps frames and their ORB features; empty when they cannot be read."""
        try:
            frames = await self._ports.recording_frames.frames(path, fps=1.0)
        except FrameError:
            return [], []
        return frames, list(await self._ports.matcher.prepare(frames) or [])

    async def _main_recording(self, main: SourceReport, root: Path, state: _Build) -> list[Any]:
        if state.main_recording is None:
            state.main_recording = []
            videos = [media for media in main.media if media.kind == "video"]
            path = root / videos[0].location if videos else None
            if self._copy_check and path is not None and path.is_file():
                state.main_recording = (await self._recording(path))[1]
        return state.main_recording

    @property
    def _copy_check(self) -> bool:
        return self._ports.matcher is not None and self._ports.recording_frames is not None

    async def _copy_of(self, frames: list[Any], other: list[Any]) -> bool:
        """Stage 1 on three frames against every second frame, then the 1 fps alignment."""
        if not frames or not other:
            return False
        trigger = [frames[int(len(frames) * share)] for share in COPY_SHARES]
        if not triggered(await self._ports.matcher.compare(trigger, other[::2])):
            return False
        return is_copy(await self._ports.matcher.matrix(frames, other))

    async def _copy_facts(
        self, candidate: CandidateView, frames: list[Frame], state: _Build
    ) -> CopyFacts:
        """An original or a copy, and how much on-screen text covers it (spec 9.4)."""
        original = self._original(candidate, state)
        picked = [frames[int(len(frames) * share)] for share in COPY_SHARES] if frames else []
        share = text_share([await self._ports.text.read(frame) for frame in picked])
        return CopyFacts(candidate.url, original, share, candidate.published_at)

    async def _shows_subject(self, path: Path, state: _Build) -> bool:
        from thoth_control_plane.footage.faces import shows_subject

        faces = await asyncio.to_thread(self._ports.faces.faces, path)
        return shows_subject(state.subject, faces)

    @staticmethod
    def _needs_subject_face(candidate: CandidateView, state: _Build) -> bool:
        """Whether a clip must show the subject's face (spec 10.12). On a commentary card only a
        query about the commentator alone does: clips of the discussed events and figures never
        show them (spec 2026-11-26, 3.4)."""
        if state.subject is None or candidate.source == "carousel":
            return False
        card = state.card
        if card is None or card.main_kind != "commentary":
            return True
        query = norm(candidate.query)
        return (
            names_subject(query, card)
            and not any(mentions(query, name) for name in discussed_names(card))
            and not has_event_term(query, card)
        )

    @staticmethod
    def _may_discuss(candidate: CandidateView, state: _Build) -> bool:
        """A clip without the subject's face may still talk about them: its text names the
        subject and the run keeps no such clip yet (spec 10.12)."""
        if state.card is None or len(state.discussing) >= MAX_DISCUSSES:
            return False
        return names_subject(norm(f"{candidate.caption} {candidate.owner_handle}"), state.card)

    @staticmethod
    def _original(candidate: CandidateView, state: _Build) -> bool:
        """A creator's, a traced or an own account's clip (spec 9.4)."""
        return candidate.source in ORIGINAL_SOURCES or (
            state.card is not None and is_own_account(candidate.owner_handle, state.card)
        )

    async def _evidence(
        self, candidate: CandidateView, path: Path, state: _Build
    ) -> _Evidence | None:
        """What the copy check needs about a clip (spec 2026-11-15, 9.4): its 1 fps features,
        whether it copies the main, and whether it is an original and how clean; None when the
        check is off."""
        if not self._copy_check:
            return None
        frames, features = await self._recording(path)
        return _Evidence(
            features=features,
            facts=await self._copy_facts(candidate, frames, state),
            source=candidate.url.partition(SECTION_MARK)[0],
            copies_main=await self._copy_of(features, state.main_recording or []),
        )

    async def _losers(
        self, features: list[Any], facts: CopyFacts, source: str, state: _Build
    ) -> list[_Recording] | None:
        """The kept copies this clip beats, or None when any kept copy stays over it: every
        comparison runs before anything is displaced (final review, 2)."""
        losers: list[_Recording] = []
        for other in list(state.recordings.values()):
            # Sections of one video share a set and a camera: that is no copy (spec 9.9).
            if other.source == source or not await self._copy_of(features, other.frames):
                continue
            if keep_first(other.facts, facts):
                return None
            losers.append(other)
        return losers

    async def _settle(
        self,
        workflow: str,
        candidate: CandidateView,
        evidence: _Evidence | None,
        losers: list[_Recording],
        hashes: list[int],
        admitted_hashes: list[list[int]],
        state: _Build,
    ) -> None:
        """After the admit: the beaten copies go, and this clip joins the copy check."""
        if evidence is None:
            return
        for loser in losers:
            await self._displace(workflow, loser, admitted_hashes, state)
        state.recordings[candidate.url] = _Recording(
            candidate.url,
            evidence.source,
            quota_key(candidate),
            evidence.features,
            evidence.facts,
            hashes,
        )

    async def _displace(
        self,
        workflow: str,
        other: _Recording,
        admitted_hashes: list[list[int]],
        state: _Build,
        reason: RejectReason = "duplicate",
    ) -> None:
        logger.info("footage clip displaced reason=%s", reason)
        await asyncio.to_thread(self._store.reject, workflow, other.url, reason)
        if state.workspace is not None:
            try:
                await asyncio.to_thread(
                    self._store.drop_library, state.workspace, workflow, other.url
                )
            except Exception as error:
                logger.warning("footage library drop failed error=%s", type(error).__name__)
        state.recordings.pop(other.url, None)
        state.old.discard(other.url)
        state.discussing.discard(other.url)
        if state.same_event is not None and state.same_event.url == other.url:
            state.same_event = None
        admitted_hashes[:] = [h for h in admitted_hashes if h is not other.hashes]
        state.displaced.append(other.query)

    async def _remember(
        self,
        workflow: str,
        candidate: CandidateView,
        clip: AdmittedClip,
        window: tuple[float, float] | None,
        hashes: list[int],
        state: _Build,
    ) -> None:
        """A kept clip joins the workspace's library; a failure there never undoes the admit."""
        assert state.card is not None and state.workspace is not None
        kept = LibraryClip(
            url=candidate.url,
            platform=candidate.platform,
            owner_handle=candidate.owner_handle,
            published_at=candidate.published_at,
            section_start=clip.clip_start,
            section_end=window[1] if window else None,
            media_location=clip.media_location,
            media_checksum=clip.media_checksum,
            hashes=hashes,
            names=card_names(state.card),
            event=f"{state.card.event} {state.card.place}".strip(),
            ocr=clip.ocr,
            said=list(candidate.said),
            relation=clip.relation,
        )
        try:
            await asyncio.to_thread(self._store.add_library, state.workspace, workflow, kept)
        except Exception as error:
            logger.warning("footage library write failed error=%s", type(error).__name__)

    async def _from_library(
        self, inputs: FootageInputs, main: SourceReport, card: ContextCard, state: _Build
    ) -> None:
        """Clips an earlier run kept for the same people join this run admitted: copied from
        storage, never searched, downloaded or checked again (spec 2026-11-15, 4.6)."""
        if state.workspace is None or self._ports.library_media is None:
            return
        workflow, root = inputs.workflow_id, inputs.artifact_root
        now = self._clock()
        since = (_when(main.post.published_at) or now) - WINDOW_BEFORE
        try:
            clips = await asyncio.to_thread(
                self._store.library, state.workspace, card_names(card), since, now
            )
        except Exception as error:
            logger.warning("footage library read failed error=%s", type(error).__name__)
            return
        known = {c.url for c in await asyncio.to_thread(self._store.candidates, workflow)}
        chosen = [
            clip
            for clip in clips
            # Spec 10.7: only clips kept as another event come back; the incident and rows
            # stored before 0035 (`unknown`) stay out.
            if clip.url not in known
            and clip.relation == "related"
            and same_event(card, clip.event, clip.names)
        ][:MAX_FOOTAGE]
        if not chosen:
            return
        # Never the main post as its own footage: by its address, then by its pictures.
        identity = MainIdentity.of(
            str(main.source.canonical_url),
            [str(inputs.report.source.canonical_url)],
            main.post.text,
        )
        itself = {
            clip.url
            for clip in chosen
            if same_as_main(identity, clip.url.partition(SECTION_MARK)[0], "")
        }
        main_hashes = await self._main_hashes(main, root)
        await asyncio.to_thread(
            self._store.add_candidates,
            workflow,
            [
                NewCandidate(
                    url=clip.url,
                    platform=clip.platform,
                    source=LIBRARY,
                    query=LIBRARY,
                    visual=(card.event or DEFAULT_VISUAL)[:300],
                    owner_handle=clip.owner_handle,
                    caption=clip.event[:2000],
                    published_at=clip.published_at,
                    source_duration=(
                        clip.section_end - clip.section_start if clip.section_end else None
                    ),
                    said=list(clip.said),
                )
                for clip in chosen
            ],
        )
        reused = 0
        await self._main_recording(main, root, state)
        rows = {c.url: c for c in await asyncio.to_thread(self._store.candidates, workflow)}
        for clip in chosen:
            if clip.url in itself:
                await asyncio.to_thread(self._store.reject, workflow, clip.url, "main")
                continue
            name = hashlib.sha256(clip.url.encode()).hexdigest()[:20] + ".mp4"
            location = PurePosixPath("reports") / workflow / "footage" / name
            path = root / location
            try:
                await self._ports.library_media(clip.media_location, path)
                duration = await self._ports.probe.duration(path)
            except Exception as error:
                logger.warning("footage library copy failed error=%s", type(error).__name__)
                state.media_causes["library_copy"] += 1  # spec 10.8
                path.unlink(missing_ok=True)
                await asyncio.to_thread(self._store.reject, workflow, clip.url, "media_failed")
                continue
            if main_hashes and is_duplicate(clip.hashes, [main_hashes]):
                path.unlink(missing_ok=True)
                await asyncio.to_thread(self._store.reject, workflow, clip.url, "duplicate")
                continue
            # Spec 10.12: a library clip is checked like any candidate for the subject's face,
            # except on a commentary card, whose clips show the discussed events (2026-11-26).
            face = state.subject is not None and card.main_kind != "commentary"
            if face and not await self._shows_subject(path, state):
                path.unlink(missing_ok=True)
                await asyncio.to_thread(self._store.reject, workflow, clip.url, "subject_absent")
                continue
            # Copies kept in the library come back once (spec 9.4, item 65).
            evidence = await self._evidence(rows[clip.url], path, state)
            losers: list[_Recording] | None = []
            if evidence is not None:
                losers = (
                    None
                    if evidence.copies_main
                    else await self._losers(
                        evidence.features, evidence.facts, evidence.source, state
                    )
                )
            if losers is None:
                path.unlink(missing_ok=True)
                await asyncio.to_thread(self._store.reject, workflow, clip.url, "duplicate")
                continue
            admitted = AdmittedClip(
                kind="footage",
                shows_object="yes",
                description=clip.event[:500],
                media_location=location.as_posix(),
                media_checksum=_sha256(path),
                media_bytes=path.stat().st_size,
                clip_duration=duration,
                clip_start=clip.section_start,
                ocr=clip.ocr,
                position=next(state.positions),
                relation=clip.relation,
            )
            await asyncio.to_thread(self._store.admit, workflow, clip.url, admitted)
            await self._settle(
                workflow, rows[clip.url], evidence, losers, list(clip.hashes), [], state
            )
            reused += 1
        reused -= len(state.displaced)
        state.displaced.clear()  # the checks count admitted clips from the store
        logger.info("footage library reused=%d of=%d", reused, len(chosen))

    @staticmethod
    def _media_failed(candidate: CandidateView, cause: str, state: _Build) -> None:
        """A media failure's cause, never its URL (spec 10.8)."""
        logger.warning("footage media failed platform=%s cause=%s", candidate.platform, cause)
        state.media_causes[cause] += 1

    async def _reject(
        self,
        workflow: str,
        root: Path,
        candidate: CandidateView,
        location: PurePosixPath,
        owned: bool,
        reason: str,
        state: _Build,
        **seen: str,
    ) -> bool:
        state.steps[candidate.url] = "store"
        if candidate.url in state.closed:  # abandoned: its media_failed is recorded
            return False
        if owned:  # a carousel slide is the acquisition's file, never deleted here
            (root / location).unlink(missing_ok=True)
        await asyncio.to_thread(self._store.reject, workflow, candidate.url, reason, **seen)
        return False

    async def _verify_admitted(
        self, workflow: str, root: Path, state: _Build | None = None
    ) -> list[list[int]]:
        # A photo or page card an earlier attempt kept but cannot be found again is dropped:
        # its ephemeral link is gone, so it can never be fetched again (spec 5c-2).
        for photo in await asyncio.to_thread(self._store.admitted, workflow, "image"):
            path = root / (photo.media_location or "")
            if not path.is_file() or _sha256(path) != photo.media_checksum:
                await asyncio.to_thread(self._store.reject, workflow, photo.url, "media_failed")
        run = await asyncio.to_thread(self._store.run, workflow)
        page = run.profile_page if run is not None else None
        if page is not None and not (root / str(page["location"])).is_file():
            await asyncio.to_thread(self._store.set_profile_page, workflow, None)
        hashes: list[list[int]] = []
        for candidate in await asyncio.to_thread(self._store.admitted, workflow):
            path = root / (candidate.media_location or "")
            if not path.is_file() or _sha256(path) != candidate.media_checksum:
                await asyncio.to_thread(self._store.reopen, workflow, candidate.url)
                continue
            # The frames admission hashed: after the stored OCR's trim (spec F7 step 4).
            trim = float((candidate.ocr or {}).get("trim_start") or 0.0)
            hashes.append(await self._hashes(path, trim, candidate.clip_duration or 0.0))
            if state is not None and self._copy_check and candidate.url not in state.recordings:
                await self._record(candidate, path, hashes[-1], state)
            if state is not None:
                self._recount(candidate, hashes[-1], state)
        return hashes

    def _recount(self, candidate: CandidateView, hashes: list[int], state: _Build) -> None:
        """A clip an earlier attempt kept holds its cap again on a retry (final review, 2)."""
        if candidate.relation == "discusses":
            state.discussing.add(candidate.url)
        if candidate.relation == "same_event":
            state.same_event = state.recordings.get(candidate.url) or _Recording(
                candidate.url,
                candidate.url.partition(SECTION_MARK)[0],
                quota_key(candidate),
                [],
                CopyFacts(
                    candidate.url,
                    self._original(candidate, state),
                    0.0,
                    candidate.published_at,
                ),
                hashes,
            )
        if self._old(candidate, state):
            state.old.add(candidate.url)

    def _old(self, candidate: CandidateView, state: _Build) -> bool:
        """Older than 30 days on a card's run: the object path keeps its own window and no cap
        (spec 10.12, revision 5)."""
        return state.card is not None and not in_window(
            candidate.published_at, state.main_published, self._clock()
        )

    async def _record(
        self, candidate: CandidateView, path: Path, hashes: list[int], state: _Build
    ) -> None:
        """A clip kept before this check (a retry, a library reuse) joins the copy check."""
        frames, features = await self._recording(path)
        state.recordings[candidate.url] = _Recording(
            candidate.url,
            candidate.url.partition(SECTION_MARK)[0],
            quota_key(candidate),
            features,
            await self._copy_facts(candidate, frames, state),
            hashes,
        )

    async def _reference(self, main: SourceReport, root: Path) -> Frame | None:
        """The main's middle frame, or None when it cannot be read."""
        videos = [media for media in main.media if media.kind == "video"]
        path = root / videos[0].location if videos else None
        if path is None or not path.is_file():
            return None
        try:
            duration = videos[0].duration_seconds or await self._ports.probe.duration(path)
            return await self._ports.frames.frame_at(path, duration / 2, width=VISION_WIDTH)
        except (FrameError, DurationError):
            return None

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
        return await self._hashes(path, 0.0, duration)

    async def _hashes(self, path: Path, start: float, duration: float) -> list[int]:
        try:
            frames = [
                await self._ports.frames.frame_at(path, second, width=VISION_WIDTH)
                for second in vision_seconds(start, duration)
            ]
        except FrameError:
            return []
        return [dhash(frame.jpeg) for frame in frames]

    async def _result(
        self, workflow: str, status: str, media_causes: Counter[str] | None = None
    ) -> FootageResult:
        candidates = await asyncio.to_thread(self._store.candidates, workflow)
        reasons = Counter(c.reason for c in candidates if c.reason)
        admitted = sum(1 for c in candidates if c.status == "admitted" and c.media_kind == "video")
        photos = sum(1 for c in candidates if c.status == "admitted" and c.media_kind == "image")
        await progress.step("footage.keep_clips", params={"count": admitted})
        logger.info(
            "footage finished status=%s admitted=%d photos=%d rejected=%s media_causes=%s",
            status,
            admitted,
            photos,
            dict(reasons),
            dict(media_causes or {}),
        )
        return FootageResult(
            status=status,  # type: ignore[arg-type]
            admitted=admitted,
            rejected=dict(reasons),
            photos=photos,
        )

    @staticmethod
    def _clean_parts(root: Path, workflow: str) -> None:
        """What a killed worker leaves: `.part` files and the downloader's scratch folders."""
        folder = root / "reports" / workflow / "footage"
        for part in folder.glob("*.part"):
            part.unlink(missing_ok=True)
        for scratch in folder.glob(SCRATCH_GLOB):
            if scratch.is_dir():
                shutil.rmtree(scratch, ignore_errors=True)
