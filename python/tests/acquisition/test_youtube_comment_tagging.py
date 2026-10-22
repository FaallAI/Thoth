"""TAG_COMMENTS_JS against a synthetic YouTube comment list in a real browser; no network.

Skipped unless Playwright and a Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.acquisition.browser_support import async_api, launch
from thoth_control_plane.acquisition.card_browser import COMMENT_ROW_ATTRIBUTE
from thoth_control_plane.acquisition.youtube_service import TAG_COMMENTS_JS


def _thread(cid: str, author: str, text: str, reply: str = "") -> str:
    return (
        f'<ytd-comment-thread-renderer id="t{cid}"><ytd-comment-view-model id="c{cid}">'
        f'<a href="/{author}">{author}</a>'
        f'<a href="/watch?v=abcDEF123_-&lc={cid}">1 day ago</a><span>{text}</span>'
        f"</ytd-comment-view-model>{reply}</ytd-comment-thread-renderer>"
    )


async def _tag(html: str, targets: list[dict[str, str]]) -> tuple[Any, Any]:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page()
            await page.set_content(f"<div id='comments'>{html}</div>")
            tagged = await page.evaluate(TAG_COMMENTS_JS, targets)
            owners = await page.eval_on_selector_all(
                f"[{COMMENT_ROW_ATTRIBUTE}]", "els => els.map(e => e.id)"
            )
        finally:
            await browser.close()
    return tagged, owners


@pytest.mark.asyncio
async def test_each_comment_is_found_by_its_own_lc_link() -> None:
    html = _thread("UgzA", "@ann", "Yes") + _thread("UgzAB", "@ann", "Yesterday")
    targets = [
        {"comment_id": "UgzAB", "author": "ann", "prefix": "Yesterday"},
        {"comment_id": "UgzA", "author": "ann", "prefix": "Yes"},
    ]
    assert await _tag(html, targets) == (["UgzAB", "UgzA"], ["cUgzA", "cUgzAB"])


@pytest.mark.asyncio
async def test_the_comment_is_tagged_not_its_thread_of_replies() -> None:
    reply = '<div class="replies"><a href="/watch?v=abcDEF123_-&lc=UgzA.reply1">r</a></div>'
    tagged, owners = await _tag(
        _thread("UgzA", "@ann", "hello", reply),
        [{"comment_id": "UgzA", "author": "ann", "prefix": "hello"}],
    )
    assert (tagged, owners) == (["UgzA"], ["cUgzA"])


@pytest.mark.asyncio
async def test_without_a_link_the_author_and_text_decide() -> None:
    html = (
        '<ytd-comment-thread-renderer><ytd-comment-view-model id="c1">'
        "<div>@anna</div><div>same words</div></ytd-comment-view-model>"
        "</ytd-comment-thread-renderer>"
        '<ytd-comment-thread-renderer><ytd-comment-view-model id="c2">'
        "<div>@ann</div><div>same words</div></ytd-comment-view-model>"
        "</ytd-comment-thread-renderer>"
    )
    target = {"comment_id": "UgzZZ", "author": "ann", "prefix": "same words"}
    # The author and the text are separate blocks, as on YouTube; "@ann" must not match the
    # "@anna" thread above it.
    assert await _tag(html, [target]) == (["UgzZZ"], ["c2"])


@pytest.mark.asyncio
async def test_scrolling_continues_until_every_target_has_rendered() -> None:
    # Two threads are already on the page, but the target only loads after a scroll.
    html = (
        _thread("UgzA", "@ann", "one")
        + _thread("UgzB", "@bob", "two")
        + f'<template id="late">{_thread("UgzLATE", "@cat", "late one")}</template>'
        + '<div style="height: 5000px"></div>'
        + "<script>window.addEventListener('scroll', () => { if (!document.getElementById("
        + "'tUgzLATE')) document.getElementById('comments').appendChild("
        + "document.getElementById('late').content.cloneNode(true)); });</script>"
    )
    target = {"comment_id": "UgzLATE", "author": "cat", "prefix": "late one"}
    assert await _tag(html, [target]) == (["UgzLATE"], ["cUgzLATE"])
