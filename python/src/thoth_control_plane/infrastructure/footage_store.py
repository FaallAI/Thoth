"""Footage state per workflow and a 24-hour search cache (editor migration 0010).

Synchronous like the source-account store; callers wrap calls in `asyncio.to_thread`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.models import (
    REJECT_REASONS,
    AdmittedClip,
    CandidateView,
    FootageObject,
    NewCandidate,
    RunView,
)
from thoth_control_plane.infrastructure.footage_models import (
    FootageCandidateRow,
    FootageRunRow,
    FootageSearchRow,
)

SEARCH_KEPT = timedelta(hours=24)


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _view(row: FootageCandidateRow) -> CandidateView:
    return CandidateView(
        url=row.url,
        platform=row.platform,
        source=row.source,
        query=row.query,
        visual=row.visual,
        owner_handle=row.owner_handle,
        caption=row.caption,
        published_at=row.published_at,
        engagement=dict(row.engagement or {}),
        source_duration=row.source_duration,
        status=row.status,
        reason=row.reason,
        story_score=row.story_score,
        kind=row.kind,
        shows_object=row.shows_object,
        description=row.description,
        media_location=row.media_location,
        media_checksum=row.media_checksum,
        media_bytes=row.media_bytes,
        clip_duration=row.clip_duration,
        clip_start=row.clip_start,
        ocr=row.ocr,
        position=row.position,
    )


def _run_view(row: FootageRunRow) -> RunView:
    return RunView(
        workflow_id=row.workflow_id,
        status=row.status,
        footage_status=row.footage_status,
        objects=[FootageObject.model_validate(item) for item in row.objects],
    )


class FootageStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> FootageStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2))

    # Search cache

    def cached_search(self, platform: str, query: str) -> list[DiscoveredVideo] | None:
        with self._sessions() as session:
            row = session.scalar(
                select(FootageSearchRow).where(
                    FootageSearchRow.platform == platform,
                    FootageSearchRow.query == normalize_query(query),
                    FootageSearchRow.expires_at > self._clock(),
                )
            )
            if row is None:
                return None
            return [DiscoveredVideo.model_validate(item) for item in row.results]

    def save_search(self, platform: str, query: str, videos: Sequence[DiscoveredVideo]) -> None:
        now = self._clock()
        key = normalize_query(query)
        with self._sessions.begin() as session:
            session.execute(delete(FootageSearchRow).where(FootageSearchRow.expires_at <= now))
            session.execute(
                delete(FootageSearchRow).where(
                    FootageSearchRow.platform == platform, FootageSearchRow.query == key
                )
            )
            session.add(
                FootageSearchRow(
                    platform=platform,
                    query=key,
                    results=[video.model_dump(mode="json") for video in videos],
                    fetched_at=now,
                    expires_at=now + SEARCH_KEPT,
                )
            )

    # Runs

    def run(self, workflow_id: str) -> RunView | None:
        with self._sessions() as session:
            row = session.get(FootageRunRow, workflow_id)
            return None if row is None else _run_view(row)

    def start_run(self, workflow_id: str, objects: Sequence[FootageObject]) -> RunView:
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                row = FootageRunRow(
                    workflow_id=workflow_id,
                    status="running",
                    objects=[item.model_dump() for item in objects],
                    started_at=self._clock(),
                )
                session.add(row)
            return _run_view(row)

    def finish_run(self, workflow_id: str, footage_status: str) -> None:
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                raise ValueError("no footage run for this workflow")
            row.status = "done"
            row.footage_status = footage_status
            row.finished_at = self._clock()

    # Candidates

    def candidates(self, workflow_id: str) -> list[CandidateView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(FootageCandidateRow)
                .where(FootageCandidateRow.workflow_id == workflow_id)
                .order_by(FootageCandidateRow.created_at, FootageCandidateRow.url)
            )
            return [_view(row) for row in rows]

    def add_candidates(self, workflow_id: str, items: Sequence[NewCandidate]) -> None:
        now = self._clock()
        with self._sessions.begin() as session:
            if session.get(FootageRunRow, workflow_id) is None:
                raise ValueError("no footage run for this workflow")
            known = set(
                session.scalars(
                    select(FootageCandidateRow.url).where(
                        FootageCandidateRow.workflow_id == workflow_id
                    )
                )
            )
            for item in items:
                if item.url in known:
                    continue
                if item.reason is not None and item.reason not in REJECT_REASONS:
                    raise ValueError(f"unknown footage reason {item.reason}")
                known.add(item.url)
                session.add(
                    FootageCandidateRow(
                        workflow_id=workflow_id,
                        url=item.url,
                        platform=item.platform,
                        source=item.source,
                        query=item.query,
                        visual=item.visual,
                        owner_handle=item.owner_handle,
                        caption=item.caption,
                        published_at=item.published_at,
                        engagement=dict(item.engagement),
                        source_duration=item.source_duration,
                        status=item.status,
                        reason=item.reason,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def score(self, workflow_id: str, url: str, story_score: float) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.story_score = story_score
            row.updated_at = self._clock()

    def reject(
        self,
        workflow_id: str,
        url: str,
        reason: str,
        *,
        story_score: float | None = None,
        kind: str | None = None,
        shows_object: str | None = None,
        description: str | None = None,
    ) -> None:
        if reason not in REJECT_REASONS:
            raise ValueError(f"unknown footage reason {reason}")
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "rejected"
            row.reason = reason
            if story_score is not None:
                row.story_score = story_score
            row.kind = kind
            row.shows_object = shows_object
            row.description = description
            row.updated_at = self._clock()

    def admit(self, workflow_id: str, url: str, clip: AdmittedClip) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "admitted"
            row.reason = None
            row.kind = clip.kind
            row.shows_object = clip.shows_object
            row.description = clip.description
            row.media_location = clip.media_location
            row.media_checksum = clip.media_checksum
            row.media_bytes = clip.media_bytes
            row.clip_duration = clip.clip_duration
            row.clip_start = clip.clip_start
            row.ocr = clip.ocr
            row.position = clip.position
            row.updated_at = self._clock()

    def reopen(self, workflow_id: str, url: str) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "pending"
            row.reason = None
            row.media_location = row.media_checksum = None
            row.media_bytes = None
            row.clip_duration = row.clip_start = None
            row.ocr = None
            row.position = None
            row.updated_at = self._clock()

    def admitted(self, workflow_id: str) -> list[CandidateView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(FootageCandidateRow)
                .where(
                    FootageCandidateRow.workflow_id == workflow_id,
                    FootageCandidateRow.status == "admitted",
                )
                .order_by(FootageCandidateRow.position)
            )
            return [_view(row) for row in rows]

    @staticmethod
    def _row(session: Session, workflow_id: str, url: str) -> FootageCandidateRow:
        row = session.scalar(
            select(FootageCandidateRow).where(
                FootageCandidateRow.workflow_id == workflow_id, FootageCandidateRow.url == url
            )
        )
        if row is None:
            raise ValueError("no such footage candidate")
        return row
