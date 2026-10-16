"""The report store on in-memory SQLite (the footage store's test pattern)."""

from __future__ import annotations

import asyncio
from hashlib import sha256

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from thoth_control_plane.infrastructure.report_models import WorkflowReportRow
from thoth_control_plane.infrastructure.report_store import (
    ReportInvalid,
    ReportStore,
    ReportStoreUnavailable,
    read_report,
)

LOCATION = "reports/wf_test/source-report.json"
CONTENT = b'{\n  "schema_version": 3,\n  "caption": "a\u0000b"\n}'


class Doc(BaseModel):
    schema_version: int


def test_put_then_get_returns_the_exact_bytes(report_store: ReportStore) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    assert report_store.get(LOCATION) == CONTENT


def test_a_row_records_checksum_size_kind_and_folder(report_store: ReportStore) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    with report_store._sessions() as session:
        row = session.scalar(select(WorkflowReportRow))
    assert row is not None
    assert row.workflow_id == "wf_test"
    assert row.kind == "source_report"
    assert row.sha256 == sha256(CONTENT).hexdigest()
    assert row.size_bytes == len(CONTENT)


def test_a_second_put_replaces_the_row(report_store: ReportStore) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    report_store.put(LOCATION, "source_report", b'{"schema_version": 4}')
    assert report_store.get(LOCATION) == b'{"schema_version": 4}'


def test_an_absent_location_is_none(report_store: ReportStore) -> None:
    assert report_store.get("reports/wf_none/source-report.json") is None


def test_insert_missing_never_overwrites(report_store: ReportStore) -> None:
    assert report_store.insert_missing(LOCATION, "source_report", CONTENT) is True
    assert report_store.insert_missing(LOCATION, "source_report", b'{"x": 1}') is False
    assert report_store.get(LOCATION) == CONTENT


@pytest.mark.parametrize(
    ("location", "kind", "content"),
    [
        (LOCATION, "source_report", b"not json"),
        (LOCATION, "source_report", b"\xff\xfe"),
        (LOCATION, "source_report", b'{"x": NaN}'),
        (LOCATION, "source_report", b'{"x": Infinity}'),
        (LOCATION, "source_report", b'{"x": -Infinity}'),
        (LOCATION, "source_report", b'{"x": "\\ud800"}'),
        (LOCATION, "source_report", b'{"\\udc00": 1}'),
        (LOCATION, "media", CONTENT),
        ("/etc/passwd", "source_report", CONTENT),
        ("reports/../x/source-report.json", "source_report", CONTENT),
        ("reports/wf_test/clip.mp4", "source_report", CONTENT),
    ],
)
def test_invalid_input_is_refused(
    report_store: ReportStore, location: str, kind: str, content: bytes
) -> None:
    with pytest.raises(ReportInvalid):
        report_store.put(location, kind, content)


def test_a_database_error_is_unavailable_never_none() -> None:
    from sqlalchemy import create_engine

    broken = ReportStore(create_engine("sqlite:////nonexistent/dir/db.sqlite"))
    with pytest.raises(ReportStoreUnavailable):
        broken.get(LOCATION)
    with pytest.raises(ReportStoreUnavailable):
        broken.put(LOCATION, "source_report", CONTENT)


def test_read_report_validates_and_treats_a_bad_document_as_absent(
    report_store: ReportStore,
) -> None:
    report_store.put(LOCATION, "source_report", CONTENT)
    report_store.put("reports/wf_bad/source-report.json", "source_report", b'{"x": 1}')
    assert asyncio.run(read_report(report_store, LOCATION, Doc)) == Doc(schema_version=3)
    assert asyncio.run(read_report(report_store, "reports/wf_bad/source-report.json", Doc)) is None
    assert asyncio.run(read_report(report_store, "reports/wf_no/source-report.json", Doc)) is None
