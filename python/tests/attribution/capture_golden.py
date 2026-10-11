"""Record one golden attribution case from live traffic (operator-authorized; plan Task 11).

Run only inside the capture container. It acquires the repost, runs attribution through
recording ports with a wide tuning (more finalists, no early exit), then records the OCR boxes
of every frame it saw, the matcher's inliers per candidate, and a visual class per candidate, so
a replay can use any tuning.
The fixture holds no key, no URL query, and no CDN address.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.policy import Mode, Outcome
from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.attribution.models import Platform
from thoth_control_plane.attribution.ports import (
    AcquiredCandidate,
    CoverReading,
    Decisions,
    Frame,
    VisualKind,
)
from thoth_control_plane.attribution.service import AttributionPorts, SourceAttributor, Tuning
from thoth_control_plane.infrastructure.source_account_store import AccountLease

# No candidate can reach 10,000 matched frames, so every finalist is acquired and recorded.
CAPTURE_TUNING = Tuning(max_finalists=5, finalist_concurrency=1, min_matched_frames=10_000)
WORKFLOW = "wf_golden"


def _plain(report: SourceReport) -> dict[str, Any]:
    trimmed = report.model_copy(update={"comments": [], "post_card": None, "profile_card": None})
    return json.loads(trimmed.model_dump_json())


class StaticLeases:
    """Sessions from cookie files, for the capture only: no store, no rotation, no cooldown.

    The mode is `fallback`, the production default: Instagram's profile parser reads the
    anonymous page and returns no_data on the signed-in one, so anonymous goes first.
    """

    def __init__(self, sessions: dict[str, SessionAccess]) -> None:
        self._sessions = sessions

    async def mode(self, platform: Platform) -> Mode:
        return "fallback" if platform in self._sessions else "anonymous"

    async def lease(self, platform: Platform) -> AccountLease | None:
        access = self._sessions.get(platform)
        if access is None:
            return None
        return AccountLease("capture", platform, access, datetime.now(UTC))

    async def release(self, lease: AccountLease, outcome: Outcome | None) -> None:
        return None


class _Store:
    def __init__(self) -> None:
        self.frames: dict[str, list[Frame]] = {}
        self.cover: CoverReading | None = None
        self.decisions: Decisions | None = None
        self.discovery: dict[str, list[DiscoveredVideo]] = {}
        self.acquired: dict[str, tuple[SourceReport, str | None]] = {}


class _Frames:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        frames = await self._inner.frames(video, fps=fps, seconds=seconds)
        self._store.frames[video.stem] = frames
        return frames


class _Vision:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def read_cover(self, frames: Sequence[Frame]) -> CoverReading | None:
        self._store.cover = await self._inner.read_cover(frames)
        return self._store.cover

    async def classify(self, frames: Sequence[Frame]) -> VisualKind | None:
        return await self._inner.classify(frames)


class _Decisions:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def decide(self, evidence: dict[str, object], handles: Sequence[str]) -> Decisions | None:
        self._store.decisions = await self._inner.decide(evidence, handles)
        return self._store.decisions


class _Discoverer:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    def supports(self, platform: Platform) -> bool:
        return self._inner.supports(platform)

    async def discover(self, platform: Platform, handle: str) -> list[DiscoveredVideo]:
        videos = await self._inner.discover(platform, handle)
        self._store.discovery[handle] = videos
        return videos


class _Acquirer:
    def __init__(self, inner: Any, store: _Store) -> None:
        self._inner, self._store = inner, store

    async def acquire(self, candidate_id: str, url: str) -> AcquiredCandidate | None:
        acquired = await self._inner.acquire(candidate_id, url)
        if acquired is not None:
            key = acquired.video.stem if acquired.video is not None else None
            self._store.acquired[url] = (acquired.report, key)
        return acquired

    async def discard(self, candidate_id: str) -> None:
        return None  # keep every candidate until its frames are recorded


async def record_case(
    ports: AttributionPorts,
    report: SourceReport,
    video: Path | None,
    *,
    case: str,
    expected: dict[str, Any],
    scout: dict[str, Any],
    departure: str | None = None,
) -> dict[str, Any]:
    store = _Store()
    recording = replace(
        ports,
        frames=_Frames(ports.frames, store),
        discoverer=_Discoverer(ports.discoverer, store),
        acquirer=_Acquirer(ports.acquirer, store),
        vision=_Vision(ports.vision, store) if ports.vision is not None else None,
        decisions=_Decisions(ports.decisions, store) if ports.decisions is not None else None,
    )
    await SourceAttributor(recording, CAPTURE_TUNING).identify(WORKFLOW, report, video)

    frames: dict[str, list[dict[str, Any]]] = {}
    for key, recorded in store.frames.items():
        entries = []
        for frame in recorded:
            boxes = await ports.text.read(frame)
            entries.append(
                {
                    "second": frame.second,
                    "boxes": [[box.text, round(box.top, 4), round(box.bottom, 4)] for box in boxes],
                }
            )
        frames[key] = entries
    prepared = {
        key: await ports.matcher.prepare(recorded)
        for key, recorded in store.frames.items()
        if recorded
    }
    repost_key = video.stem if video is not None else None
    repost = prepared.get(repost_key) if repost_key is not None else None
    matches = {
        key: await ports.matcher.compare(repost, value)
        for key, value in prepared.items()
        if repost and value and key != repost_key
    }
    classify: dict[str, str] = {}
    if ports.vision is not None:
        for _, key in store.acquired.values():
            if key is not None and store.frames.get(key):
                classify[key] = await ports.vision.classify(store.frames[key][:3]) or "unknown"
    return {
        "case": case,
        "synthetic": False,
        "report": _plain(report),
        "repost_frames": video.stem if video is not None else None,
        "frames": frames,
        "matches": matches,
        "unmatchable": sorted(key for key, value in prepared.items() if not value),
        "cover": store.cover.model_dump() if store.cover is not None else None,
        "classify": classify,
        "decisions": vars(store.decisions) if store.decisions is not None else None,
        "discovery": (
            {
                "by_handle": {
                    handle: [json.loads(item.model_dump_json()) for item in videos]
                    for handle, videos in store.discovery.items()
                }
            }
            if store.discovery
            else None
        ),
        "acquired": {
            url: {"report": _plain(acquired_report), "frames": key}
            for url, (acquired_report, key) in store.acquired.items()
        },
        "expected": expected,
        "scout": scout,
        **({"departure": departure} if departure else {}),
    }


async def _main(arguments: argparse.Namespace) -> None:
    from thoth_control_plane.acquisition.accounts.cookies import parse_cookies
    from thoth_control_plane.activities.source_attribution import _video, build_production_ports
    from thoth_control_plane.activities.source_investigation import (
        build_production_acquisition_runner,
    )
    from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer
    from thoth_control_plane.config import Settings

    # The capture container's own IP is rate-limited by TikTok's profile listing; a
    # session carries the operator's proxy when THOTH_CAPTURE_PROXY is set.
    proxy = os.environ.get("THOTH_CAPTURE_PROXY") or None
    sessions: dict[str, SessionAccess] = {}
    for entry in arguments.cookies:
        platform, _, path = entry.partition("=")
        text = Path(path).read_text(encoding="utf-8")
        sessions[platform] = SessionAccess(
            parse_cookies(platform, text, now=datetime.now(UTC)),  # type: ignore[arg-type]
            proxy,
        )

    with tempfile.TemporaryDirectory(prefix="thoth-golden-") as directory:
        root = Path(directory)
        settings = Settings(  # type: ignore[call-arg]
            THOTH_CONTROL_PLANE_API_KEY="capture-only", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=root
        )
        runner = build_production_acquisition_runner(settings)
        result = await runner(WORKFLOW, arguments.url, root)
        if result.report is None:
            code = result.failure.code if result.failure is not None else "unknown"
            raise SystemExit(f"repost acquisition failed: {code}")
        expected: dict[str, Any] = {
            "verdict": arguments.expect_verdict,
            "source_url": arguments.expect_source_url,
        }
        ports = replace(
            build_production_ports(settings, root),
            discoverer=ProfileDiscoverer(leases=StaticLeases(sessions)),
        )
        fixture = await record_case(
            ports,
            result.report,
            _video(result.report, root),
            case=arguments.case,
            expected=expected,
            scout={"main_url": arguments.scout_main_url, "note": arguments.scout_note},
            departure=arguments.departure,
        )
    Path(arguments.out).write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    counts = {key: len(value) for key, value in fixture["frames"].items()}
    print("recorded", arguments.case, "frames:", counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--expect-verdict", required=True, choices=["original", "replaced", "unresolved"]
    )
    parser.add_argument("--expect-source-url", default=None)
    parser.add_argument("--scout-main-url", default=None)
    parser.add_argument("--scout-note", default="")
    parser.add_argument("--departure", default=None)
    parser.add_argument("--cookies", action="append", default=[], help="platform=path")
    asyncio.run(_main(parser.parse_args()))
