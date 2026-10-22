"""Style A crop geometry and selectors in a real browser; no network (spec 5c-2, Task 0 pages).

The JS is checked on synthetic pages with fixed sizes; the selectors on the pages recorded live
on 2026-10-22 (scripts, styles and query strings stripped). Skipped unless Playwright and a
Chromium build are installed (the acquisition extra).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition import instagram_service, x_service, youtube_service
from thoth_control_plane.acquisition.card_browser import MEDIA_BOX_JS, PROFILE_PAGE_JS, media_box
from thoth_control_plane.acquisition.models import MediaBox

async_api = pytest.importorskip("playwright.async_api")

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
        try:
            browser = await playwright.chromium.launch()
        except Exception:
            pytest.skip("no Chromium build installed")
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.set_content(html)
            return await page.evaluate(script, arg)
        finally:
            await browser.close()


async def _count(name: str, selector: str) -> int:
    async with async_api.async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch()
        except Exception:
            pytest.skip("no Chromium build installed")
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
    rect = await _run(GRID.format(items=items), PROFILE_PAGE_JS, [".head", ".item", 2])
    assert (rect["x"], rect["y"], rect["width"], rect["height"]) == (0, 0, 600, 800)


@pytest.mark.asyncio
async def test_profile_page_js_is_none_without_grid_items() -> None:
    rect = await _run(GRID.format(items=""), PROFILE_PAGE_JS, [".head", ".item", 2])
    assert rect is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page", "selector", "minimum"),
    [
        ("x-post", x_service.POST_CARD_SELECTOR.format(post_id=X_POST_ID), 1),
        ("x-post", x_service.POST_CARD_SELECTOR.format(post_id=X_POST_ID) + " video", 1),
        ("x-profile", x_service.PROFILE_CARD_SELECTOR.format(owner=X_OWNER), 1),
        ("x-profile", x_service.PROFILE_PAGE_ITEMS, 1),
        ("instagram-post", instagram_service.POST_CARD_SELECTOR, 1),
        ("instagram-post", instagram_service.POST_CARD_SELECTOR + " video", 1),
        ("instagram-profile", instagram_service.PROFILE_CARD_SELECTOR, 1),
        ("instagram-profile", instagram_service.PROFILE_PAGE_ITEMS, 6),
        ("youtube-profile", youtube_service.PROFILE_CARD_SELECTOR, 1),
        ("youtube-profile", youtube_service.PROFILE_PAGE_ITEMS, 6),
    ],
)
async def test_layout_selectors_match_the_recorded_pages(
    page: str, selector: str, minimum: int
) -> None:
    assert await _count(page, selector) >= minimum
