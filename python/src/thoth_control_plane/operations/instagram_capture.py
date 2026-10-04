"""Operator-run, read-only Instagram capture for the Stage 3b method comparison.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, image, carousel, share, profile) from `--urls` and writes
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

from thoth_control_plane.acquisition.adapters.instagram import (
    CANONICAL_BASE,
    InstagramUrlError,
    canonical_instagram_share_url,
    canonicalize_instagram_post_url,
    parse_post,
)
from thoth_control_plane.acquisition.adapters.threads import _match_safe_path, json_roots
from thoth_control_plane.acquisition.browser import HeadlessBrowserError
from thoth_control_plane.acquisition.instagram_service import (
    InstagramHeadlessBrowser,
    InstagramRequestFetcher,
    comment_targets,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError

KINDS = ("video", "image", "carousel", "share", "profile")
SPACING_SECONDS = 5
PROFILE_PATH = re.compile(r"^/(?P<handle>[A-Za-z0-9._]{1,64})/?$")


async def _post(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_instagram_post_url(url)
    target = str(identity.canonical_url)
    raw: dict[str, Any] = {"kind": kind, "post_id": identity.post_id, "cards": None}
    try:
        texts = await InstagramRequestFetcher().fetch(target)
        raw["request"] = {"status": "ok", "script_texts": texts}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "script_texts": []}
    await asyncio.sleep(SPACING_SECONDS)
    browser = InstagramHeadlessBrowser()
    try:
        try:
            raw["headless"] = {"status": "ok", "script_texts": await browser.scripts(target)}
        except HeadlessBrowserError as error:
            raw["headless"] = {"status": error.reason.value, "script_texts": []}
        parsed = None
        for method in ("request", "headless"):
            parsed = parsed or parse_post(json_roots(raw[method]["script_texts"]), identity)
        if parsed is None:
            return raw
        targets = comment_targets(parsed.comments)
        await asyncio.sleep(SPACING_SECONDS)
        cards = await browser.cards(
            target,
            f"{CANONICAL_BASE}/{parsed.post.owner_handle}/",
            want_post=True,
            targets=targets,
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
        "comment_targets": len(targets),
        "profile": cards.profile_png is not None,
        "problems": cards.problems,
    }
    return raw


def _lands_on_post(url: str) -> bool:
    try:
        canonicalize_instagram_post_url(url)
    except InstagramUrlError:
        return False
    return True


async def _share(kind: str, url: str, out: Path) -> dict[str, Any]:
    share_url = canonical_instagram_share_url(url)
    raw: dict[str, Any] = {"kind": kind}
    try:
        landing = await InstagramRequestFetcher().landing(share_url)
        raw["request"] = {"status": "ok", "lands_on_post": _lands_on_post(landing)}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "lands_on_post": False}
    await asyncio.sleep(SPACING_SECONDS)
    browser = InstagramHeadlessBrowser()
    try:
        landing = await browser.resolve(share_url)
        raw["headless"] = {"status": "ok", "lands_on_post": _lands_on_post(landing)}
    except HeadlessBrowserError as error:
        raw["headless"] = {"status": error.reason.value, "lands_on_post": False}
    finally:
        await browser.close()
    return raw


async def _profile(kind: str, url: str, out: Path) -> dict[str, Any]:
    handle = _match_safe_path(url, PROFILE_PATH, "instagram", InstagramUrlError).group("handle")
    raw: dict[str, Any] = {"kind": kind, "handle": handle}
    try:
        texts = await InstagramRequestFetcher().fetch(f"{CANONICAL_BASE}/{handle}/")
        raw["request"] = {"status": "ok", "script_texts": texts}
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "script_texts": []}
    return raw


CAPTURES = {"share": _share, "profile": _profile}


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": raw["kind"]}
    for method in ("request", "headless"):
        capture = raw.get(method)
        if capture is None:
            continue
        detail = (
            {"script_texts": len(capture["script_texts"])}
            if "script_texts" in capture
            else {"lands_on_post": capture["lands_on_post"]}
        )
        summary[method] = {"status": capture["status"], **detail}
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
        try:
            raw = await CAPTURES.get(kind, _post)(kind, url.strip(), out)
        except InstagramUrlError:
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
