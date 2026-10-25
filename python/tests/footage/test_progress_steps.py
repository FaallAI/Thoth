"""Footage step emissions over the service fakes (phase 3, D3).

One representative build with a search hit on one platform and a creator listing runs the
real `FootageBuilder.build` inside `progress.scoped` with a fake sink.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from tests.footage.test_service import (
    NOW,
    CreatorListing,
    Search,
    _builder,
    _creator,
    _hits,
    _inputs,
    _own,
    _video,
)
from thoth_control_plane import progress
from thoth_control_plane.infrastructure.footage_store import FootageStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.progress import StepRecord, StepScope

FOOTAGE_SCOPE = StepScope(workflow_id="wf_a", stage="footage", attempt=1)


class StepSink:
    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def append(self, scope: StepScope, record: StepRecord) -> None:
        self.records.append(record)


@pytest.fixture
def sink() -> StepSink:
    installed = StepSink()
    progress.install(installed)
    return installed


@pytest.fixture
def store(tmp_path: Path) -> FootageStore:
    """The service-test store: a file database, because the builder calls it from threads."""
    engine = create_engine(f"sqlite:///{tmp_path / 'footage.db'}")
    Base.metadata.create_all(engine)
    return FootageStore(engine, clock=lambda: NOW)


def sequence(sink: StepSink) -> list[tuple[str, int | None, int | None, dict | None]]:
    return [(r.code, r.n, r.total, r.params) for r in sink.records]


@pytest.mark.asyncio
async def test_a_build_plans_searches_screens_and_keeps(
    sink: StepSink, store, tmp_path: Path
) -> None:
    ports = _creator(CreatorListing(videos=[_own(1, "banjir kemang dari sisi lain")], photos=[]))
    builder = _builder(store, search=Search(_hits(_video(1))), **ports)

    with progress.scoped(FOOTAGE_SCOPE):
        result = await builder.build(_inputs(tmp_path))

    assert result.status == "ok"
    steps = sequence(sink)
    assert steps[0] == ("footage.plan_queries", None, None, {"count": 2})
    # The platforms search concurrently and each reports a completion count (1..3),
    # never its index in SEARCH_PLATFORMS; which intermediate counts survive the
    # one-second coalescing window is timing.
    searches = [step for step in steps if step[0] == "footage.search_platforms"]
    assert 2 <= len(searches) <= 3
    for _, n, total, params in searches:
        assert total == 3
        assert params is not None and params["platform"] in ("tiktok", "youtube", "x")
        assert 1 <= n <= 3
    assert searches[-1][1] == 3
    ordered = [code for code, *_ in steps]
    last_search = max(i for i, code in enumerate(ordered) if code == "footage.search_platforms")
    assert ordered.index("footage.creator_listing") > last_search
    assert steps[-2:] == [
        ("footage.screen_clips", 2, 2, None),
        ("footage.keep_clips", None, None, {"count": 2}),
    ]


class StaggeredSearch(Search):
    """X answers at once, the other platforms later, so X settles first."""

    delays = {"tiktok": 0.30, "youtube": 0.15, "x": 0.0}

    async def search(self, platform: str, queries: Any, limit: int) -> Any:
        await asyncio.sleep(self.delays[platform])
        return await super().search(platform, queries, limit)


@pytest.mark.asyncio
async def test_a_platform_that_finishes_first_reports_the_first_completion(
    sink: StepSink, store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No coalescing holds: each platform's completion count is recorded as it lands.
    monkeypatch.setattr(progress, "COALESCE_SECONDS", 0.0)
    ports = _creator(CreatorListing(videos=[_own(1, "banjir kemang dari sisi lain")], photos=[]))
    builder = _builder(store, search=StaggeredSearch(_hits(_video(1))), **ports)

    with progress.scoped(FOOTAGE_SCOPE):
        result = await builder.build(_inputs(tmp_path))

    assert result.status == "ok"
    searches = [step for step in sequence(sink) if step[0] == "footage.search_platforms"]
    counts = {params["platform"]: n for _, n, _, params in searches}
    # X is last in SEARCH_PLATFORMS but finishes first, so its n is a completion
    # count, not the platform index.
    assert counts == {"x": 1, "youtube": 2, "tiktok": 3}
    assert searches[-1][1:3] == (3, 3)
