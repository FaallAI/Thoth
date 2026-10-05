"""Operator-run, read-only YouTube capture for the Stage 3d evidence and golden fixtures.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, short, channel) from `--urls`. For a video it runs the
real extract, format choice, download, merge, and validation, then the card crops; for a
channel, the flat listings and the candidates' details. Raw JSON and card PNGs go under
`--out`; the merged video is validated and then deleted. URLs, handles, titles, and text are
never printed; stdout carries kinds, statuses, and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from thoth_control_plane.acquisition.adapters.threads import _match_safe_path
from thoth_control_plane.acquisition.adapters.youtube import (
    CANONICAL_BASE,
    YouTubeUrlError,
    canonicalize_youtube_url,
    channel_candidates,
    parse_info,
    select_formats,
    video_url,
)
from thoth_control_plane.acquisition.card_browser import comment_targets
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializationError,
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.models import AcquisitionStrategy
from thoth_control_plane.acquisition.youtube_discovery import GRID_SIZE, TABS
from thoth_control_plane.acquisition.youtube_service import (
    YouTubeHeadlessBrowser,
    YtDlpClient,
    YtDlpError,
)

KINDS = ("video", "short", "channel")
SPACING_SECONDS = 5
CHANNEL_PATH = re.compile(r"/@(?P<handle>[A-Za-z0-9._-]{1,64})/?")
MB = 1024 * 1024


def _bucket(size: int) -> str:
    """Size as a coarse bucket, never an exact value."""
    for limit in (10, 50, 100, 250, 450):
        if size < limit * MB:
            return f"<{limit}MB"
    return ">=450MB"


async def _video(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_youtube_url(url)
    client = YtDlpClient()
    raw: dict[str, Any] = {"kind": kind, "video_id": identity.video_id}
    try:
        info = await client.extract(str(identity.canonical_url), comments=True)
        raw["extract"] = {"status": "ok", "info": info}
    except YtDlpError as error:
        raw["extract"] = {"status": error.reason.value, "info": None}
        return raw
    parsed = parse_info(info, identity)
    choice = select_formats(info.get("formats"), parsed.duration_seconds if parsed else None)
    raw["media"] = {"choice": None, "valid": False}
    if parsed is None or choice is None:
        return raw
    raw["media"]["choice"] = {
        "short_side": choice.short_side,
        "estimate": _bucket(choice.estimated_bytes),
    }
    work = out / f"{kind}.download"
    try:
        work.mkdir(parents=True, exist_ok=True)
        merged = await client.download(str(identity.canonical_url), choice, work)
        async with httpx.AsyncClient() as http:
            location = PurePosixPath(f"{kind}-media")
            media = await MediaMaterializer(http, resolve_host_via_getaddrinfo).adopt(
                merged, work / location, location, AcquisitionStrategy.YT_DLP
            )
        raw["media"].update({"valid": True, "size": _bucket(media.bytes)})
    except MediaMaterializationError:
        raw["media"]["valid"] = False
    finally:
        shutil.rmtree(work, ignore_errors=True)
    await asyncio.sleep(SPACING_SECONDS)
    browser = YouTubeHeadlessBrowser()
    try:
        cards = await browser.cards(
            str(identity.canonical_url),
            parsed.channel_url,
            want_post=False,
            targets=comment_targets(parsed.comments),
        )
    finally:
        await browser.close()
    for n, png in enumerate(cards.comment_pngs.values(), start=1):
        (out / f"{kind}-comment-{n}.png").write_bytes(png)
    if cards.profile_png is not None:
        (out / f"{kind}-profile.png").write_bytes(cards.profile_png)
    raw["cards"] = {
        "comments": len(cards.comment_pngs),
        "comment_targets": len(parsed.comments),
        "profile": cards.profile_png is not None,
        "problems": cards.problems,
    }
    return raw


async def _channel(kind: str, url: str, out: Path) -> dict[str, Any]:
    handle = _match_safe_path(url, CHANNEL_PATH, "youtube", YouTubeUrlError).group("handle")
    client = YtDlpClient()
    raw: dict[str, Any] = {"kind": kind, "handle": handle, "listings": {}, "details": {}}
    for tab in TABS:
        try:
            listing = await client.listing(f"{CANONICAL_BASE}/@{handle}/{tab}", GRID_SIZE)
            raw["listings"][tab] = {"status": "ok", "listing": listing}
        except YtDlpError as error:
            raw["listings"][tab] = {"status": error.reason.value, "listing": None}
        await asyncio.sleep(SPACING_SECONDS)
    listings = [v["listing"] for v in raw["listings"].values() if v["listing"] is not None]
    for video_id in channel_candidates(listings, GRID_SIZE):
        try:
            raw["details"][video_id] = await client.extract(video_url(video_id), comments=False)
        except YtDlpError as error:
            raw["details"][video_id] = {"error": error.reason.value}
        await asyncio.sleep(SPACING_SECONDS)
    return raw


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": raw["kind"]}
    if "extract" in raw:
        info = raw["extract"]["info"] or {}
        formats = info.get("formats") or []
        summary["extract"] = {
            "status": raw["extract"]["status"],
            "comments": len(info.get("comments") or []),
            "formats": len(formats),
        }
    if "media" in raw:
        summary["media"] = raw["media"]
    if raw.get("cards") is not None:
        summary["cards"] = raw["cards"]
    if "listings" in raw:
        summary["listings"] = {
            tab: {
                "status": value["status"],
                "entries": len((value["listing"] or {}).get("entries") or []),
            }
            for tab, value in raw["listings"].items()
        }
        summary["details"] = {
            "count": len(raw["details"]),
            "ok": sum("error" not in detail for detail in raw["details"].values()),
        }
    return summary


async def _run(urls: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for line in urls.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in KINDS:
            print(json.dumps({"error": "unknown_kind"}))
            return 2
        kind, url = parts
        capture = _channel if kind == "channel" else _video
        try:
            raw = await capture(kind, url.strip(), out)
        except YouTubeUrlError:
            print(json.dumps({"kind": kind, "error": "invalid_source_url"}))
            return 2
        (out / f"{kind}.json").write_text(json.dumps(raw, default=str), encoding="utf-8")
        print(json.dumps(_summary(raw)))
        await asyncio.sleep(SPACING_SECONDS)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # Scrapling logs fetched URLs at info level; keep them out of the operator's terminal.
    logging.getLogger("scrapling").setLevel(logging.WARNING)
    return asyncio.run(_run(args.urls, args.out))


if __name__ == "__main__":
    sys.exit(main())
