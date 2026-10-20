"""Usage metering (spec 2026-10-20 metering, section 2).

The meter scope says whose work runs now. A Temporal interceptor sets it for every activity, and
`current_actor` for every API request. `record` writes one usage event against it. The meter
never fails the work it measures: a sink error is a `warn`, and with no sink installed nothing
is recorded.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID

logger = logging.getLogger(__name__)

Kind = Literal[
    "account_lease", "workflow_completed", "video_rendered", "media_stored", "provider_call"
]
Unit = Literal[
    "session", "workflow", "second", "byte", "call", "token_in", "token_out", "character"
]
KINDS: frozenset[str] = frozenset(get_args(Kind))
UNITS: frozenset[str] = frozenset(get_args(Unit))


@dataclass(frozen=True)
class MeterScope:
    workspace_id: str
    workflow_id: str | None = None
    project_id: str | None = None


@dataclass(frozen=True)
class UsageRecord:
    workspace_id: str
    kind: str
    key: str
    quantity: float
    unit: str
    workflow_id: str | None = None
    project_id: str | None = None


class UsageSink(Protocol):
    def record(self, event: UsageRecord) -> None: ...
    def workspace_of_workflow(self, workflow_id: str) -> str | None: ...
    def workspace_of_project(self, project_id: str) -> str | None: ...


_scope: ContextVar[MeterScope | None] = ContextVar("thoth_meter_scope", default=None)
# ponytail: one process-wide sink; the API and the worker each install the editor database's.
_sink: UsageSink | None = None


def install(sink: UsageSink | None) -> None:
    global _sink
    _sink = sink


def installed() -> UsageSink | None:
    return _sink


def current_scope() -> MeterScope | None:
    return _scope.get()


def enter_scope(scope: MeterScope | None) -> None:
    """Set the scope for the rest of this task; each API request runs in its own task."""
    _scope.set(scope)


@contextlib.contextmanager
def scoped(scope: MeterScope | None) -> Iterator[None]:
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def record_sync(
    kind: str, key: str, quantity: float, unit: str, *, in_scope_only: bool = False
) -> None:
    sink = _sink
    if sink is None:
        return
    scope = _scope.get()
    if scope is None:
        if in_scope_only:
            return
        logger.warning("usage outside a meter scope recorded for the bootstrap kind=%s", kind)
        scope = MeterScope(BOOTSTRAP_WORKSPACE_ID)
    try:
        sink.record(
            UsageRecord(
                scope.workspace_id,
                kind,
                key[:200],
                float(quantity),
                unit,
                scope.workflow_id,
                scope.project_id,
            )
        )
    except Exception:
        logger.warning("usage event not recorded kind=%s", kind)


async def record(kind: str, key: str, quantity: float, unit: str) -> None:
    if _sink is None:
        return
    # to_thread copies the context, so the scope travels with the write.
    await asyncio.to_thread(record_sync, kind, key, quantity, unit)


async def record_call(
    key: str,
    *,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    characters: int | None = None,
) -> None:
    """One provider call, with what the provider reported about its size."""
    await record("provider_call", key, 1, "call")
    for unit, value in (
        ("token_in", tokens_in),
        ("token_out", tokens_out),
        ("character", characters),
    ):
        if isinstance(value, int) and value > 0:
            await record("provider_call", key, value, unit)


async def record_model_run(model: str, run: Any) -> None:
    metrics = getattr(run, "metrics", None)
    await record_call(
        model,
        tokens_in=getattr(metrics, "input_tokens", None),
        tokens_out=getattr(metrics, "output_tokens", None),
    )


def _lookup(call: Any, value: str) -> str | None:
    try:
        return call(value)
    except Exception:
        logger.warning("meter scope lookup unavailable")
        return None


def workflow_scope(workflow_id: str, memo_workspace: str | None = None) -> MeterScope:
    """The memo the gateway wrote at start, else the run row, else the bootstrap (spec 1.2)."""
    workspace = memo_workspace
    if workspace is None and _sink is not None:
        workspace = _lookup(_sink.workspace_of_workflow, workflow_id)
    if workspace is None:
        logger.warning("a workflow without a known workspace is metered for the bootstrap")
        workspace = BOOTSTRAP_WORKSPACE_ID
    return MeterScope(workspace, workflow_id=workflow_id)


def project_scope(project_id: str) -> MeterScope | None:
    if _sink is None:
        return None
    workspace = _lookup(_sink.workspace_of_project, project_id) or BOOTSTRAP_WORKSPACE_ID
    return MeterScope(workspace, project_id=project_id)


@dataclass(frozen=True)
class CostLine:
    kind: str
    key: str
    unit: str
    quantity: float
    usd: float | None


@dataclass(frozen=True)
class Estimate:
    lines: tuple[CostLine, ...]
    usd: float
    unpriced: tuple[CostLine, ...]


def estimate(totals: Sequence[Any], prices: Mapping[tuple[str, str, str], float]) -> Estimate:
    """Σ quantity × unit price; a key of `*` prices every key of its kind and unit."""
    lines = []
    for total in totals:
        price = prices.get((total.kind, total.key, total.unit))
        if price is None:
            price = prices.get((total.kind, "*", total.unit))
        usd = None if price is None else total.quantity * price
        lines.append(CostLine(total.kind, total.key, total.unit, total.quantity, usd))
    priced = math.fsum(line.usd for line in lines if line.usd is not None)
    return Estimate(tuple(lines), priced, tuple(line for line in lines if line.usd is None))
