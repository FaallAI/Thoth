"""Which of the credited account's videos deserve a closer look, in the order to try them.

Everything here uses metadata discovery already returned, so it costs nothing. The window and
ratios come from Scout's `lib/main_gate.ts` (`isPlausibleSource`).
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.credit import normalize

logger = logging.getLogger(__name__)

# The same relative place in the repository and in the image (/opt/thoth/scout/config).
# Stage 10 moves this list into Python when Scout retires.
DEFAULT_CURATED_FILE = Path(__file__).resolve().parents[4] / "scout" / "config" / "ig_accounts.json"
MAX_SOURCE_AGE = timedelta(days=14)
MIN_DURATION_RATIO = 0.9


def load_curated(path: Path = DEFAULT_CURATED_FILE) -> frozenset[str]:
    """Curated aggregator accounts, normalized; an unreadable list excludes nobody."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("curated account list unavailable; no account is excluded as aggregator")
        return frozenset()
    entries = data.get("accounts", []) if isinstance(data, dict) else data
    handles: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        text = re.sub(r"^https?://(www\.)?instagram\.com/", "", str(entry).strip(), flags=re.I)
        key = normalize(re.split(r"[/?#]", text, maxsplit=1)[0])
        if key:
            handles.add(key)
    return frozenset(handles)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def plausible(
    video: DiscoveredVideo, repost_time: datetime | None, repost_duration: float | None
) -> bool:
    """Published shortly before the repost and not shorter than it; unknown values pass."""
    published = parse_time(video.published_at)
    if repost_time is not None and published is not None:
        gap = repost_time - published
        if gap <= timedelta(0) or gap > MAX_SOURCE_AGE:
            return False
    duration = video.duration_seconds
    return not (repost_duration and duration and duration < repost_duration * MIN_DURATION_RATIO)


def shortlist(
    videos: Iterable[DiscoveredVideo],
    *,
    repost_owner: str,
    curated: frozenset[str],
    repost_time: datetime | None,
    repost_duration: float | None,
) -> tuple[list[DiscoveredVideo], dict[str, int]]:
    """The plausible videos, closest before the repost first, then the most played."""
    owner = normalize(repost_owner)
    counts: Counter[str] = Counter()
    kept: list[DiscoveredVideo] = []
    for video in videos:
        account = normalize(video.owner_handle)
        if account == owner or account in curated:
            counts["excluded_account"] += 1
        elif not plausible(video, repost_time, repost_duration):
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
