"""Workflow reports in PostgreSQL (editor migration 0011): their single source of truth.

Synchronous like the footage store; callers wrap calls in `asyncio.to_thread` (`read_report`
does it for reads). A database error is `ReportStoreUnavailable`, never an absent report.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from thoth_control_plane.infrastructure.report_models import WorkflowReportRow

if TYPE_CHECKING:
    from thoth_control_plane.config import Settings

REPORT_KINDS = frozenset(
    {"source_report", "original_source_report", "source_attribution", "content_set"}
)
#: `reports/<id>/<name>.json` or `legacy-scout/<id>/<name>.json`, one safe segment each.
_LOCATION = re.compile(
    r"^(reports|legacy-scout)/([A-Za-z][A-Za-z0-9_-]{0,127})/[a-z][a-z-]*\.json$"
)

M = TypeVar("M", bound=BaseModel)


class ReportInvalid(ValueError):
    """The location, kind, or content cannot be a stored report."""


class ReportStoreUnavailable(RuntimeError):
    """The database could not be reached or refused the statement."""


class Reports(Protocol):
    def put(self, location: str, kind: str, content: bytes) -> None: ...

    def get(self, location: str) -> bytes | None: ...


def _checked(location: str, kind: str, content: bytes) -> tuple[str, str]:
    """Return (folder id, text) or raise `ReportInvalid`."""
    match = _LOCATION.fullmatch(location)
    if match is None or kind not in REPORT_KINDS:
        raise ReportInvalid("report_location_or_kind_invalid")
    try:
        text = content.decode("utf-8")
        json.loads(text)
    except (UnicodeDecodeError, ValueError) as error:
        raise ReportInvalid("report_content_invalid") from error
    return match.group(2), text


class ReportStore:
    def __init__(
        self, engine: Engine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._clock = clock

    @classmethod
    def connect(cls, database_url: str) -> ReportStore:
        url = make_url(database_url).set(drivername="postgresql+psycopg")
        return cls(create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2))

    def put(self, location: str, kind: str, content: bytes) -> None:
        """Store or replace one report (a Temporal retry rewrites the same row)."""
        folder, text = _checked(location, kind, content)
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                row = session.get(WorkflowReportRow, location)
                if row is None:
                    session.add(self._row(location, folder, kind, text, content, now))
                    return
                row.kind = kind
                row.content = text
                row.sha256 = sha256(content).hexdigest()
                row.size_bytes = len(content)
                row.updated_at = now
        except SQLAlchemyError as error:
            raise ReportStoreUnavailable("report_store_unavailable") from error

    def get(self, location: str) -> bytes | None:
        try:
            with self._sessions() as session:
                row = session.get(WorkflowReportRow, location)
        except SQLAlchemyError as error:
            raise ReportStoreUnavailable("report_store_unavailable") from error
        return None if row is None else row.content.encode("utf-8")

    def insert_missing(self, location: str, kind: str, content: bytes) -> bool:
        """Import only: insert when absent, never overwrite. True when it inserted."""
        folder, text = _checked(location, kind, content)
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                if session.get(WorkflowReportRow, location) is not None:
                    return False
                session.add(self._row(location, folder, kind, text, content, now))
                return True
        except SQLAlchemyError as error:
            raise ReportStoreUnavailable("report_store_unavailable") from error

    @staticmethod
    def _row(
        location: str, folder: str, kind: str, text: str, content: bytes, now: datetime
    ) -> WorkflowReportRow:
        return WorkflowReportRow(
            location=location,
            workflow_id=folder,
            kind=kind,
            content=text,
            sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            created_at=now,
            updated_at=now,
        )


async def read_report(reports: Reports, location: str, model: type[M]) -> M | None:
    """The report, or None when it is absent or no longer matches `model`.

    `ReportStoreUnavailable` propagates: a database outage is not a missing report.
    """
    raw = await asyncio.to_thread(reports.get, location)
    if raw is None:
        return None
    try:
        return model.model_validate_json(raw)
    except ValidationError:
        return None


def connect_reports(settings: Settings) -> ReportStore:
    """The production store; the editor database is required (spec 2026-10-16)."""
    from thoth_control_plane.config import SettingsValidationError

    if settings.THOTH_EDITOR_DATABASE_URL is None:
        raise SettingsValidationError("editor_database_missing")
    return ReportStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
