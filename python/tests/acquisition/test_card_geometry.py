"""Style A crop geometry and selectors in a real browser; no network (spec 5c-2, Task 0 pages).

The JS is checked on synthetic pages with fixed sizes; the selectors on the pages recorded live
on 2026-10-22 (scripts, styles and query strings stripped). Skipped unless Playwright and a
Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.acquisition.browser_support import async_api, launch
from thoth_control_plane.acquisition import (
    browser,
    discovery,
    instagram_service,
    threads_service,
    x_service,
    youtube_service,
)
from thoth_control_plane.acquisition.card_browser import MEDIA_BOX_JS, PROFILE_PAGE_JS, media_box
from thoth_control_plane.acquisition.models import MediaBox

PAGES = Path(__file__).parent / "pages"
X_POST_ID = "2110509448032862621"
X_OWNER = "InFebriyan128"

POST = """<style>body{margin:0}</style>
<div class="post" style="position:absolute;left:0;top:0;width:400px;height:800px">
  <img style="position:absolute;left:10px;top:10px;width:40px;height:40px">
  <video style="position:absolute;left:0;top:200px;width:400px;height:400px"></video>
</div>"""
GRID = """<style>body{{margin:0}}</style><div class="head" style="width:600px;height:200px"></div>
<div style="display:grid;grid-template-columns:repeat(3,200px)">{items}</div>"""


async def _run(html: str, script: str, arg: Any) -> Any:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.set_content(html)
            return await page.evaluate(script, arg)
        finally:
            await browser.close()


async def _count(name: str, selector: str) -> int:
    async with async_api.async_playwright() as playwright:
        browser = await launch(playwright)
        try:
            page = await browser.new_page()
            await page.route("**/*", lambda route: route.abort())
            html = (PAGES / f"{name}.html").read_text(encoding="utf-8")
            await page.set_content(html, wait_until="domcontentloaded")
            return await page.locator(selector).count()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_media_box_js_takes_the_large_media_and_skips_the_avatar() -> None:
    boxes = await _run(POST, MEDIA_BOX_JS, ".post")
    assert media_box(boxes["card"], boxes["media"]) == MediaBox(x=0.0, y=0.25, w=1.0, h=0.5)


@pytest.mark.asyncio
async def test_media_box_js_is_none_without_media() -> None:
    html = '<div class="post" style="width:400px;height:300px">text</div>'
    boxes = await _run(html, MEDIA_BOX_JS, ".post")
    assert boxes["media"] is None


@pytest.mark.asyncio
async def test_profile_page_js_covers_the_header_and_two_rows() -> None:
    items = "".join('<a class="item" style="height:300px;display:block"></a>' for _ in range(9))
    head = {"x": 0, "y": 0, "width": 600, "height": 200}
    rect = await _run(GRID.format(items=items), PROFILE_PAGE_JS, [head, ".item", 2])
    assert (rect["x"], rect["y"], rect["width"], rect["height"]) == (0, 0, 600, 800)


@pytest.mark.asyncio
async def test_profile_page_js_is_none_without_grid_items() -> None:
    head = {"x": 0, "y": 0, "width": 600, "height": 200}
    rect = await _run(GRID.format(items=""), PROFILE_PAGE_JS, [head, ".item", 2])
    assert rect is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page", "selector", "minimum"),
    [
        ("x-post", x_service.POST_CARD_SELECTOR.format(post_id=X_POST_ID), 1),
        ("x-post", x_service.POST_CARD_SELECTOR.format(post_id=X_POST_ID) + " video", 1),
        ("x-profile", x_service.PROFILE_PAGE_ITEMS, 1),
        ("instagram-post", instagram_service.POST_CARD_SELECTOR, 1),
        ("instagram-post", instagram_service.POST_CARD_SELECTOR + " video", 1),
        ("instagram-profile", instagram_service.PROFILE_CARD_SELECTOR, 1),
        ("instagram-profile", instagram_service.PROFILE_PAGE_ITEMS, 6),
        ("youtube-profile", youtube_service.PROFILE_CARD_SELECTOR, 1),
        ("youtube-profile", youtube_service.PROFILE_PAGE_ITEMS, 6),
        # The channel home tab, which the profile visit opens (Task 12).
        ("youtube-home", youtube_service.PROFILE_PAGE_ITEMS, 6),
        ("tiktok-post", '[data-media-card-description-container="true"]', 1),
        # Signed out the grid fails to load, so only the header is recorded; Task 12 checks the
        # grid in a signed-in visit (spec 5c-2).
        ("tiktok-profile", discovery.PROFILE_HEADER, 1),
    ],
)
async def test_layout_selectors_match_the_recorded_pages(
    page: str, selector: str, minimum: int
) -> None:
    assert await _count(page, selector) >= minimum


@pytest.mark.asyncio
async def test_tiktok_post_card_js_finds_the_caption_block_on_the_recorded_page() -> None:
    html = (PAGES / "tiktok-post.html").read_text(encoding="utf-8")
    rect = await _run(html, browser.POST_CARD_JS, None)
    assert rect is not None and rect["width"] > 0 and rect["height"] > 0


@pytest.mark.asyncio
async def test_hiding_the_threads_dialog_also_lifts_its_dimming_overlay() -> None:
    # Task 12: the dialog was hidden but its fixed backdrop still darkened the post card.
    html = (
        '<div id="overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.6)">'
        '<div><div role="dialog">Say more with Threads</div></div></div>'
        '<div data-pressable-container="true">the post</div>'
    )
    script = (
        threads_service.HIDE_DIALOGS_JS
        + "; (() => getComputedStyle(document.getElementById('overlay')).visibility)"
    )
    async with async_api.async_playwright() as playwright:
        chromium = await launch(playwright)
        try:
            page = await chromium.new_page()
            await page.set_content(html)
            await page.evaluate(threads_service.HIDE_DIALOGS_JS)
            hidden = await page.evaluate(
                "() => getComputedStyle(document.getElementById('overlay')).visibility"
            )
        finally:
            await chromium.close()
    assert script and hidden == "hidden"


async def _x_profile(owner: str) -> dict[str, Any]:
    """Tag the recorded X profile page for `owner`, then measure the tagged header and page."""
    async with async_api.async_playwright() as playwright:
        chromium = await launch(playwright)
        try:
            page = await chromium.new_page(viewport={"width": 1280, "height": 720})
            await page.route("**/*", lambda route: route.abort())
            html = (PAGES / "x-profile.html").read_text(encoding="utf-8")
            # `load`, then one snapshot: under CPU load the stripped page still reflows after
            # DOMContentLoaded, and two separate box reads could straddle that reflow.
            await page.set_content(html, wait_until="load")
            tagged = await page.evaluate(x_service.TAG_PROFILE_JS, owner)
            selector = x_service.PROFILE_CARD_SELECTOR
            count = await page.locator(selector).count()
            boxes = await page.evaluate(
                "(s) => [document.querySelector(s), document.querySelector('main article')]"
                ".map((e) => e && (({x, y, width, height}) => ({x, y, width, height}))"
                "(e.getBoundingClientRect()))",
                selector,
            )
            head, article = boxes
            rect = (
                await page.evaluate(PROFILE_PAGE_JS, [head, x_service.PROFILE_PAGE_ITEMS, 1])
                if head
                else None
            )
        finally:
            await chromium.close()
    return {"tagged": tagged, "count": count, "head": head, "article": article, "rect": rect}


@pytest.mark.asyncio
async def test_x_profile_tag_marks_the_header_on_the_recorded_page() -> None:
    found = await _x_profile(X_OWNER)
    assert found["tagged"] is True and found["count"] == 1
    head, article = found["head"], found["article"]
    assert head["height"] > 0 and head["y"] + head["height"] <= article["y"] + 1


@pytest.mark.asyncio
async def test_x_profile_tag_marks_nothing_without_the_owner() -> None:
    found = await _x_profile("nobody_here")
    assert found["tagged"] is False and found["count"] == 0


@pytest.mark.asyncio
async def test_the_x_page_card_finds_its_header_and_first_post_on_the_recorded_page() -> None:
    # The header is tagged by shape (spec 2026-10-23 G5); only its box reaches the page script.
    found = await _x_profile(X_OWNER)
    assert found["rect"] is not None and found["rect"]["height"] > found["head"]["height"]


@pytest.mark.asyncio
async def test_the_threads_backdrop_beside_the_dialog_is_hidden_too() -> None:
    # Live check 2026-10-22: the dimming layer is an empty fixed sibling at rgba(0,0,0,.7).
    html = (
        '<div id="backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,.7)"></div>'
        '<div style="position:fixed;inset:0"><div role="dialog">Say more with Threads</div></div>'
        '<div id="post" data-pressable-container="true">the post</div>'
    )
    async with async_api.async_playwright() as playwright:
        chromium = await launch(playwright)
        try:
            page = await chromium.new_page()
            await page.set_content(html)
            await page.evaluate(threads_service.HIDE_DIALOGS_JS)
            seen = await page.evaluate(
                "() => ['backdrop', 'post'].map(id => "
                "getComputedStyle(document.getElementById(id)).visibility)"
            )
        finally:
            await chromium.close()
    assert seen == ["hidden", "visible"]
