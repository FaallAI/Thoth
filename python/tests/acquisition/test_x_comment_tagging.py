"""TAG_REPLIES_JS against a synthetic X reply list in a real browser; no network.

Skipped unless Playwright and a Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE
from thoth_control_plane.acquisition.x_service import TAG_REPLIES_JS

async_api = pytest.importorskip("playwright.async_api")

ROW = "<article><div>Name</div><div>@{a}</div><div>{t}</div>{quote}</article>"


def _list(rows: list[tuple[str, str, str]]) -> str:
    return "<main>" + "".join(ROW.format(a=a, t=t, quote=q) for a, t, q in rows) + "</main>"


async def _tag(html: str, targets: list[dict[str, str]]) -> tuple[Any, Any]:
    async with async_api.async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception:
            pytest.skip("no Chromium build installed")
        try:
            page = await browser.new_page()
            await page.set_content(html)
            tagged = await page.evaluate(TAG_REPLIES_JS, targets)
            rows = await page.eval_on_selector_all(
                f"[{COMMENT_ROW_ATTRIBUTE}]",
                f"els => els.map(e => [e.tagName, e.getAttribute('{COMMENT_ROW_ATTRIBUTE}')])",
            )
        finally:
            await browser.close()
    return tagged, rows


@pytest.mark.asyncio
async def test_identical_text_from_two_authors_tags_each_own_row() -> None:
    html = _list(
        [("user_001", "the post", ""), ("ann", "😢", ""), ("bob", "nice", ""), ("cid", "😢", "")]
    )
    targets = [
        {"comment_id": "1", "author": "ann", "prefix": "😢"},
        {"comment_id": "3", "author": "cid", "prefix": "😢"},
    ]
    tagged, rows = await _tag(html, targets)
    assert tagged == ["1", "3"]
    assert rows == [["ARTICLE", "1"], ["ARTICLE", "3"]]


@pytest.mark.asyncio
async def test_a_quoted_tweet_is_never_a_reply_row() -> None:
    quote = "<article><div>@cid</div><div>quoted words</div></article>"
    html = _list([("ann", "hello", quote)])
    target = {"comment_id": "9", "author": "cid", "prefix": "quoted words"}
    assert await _tag(html, [target]) == ([], [])


@pytest.mark.asyncio
async def test_a_handle_never_matches_a_longer_handle() -> None:
    html = _list([("anna", "same words", "")])
    target = {"comment_id": "9", "author": "ann", "prefix": "same words"}
    assert await _tag(html, [target]) == ([], [])
