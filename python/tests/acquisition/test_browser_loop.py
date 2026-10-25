"""Browser sessions run on their own event loop, so a busy browser never stalls the worker's."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from thoth_control_plane import progress as thoth_progress
from thoth_control_plane.acquisition import browser, instagram_reels
from thoth_control_plane.acquisition.browser_loop import LoopBoundSession, on_browser_loop


class _Session:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.threads: list[int] = []

    async def __aenter__(self) -> _Session:
        self.threads.append(threading.get_ident())
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.threads.append(threading.get_ident())

    async def fetch(self, url: str, *, page_action: Any = None) -> str:
        self.threads.append(threading.get_ident())
        if page_action is not None:
            await page_action(url)
        return url


async def test_a_busy_browser_never_holds_the_callers_loop() -> None:
    built: list[_Session] = []

    def factory(**kwargs: Any) -> _Session:
        built.append(_Session(**kwargs))
        return built[-1]

    async def busy(page: Any) -> None:
        time.sleep(0.5)  # a burst of protocol dispatch: Python running on the browser's loop

    gaps: list[float] = []

    async def heartbeat() -> None:
        while True:
            before = time.monotonic()
            await asyncio.sleep(0.01)
            gaps.append(time.monotonic() - before)

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)
    async with LoopBoundSession(factory, headless=True) as session:
        assert (
            await session.fetch("https://example.test/", page_action=busy)
            == "https://example.test/"
        )
    await asyncio.sleep(0.05)
    beat.cancel()

    assert max(gaps) < 0.2
    assert built[0].kwargs == {"headless": True}
    assert len(built[0].threads) == 3
    assert threading.get_ident() not in built[0].threads


async def test_errors_and_cancellation_cross_the_loop_boundary() -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class _Slow(_Session):
        async def fetch(self, url: str, *, page_action: Any = None) -> str:
            if url == "boom":
                raise RuntimeError("boom")
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return url

    async with LoopBoundSession(_Slow) as session:
        with pytest.raises(RuntimeError, match="boom"):
            await session.fetch("boom")
        task = asyncio.create_task(session.fetch("slow"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(cancelled.wait, 2)


def test_the_default_browser_session_is_loop_bound() -> None:
    assert isinstance(browser._default_session_factory(headless=True), LoopBoundSession)
    assert instagram_reels._default_session_factory is browser._default_session_factory


async def test_the_step_scope_reaches_the_browser_loop() -> None:
    """Run-progress guard (phase 3, task 1): a step recorded from a page action that runs
    on the browser loop still carries the activity's scope, so the card emissions there
    are recorded. If this ever fails, the card instrumentation must stop relying on it."""
    records: list[tuple[thoth_progress.StepScope, thoth_progress.StepRecord]] = []

    class Sink:
        def append(self, scope, record) -> None:
            records.append((scope, record))

    thoth_progress.install(Sink())
    try:
        scope = thoth_progress.StepScope(workflow_id="wf_loop", stage="source", attempt=1)
        with thoth_progress.scoped(scope):
            await on_browser_loop(work())
    finally:
        thoth_progress.install(None)

    assert [(scope, record.code) for scope, record in records] == [
        (scope, "source.read_link")
    ]


async def work() -> None:
    await thoth_progress.step("source.read_link")


async def test_step_sync_from_a_thread_inside_the_scope_is_recorded() -> None:
    records: list[tuple[thoth_progress.StepScope, thoth_progress.StepRecord]] = []

    class Sink:
        def append(self, scope, record) -> None:
            records.append((scope, record))

    thoth_progress.install(Sink())
    try:
        scope = thoth_progress.StepScope(workflow_id="wf_thread", stage="source", attempt=1)
        with thoth_progress.scoped(scope):
            await asyncio.to_thread(thoth_progress.step_sync, "source.read_link")
    finally:
        thoth_progress.install(None)

    assert [(scope, record.code) for scope, record in records] == [
        (scope, "source.read_link")
    ]
