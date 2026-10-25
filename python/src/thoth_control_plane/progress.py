"""Run-progress steps recorded from inside activities (spec 2026-10-25, G2).

A Temporal interceptor sets the scope (workflow id, stage, attempt) for every mapped activity,
like the meter scope. `step` writes one step against it, straight to Postgres — not through
heartbeats, which Temporal throttles by 30 s or more (spec section 3). The recorder never fails
the work it reports: a sink error is a `warn`, and with no sink installed nothing is recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from thoth_control_plane.domain.models import StepKind

logger = logging.getLogger(__name__)

#: The closed first-version catalogue (spec section 5): codes are `stage.name`, never renamed.
CATALOGUE: dict[str, StepKind] = {
    "source.read_link": "info",
    "source.fetch_post": "info",
    "source.download_media": "info",
    "source.capture_post_card": "info",
    "source.capture_comment_cards": "info",
    "source.gate_covered": "warning",
    "source.page_gap": "wait",
    "source.capture_embed_cards": "info",
    "source.capture_profile": "info",
    "source.login_wall": "warning",
    "source.save_report": "info",
    "attribution.read_text": "info",
    "attribution.ask_vision": "info",
    "attribution.search_candidates": "info",
    "attribution.compare_frames": "info",
    "attribution.verdict": "info",
    "footage.plan_queries": "info",
    "footage.search_platforms": "info",
    "footage.screen_clips": "info",
    "footage.creator_listing": "info",
    "footage.keep_clips": "info",
    "assembly.read_subtitles": "info",
    "assembly.judge_comments": "info",
    "assembly.find_figures": "info",
    "assembly.save_content_set": "info",
}

#: `params` holds a small whitelisted map; a URL, a cookie, a token or raw exception text
#: never matches it, so they cannot be stored even by mistake.
PARAM_KEYS = frozenset({"verdict", "platform", "count"})
PARAM_VALUE_PATTERN = re.compile(r"^[a-z0-9_.-]{1,40}$")

#: Progress updates of one code coalesce to at most one written row per this window. An update
#: inside the window is held, not dropped: it is written before the next step of another code,
#: when the window ends, or when the activity ends, so the current step never lags behind.
COALESCE_SECONDS = 1.0

#: Tests patch this clock; production reads the process-wide monotonic time.
_monotonic: Any = time.monotonic


@dataclass(frozen=True)
class StepScope:
    workflow_id: str
    stage: str
    attempt: int
    # The last written code and when, the held update and its timer: all inside this scope.
    coalesce: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    # The activity's event loop, which runs the timer that writes a held update; without
    # one, a held update waits for the next step or `flush`.
    loop: asyncio.AbstractEventLoop | None = field(default=None, compare=False, repr=False)
    # Steps may come from several threads (`to_thread`); writes stay in order per scope.
    lock: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)


@dataclass(frozen=True)
class StepRecord:
    at: datetime
    kind: StepKind
    code: str
    n: int | None = None
    total: int | None = None
    wait_until: datetime | None = None
    params: dict[str, str | int] | None = None


class StepSink(Protocol):
    def append(self, scope: StepScope, record: StepRecord) -> None: ...


_scope: ContextVar[StepScope | None] = ContextVar("thoth_step_scope", default=None)
# Strong references to running timer writes, so they are not collected mid-flight.
_flushes: set[asyncio.Task[None]] = set()
# ponytail: one process-wide sink; the worker installs the editor database's.
_sink: StepSink | None = None


def install(sink: StepSink | None) -> None:
    global _sink
    _sink = sink


def installed() -> StepSink | None:
    return _sink


def current_scope() -> StepScope | None:
    return _scope.get()


@contextlib.contextmanager
def scoped(scope: StepScope | None) -> Iterator[None]:
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def _kind_of(code: str, *, n: int | None, wait_until: datetime | None) -> StepKind:
    """The recorded kind (D2): a wait outranks a warning, which outranks progress."""
    if wait_until is not None:
        return "wait"
    if CATALOGUE[code] == "warning":
        return "warning"
    if n is not None:
        return "progress"
    return "info"


def _safe_params(
    params: Mapping[str, str | int] | None, *, code: str
) -> dict[str, str | int] | None:
    """The whitelisted map, or None when any key or value is outside it (D3)."""
    if params is None:
        return None
    safe: dict[str, str | int] = {}
    for key, value in params.items():
        allowed_value = isinstance(value, int) and not isinstance(value, bool)
        if key not in PARAM_KEYS or not (
            allowed_value or (isinstance(value, str) and PARAM_VALUE_PATTERN.fullmatch(value))
        ):
            logger.warning("step params dropped: outside the whitelist code=%s", code)
            return None
        safe[key] = value
    return safe or None


def _coalesced(scope: StepScope, code: str, *, n: int | None, total: int | None) -> bool:
    """True when this progress update repeats the last written code inside the window."""
    if n is not None and total is not None and n == total:
        return False
    if scope.coalesce.get("code") != code:
        return False
    written_at = scope.coalesce.get("at")
    return written_at is not None and (_monotonic() - written_at) < COALESCE_SECONDS


def step_sync(
    code: str,
    *,
    n: int | None = None,
    total: int | None = None,
    wait_until: datetime | None = None,
    params: Mapping[str, str | int] | None = None,
) -> None:
    """Record one step synchronously; the write blocks, so call it only from a worker
    thread (`to_thread`), never from an event-loop thread — use `step` there."""
    sink = _sink
    if sink is None:
        logger.debug("step not recorded, no sink code=%s", code)
        return
    scope = _scope.get()
    if scope is None:
        logger.debug("step not recorded, no scope code=%s", code)
        return
    if code not in CATALOGUE:
        logger.warning("unknown step code dropped code=%s", code)
        return
    if code.split(".", 1)[0] != scope.stage:
        logger.warning("step outside its scope's stage dropped code=%s", code)
        return
    kind = _kind_of(code, n=n, wait_until=wait_until)
    record = StepRecord(
        at=datetime.now(UTC),
        kind=kind,
        code=code,
        n=n,
        total=total,
        wait_until=wait_until,
        params=_safe_params(params, code=code),
    )
    with scope.lock:
        held = kind == "progress" and _coalesced(scope, code, n=n, total=total)
        if held:
            scope.coalesce["pending"] = record  # the newest update of this code wins
        else:
            pending = scope.coalesce.pop("pending", None)
            if pending is not None and pending.code != code:
                _write(sink, scope, pending)  # older, so it goes first
            _write(sink, scope, record)  # a held update of this code is superseded
    if held and scope.loop is not None:
        scope.loop.call_soon_threadsafe(_arm, scope)


def _write(sink: StepSink, scope: StepScope, record: StepRecord) -> None:
    """Write one step; the caller holds the scope's lock."""
    try:
        sink.append(scope, record)
    except Exception:
        logger.warning("step not recorded code=%s", record.code)
    else:
        scope.coalesce["code"] = record.code
        scope.coalesce["at"] = _monotonic()


def _arm(scope: StepScope) -> None:
    """On the loop: write the held update when the window ends, unless a timer already will."""
    if scope.loop is None or scope.coalesce.get("timer") is not None:
        return
    written_at = scope.coalesce.get("at", _monotonic())
    delay = max(0.0, COALESCE_SECONDS - (_monotonic() - written_at))
    scope.coalesce["timer"] = scope.loop.call_later(delay, _fire, scope)


def _fire(scope: StepScope) -> None:
    scope.coalesce["timer"] = None
    task = asyncio.ensure_future(asyncio.to_thread(flush_sync, scope))
    _flushes.add(task)
    task.add_done_callback(_flushes.discard)


def flush_sync(scope: StepScope) -> None:
    """Write the scope's held update, if any."""
    sink = _sink
    if sink is None:
        return
    with scope.lock:
        pending = scope.coalesce.pop("pending", None)
        if pending is not None:
            _write(sink, scope, pending)


async def flush(scope: StepScope) -> None:
    """Called when the activity ends: cancel the timer and write the held update now."""
    timer = scope.coalesce.pop("timer", None)
    if timer is not None:
        timer.cancel()
    if scope.coalesce.get("pending") is not None:
        await asyncio.to_thread(flush_sync, scope)


async def step(
    code: str,
    *,
    n: int | None = None,
    total: int | None = None,
    wait_until: datetime | None = None,
    params: Mapping[str, str | int] | None = None,
) -> None:
    """Record one step from inside an activity; never raises into the work."""
    if _sink is None:
        return
    # to_thread copies the context, so the scope travels with the write.
    await asyncio.to_thread(step_sync, code, n=n, total=total, wait_until=wait_until, params=params)
