"""Browser sessions run on their own event loop, in their own thread.

Playwright pumps every protocol message through Python on the loop that owns its connection. On
the worker's loop a burst of browser events held that loop past Temporal's 2 s deadlock limit
(TMPRL1101). On a loop of its own the browser still shares the GIL, but the worker's loop gets it
back every switch interval.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _browser_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="browser-loop", daemon=True).start()
            _loop = loop
    return _loop


async def on_browser_loop(work: Coroutine[Any, Any, T]) -> T:
    """Run `work` on the browser loop; cancelling the caller cancels it there too."""
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(work, _browser_loop()))


class LoopBoundSession:
    """A Scrapling-shaped session (`__aenter__`, `fetch`, `__aexit__`) built and driven on the
    browser loop; `page_setup` and `page_action` callbacks run there too."""

    def __init__(self, factory: Callable[..., Any], **kwargs: Any) -> None:
        self._factory = factory
        self._kwargs = kwargs
        self._session: Any = None

    async def __aenter__(self) -> LoopBoundSession:
        self._session = await on_browser_loop(self._enter())
        return self

    async def _enter(self) -> Any:
        session = self._factory(**self._kwargs)
        await session.__aenter__()
        return session

    async def __aexit__(self, *exc: object) -> Any:
        return await on_browser_loop(self._session.__aexit__(*exc))

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return await on_browser_loop(self._session.fetch(*args, **kwargs))
