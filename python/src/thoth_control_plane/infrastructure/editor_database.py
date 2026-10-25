"""One pooled engine per editor database for the ORM repositories (spec 2026-10-26, D2).

The psycopg repositories opened a new connection for every call; these share one small pool
per database URL. Sessions are synchronous like the other stores: async callers go through
`asyncio.to_thread`.
"""

from __future__ import annotations

import functools

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


@functools.cache
def editor_engine(database_url: str) -> Engine:
    url = make_url(database_url).set(drivername="postgresql+psycopg")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=4,
        hide_parameters=True,
        connect_args={"connect_timeout": 10},
    )


def editor_sessions(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(editor_engine(database_url), expire_on_commit=False)


def advisory_xact_lock(session: Session, first: str, second: str | int) -> None:
    """Hold a transaction-scoped advisory lock, keyed exactly as the psycopg repositories
    keyed it: `hashtext(first)` with `hashtext(second)`, or with an integer `second`."""
    key = func.hashtext(second) if isinstance(second, str) else second
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(first), key)))
