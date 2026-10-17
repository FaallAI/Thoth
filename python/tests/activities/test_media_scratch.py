"""The per-activity media scratch directory (spec 2026-10-17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.activities.test_source_investigation import _load_fixture_report
from thoth_control_plane.activities.media_scratch import (
    MediaScratch,
    media_locations,
    report_media_locations,
)
from thoth_control_plane.infrastructure.media_store import LocalMediaStore, MediaLocatorInvalid

LOCATION = "reports/wf_a/media/tiktok-1.mp4"


def _store(tmp_path: Path) -> LocalMediaStore:
    root = tmp_path / "store"
    root.mkdir()
    return LocalMediaStore(root)


async def test_pull_lays_files_out_like_the_store_and_skips_absent_ones(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "v.mp4"
    source.write_bytes(b"video")
    store.put_file(LOCATION, source)
    async with MediaScratch(store, tmp_path / "scratch") as scratch:
        fetched = await scratch.pull([LOCATION, "reports/wf_a/media/absent.mp4", LOCATION])
        assert fetched == [LOCATION]
        assert (scratch.root / LOCATION).read_bytes() == b"video"
        assert scratch.root.parent == tmp_path / "scratch"


async def test_push_uploads_what_exists_and_the_directory_is_removed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    async with MediaScratch(store) as scratch:
        made = scratch.root / "reports/wf_a/cards/profile.png"
        made.parent.mkdir(parents=True)
        made.write_bytes(b"png")
        pushed = await scratch.push(["reports/wf_a/cards/profile.png", "reports/wf_a/cards/no.png"])
        root = scratch.root
    assert pushed == ["reports/wf_a/cards/profile.png"]
    assert store.stat("reports/wf_a/cards/profile.png").size_bytes == 3
    assert not root.exists()


async def test_the_scratch_directory_is_removed_when_the_body_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        async with MediaScratch(_store(tmp_path), tmp_path / "scratch") as scratch:
            (scratch.root / "big.mp4").write_bytes(b"x" * 1024)
            raise RuntimeError("cancelled mid-run")
    assert list((tmp_path / "scratch").iterdir()) == []


async def test_pull_skips_and_push_refuses_an_unsafe_locator(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"canary")
    async with MediaScratch(_store(tmp_path)) as scratch:
        assert await scratch.pull([str(outside), "reports/../outside.mp4"]) == []
        with pytest.raises(MediaLocatorInvalid):
            await scratch.push(["reports/..\\..\\outside.mp4"])
    assert outside.read_bytes() == b"canary"


def test_report_locations_cover_media_and_every_card() -> None:
    report = _load_fixture_report()
    every = report_media_locations(report)
    assert media_locations(report) == [str(media.location) for media in report.media]
    assert set(media_locations(report)) <= set(every)
    cards = [str(c.card.location) for c in report.comments if c.card]
    assert set(cards) <= set(every)
    assert media_locations(None) == []


async def test_push_warns_about_recorded_files_it_cannot_find(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    async with MediaScratch(_store(tmp_path)) as scratch:
        with caplog.at_level(logging.WARNING):
            await scratch.push(["reports/wf_a/cards/no.png", "reports/wf_a/media/gone.mp4"])
    assert "2 recorded media files" in caplog.text
    assert "no.png" not in caplog.text and "wf_a" not in caplog.text
