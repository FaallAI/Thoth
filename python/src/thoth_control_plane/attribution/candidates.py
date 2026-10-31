"""Which of the credited account's videos deserve a closer look, in the order to try them.

Everything here uses metadata discovery already returned, so it costs nothing. The window and
ratios come from Scout's `lib/main_gate.ts` (`isPlausibleSource`).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.credit import normalize

MAX_SOURCE_AGE = timedelta(days=14)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def plausible(video: DiscoveredVideo, repost_time: datetime | None) -> bool:
    """Published shortly before the repost; an unknown time passes.

    Duration is no filter: a reaction repost runs longer than the original it shows.
    """
    published = parse_time(video.published_at)
    if repost_time is None or published is None:
        return True
    gap = repost_time - published
    return timedelta(0) < gap <= MAX_SOURCE_AGE


def shortlist(
    videos: Iterable[DiscoveredVideo],
    *,
    repost_owner: str,
    curated: frozenset[str],
    repost_time: datetime | None,
) -> tuple[list[DiscoveredVideo], dict[str, int]]:
    """The plausible videos, closest before the repost first, then the most played."""
    owner = normalize(repost_owner)
    counts: Counter[str] = Counter()
    kept: list[DiscoveredVideo] = []
    for video in videos:
        account = normalize(video.owner_handle)
        if account == owner or account in curated:
            counts["excluded_account"] += 1
        elif not plausible(video, repost_time):
            counts["filtered_window"] += 1
        else:
            kept.append(video)
    kept.sort(key=lambda video: _order(video, repost_time))
    return kept, dict(counts)


def _order(video: DiscoveredVideo, repost_time: datetime | None) -> tuple[float, int]:
    published = parse_time(video.published_at)
    gap = (
        (repost_time - published).total_seconds()
        if repost_time is not None and published is not None
        else math.inf
    )
    return gap, -video.engagement.get("play", 0)
