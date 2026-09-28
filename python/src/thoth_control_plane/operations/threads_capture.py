"""Operator-run, read-only Threads capture for the Stage 3a method comparison.

Never run by the test suite and only after the operator authorizes the capture. Reads
`<kind> <url>` lines (kind: video, image, text) from `--urls`, fetches each post once per
method, and writes one raw JSON per post plus the card PNG under `--out`. URLs, handles,
and bodies are never printed; stdout carries kinds, statuses, and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.adapters.threads import canonicalize_threads_post_url
from thoth_control_plane.acquisition.browser import HeadlessBrowserError
from thoth_control_plane.acquisition.threads_service import (
    RequestFetchError,
    ThreadsHeadlessBrowser,
    ThreadsRequestFetcher,
)

KINDS = ("video", "image", "text")


async def _capture(kind: str, url: str, out: Path) -> dict[str, Any]:
    identity = canonicalize_threads_post_url(url)
    target = str(identity.canonical_url)
    raw: dict[str, Any] = {
        "kind": kind,
        "post_id": identity.post_id,
        "owner": identity.owner_handle,
    }
    try:
        raw["request"] = {
            "status": "ok",
            "script_texts": await ThreadsRequestFetcher().fetch(target),
        }
    except RequestFetchError as error:
        raw["request"] = {"status": error.reason.value, "script_texts": []}
    browser = ThreadsHeadlessBrowser()
    try:
        page = await browser.fetch(target)
        raw["headless"] = {
            "status": "ok",
            "xhr_bodies": page.xhr_bodies,
            "script_texts": page.script_texts,
            "card": page.card_png is not None,
        }
        if page.card_png is not None:
            (out / f"{kind}-card.png").write_bytes(page.card_png)
    except HeadlessBrowserError as error:
        raw["headless"] = {
            "status": error.reason.value,
            "xhr_bodies": [],
            "script_texts": [],
            "card": False,
        }
    finally:
        await browser.close()
    (out / f"{kind}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return raw


async def _run(urls: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for line in urls.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        kind, url = line.split(maxsplit=1)
        if kind not in KINDS:
            print(json.dumps({"error": "unknown_kind"}))
            return 2
        raw = await _capture(kind, url.strip(), out)
        print(
            json.dumps(
                {
                    "kind": kind,
                    "request": [raw["request"]["status"], len(raw["request"]["script_texts"])],
                    "headless": [
                        raw["headless"]["status"],
                        len(raw["headless"]["xhr_bodies"]),
                        len(raw["headless"]["script_texts"]),
                        raw["headless"]["card"],
                    ],
                }
            )
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.urls, args.out))


if __name__ == "__main__":
    sys.exit(main())
