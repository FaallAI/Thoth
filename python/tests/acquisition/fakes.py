"""Shared fakes for card-browser and acquirer tests: no Scrapling, no network."""

from __future__ import annotations

from typing import Any

from tests.acquisition.png_fixtures import make_png
from thoth_control_plane.acquisition.materializer import MediaMaterializationError
from thoth_control_plane.acquisition.models import MaterializedMedia


class FakeLocator:
    def __init__(self, page: FakeCardPage, selector: str) -> None:
        self.first, self._page, self._selector = self, page, selector

    async def click(self, timeout: int) -> None:
        self._page.clicked.append(self._selector)

    async def scroll_into_view_if_needed(self, timeout: int) -> None:
        return None

    async def screenshot(self, timeout: int) -> bytes:
        self._page.shots.append(self._selector)
        return make_png(400, 200)


class FakeCardPage:
    """A page whose tagging script tags `tagged`; records clicks, shots, and scripts."""

    def __init__(self, url: str, tagged: list[str] | None = None) -> None:
        self.url, self.tagged = url, tagged or []
        self.clicked: list[str] = []
        self.shots: list[str] = []
        self.evaluated: list[tuple[str, object]] = []

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    async def evaluate(self, script: str, arg: object) -> list[str]:
        self.evaluated.append((script, arg))
        return self.tagged


class FakeActive:
    def __init__(self, pages: dict[str, FakeCardPage]) -> None:
        self.pages, self.visits = pages, []

    async def fetch(self, url: str, **kwargs: Any) -> Any:
        self.visits.append(url)
        page = self.pages[url]
        if kwargs.get("page_action") is not None:
            await kwargs["page_action"](page)
        return page


class FakeSession:
    def __init__(self, active: Any = None, enter_error: Exception | None = None) -> None:
        self.active, self.enter_error, self.exited = active, enter_error, 0

    async def __aenter__(self) -> Any:
        if self.enter_error is not None:
            raise self.enter_error
        return self.active

    async def __aexit__(self, *exc: object) -> None:
        self.exited += 1


def card_session(pages: dict[str, FakeCardPage]) -> FakeSession:
    return FakeSession(FakeActive(pages))


class FakeMaterializer:
    """Writes a placeholder file per item; raises at `fail_at` like a failed validation."""

    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at

    async def materialize(
        self, candidate, destination, relative_location, strategy, *, media_id="media_1", index=1
    ):
        if index == self.fail_at:
            raise MediaMaterializationError()
        video = candidate.kind == "video"
        suffix = ".mp4" if video else ".jpg"
        destination.with_suffix(suffix).parent.mkdir(parents=True, exist_ok=True)
        destination.with_suffix(suffix).write_bytes(b"x")
        return MaterializedMedia(
            media_id=media_id,
            kind=candidate.kind,
            index=index,
            location=relative_location.with_suffix(suffix),
            media_type="video/mp4" if video else "image/jpeg",
            bytes=20_000 if video else 5_000,
            checksum="sha256:" + "0" * 64,
            acquisition_strategy=strategy,
        )
