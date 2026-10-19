"""Projects owned by the control plane, on in-memory SQLite."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.domain.projects import Project
from thoth_control_plane.infrastructure import run_models  # noqa: F401  (registers the tables)
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.source_account_models import Base

T0 = datetime(2026, 10, 18, 8, tzinfo=UTC)


@pytest.fixture
def store() -> ProjectStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    ticks = iter(T0 + timedelta(seconds=n) for n in range(100))
    return ProjectStore(engine, clock=lambda: next(ticks))


WS = "ws_bootstrap"
OTHER = "ws_other"


def test_create_mints_a_uuid_and_trims_the_name(store: ProjectStore) -> None:
    project = store.create("  News  ", WS)
    assert project.name == "News"
    assert len(project.project_id) == 36
    assert store.get(project.project_id, WS) == project


def test_list_is_newest_updated_first(store: ProjectStore) -> None:
    first = store.create("A", WS)
    second = store.create("B", WS)
    assert [p.project_id for p in store.list(WS)] == [second.project_id, first.project_id]


def test_a_project_belongs_to_one_workspace(store: ProjectStore) -> None:
    mine = store.create("Mine", WS)
    theirs = store.create("Theirs", OTHER)
    assert [p.project_id for p in store.list(WS)] == [mine.project_id]
    assert [p.project_id for p in store.list(OTHER)] == [theirs.project_id]
    assert store.get(theirs.project_id, WS) is None
    assert store.get(mine.project_id, OTHER) is None


def test_insert_missing_keeps_the_id_lands_in_bootstrap_and_never_overwrites(
    store: ProjectStore,
) -> None:
    when = datetime(2026, 9, 1, tzinfo=UTC)
    legacy = Project(
        project_id="db766411-3cb0-47a4-9dc9-b67d22f6f34e",
        name="test",
        created_at=when,
        updated_at=when,
    )
    assert store.insert_missing(legacy) is True
    assert store.insert_missing(legacy.model_copy(update={"name": "other"})) is False
    assert store.get(legacy.project_id, WS) == legacy
    assert store.get(legacy.project_id, OTHER) is None


def test_an_absent_project_is_none(store: ProjectStore) -> None:
    assert store.get("missing", WS) is None
