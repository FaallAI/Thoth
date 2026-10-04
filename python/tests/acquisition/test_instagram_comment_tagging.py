"""TAG_COMMENTS_JS against a synthetic comment list in a real browser; no network.

Skipped unless Playwright and a Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.instagram_service import (
    COMMENT_ROW_ATTRIBUTE,
    TAG_COMMENTS_JS,
)

async_api = pytest.importorskip("playwright.async_api")

ROW = (
    '<li><a href="/{a}/"><img src="data:," alt=""></a>'
    '<div><a href="/{a}/">{a}</a><span>{t}</span></div></li>'
)


def _list(rows: list[tuple[str, str]]) -> str:
    return "<ul>" + "".join(ROW.format(a=a, t=t) for a, t in rows) + "</ul>"


async def _tag(html: str, targets: list[dict[str, str]]) -> tuple[Any, Any]:
    async with async_api.async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception:
            pytest.skip("no Chromium build installed")
        try:
            page = await browser.new_page()
            await page.set_content(html)
            tagged = await page.evaluate(TAG_COMMENTS_JS, targets)
            rows = await page.eval_on_selector_all(
                f"[{COMMENT_ROW_ATTRIBUTE}]",
                f"els => els.map(e => [e.tagName, e.getAttribute('{COMMENT_ROW_ATTRIBUTE}')])",
            )
        finally:
            await browser.close()
    return tagged, rows


@pytest.mark.asyncio
async def test_identical_text_from_two_authors_tags_each_own_row() -> None:
    html = _list([("ann", "😢"), ("bob", "nice"), ("cid", "😢")])
    targets = [
        {"comment_id": "1", "author": "ann", "prefix": "😢"},
        {"comment_id": "3", "author": "cid", "prefix": "😢"},
    ]
    tagged, rows = await _tag(html, targets)
    # Never the whole list: a card is one comment's own row.
    assert tagged == ["1", "3"]
    assert rows == [["LI", "1"], ["LI", "3"]]


@pytest.mark.asyncio
async def test_a_comment_whose_author_has_no_row_is_not_tagged() -> None:
    html = _list([("ann", "same text"), ("bob", "other")])
    tagged, rows = await _tag(html, [{"comment_id": "9", "author": "bob", "prefix": "same"}])
    assert (tagged, rows) == ([], [])
