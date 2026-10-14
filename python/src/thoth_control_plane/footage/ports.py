"""What the footage builder needs from the outside world; adapters implement it."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.attribution.ports import Frame
from thoth_control_plane.footage.adapters.vision import FootageAnswer
from thoth_control_plane.footage.models import (
    AdmittedClip,
    CandidateView,
    FootageObject,
    NewCandidate,
    RunView,
    SearchBatch,
)
from thoth_control_plane.footage.queries import FootageQueryAnswer


class QueryModel(Protocol):
    async def read(self, prompt: str) -> FootageQueryAnswer | None: ...


class SearchPort(Protocol):
    async def search(self, platform: str, queries: Sequence[str], limit: int) -> SearchBatch: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ClipDownloader(Protocol):
    async def download(
        self, url: str, window: tuple[float, float] | None, target: Path
    ) -> Path: ...


class FootageJudge(Protocol):
    async def judge(self, frames: Sequence[Frame], visual: str) -> FootageAnswer: ...


class FootageState(Protocol):
    """`FootageStore`'s methods; synchronous, called through `asyncio.to_thread`."""

    def cached_search(self, platform: str, query: str) -> list[DiscoveredVideo] | None: ...
    def save_search(self, platform: str, query: str, videos: Sequence[DiscoveredVideo]) -> None: ...
    def run(self, workflow_id: str) -> RunView | None: ...
    def start_run(self, workflow_id: str, objects: Sequence[FootageObject]) -> RunView: ...
    def finish_run(self, workflow_id: str, footage_status: str) -> None: ...
    def candidates(self, workflow_id: str) -> list[CandidateView]: ...
    def add_candidates(self, workflow_id: str, items: Sequence[NewCandidate]) -> None: ...
    def score(self, workflow_id: str, url: str, story_score: float) -> None: ...
    def reject(self, workflow_id: str, url: str, reason: str, **fields: object) -> None: ...
    def admit(self, workflow_id: str, url: str, clip: AdmittedClip) -> None: ...
    def reopen(self, workflow_id: str, url: str) -> None: ...
    def admitted(self, workflow_id: str) -> list[CandidateView]: ...
