"""The orphan-upload sweep: only old objects no asset row points at are deleted."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from thoth_control_plane.application.editor_asset_ports import EditorAssetPersistenceError
from thoth_control_plane.application.editor_asset_uploads import sweep_unregistered_uploads

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


class Store:
    def __init__(self, old: list[str]) -> None:
        self.old = old
        self.listed: list[tuple[str, datetime | None]] = []
        self.deleted: list[str] = []

    def list(self, prefix: str, *, older_than: datetime | None = None) -> list[str]:
        self.listed.append((prefix, older_than))
        return list(self.old)

    def delete(self, location: str) -> None:
        self.deleted.append(location)


class Assets:
    def __init__(self, registered: set[str], *, broken: bool = False) -> None:
        self.registered = registered
        self.broken = broken
        self.asked: list[list[str]] = []

    async def registered_locations(self, locations: list[str]) -> set[str]:
        self.asked.append(list(locations))
        if self.broken:
            raise EditorAssetPersistenceError()
        return {location for location in locations if location in self.registered}


@pytest.mark.asyncio
async def test_an_old_unregistered_upload_is_deleted_and_a_registered_one_kept() -> None:
    store = Store(["uploads/p1/asset_kept.mp4", "uploads/p1/asset_orphan.mp4"])
    assets = Assets({"uploads/p1/asset_kept.mp4"})

    removed = await sweep_unregistered_uploads(store, assets, NOW)

    assert removed == 1
    assert store.deleted == ["uploads/p1/asset_orphan.mp4"]
    # Only objects older than the grace period are candidates: an import in flight is younger.
    assert store.listed == [("uploads/", NOW - timedelta(hours=1))]


@pytest.mark.asyncio
async def test_a_database_failure_deletes_nothing() -> None:
    store = Store(["uploads/p1/asset_a.mp4"])
    with pytest.raises(EditorAssetPersistenceError):
        await sweep_unregistered_uploads(store, Assets(set(), broken=True), NOW)
    assert store.deleted == []


@pytest.mark.asyncio
async def test_many_candidates_are_checked_in_bounded_batches() -> None:
    old = [f"uploads/p1/asset_{i:04d}.mp4" for i in range(1201)]
    assets = Assets(set(old))

    assert await sweep_unregistered_uploads(Store(old), assets, NOW) == 0
    assert [len(batch) for batch in assets.asked] == [500, 500, 201]


@pytest.mark.asyncio
async def test_nothing_old_asks_the_database_nothing() -> None:
    assets = Assets(set())
    assert await sweep_unregistered_uploads(Store([]), assets, NOW) == 0
    assert assets.asked == []
