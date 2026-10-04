"""Operator-run, read-only X capture for the Stage 3c evidence and golden fixtures.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, image, text, replies, profile) from `--urls` and writes
one raw JSON per line plus the card PNGs under `--out`. URLs, handles, and bodies are never
printed; stdout carries kinds, statuses, and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.seroval import decode_scripts
from thoth_control_plane.acquisition.adapters.threads import _match_safe_path
from thoth_control_plane.acquisition.adapters.x import (
    CANONICAL_BASE,
    XUrlError,
    canonicalize_x_post_url,
    page_tweets,
    parse_page,
    post_url,
    syndication_author,
)
from thoth_control_plane.acquisition.card_browser import comment_targets
from thoth_control_plane.acquisition.threads_service import RequestFetchError
from thoth_control_plane.acquisition.x_service import XHeadlessBrowser, XRequestFetcher

KINDS = ("video", "image", "text", "replies", "profile")
SPACING_SECONDS = 5
PROFILE_PATH = re.compile(r"^/(?P<handle>[A-Za-z0-9_]{1,15})/?$")


async def _page(fetcher: XRequestFetcher, url: str) -> dict[str, Any]:
    try:
        return {"status": "ok", "html": await fetcher.page(url)}
    except RequestFetchError as error:
        return {"status": error.reason.value, "html": ""}


async def _post(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_x_post_url(url)
    fetcher = XRequestFetcher()
    raw: dict[str, Any] = {"kind": kind, "post_id": identity.post_id, "cards": None}
    try:
        data = await fetcher.syndication(identity.post_id)
        raw["syndication"] = {"status": "ok", "data": data}
    except RequestFetchError as error:
        raw["syndication"] = {"status": error.reason.value, "data": None}
    author = syndication_author(raw["syndication"]["data"])
    if author is None:
        return raw
    target = post_url(author, identity.post_id)
    await asyncio.sleep(SPACING_SECONDS)
    raw["page"] = await _page(fetcher, target)
    page = parse_page(decode_scripts(raw["page"]["html"]), identity)
    await asyncio.sleep(SPACING_SECONDS)
    browser = XHeadlessBrowser()
    try:
        cards = await browser.cards(
            target,
            f"{CANONICAL_BASE}/{author}",
            want_post=True,
            targets=comment_targets(page.comments),
        )
    finally:
        await browser.close()
    if cards.post_png is not None:
        (out / f"{kind}-post.png").write_bytes(cards.post_png)
    for n, png in enumerate(cards.comment_pngs.values(), start=1):
        (out / f"{kind}-comment-{n}.png").write_bytes(png)
    if cards.profile_png is not None:
        (out / f"{kind}-profile.png").write_bytes(cards.profile_png)
    raw["cards"] = {
        "post": cards.post_png is not None,
        "comments": len(cards.comment_pngs),
        "comment_targets": len(page.comments),
        "profile": cards.profile_png is not None,
        "problems": cards.problems,
    }
    return raw


async def _profile(kind: str, url: str, out: Path) -> dict[str, Any]:
    handle = _match_safe_path(url, PROFILE_PATH, "x", XUrlError).group("handle")
    raw: dict[str, Any] = {"kind": kind, "handle": handle}
    raw["page"] = await _page(XRequestFetcher(), f"{CANONICAL_BASE}/{handle}")
    return raw


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": raw["kind"]}
    syndication = raw.get("syndication")
    if syndication is not None:
        data = syndication["data"]
        summary["syndication"] = {
            "status": syndication["status"],
            "typename": data.get("__typename") if isinstance(data, dict) else None,
        }
    page = raw.get("page")
    if page is not None:
        tweets = page_tweets(decode_scripts(page["html"]))
        summary["page"] = {"status": page["status"], "decoded_tweets": len(tweets)}
    if raw.get("cards") is not None:
        summary["cards"] = raw["cards"]
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
        capture = _profile if kind == "profile" else _post
        try:
            raw = await capture(kind, url.strip(), out)
        except XUrlError:
            print(json.dumps({"kind": kind, "error": "invalid_source_url"}))
            return 2
        (out / f"{kind}.json").write_text(json.dumps(raw), encoding="utf-8")
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
