"""Style templates: built-in ones from code, a workspace's own from PostgreSQL (spec 2026-11-10).

SQLAlchemy ORM on the shared editor pool; async callers reach the synchronous session through
`asyncio.to_thread`. A workspace sees the built-in templates and the latest revision of its own.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from thoth_control_plane.domain.style_templates import BUILT_IN_STYLES, StyleTemplate
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import StyleTemplateRow


def _find(styles: list[StyleTemplate], template_id: str) -> StyleTemplate | None:
    return next((style for style in styles if style.template_id == template_id), None)


def _latest(rows: list[StyleTemplateRow]) -> list[StyleTemplate]:
    latest: dict[str, StyleTemplateRow] = {}
    for row in rows:
        if row.template_id not in latest or row.revision > latest[row.template_id].revision:
            latest[row.template_id] = row
    return [StyleTemplate.model_validate(row.body) for row in latest.values()]


class PostgresStyleTemplateRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def _own(self, workspace_id: str) -> list[StyleTemplate]:
        with editor_sessions(self._database_url).begin() as session:
            rows = session.scalars(
                select(StyleTemplateRow).where(StyleTemplateRow.workspace_id == workspace_id)
            ).all()
            return sorted(_latest(list(rows)), key=lambda style: style.template_id)

    async def list_for(self, workspace_id: str) -> list[StyleTemplate]:
        own = await asyncio.to_thread(self._own, workspace_id)
        return [*BUILT_IN_STYLES.values(), *own]

    async def get(self, template_id: str, workspace_id: str) -> StyleTemplate | None:
        return next(
            (
                style
                for style in await self.list_for(workspace_id)
                if style.template_id == template_id
            ),
            None,
        )


class MemoryStyleTemplateRepository:
    """The same reads over in-memory templates, for tests and installs without a database."""

    def __init__(self, own: dict[str, list[StyleTemplate]] | None = None) -> None:
        self._own = own or {}

    async def list_for(self, workspace_id: str) -> list[StyleTemplate]:
        return [*BUILT_IN_STYLES.values(), *self._own.get(workspace_id, [])]

    async def get(self, template_id: str, workspace_id: str) -> StyleTemplate | None:
        return next(
            (
                style
                for style in await self.list_for(workspace_id)
                if style.template_id == template_id
            ),
            None,
        )
