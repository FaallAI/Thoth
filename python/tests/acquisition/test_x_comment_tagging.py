"""TAG_REPLIES_JS against a synthetic X reply list in a real browser; no network.

Skipped unless Playwright and a Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.acquisition.browser_support import async_api, launch
from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE
from thoth_control_plane.acquisition.x_service import (
    POST_CARD_SELECTOR,
    PROFILE_CARD_SELECTOR,
    TAG_REPLIES_JS,
)

ROW = "<article><div>Name</div><div>@{a}</div><div>{t}</div>{quote}</article>"
LINKED = '<article id="a{i}"><a href="/{a}/status/{i}">@{a}</a><div>{t}</div></article>'


def _list(rows: list[tuple[str, str, str]]) -> str:
    return "<main>" + "".join(ROW.format(a=a, t=t, quote=q) for a, t, q in rows) + "</main>"


async def _tag(html: str, targets: list[dict[str, str]]) -> tuple[Any, Any]:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
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


@pytest.mark.asyncio
async def test_the_post_selector_skips_the_parent_tweet() -> None:
    post_id = "1800000000000000001"
    parent = '<article id="parent"><a href="/parent_01/status/1700000000000000001">t</a></article>'
    post = f'<article id="post"><a href="/user_001/status/{post_id}">t</a></article>'
    reply = '<article id="reply"><a href="/fan_001/status/1800000000000000101">t</a></article>'
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page()
            await page.set_content(f"<main>{parent}{post}{reply}</main>")
            selector = POST_CARD_SELECTOR.format(post_id=post_id)
            found = await page.locator(selector).first.get_attribute("id")
        finally:
            await browser.close()
    assert found == "post"


@pytest.mark.asyncio
async def test_a_reply_row_is_the_one_linking_to_its_own_status() -> None:
    # The post (by the same author) also says "Yes" first; the reply's own link decides.
    post = LINKED.format(a="ann", i="1800000000000000001", t="Yesterday was great")
    reply = LINKED.format(a="ann", i="1800000000000000101", t="Yes")
    target = {"comment_id": "1800000000000000101", "author": "ann", "prefix": "Yes"}
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page()
            await page.set_content(f"<main>{post}{reply}</main>")
            tagged = await page.evaluate(TAG_REPLIES_JS, [target])
            owner = await page.eval_on_selector(
                f"[{COMMENT_ROW_ATTRIBUTE}]", "(e) => e.getAttribute('id')"
            )
        finally:
            await browser.close()
    assert (tagged, owner) == (["1800000000000000101"], "a1800000000000000101")


@pytest.mark.asyncio
async def test_the_profile_selector_fails_closed() -> None:
    blocks = "<main><div>a</div><div>b</div><div>c</div><div>Sign up today</div></main>"
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page()
            await page.set_content(blocks)
            selector = PROFILE_CARD_SELECTOR.format(owner="user_001")
            missing = await page.locator(selector).count()
            await page.set_content(blocks.replace("Sign up today", "Name @user_001 bio"))
            found = await page.locator(selector).count()
        finally:
            await browser.close()
    assert (missing, found) == (0, 1)
