"""Ports that answer from a recorded case; the service tests and golden fixtures share them.

A case maps frame keys to frames. A video path's stem names its key; a frame's JPEG bytes carry
`"<key>:<second>"`, so the matcher and the OCR reader can find what was recorded for it.
`matches` maps a candidate key to the inliers each repost frame found in it; a key listed
in `unmatchable` has no features to match (flat frames).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.attribution.ports import (
    AcquiredCandidate,
    CoverReading,
    Decisions,
    Frame,
    VisualKind,
)
from thoth_control_plane.attribution.service import AttributionPorts


def parse_report(data: dict[str, Any]) -> SourceReport:
    return SourceReport.model_validate_json(json.dumps(data))


def frame_key(frame: Frame) -> tuple[str, float]:
    key, second = frame.jpeg.decode().rsplit(":", 1)
    return key, float(second)


class ReplayFrames:
    def __init__(self, frames: dict[str, list[dict[str, Any]]]) -> None:
        self._frames = frames
        self.calls: list[str] = []

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        self.calls.append(video.stem)
        if video.stem not in self._frames:
            raise FileNotFoundError(video.stem)
        return [
            Frame(entry["second"], f"{video.stem}:{entry['second']}".encode())
            for entry in self._frames[video.stem]
            if seconds is None or entry["second"] < seconds
        ]


class ReplayMatcher:
    def __init__(self, case: dict[str, Any]) -> None:
        self._matches: dict[str, list[int]] = case.get("matches", {})
        self._unmatchable = set(case.get("unmatchable", []))

    async def prepare(self, frames: Sequence[Frame]) -> str:
        key = frame_key(frames[0])[0]
        return "" if key in self._unmatchable else key

    async def compare(self, repost: str, candidate: str) -> list[int]:
        return list(self._matches.get(candidate, []))


class ReplayScenes:
    def __init__(self, cuts: list[float]) -> None:
        self._cuts = cuts

    async def cuts(self, video: Path) -> list[float]:
        return list(self._cuts)


class ReplayText:
    def __init__(self, frames: dict[str, list[dict[str, Any]]]) -> None:
        self._boxes = {
            (key, entry["second"]): entry.get("boxes", [])
            for key, entries in frames.items()
            for entry in entries
        }
        self.calls = 0

    async def read(self, frame: Frame) -> list[TextBox]:
        self.calls += 1
        return [
            TextBox(text, top, bottom)
            for text, top, bottom in self._boxes.get(frame_key(frame), [])
        ]


class ReplayVision:
    def __init__(self, cover: dict[str, Any], classify: dict[str, str]) -> None:
        self._cover = cover
        self._classify = classify
        self.calls = 0
        self.cover_seconds: list[float] = []

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading:
        self.calls += 1
        self.cover_seconds = [frame_key(frame)[1] for frame in frames]
        return CoverReading(**self._cover)

    async def classify(self, frames: Sequence[Frame]) -> VisualKind:
        self.calls += 1
        return self._classify.get(frame_key(frames[0])[0], "footage")  # type: ignore[return-value]


def ReplayVisionCover(case: dict[str, Any]) -> Any:
    """The case's cover reading as a bound coroutine, for fakes that fail only elsewhere."""

    async def read_cover(frames: Sequence[Frame]) -> CoverReading:
        return CoverReading(**case["cover"])

    return read_cover


class ReplayDecisions:
    def __init__(self, decisions: dict[str, Any]) -> None:
        self._decisions = decisions
        self.calls: list[tuple[dict[str, object], list[str]]] = []

    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions:
        self.calls.append((evidence, list(handles)))
        return Decisions(**self._decisions)


class ReplayDiscoverer:
    def __init__(self, discovery: dict[str, Any] | None) -> None:
        self._discovery = discovery
        self.calls: list[tuple[str, str]] = []

    def supports(self, platform: Platform) -> bool:
        return platform != "threads"

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        self.calls.append((platform, handle))
        if self._discovery is None:
            raise RuntimeError("discovery unavailable")
        # A capture records discovery per handle; a hand-written case lists one set for all.
        by_handle = self._discovery.get("by_handle")
        videos = by_handle.get(handle, []) if by_handle is not None else self._discovery["videos"]
        return [DiscoveredVideo.model_validate_json(json.dumps(video)) for video in videos]


class ReplayAcquirer:
    def __init__(self, acquired: dict[str, dict[str, Any]]) -> None:
        self._acquired = acquired
        self.acquired: list[str] = []
        self.discarded: list[str] = []

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        self.acquired.append(candidate_id)
        entry = self._acquired.get(url)
        if entry is None:
            return None
        video = Path(f"{entry['frames']}.mp4") if entry.get("frames") else None
        return AcquiredCandidate(candidate_id, parse_report(entry["report"]), video)

    async def discard(self, candidate_id: str) -> None:
        self.discarded.append(candidate_id)


def replay_ports(case: dict[str, Any]) -> AttributionPorts:
    frames = case["frames"]
    return AttributionPorts(
        frames=ReplayFrames(frames),
        matcher=ReplayMatcher(case),
        text=ReplayText(frames),
        discoverer=ReplayDiscoverer(case.get("discovery")),
        acquirer=ReplayAcquirer(case.get("acquired", {})),
        vision=ReplayVision(case["cover"], case.get("classify", {})),
        decisions=ReplayDecisions(case["decisions"]),
        scenes=ReplayScenes(case.get("cuts", [])),
    )
