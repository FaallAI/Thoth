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
