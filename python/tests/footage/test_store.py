"""The footage store on in-memory SQLite (the source-account store's test pattern)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.models import AdmittedClip, FootageObject, NewCandidate
from thoth_control_plane.infrastructure.footage_store import FootageStore
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
OBJECTS = [FootageObject(query="banjir jakarta", visual="a flooded street")]


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> FootageStore:
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    return FootageStore(engine, clock=clock)


def _video(n: int = 1) -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=f"740000000000000000{n}",
        owner_handle="kreator",
        canonical_url=f"https://www.tiktok.com/@kreator/video/740000000000000000{n}",
        caption="banjir lagi di jakarta",
        duration_seconds=42.0,
        engagement={"like": 10},
    )


def _candidate(url: str = "https://x.com/a/status/1", **changes: object) -> NewCandidate:
    values: dict[str, object] = {
        "url": url,
        "platform": "x",
        "source": "search",
        "query": "banjir jakarta",
        "visual": "a flooded street",
        "owner_handle": "a",
        "caption": "banjir",
    }
    values.update(changes)
    return NewCandidate(**values)  # type: ignore[arg-type]


def _clip(position: int) -> AdmittedClip:
    return AdmittedClip(
        kind="footage",
        shows_object="yes",
        description="A flooded street.",
        media_location="reports/wf_a/footage/abc.mp4",
        media_checksum="sha256:" + "a" * 64,
        media_bytes=2048,
        clip_duration=20.0,
        clip_start=4.2,
        ocr={"outcome": "clean"},
        position=position,
    )


def test_a_search_is_cached_for_a_day_and_pruned_after(store: FootageStore, clock: Clock) -> None:
    store.save_search("tiktok", "  Banjir   Jakarta ", [_video()])
    cached = store.cached_search("tiktok", "banjir jakarta")
    assert cached is not None and cached[0].post_id == "7400000000000000001"
    assert store.cached_search("youtube", "banjir jakarta") is None

    clock.now = NOW + timedelta(hours=25)
    assert store.cached_search("tiktok", "banjir jakarta") is None
    store.save_search("tiktok", "other", [])  # a write prunes expired rows
    clock.now = NOW
    assert store.cached_search("tiktok", "banjir jakarta") is None


def test_nul_characters_never_reach_the_database(store: FootageStore) -> None:
    dirty = _video().model_copy(update={"caption": "ban\x00jir"})
    store.save_search("tiktok", "banjir", [dirty])
    cached = store.cached_search("tiktok", "banjir")
    assert cached is not None and cached[0].caption == "banjir"

    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate(caption="ban\x00jir", owner_handle="a\x00")])
    row = store.candidates("wf_a")[0]
    assert row.caption == "banjir" and row.owner_handle == "a"


def test_saving_a_search_again_replaces_it(store: FootageStore) -> None:
    store.save_search("tiktok", "banjir jakarta", [_video(1)])
    store.save_search("tiktok", "banjir jakarta", [_video(2)])
    cached = store.cached_search("tiktok", "banjir jakarta")
    assert [video.post_id for video in cached or []] == ["7400000000000000002"]


def test_a_run_starts_once_and_keeps_its_objects(store: FootageStore) -> None:
    first = store.start_run("wf_a", OBJECTS)
    again = store.start_run("wf_a", [])
    assert first.objects == OBJECTS and again.objects == OBJECTS
    store.finish_run("wf_a", "ok")
    run = store.run("wf_a")
    assert run is not None and run.status == "done" and run.footage_status == "ok"
    assert store.run("wf_b") is None


def test_candidates_are_unique_per_workflow_and_url(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate(), _candidate()])
    store.add_candidates("wf_a", [_candidate()])
    assert len(store.candidates("wf_a")) == 1


def test_decisions_and_admission_order(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates(
        "wf_a",
        [
            _candidate("https://x.com/a/status/1"),
            _candidate("https://x.com/a/status/2"),
            _candidate("https://x.com/a/status/3", status="rejected", reason="spam"),
        ],
    )
    store.score("wf_a", "https://x.com/a/status/1", 0.7)
    store.reject("wf_a", "https://x.com/a/status/2", "commentary", kind="commentary")
    store.admit("wf_a", "https://x.com/a/status/1", _clip(0))

    by_url = {c.url: c for c in store.candidates("wf_a")}
    assert by_url["https://x.com/a/status/2"].reason == "commentary"
    assert by_url["https://x.com/a/status/3"].reason == "spam"
    admitted = store.admitted("wf_a")
    assert [c.url for c in admitted] == ["https://x.com/a/status/1"]
    assert admitted[0].story_score == 0.7 and admitted[0].clip_start == 4.2


def test_reopen_returns_an_admitted_candidate_to_pending(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate()])
    store.admit("wf_a", "https://x.com/a/status/1", _clip(0))
    store.reopen("wf_a", "https://x.com/a/status/1")
    (candidate,) = store.candidates("wf_a")
    assert candidate.status == "pending" and candidate.media_location is None
    assert store.admitted("wf_a") == []


def test_an_unknown_reason_is_refused(store: FootageStore) -> None:
    store.start_run("wf_a", OBJECTS)
    store.add_candidates("wf_a", [_candidate()])
    with pytest.raises(ValueError):
        store.reject("wf_a", "https://x.com/a/status/1", "seen")


def test_a_candidate_needs_its_run(store: FootageStore) -> None:
    with pytest.raises(ValueError):
        store.add_candidates("wf_missing", [_candidate()])


@pytest.mark.parametrize(
    ("status", "reason"),
    [("admitted", None), ("bogus", None), ("rejected", None), ("pending", "spam")],
)
def test_a_candidate_pair_postgres_would_refuse_is_refused(
    store: FootageStore, status: str, reason: str | None
) -> None:
    store.start_run("wf_a", OBJECTS)
    items = [
        _candidate("https://x.com/a/status/1"),
        _candidate("https://x.com/a/status/2", status=status, reason=reason),
    ]
    with pytest.raises(ValueError):
        store.add_candidates("wf_a", items)
    assert store.candidates("wf_a") == []


def test_creator_photo_candidates_round_trip(store: FootageStore) -> None:
    # Spec 5c-2, G4: an admitted creator photo is read apart from the clips.
    store.start_run("wf_1", OBJECTS)
    photo = "https://www.instagram.com/p/PHOTO1/"
    store.add_candidates(
        "wf_1",
        [
            _candidate(),
            _candidate(photo, platform="instagram", source="creator", media_kind="image"),
        ],
    )
    store.admit("wf_1", "https://x.com/a/status/1", _clip(0))
    store.admit("wf_1", photo, _clip(0))
    assert [view.url for view in store.admitted("wf_1", "image")] == [photo]
    assert [view.url for view in store.admitted("wf_1")] == ["https://x.com/a/status/1"]
    assert store.admitted("wf_1", "image")[0].media_kind == "image"


def test_a_run_keeps_its_profile_page_card(store: FootageStore) -> None:
    # TikTok's page card comes from the creator listing (spec 5c-2, Task 0 ruling).
    store.start_run("wf_1", OBJECTS)
    card = {"location": "reports/wf_1/cards/profile-page.png", "bytes": 4000}
    store.set_profile_page("wf_1", card)
    run = store.run("wf_1")
    assert run is not None and run.profile_page == card
