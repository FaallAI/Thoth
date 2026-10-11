"""Free metadata filters: the plausibility window, excluded accounts, and the order to try."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.candidates import (
    DEFAULT_CURATED_FILE,
    load_curated,
    shortlist,
)

REPOST_TIME = datetime(2026, 8, 24, 7, 26, 32, tzinfo=UTC)
SOURCE = "vincentius.christ76"


def _video(
    n: int,
    published: str | None,
    duration: float | None = 124.0,
    plays: int = 0,
    owner: str = SOURCE,
) -> DiscoveredVideo:
    post_id = str(7677137235434687000 + n)
    return DiscoveredVideo(
        post_id=post_id,
        owner_handle=owner,
        canonical_url=f"https://www.tiktok.com/@{owner}/video/{post_id}",
        published_at=published,
        duration_seconds=duration,
        engagement={"play": plays},
    )


def _kept(videos: list[DiscoveredVideo]) -> tuple[list[int], dict[str, int]]:
    kept, counts = shortlist(
        videos,
        repost_owner="detikjatim",
        curated=frozenset({"curatedaggregator"}),
        repost_time=REPOST_TIME,
    )
    return [int(video.post_id) - 7677137235434687000 for video in kept], counts


def test_the_window_keeps_only_plausible_sources() -> None:
    kept, counts = _kept(
        [
            _video(1, "2026-08-24T10:00:00Z"),  # after the repost
            _video(2, "2026-08-23T08:13:31Z"),  # 23 hours before: plausible
            _video(3, "2026-08-08T00:00:00Z"),  # more than 14 days before
            _video(4, None, duration=None),  # unknown values pass
        ]
    )

    assert kept == [2, 4]
    assert counts == {"filtered_window": 2}


def test_a_source_shorter_than_its_repost_is_kept() -> None:
    # A reaction repost shows a 20 s original inside a 90 s video.
    kept, _ = _kept([_video(1, "2026-08-23T08:13:31Z", duration=20.0)])

    assert kept == [1]


def test_closest_before_the_repost_comes_first_then_most_played() -> None:
    kept, _ = _kept(
        [
            _video(1, "2026-08-20T00:00:00Z", plays=9),
            _video(2, "2026-08-23T00:00:00Z", plays=1),
            _video(3, None, plays=100),
            _video(4, None, plays=500),
        ]
    )

    assert kept == [2, 1, 4, 3]


def test_the_reposting_and_curated_accounts_are_excluded() -> None:
    kept, counts = _kept(
        [
            _video(1, "2026-08-23T00:00:00Z", owner="detik_jatim"),
            _video(2, "2026-08-23T00:00:00Z", owner="curated.aggregator"),
            _video(3, "2026-08-23T00:00:00Z"),
        ]
    )

    assert kept == [3]
    assert counts == {"excluded_account": 2}


def test_the_curated_list_reads_every_shape_and_degrades_to_empty(tmp_path: Path) -> None:
    listed = tmp_path / "list.json"
    listed.write_text(json.dumps(["@One.Account", "https://www.instagram.com/two_acc/?hl=id"]))
    keyed = tmp_path / "keyed.json"
    keyed.write_text(json.dumps({"accounts": ["three"]}))

    assert load_curated(listed) == frozenset({"oneaccount", "twoacc"})
    assert load_curated(keyed) == frozenset({"three"})
    assert load_curated(tmp_path / "missing.json") == frozenset()


def test_the_default_curated_file_is_the_scout_list() -> None:
    repository = Path(__file__).resolve().parents[3]

    assert repository / "scout" / "config" / "ig_accounts.json" == DEFAULT_CURATED_FILE
    assert DEFAULT_CURATED_FILE.is_file()
