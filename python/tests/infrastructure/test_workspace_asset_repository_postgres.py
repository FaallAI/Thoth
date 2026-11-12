"""A workspace's asset library on the migrated PostgreSQL schema (spec 2026-11-13)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.postgres_support import DATABASE_URL, empty_tables, needs_postgres, reset_schema
from thoth_control_plane.domain.workspace_assets import WorkspaceAsset, WorkspaceAssetRecord
from thoth_control_plane.infrastructure.workspace_asset_repository import (
    PostgresWorkspaceAssetRepository,
)

pytestmark = [needs_postgres, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def migrated() -> None:
    reset_schema()


@pytest.fixture
def library(migrated: None) -> PostgresWorkspaceAssetRepository:
    empty_tables()
    return PostgresWorkspaceAssetRepository(DATABASE_URL)


def record(workspace_id: str, asset_id: str, checksum: str = "sha256:" + "a" * 64):
    return WorkspaceAssetRecord(
        asset=WorkspaceAsset(
            asset_id=asset_id,
            workspace_id=workspace_id,
            kind="sfx",
            name="Vine Boom",
            labels={"category": "meme"},
            media_type="audio/mpeg",
            checksum=checksum,
            duration_seconds=1.5,
            has_audio=True,
            created_at=datetime.now(UTC),
        ),
        location=f"library/{workspace_id}/{asset_id}.mp3",
    )


async def test_add_then_list_returns_the_item_for_its_workspace_only(
    library: PostgresWorkspaceAssetRepository,
) -> None:
    await library.add(record("ws_a", "lib_1"))
    assert [item.asset_id for item in await library.list("ws_a")] == ["lib_1"]
    assert await library.list("ws_b") == []
    assert await library.get("ws_b", "lib_1") is None
    found = await library.get("ws_a", "lib_1")
    assert found is not None and found.location == "library/ws_a/lib_1.mp3"
    assert found.asset.labels == {"category": "meme"}


async def test_same_checksum_in_one_workspace_returns_the_existing_item(
    library: PostgresWorkspaceAssetRepository,
) -> None:
    first = await library.add(record("ws_a", "lib_1"))
    second = await library.add(record("ws_a", "lib_2"))
    assert second.asset.asset_id == first.asset.asset_id == "lib_1"
    assert len(await library.list("ws_a")) == 1


async def test_same_checksum_in_two_workspaces_makes_two_items(
    library: PostgresWorkspaceAssetRepository,
) -> None:
    await library.add(record("ws_a", "lib_1"))
    await library.add(record("ws_b", "lib_2"))
    assert [item.asset_id for item in await library.list("ws_a")] == ["lib_1"]
    assert [item.asset_id for item in await library.list("ws_b")] == ["lib_2"]


async def test_update_changes_name_labels_and_kind_only_in_its_workspace(
    library: PostgresWorkspaceAssetRepository,
) -> None:
    await library.add(record("ws_a", "lib_1"))
    assert await library.update("ws_b", "lib_1", name="Theirs", labels=None, kind=None) is None
    updated = await library.update(
        "ws_a", "lib_1", name="Boom", labels={"mood": "shock"}, kind="backsound"
    )
    assert updated is not None
    assert (updated.name, updated.labels, updated.kind) == ("Boom", {"mood": "shock"}, "backsound")
    kept = await library.update("ws_a", "lib_1", name=None, labels=None, kind=None)
    assert kept is not None and kept.name == "Boom"


async def test_delete_returns_the_location_and_is_scoped(
    library: PostgresWorkspaceAssetRepository,
) -> None:
    await library.add(record("ws_a", "lib_1"))
    assert await library.delete("ws_b", "lib_1") is None
    assert len(await library.list("ws_a")) == 1
    assert await library.delete("ws_a", "lib_1") == "library/ws_a/lib_1.mp3"
    assert await library.list("ws_a") == []
