"""Per-activity local copies of workflow media (spec 2026-10-17).

Code that needs a file path (ffmpeg, ORB, ONNX, OCR, yt-dlp) works in a private directory laid
out like the store, `<root>/<locator>`. The activity pulls what it reads, pushes what it made,
and the directory is removed when the activity leaves it, whatever the outcome.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType

from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.infrastructure.media_store import (
    MediaLocatorInvalid,
    MediaStore,
    MediaUnavailable,
    checked_locator,
)


def media_locations(report: SourceReport | None) -> list[str]:
    """The report's media files: what a reader of the post's video or images needs."""
    return [str(media.location) for media in report.media] if report is not None else []


def report_media_locations(report: SourceReport) -> list[str]:
    """Every file the report records: its media and every card."""
    locations = media_locations(report)
    locations += [str(comment.card.location) for comment in report.comments if comment.card]
    for card in (report.profile_card, report.post_card):
        if card is not None:
            locations.append(str(card.location))
    return locations


class MediaScratch:
    def __init__(self, store: MediaStore, parent: Path | None = None) -> None:
        self._store = store
        self._parent = parent
        self.root = Path()

    async def __aenter__(self) -> MediaScratch:
        if self._parent is not None:
            await asyncio.to_thread(self._parent.mkdir, parents=True, exist_ok=True)
        made = await asyncio.to_thread(tempfile.mkdtemp, prefix="thoth-media-", dir=self._parent)
        self.root = Path(made)
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await asyncio.to_thread(shutil.rmtree, self.root, True)

    async def pull(self, locations: Iterable[str]) -> list[str]:
        """Fetch each object to its place; an absent object or unsafe locator is left out, as a
        missing file was before. A store outage propagates."""
        fetched: list[str] = []
        for location in dict.fromkeys(locations):
            try:
                await asyncio.to_thread(self._store.fetch, location, self._path(location))
            except (MediaUnavailable, MediaLocatorInvalid):
                continue
            fetched.append(location)
        return fetched

    async def push(self, locations: Iterable[str]) -> list[str]:
        """Upload each file this activity made; a locator with no file here is left out."""
        pushed: list[str] = []
        for location in dict.fromkeys(locations):
            path = self._path(location)
            if not path.is_file():
                continue
            await asyncio.to_thread(self._store.put_file, location, path)
            pushed.append(location)
        return pushed

    def _path(self, location: str) -> Path:
        return self.root.joinpath(*checked_locator(location).split("/"))
