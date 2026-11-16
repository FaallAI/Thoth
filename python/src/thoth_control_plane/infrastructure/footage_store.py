"""Footage state per workflow and a 24-hour search cache (editor migration 0010).

Synchronous like the source-account store; callers wrap calls in `asyncio.to_thread`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.frames import is_duplicate
from thoth_control_plane.footage.models import (
    REJECT_REASONS,
    AdmittedClip,
    CandidateView,
    FootageObject,
    LibraryClip,
    NewCandidate,
    RunView,
)
from thoth_control_plane.infrastructure.footage_models import (
    FootageCandidateRow,
    FootageLibraryRow,
    FootageRunRow,
    FootageSearchRow,
)

SEARCH_KEPT = timedelta(hours=24)


def normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _text(value: str | None) -> str | None:
    """PostgreSQL TEXT refuses NUL, so scraped text loses it before it is stored."""
    return None if value is None else value.replace("\x00", "")


def _said(value: object) -> list[dict[str, Any]]:
    """Stored `said`, or [] for anything that is not a list of objects (spec 9.5)."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _view(row: FootageCandidateRow) -> CandidateView:
    return CandidateView(
        url=row.url,
        platform=row.platform,
        source=row.source,
        media_kind=row.media_kind,
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
        said=_said(row.said),
        relation=row.relation or "unknown",
    )


def _run_view(row: FootageRunRow) -> RunView:
    return RunView(
        workflow_id=row.workflow_id,
        status=row.status,
        footage_status=row.footage_status,
        objects=[FootageObject.model_validate(item) for item in row.objects],
        profile_page=row.profile_page,
        context=row.context,
    )


LIBRARY_LOOKUP = 12


def _parsed(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _library_clip(row: FootageLibraryRow) -> LibraryClip:
    return LibraryClip(
        url=row.url,
        platform=row.platform,
        owner_handle=row.owner_handle,
        published_at=row.published_at,
        section_start=row.section_start,
        section_end=row.section_end,
        media_location=row.media_location,
        media_checksum=row.media_checksum,
        hashes=list(row.hashes or []),
        names=list(row.names or []),
        event=row.event,
        ocr=dict(row.ocr or {}),
        said=_said(row.said),
        relation=row.relation or "unknown",
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
                    # jsonb refuses a NUL escape as well
                    results=json.loads(
                        json.dumps([video.model_dump(mode="json") for video in videos]).replace(
                            "\\u0000", ""
                        )
                    ),
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

    def set_profile_page(self, workflow_id: str, card: dict[str, object] | None) -> None:
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                raise ValueError("no footage run for this workflow")
            row.profile_page = card

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
                if item.status not in ("pending", "rejected"):
                    raise ValueError(f"cannot add a candidate as {item.status}")
                if (item.status == "rejected") != (item.reason is not None):
                    raise ValueError("a candidate has a reason exactly when it is rejected")
                if item.reason is not None and item.reason not in REJECT_REASONS:
                    raise ValueError(f"unknown footage reason {item.reason}")
                known.add(item.url)
                session.add(
                    FootageCandidateRow(
                        workflow_id=workflow_id,
                        url=item.url,
                        platform=item.platform,
                        source=item.source,
                        media_kind=item.media_kind,
                        query=_text(item.query),
                        visual=_text(item.visual),
                        owner_handle=_text(item.owner_handle),
                        caption=_text(item.caption),
                        published_at=item.published_at,
                        engagement=dict(item.engagement),
                        source_duration=item.source_duration,
                        status=item.status,
                        reason=item.reason,
                        said=list(item.said),
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
            row.description = _text(description)
            row.updated_at = self._clock()

    def admit(self, workflow_id: str, url: str, clip: AdmittedClip) -> None:
        with self._sessions.begin() as session:
            row = self._row(session, workflow_id, url)
            row.status = "admitted"
            row.reason = None
            row.kind = clip.kind
            row.shows_object = clip.shows_object
            row.description = _text(clip.description)
            row.media_location = clip.media_location
            row.media_checksum = clip.media_checksum
            row.media_bytes = clip.media_bytes
            row.clip_duration = clip.clip_duration
            row.clip_start = clip.clip_start
            row.ocr = clip.ocr
            row.position = clip.position
            row.relation = clip.relation
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
            row.relation = "unknown"
            row.updated_at = self._clock()

    def admitted(self, workflow_id: str, media_kind: str = "video") -> list[CandidateView]:
        with self._sessions() as session:
            rows = session.scalars(
                select(FootageCandidateRow)
                .where(
                    FootageCandidateRow.workflow_id == workflow_id,
                    FootageCandidateRow.status == "admitted",
                    FootageCandidateRow.media_kind == media_kind,
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

    # Footage library (spec 2026-11-15): the run's context card and the per-workspace library.

    def set_context(self, workflow_id: str, context: dict[str, object] | None) -> None:
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                raise ValueError("no footage run for this workflow")
            row.context = context

    def add_objects(self, workflow_id: str, objects: Sequence[FootageObject]) -> None:
        """Round two's queries join the run's objects, so a retry searches them too."""
        with self._sessions.begin() as session:
            row = session.get(FootageRunRow, workflow_id)
            if row is None:
                raise ValueError("no footage run for this workflow")
            known = {item["query"] for item in row.objects}
            row.objects = [
                *row.objects,
                *(item.model_dump() for item in objects if item.query not in known),
            ]

    def workspace_of(self, workflow_id: str) -> str | None:
        from thoth_control_plane.infrastructure.run_models import ProjectRow, WorkflowRunRow

        with self._sessions() as session:
            return session.scalar(
                select(ProjectRow.workspace_id)
                .join(WorkflowRunRow, WorkflowRunRow.project_id == ProjectRow.project_id)
                .where(WorkflowRunRow.workflow_id == workflow_id)
            )

    def add_library(self, workspace_id: str, workflow_id: str, clip: LibraryClip) -> None:
        """Keep a clip; a copy of a kept clip (same pictures) merges into it, and the earlier
        published one stays the source with its credit."""
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(FootageLibraryRow).where(FootageLibraryRow.workspace_id == workspace_id)
            ).all()
            same = next(
                (r for r in rows if r.url == clip.url and r.section_start == clip.section_start),
                None,
            ) or next((r for r in rows if is_duplicate(clip.hashes, [r.hashes or []])), None)
            if same is None:
                session.add(
                    FootageLibraryRow(
                        id=uuid.uuid4().hex,
                        workspace_id=workspace_id,
                        first_workflow_id=workflow_id,
                        created_at=self._clock(),
                        **self._library_fields(clip),
                    )
                )
                return
            same.names = sorted({*(same.names or []), *clip.names})
            # Spec 10.7: a later run that keeps the clip as another event makes it reusable.
            related = "related" in (same.relation, clip.relation)
            new, old = _parsed(clip.published_at), _parsed(same.published_at)
            if new is not None and (old is None or new < old):
                for name, value in self._library_fields(clip).items():
                    if name != "names":
                        setattr(same, name, value)
            if related:
                same.relation = "related"

    @staticmethod
    def _library_fields(clip: LibraryClip) -> dict[str, object]:
        return {
            "url": clip.url,
            "platform": clip.platform,
            "owner_handle": clip.owner_handle,
            "published_at": clip.published_at,
            "section_start": clip.section_start,
            "section_end": clip.section_end,
            "media_location": clip.media_location,
            "media_checksum": clip.media_checksum,
            "hashes": list(clip.hashes),
            "names": sorted(set(clip.names)),
            "event": clip.event,
            "ocr": dict(clip.ocr),
            "said": list(clip.said),
            "relation": clip.relation,
        }

    def drop_library(self, workspace_id: str, workflow_id: str, url: str) -> None:
        """Forget a clip this run kept and then lost to a cleaner copy (spec 9.4); a row an
        earlier run kept stays."""
        with self._sessions.begin() as session:
            session.execute(
                delete(FootageLibraryRow).where(
                    FootageLibraryRow.workspace_id == workspace_id,
                    FootageLibraryRow.first_workflow_id == workflow_id,
                    FootageLibraryRow.url == url,
                )
            )

    def library(
        self, workspace_id: str, names: Sequence[str], since: datetime, until: datetime
    ) -> list[LibraryClip]:
        """The workspace's clips sharing a name, published in the window or at an unknown
        time, newest first."""
        # ponytail: filters the workspace's rows in Python; a jsonb `?|` index when it grows.
        wanted = set(names)
        with self._sessions() as session:
            rows = session.scalars(
                select(FootageLibraryRow).where(FootageLibraryRow.workspace_id == workspace_id)
            ).all()
        found = []
        for row in rows:
            when = _parsed(row.published_at)
            if wanted & set(row.names or []) and (when is None or since <= when <= until):
                found.append(row)
        found.sort(key=lambda r: _parsed(r.published_at) or since, reverse=True)
        return [_library_clip(row) for row in found[:LIBRARY_LOOKUP]]
