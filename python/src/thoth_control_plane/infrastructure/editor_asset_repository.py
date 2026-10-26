"""PostgreSQL reads for the validated assets a project may place on its timeline.

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TypeVar

from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session

from thoth_control_plane.application.editor_asset_ports import EditorAssetPersistenceError
from thoth_control_plane.domain.editor_assets import (
    ASSET_PAGE_LIMIT_MAX,
    EditorAsset,
    EditorAssetPage,
    EditorAssetRecord,
)
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import EditorAssetRow

T = TypeVar("T")

#: Public fields. ``artifact_location`` is deliberately absent: a listing must never be
#: able to return a locator.
_PUBLIC_FIELDS = (
    "asset_id",
    "project_id",
    "kind",
    "media_type",
    "duration_in_frames",
    "width",
    "height",
    "fps",
    "has_audio",
    "validation_state",
    "checksum",
)


def _cursor_token(created_at: datetime, asset_id: str) -> str:
    raw = f"{created_at.isoformat()}|{asset_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    created_at_raw, asset_id = raw.split("|", 1)
    return datetime.fromisoformat(created_at_raw), asset_id


def _asset(row: EditorAssetRow) -> EditorAsset:
    return EditorAsset.model_validate({field: getattr(row, field) for field in _PUBLIC_FIELDS})


def _record(row: EditorAssetRow) -> EditorAssetRecord:
    return EditorAssetRecord(
        asset=_asset(row), artifact_location=row.artifact_location, provenance=row.provenance
    )


def _ready(project_id: str) -> Select[tuple[EditorAssetRow]]:
    return select(EditorAssetRow).where(
        EditorAssetRow.project_id == project_id, EditorAssetRow.validation_state == "ready"
    )


class PostgresEditorAssetRepository:
    """Project-scoped reads and one-row registration of validated assets."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(self, work: Callable[[Session], T]) -> T:
        """Run `work(session)` in one transaction; every failure is the same safe error."""

        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        try:
            return await asyncio.to_thread(unit)
        except Exception as error:
            raise EditorAssetPersistenceError() from error

    async def list_ready(
        self, *, project_id: str, limit: int, cursor: str | None
    ) -> EditorAssetPage:
        clamped = max(1, min(int(limit), ASSET_PAGE_LIMIT_MAX))

        def read(session: Session) -> EditorAssetPage:
            query = _ready(project_id)
            if cursor:
                created_at, asset_id = _decode_cursor(cursor)
                query = query.where(
                    tuple_(EditorAssetRow.created_at, EditorAssetRow.asset_id)
                    < tuple_(created_at, asset_id)
                )
            rows = session.scalars(
                query.order_by(
                    EditorAssetRow.created_at.desc(), EditorAssetRow.asset_id.desc()
                ).limit(clamped + 1)
            ).all()
            page = rows[:clamped]
            next_cursor = (
                _cursor_token(page[-1].created_at, page[-1].asset_id)
                if len(rows) > clamped
                else None
            )
            return EditorAssetPage(
                assets=tuple(_asset(row) for row in page), next_cursor=next_cursor
            )

        return await self._run(read)

    async def get_ready_record(self, *, project_id: str, asset_id: str) -> EditorAssetRecord | None:
        def read(session: Session) -> EditorAssetRecord | None:
            row = session.scalar(_ready(project_id).where(EditorAssetRow.asset_id == asset_id))
            return None if row is None else _record(row)

        return await self._run(read)

    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None:
        def read(session: Session) -> EditorAssetRecord | None:
            row = session.scalar(
                _ready(project_id)
                .where(EditorAssetRow.checksum == checksum)
                .order_by(EditorAssetRow.created_at, EditorAssetRow.asset_id)
                .limit(1)
            )
            return None if row is None else _record(row)

        return await self._run(read)

    async def get_ready_records(
        self, *, project_id: str, asset_ids: tuple[str, ...]
    ) -> tuple[EditorAssetRecord, ...]:
        if not asset_ids:
            return ()
        wanted = list(asset_ids[:ASSET_PAGE_LIMIT_MAX])

        def read(session: Session) -> dict[str, EditorAssetRecord]:
            rows = session.scalars(
                _ready(project_id).where(EditorAssetRow.asset_id.in_(wanted)).limit(len(wanted))
            ).all()
            return {row.asset_id: _record(row) for row in rows}

        records = await self._run(read)
        # Answer in the caller's order and stay silent about anything missing:
        # the caller decides what an absent asset means.
        return tuple(records[asset_id] for asset_id in wanted if asset_id in records)

    async def register_ready(self, record: EditorAssetRecord) -> None:
        """Insert one validated upload in a single statement: all of it, or no row."""
        asset = record.asset

        def write(session: Session) -> None:
            session.add(
                EditorAssetRow(
                    project_id=asset.project_id,
                    asset_id=asset.asset_id,
                    kind=asset.kind,
                    media_type=asset.media_type,
                    artifact_location=record.artifact_location,
                    duration_in_frames=asset.duration_in_frames,
                    width=asset.width,
                    height=asset.height,
                    fps=asset.fps,
                    has_audio=asset.has_audio,
                    validation_state=asset.validation_state,
                    checksum=asset.checksum,
                    provenance=record.provenance,
                )
            )

        await self._run(write)

    async def registered_locations(self, locations: Sequence[str]) -> set[str]:
        wanted = list(locations)

        def read(session: Session) -> set[str]:
            return set(
                session.scalars(
                    select(EditorAssetRow.artifact_location).where(
                        EditorAssetRow.artifact_location.in_(wanted)
                    )
                )
            )

        return await self._run(read)
