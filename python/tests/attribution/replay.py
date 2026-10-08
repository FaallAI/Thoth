"""Ports that answer from a recorded case; the service tests and golden fixtures share them.

A case maps frame keys to frames. A video path's stem names its key; a frame's JPEG bytes carry
`"<key>:<second>"`, so the hasher and the OCR reader can find what was recorded for it.
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


class ReplayHasher:
    def __init__(self, frames: dict[str, list[dict[str, Any]]]) -> None:
        self._hashes = {
            (key, entry["second"]): entry.get("hash")
            for key, entries in frames.items()
            for entry in entries
        }

    def hash(self, frame: Frame) -> int | None:
        value = self._hashes.get(frame_key(frame))
        return int(value, 16) if value else None


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
    def __init__(self, cover: dict[str, str] | None, classify: dict[str, str]) -> None:
        self._cover = cover
        self._classify = classify
        self.calls = 0

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None:
        self.calls += 1
        return CoverReading(**self._cover) if self._cover is not None else None

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None:
        self.calls += 1
        return self._classify.get(frame_key(frames[0])[0], "footage")  # type: ignore[return-value]


class ReplayDecisions:
    def __init__(self, decisions: dict[str, Any]) -> None:
        self._decisions = decisions
        self.calls: list[tuple[dict[str, object], list[str]]] = []

    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions | None:
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
        return [
            DiscoveredVideo.model_validate_json(json.dumps(video))
            for video in self._discovery["videos"]
        ]


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
        hasher=ReplayHasher(frames),
        text=ReplayText(frames),
        discoverer=ReplayDiscoverer(case.get("discovery")),
        acquirer=ReplayAcquirer(case.get("acquired", {})),
        vision=ReplayVision(case.get("cover"), case.get("classify", {}))
        if case.get("vision", True)
        else None,
        decisions=ReplayDecisions(case["decisions"]) if case.get("decisions") else None,
    )
