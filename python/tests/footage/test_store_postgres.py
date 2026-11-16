"""The footage store on PostgreSQL, where the migrations' CHECK constraints apply (footage library
spec 2026-11-15; the SQLite store tests have no CHECKs)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from thoth_control_plane.footage.models import FootageObject, LibraryClip, NewCandidate
from thoth_control_plane.infrastructure.footage_store import FootageStore
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "editor"
DATABASE_URL = os.environ.get("THOTH_TEST_EDITOR_DATABASE_URL", "")
REQUIRED = os.environ.get("THOTH_REQUIRE_POSTGRES_TESTS") == "1"
if REQUIRED and not DATABASE_URL:
    raise RuntimeError("THOTH_REQUIRE_POSTGRES_TESTS=1 but THOTH_TEST_EDITOR_DATABASE_URL is unset")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="needs a disposable Postgres")

PODCAST = "https://www.youtube.com/watch?v=Sy_S4TgvKbY"


@pytest.fixture
def store() -> FootageStore:
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    apply_editor_migrations(DATABASE_URL, MIGRATIONS)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('ws1', 'W')")
    return FootageStore.connect(DATABASE_URL)


def _candidate(url: str, source: str) -> NewCandidate:
    return NewCandidate(
        url=url, platform="youtube", source=source, query="q", visual="v", owner_handle="o"
    )


def test_the_new_sources_and_the_repost_reason_are_stored(store: FootageStore) -> None:
    store.start_run("wf_a", [FootageObject(query="q", visual="v")])
    store.set_context("wf_a", {"people": [{"name": "Mutant"}], "refined": True})
    store.add_candidates(
        "wf_a",
        [
            _candidate(f"{PODCAST}#t=165.4", "section"),
            _candidate(PODCAST, "trace"),
            _candidate("https://www.tiktok.com/@a/video/7700000000000000001", "library"),
            _candidate("https://www.youtube.com/watch?v=hDLHWIonVJc", "search"),
        ],
    )
    store.reject("wf_a", "https://www.youtube.com/watch?v=hDLHWIonVJc", "repost")
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert {c.source for c in rows.values()} == {"section", "trace", "library", "search"}
    assert rows["https://www.youtube.com/watch?v=hDLHWIonVJc"].reason == "repost"
    run = store.run("wf_a")
    assert run is not None and run.context == {"people": [{"name": "Mutant"}], "refined": True}


def test_the_library_round_trips_on_postgres(store: FootageStore) -> None:
    clip = LibraryClip(
        url=f"{PODCAST}#t=165.4",
        platform="youtube",
        owner_handle="curhatbang",
        published_at="2026-11-12T10:00:00Z",
        section_start=164.4,
        section_end=172.4,
        media_location="reports/wf_a/footage/a.mp4",
        media_checksum="sha256:" + "a" * 64,
        hashes=[1, 2, 3, 4],
        names=["mutant", "denny sumargo"],
        event="Mutant ingin diundang podcast Densu",
        ocr={"outcome": "clean"},
    )
    store.add_library("ws1", "wf_a", clip)
    store.add_library("ws1", "wf_b", clip)  # the same clip again merges
    found = store.library(
        "ws1", ["mutant"], datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)
    )
    assert [c.url for c in found] == [clip.url]
    assert found[0].ocr == {"outcome": "clean"} and found[0].hashes == [1, 2, 3, 4]


SAID = [{"text": "bawa pedang", "start_seconds": 292.0, "end_seconds": 296.0}]


def _clip(url: str, said: list[dict[str, object]] | None = None) -> LibraryClip:
    return LibraryClip(
        url=url,
        platform="tiktok",
        owner_handle="jawaposofficial",
        published_at="2026-11-12T10:00:00Z",
        section_start=0.0,
        section_end=None,
        media_location="reports/wf_a/footage/b.mp4",
        media_checksum="sha256:" + "b" * 64,
        hashes=[9, 9, 9],
        names=["mutant"],
        event="e",
        said=said or [],
    )


def test_said_round_trips_on_a_candidate(store: FootageStore) -> None:  # spec 9.5
    store.start_run("wf_a", [FootageObject(query="q", visual="v")])
    row = _candidate(f"{PODCAST}#t=292.0", "section")
    store.add_candidates("wf_a", [NewCandidate(**{**row.__dict__, "said": SAID})])
    assert store.candidates("wf_a")[0].said == SAID


def test_said_round_trips_on_a_library_clip(store: FootageStore) -> None:
    store.add_library("ws1", "wf_a", _clip(f"{PODCAST}#t=292.0", SAID))
    found = store.library(
        "ws1", ["mutant"], datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)
    )
    assert found[0].said == SAID


def test_odd_stored_said_reads_as_empty(store: FootageStore) -> None:  # Review Focus 5
    store.start_run("wf_a", [FootageObject(query="q", visual="v")])
    store.add_candidates("wf_a", [_candidate(PODCAST, "search")])
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("UPDATE footage_candidates SET said = '{\"x\": 1}'::jsonb")
    assert store.candidates("wf_a")[0].said == []


def test_drop_library_keeps_an_earlier_runs_row(store: FootageStore) -> None:  # Review Focus 4
    old = "https://www.tiktok.com/@a/video/7700000000000000001"
    new = "https://www.tiktok.com/@b/video/7700000000000000002"
    store.add_library("ws1", "wf_a", _clip(old))
    store.add_library("ws1", "wf_b", LibraryClip(**{**_clip(new).__dict__, "hashes": [1, 2]}))
    store.drop_library("ws1", "wf_b", old)
    store.drop_library("ws1", "wf_b", new)
    found = store.library(
        "ws1", ["mutant"], datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)
    )
    assert [c.url for c in found] == [old]


def test_relation_round_trips_on_candidates_and_library(store: FootageStore) -> None:  # 10.7
    from dataclasses import replace

    from thoth_control_plane.footage.models import AdmittedClip

    store.start_run("wf_a", [FootageObject(query="q", visual="v")])
    url, other = f"{PODCAST}#t=292.0", "https://www.tiktok.com/@a/video/7700000000000000009"
    store.add_candidates("wf_a", [_candidate(url, "section"), _candidate(other, "search")])
    clip = AdmittedClip(
        kind="footage",
        shows_object="yes",
        description="d",
        media_location="reports/wf_a/footage/a.mp4",
        media_checksum="sha256:" + "a" * 64,
        media_bytes=1,
        clip_duration=8.0,
        clip_start=0.0,
        ocr={},
        position=0,
        relation="discusses",
    )
    store.admit("wf_a", url, clip)
    for reason in ("same_event", "subject_absent", "too_old"):
        store.reject("wf_a", other, reason)
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert rows[url].relation == "discusses" and rows[other].relation == "unknown"
    assert rows[other].reason == "too_old"
    store.add_library("ws1", "wf_a", replace(_clip(url), relation="related"))
    found = store.library(
        "ws1", ["mutant"], datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)
    )
    assert found[0].relation == "related"
