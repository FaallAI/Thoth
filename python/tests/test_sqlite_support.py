"""The tests' SQLite engine is safe across threads (CI segfault, 2026-10-23)."""

from __future__ import annotations

import threading

from sqlalchemy import text

from tests.sqlite_support import sqlite_engine


def _connection_id(engine, seen: list[int]) -> None:
    raw = engine.raw_connection()
    try:
        seen.append(id(raw.driver_connection))
    finally:
        raw.close()


def test_each_thread_gets_its_own_connection() -> None:
    engine = sqlite_engine()
    seen: list[int] = []
    holder = engine.raw_connection()  # held open, so the pool cannot hand the same one back
    try:
        thread = threading.Thread(target=_connection_id, args=(engine, seen))
        thread.start()
        thread.join()
        assert seen and seen[0] != id(holder.driver_connection)
    finally:
        holder.close()


def test_threads_see_the_same_database() -> None:
    engine = sqlite_engine()
    with engine.begin() as connection:
        connection.execute(text("create table t (n integer)"))
        connection.execute(text("insert into t values (7)"))
    found: list[int] = []

    def read() -> None:
        with engine.connect() as connection:
            found.append(connection.execute(text("select n from t")).scalar_one())

    thread = threading.Thread(target=read)
    thread.start()
    thread.join()
    assert found == [7]


def test_engines_do_not_share_data() -> None:
    first, second = sqlite_engine(), sqlite_engine()
    with first.begin() as connection:
        connection.execute(text("create table only_here (n integer)"))
    with second.connect() as connection:
        names = connection.execute(text("select name from sqlite_master")).scalars().all()
    assert "only_here" not in names
