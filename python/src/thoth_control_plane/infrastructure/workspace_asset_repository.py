"""A workspace's asset library in PostgreSQL (spec 2026-11-13).

SQLAlchemy ORM on the shared editor pool; async callers reach the synchronous session through
`asyncio.to_thread`. Every read and write names the workspace, so one workspace never reaches
another's items.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from thoth_control_plane.domain.workspace_assets import (
    LibraryKind,
    WorkspaceAsset,
    WorkspaceAssetRecord,
)
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import WorkspaceAssetRow

T = TypeVar("T")


def _asset(row: WorkspaceAssetRow) -> WorkspaceAsset:
    return WorkspaceAsset(
        asset_id=row.asset_id,
        workspace_id=row.workspace_id,
        kind=row.kind,  # type: ignore[arg-type]
        name=row.name,
        labels=row.labels or {},
        media_type=row.media_type,
        checksum=row.checksum,
        duration_seconds=row.duration_seconds,
        width=row.width,
        height=row.height,
        has_audio=row.has_audio,
        created_at=row.created_at,
    )


def _record(row: WorkspaceAssetRow) -> WorkspaceAssetRecord:
    return WorkspaceAssetRecord(asset=_asset(row), location=row.location)


class PostgresWorkspaceAssetRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(self, work: Callable[[Session], T]) -> T:
        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        return await asyncio.to_thread(unit)

    async def list(self, workspace_id: str) -> list[WorkspaceAsset]:
        def work(session: Session) -> list[WorkspaceAsset]:
            rows = session.scalars(
                select(WorkspaceAssetRow)
                .where(WorkspaceAssetRow.workspace_id == workspace_id)
                .order_by(WorkspaceAssetRow.created_at.desc(), WorkspaceAssetRow.asset_id)
            )
            return [_asset(row) for row in rows]

        return await self._run(work)

    async def get(self, workspace_id: str, asset_id: str) -> WorkspaceAssetRecord | None:
        def work(session: Session) -> WorkspaceAssetRecord | None:
            row = session.get(WorkspaceAssetRow, (workspace_id, asset_id))
            return None if row is None else _record(row)

        return await self._run(work)

    async def add(self, record: WorkspaceAssetRecord) -> WorkspaceAssetRecord:
        """Store one item; the same file already in this workspace is returned instead."""
        asset = record.asset

        def work(session: Session) -> WorkspaceAssetRecord:
            # Parallel uploads of one file race here: the key decides, and the loser reads the
            # winner's row (READ COMMITTED gives this statement a fresh snapshot).
            session.execute(
                insert(WorkspaceAssetRow)
                .values(
                    workspace_id=asset.workspace_id,
                    asset_id=asset.asset_id,
                    kind=asset.kind,
                    name=asset.name,
                    labels=asset.labels,
                    media_type=asset.media_type,
                    location=record.location,
                    checksum=asset.checksum,
                    duration_seconds=asset.duration_seconds,
                    width=asset.width,
                    height=asset.height,
                    has_audio=asset.has_audio,
                    created_at=asset.created_at,
                )
                .on_conflict_do_nothing(index_elements=["workspace_id", "checksum"])
            )
            row = session.scalars(
                select(WorkspaceAssetRow).where(
                    WorkspaceAssetRow.workspace_id == asset.workspace_id,
                    WorkspaceAssetRow.checksum == asset.checksum,
                )
            ).one()
            return _record(row)

        return await self._run(work)

    async def update(
        self,
        workspace_id: str,
        asset_id: str,
        *,
        name: str | None,
        labels: dict[str, object] | None,
        kind: LibraryKind | None,
    ) -> WorkspaceAsset | None:
        def work(session: Session) -> WorkspaceAsset | None:
            row = session.get(WorkspaceAssetRow, (workspace_id, asset_id), with_for_update=True)
            if row is None:
                return None
            if name is not None:
                row.name = name
            if labels is not None:
                row.labels = labels
            if kind is not None:
                row.kind = kind
            session.flush()
            return _asset(row)

        return await self._run(work)

    async def delete(self, workspace_id: str, asset_id: str) -> str | None:
        def work(session: Session) -> str | None:
            row = session.get(WorkspaceAssetRow, (workspace_id, asset_id), with_for_update=True)
            if row is None:
                return None
            location = row.location
            session.delete(row)
            return location

        return await self._run(work)
