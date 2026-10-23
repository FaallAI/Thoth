"""A private SQLite database per test that threads can share safely.

The tests used one in-memory connection for every thread (`StaticPool` with
`check_same_thread=False`). A query run through `asyncio.to_thread` and one on the event loop
could then touch that connection at once, which crashed CI with a segfault (2026-10-23, PR #47).
A file gives each thread its own connection, and SQLite's file lock orders the writers.
"""

from __future__ import annotations

import shutil
import tempfile
import weakref
from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def sqlite_engine() -> Engine:
    """An empty database in its own temporary directory, removed with the engine."""
    directory = Path(tempfile.mkdtemp(prefix="thoth-sqlite-"))
    # `timeout` is SQLite's busy wait: a writer queues behind another thread instead of failing.
    engine = create_engine(f"sqlite:///{directory / 'test.db'}", connect_args={"timeout": 30})
    event.listen(engine, "connect", _fast)
    weakref.finalize(engine, shutil.rmtree, directory, True)
    return engine


def _fast(dbapi_connection, _record) -> None:
    """A throwaway database needs no durability: no fsync per commit (the suite ran twice as
    long with it), and WAL lets one thread read while another writes."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.close()
