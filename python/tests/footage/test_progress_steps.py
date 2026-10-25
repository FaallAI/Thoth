"""Footage step emissions over the service fakes (phase 3, D3).

One representative build with a search hit on one platform and a creator listing runs the
real `FootageBuilder.build` inside `progress.scoped` with a fake sink.
"""

from __future__ import annotations

from pathlib import Path

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
    # The three platform searches run concurrently, so which intermediate updates survive
    # the one-second coalescing window is timing; every survivor keeps its platform's n.
    searches = [step for step in steps if step[0] == "footage.search_platforms"]
    of = {name: number for number, name in enumerate(("tiktok", "youtube", "x"), start=1)}
    assert {2 <= len(searches) <= 3}
    for _, n, total, params in searches:
        assert (n, total) == (of[params["platform"]], 3)
    assert (3, 3, {"platform": "x"}) in [(n, total, params) for _, n, total, params in searches]
    ordered = [code for code, *_ in steps]
    last_search = max(i for i, code in enumerate(ordered) if code == "footage.search_platforms")
    assert ordered.index("footage.creator_listing") > last_search
    assert steps[-2:] == [
        ("footage.screen_clips", 2, 2, None),
        ("footage.keep_clips", None, None, {"count": 2}),
    ]
