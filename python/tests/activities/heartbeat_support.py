"""A heartbeat and a media store that record whether the store ran inside the heartbeat."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from thoth_control_plane.infrastructure.media_store import LocalMediaStore


class WatchedHeartbeat:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    async def __call__(self) -> None:
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.stopped.set()


class WatchingStore(LocalMediaStore):
    """Each store call records (call, heartbeat running?)."""

    def __init__(self, root: Path, heartbeat: WatchedHeartbeat) -> None:
        super().__init__(root)
        self._heartbeat = heartbeat
        self.calls: list[tuple[str, bool]] = []

    def _running(self) -> bool:
        # A heartbeat started first has run before the store's thread is scheduled.
        return self._heartbeat.started.wait(2) and not self._heartbeat.stopped.is_set()

    def fetch(self, location: str, destination: Path) -> None:
        self.calls.append(("fetch", self._running()))
        super().fetch(location, destination)

    def put_file(self, location: str, path: Path) -> None:
        self.calls.append(("put", self._running()))
        super().put_file(location, path)
