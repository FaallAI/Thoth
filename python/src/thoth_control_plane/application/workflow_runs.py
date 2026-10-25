"""Record, list, settle, and move workflow runs (spec 2026-10-18, sections 3.3 and 3.4).

A run row is written when a workflow starts and settled when it is read, so the workflow code
stays untouched. Store calls run in `asyncio.to_thread`; the stores are synchronous.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from thoth_control_plane.application.estimates import estimate_seconds_remaining
from thoth_control_plane.application.ports import (
    RunClosed,
    RunLive,
    WorkflowRunsUnavailable,
)
from thoth_control_plane.application.workflows import (
    ArtifactNotFound,
    WorkflowApplicationError,
    WorkflowNotFound,
    WorkflowNotReady,
    WorkflowService,
)
from thoth_control_plane.auth.models import actor_workspace_id
from thoth_control_plane.billing import workflow_ref
from thoth_control_plane.domain import (
    Actor,
    ArtifactRef,
    WorkflowRequest,
    WorkflowStatus,
    WorkflowStepPage,
    WorkflowSummary,
)
from thoth_control_plane.domain.workflow_runs import (
    UNSETTLED,
    Inbox,
    InboxAccount,
    InboxRun,
    StoredRun,
    WorkflowRun,
    WorkflowRunPage,
)

logger = logging.getLogger(__name__)

#: At most this many unsettled rows of one page are asked about, concurrently.
SETTLE_LIMIT = 20
#: One slow settle must not hold the page: past this, the stored row is returned as is.
SETTLE_TIMEOUT_SECONDS = 3.0
#: The estimate's history input is cached this long per (actor, platform); the dashboard
#: polls `get` about once a second (run-progress spec 2026-10-25, G4).
ESTIMATE_CACHE_SECONDS = 60.0
#: One screen of attention per inbox list, not a ledger (spec G5).
INBOX_LIMIT = 20


def _known_status(run: StoredRun) -> dict[str, WorkflowStatus]:
    """The row's status when it is a real one: it outranks a stale live summary and P3's guess."""
    if run.status in {status.value for status in WorkflowStatus}:
        return {"status": WorkflowStatus(run.status)}
    return {}


def _inbox_run(run: StoredRun) -> InboxRun:
    failure = run.summary.failure if run.summary is not None else None
    return InboxRun(
        workflow_id=run.workflow_id,
        project_id=run.project_id,
        display_url=run.display_url,
        platform=run.platform,
        status=run.status,
        updated_at=run.updated_at,
        failure_code=failure.code if failure is not None else None,
    )


class ProjectNotFound(WorkflowApplicationError):
    """The project does not exist in the control plane."""

    default_detail = "project_not_found"


class RunNotFailed(WorkflowApplicationError):
    """The run is not in the failed state, so there is nothing to acknowledge."""

    default_detail = "run_not_failed"


class WorkflowRunService:
    def __init__(
        self,
        runs: Any,
        projects: Any,
        workflows: WorkflowService,
        gateway: Any,
        billing: Any = None,
        steps: Any = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runs = runs
        self._billing = billing
        self._projects = projects
        self._workflows = workflows
        self._gateway = gateway
        self._steps = steps
        self._monotonic = monotonic
        # ponytail: per-process estimate cache; the ceiling is one entry per
        # (actor, platform) in use, each at most 60 s stale.
        self._estimate_cache: dict[tuple[str, str, str], tuple[float, list[WorkflowSummary]]] = {}

    def _store(self) -> Any:
        if self._runs is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        return self._runs

    async def _require_project(self, project_id: str, actor: Actor) -> None:
        """The project must exist in the caller's workspace; a foreign one is not found."""
        if self._projects is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        workspace_id = actor_workspace_id(actor.actor_id)
        if await asyncio.to_thread(self._projects.get, project_id, workspace_id) is None:
            raise ProjectNotFound

    async def start(
        self,
        project_id: str | None,
        request: WorkflowRequest,
        *,
        actor: Actor,
        idempotency_key: str,
    ) -> WorkflowSummary:
        """Start, then record. A failed record answers 503; the client's retry reuses its key,
        Temporal returns the same workflow, and the row lands."""
        if project_id is not None:
            await self._require_project(project_id, actor)
        # The plan allowance (billing spec 1.4): admitted before Temporal ever starts.
        workspace = actor_workspace_id(actor.actor_id)
        ref = workflow_ref(actor.actor_type, actor.actor_id, idempotency_key)
        fresh = (
            await asyncio.to_thread(self._billing.consume, workspace, "workflow", ref)
            if self._billing is not None
            else False
        )
        try:
            summary = await self._workflows.start(
                request, actor=actor, idempotency_key=idempotency_key
            )
        except WorkflowNotReady:
            raise  # Temporal accepted the start; only reading it back stalled: the unit stays
        except BaseException:
            if fresh:  # only a unit this call took is given back
                await asyncio.to_thread(self._billing.release, workspace, "workflow", ref)
            raise
        if self._runs is None:
            if project_id is not None:
                raise WorkflowRunsUnavailable("workflow_runs_unavailable")
            return summary
        await asyncio.to_thread(
            self._runs.record_start, summary, project_id=project_id, actor=actor
        )
        return summary

    async def page(
        self,
        *,
        project_id: str | None,
        unassigned: bool,
        actor: Actor,
        cursor: str | None,
        limit: int,
    ) -> WorkflowRunPage:
        store = self._store()
        if project_id is not None:
            await self._require_project(project_id, actor)
        rows, next_cursor = await asyncio.to_thread(
            store.page,
            project_id=project_id,
            unassigned=unassigned,
            actor=actor,
            cursor=cursor,
            limit=limit,
        )
        due = [r for r in rows if r.status in UNSETTLED and not r.history_expired]
        settled = {
            run.workflow_id: run
            for run in await asyncio.gather(*(self._settle(r) for r in due[:SETTLE_LIMIT]))
        }
        return WorkflowRunPage(
            items=[settled.get(r.workflow_id, r).to_run() for r in rows],
            next_cursor=next_cursor,
        )

    async def _settle(self, run: StoredRun) -> StoredRun:
        try:
            outcome = await asyncio.wait_for(
                self._gateway.settle(run.workflow_id), timeout=SETTLE_TIMEOUT_SECONDS
            )
        except Exception as error:
            logger.warning(
                "run settle skipped workflow_id=%s reason=%s", run.workflow_id, type(error).__name__
            )
            return run
        if isinstance(outcome, RunLive):
            updated = run.with_(status=outcome.summary.status.value, summary=outcome.summary)
        elif isinstance(outcome, RunClosed):
            updated = run.with_(status=outcome.status, summary=outcome.summary or run.summary)
        else:
            summary = run.summary or await self._synthesized(run)
            updated = run.with_(history_expired=True, summary=summary)
        try:
            await asyncio.to_thread(
                self._store().settle,
                run.workflow_id,
                status=updated.status,
                summary=updated.summary,
                history_expired=updated.history_expired,
            )
        except WorkflowRunsUnavailable:
            logger.warning("run settle not saved workflow_id=%s", run.workflow_id)
        return updated

    async def _synthesized(self, run: StoredRun) -> WorkflowSummary:
        """A summary from the stored reports. Ruling P3: WorkflowSummary has no `unknown`, so it
        says `succeeded` (every backfilled run wrote its source report); the run list keeps the
        row's own status and `history_expired`."""
        artifacts: list[ArtifactRef] = await asyncio.to_thread(
            self._store().report_artifacts, run.workflow_id
        )
        return WorkflowSummary(
            workflow_id=run.workflow_id,
            status=_known_status(run).get("status", WorkflowStatus.SUCCEEDED),
            created_at=run.created_at,
            updated_at=run.updated_at,
            source={"display_url": run.display_url, "platform": run.platform},
            stages=[],
            artifacts=artifacts,
            history_expired=True,
        )

    async def steps(
        self, workflow_id: str, *, actor: Actor, after: int, limit: int
    ) -> WorkflowStepPage:
        """The run's recorded steps, in order. The dashboard polls this every second, so
        authorization comes from the run row and never queries Temporal (spec G3)."""
        if self._runs is None:
            return WorkflowStepPage(steps=[])
        run = await asyncio.to_thread(self._runs.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        if self._steps is None:
            return WorkflowStepPage(steps=[])
        return WorkflowStepPage(
            steps=await asyncio.to_thread(self._steps.page, workflow_id, after, limit)
        )

    async def get(self, workflow_id: str, *, actor: Actor) -> WorkflowSummary:
        try:
            summary = await self._workflows.get(workflow_id, actor=actor)
        except WorkflowNotFound:
            if self._runs is None:
                raise
            run = await asyncio.to_thread(self._runs.get, workflow_id)
            if run is None or not run.owned_by(actor):
                raise
            stored = run.summary or await self._synthesized(run)
            with_steps = await self._with_current_steps(
                stored.model_copy(update={"history_expired": True, **_known_status(run)})
            )
            return await self._with_estimate(with_steps, actor=actor)
        if self._runs is not None:
            try:
                await asyncio.to_thread(
                    self._runs.settle,
                    workflow_id,
                    status=summary.status.value,
                    summary=summary,
                    history_expired=False,
                )
            except WorkflowRunsUnavailable:
                logger.warning("run summary not saved workflow_id=%s", workflow_id)
        with_steps = await self._with_current_steps(summary)
        return await self._with_estimate(with_steps, actor=actor)

    async def _with_current_steps(self, summary: WorkflowSummary) -> WorkflowSummary:
        """Fill each running or waiting stage's current step, after settle, so a stored
        summary never holds it (spec G3). A step-store error costs only the field."""
        if self._steps is None or not any(
            stage.status in ("running", "waiting") for stage in summary.stages
        ):
            return summary
        try:
            current = await asyncio.to_thread(self._steps.current_steps, summary.workflow_id)
        except Exception as error:
            logger.warning(
                "current steps unavailable workflow_id=%s reason=%s",
                summary.workflow_id,
                type(error).__name__,
            )
            return summary
        return summary.model_copy(
            update={
                "stages": [
                    (
                        stage.model_copy(update={"current_step": current.get(stage.id)})
                        if stage.status in ("running", "waiting")
                        else stage
                    )
                    for stage in summary.stages
                ]
            }
        )

    async def _succeeded_histories(self, actor: Actor, platform: str) -> list[WorkflowSummary]:
        """The estimate's history input, cached briefly so a one-second dashboard poll
        does not hit the run store every time."""
        key = (actor.actor_type, actor.actor_id, platform)
        now = self._monotonic()
        cached = self._estimate_cache.get(key)
        if cached is not None and now - cached[0] < ESTIMATE_CACHE_SECONDS:
            return cached[1]
        histories = await asyncio.to_thread(self._store().recent_succeeded, actor, platform)
        self._estimate_cache[key] = (now, histories)
        return histories

    async def _with_estimate(self, summary: WorkflowSummary, *, actor: Actor) -> WorkflowSummary:
        """Fill the estimate after the current steps, never before them, and never inside
        `settle` (plan D2): a wait step must reach the math. A history-store error costs
        only the field."""
        if self._runs is None or summary.status not in (
            WorkflowStatus.RUNNING,
            WorkflowStatus.QUEUED,
        ):
            return summary
        try:
            histories = await self._succeeded_histories(actor, summary.source.platform)
        except Exception as error:
            logger.warning(
                "estimate histories unavailable workflow_id=%s reason=%s",
                summary.workflow_id,
                type(error).__name__,
            )
            return summary
        estimate = estimate_seconds_remaining(summary, histories, datetime.now(UTC))
        if estimate is None:
            return summary
        return summary.model_copy(update={"estimate_seconds_remaining": estimate})

    async def acknowledge(self, workflow_id: str, *, actor: Actor) -> None:
        """Clear a failed run from the inbox. Opening a run never acknowledges it; only
        this explicit action does (spec G5). A still-unsettled row is settled first, so a
        run that just failed can be acknowledged at once."""
        store = self._store()
        run = await asyncio.to_thread(store.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        if run.status in UNSETTLED and not run.history_expired:
            run = await self._settle(run)
        if run.status != "failed":
            raise RunNotFailed
        await asyncio.to_thread(store.acknowledge, workflow_id)

    async def inbox(
        self, *, actor: Actor, platform_admin: bool = False, accounts: Any = None
    ) -> Inbox:
        """The caller's attention list (spec G5, plan D4): approvals — after settling the
        actor's stale rows, like the run list — then unacknowledged failures, then source
        accounts in cooldown or expired for platform admins only. Without a run store the
        inbox is empty; without an account store the account list is."""
        if self._runs is None:
            return Inbox()
        store = self._runs
        due = await asyncio.to_thread(store.unsettled, actor, SETTLE_LIMIT)
        if due:
            await asyncio.gather(*(self._settle(run) for run in due))
        approvals = await asyncio.to_thread(store.awaiting_approval, actor, INBOX_LIMIT)
        failures = await asyncio.to_thread(store.unacknowledged_failures, actor, INBOX_LIMIT)
        return Inbox(
            approvals=[_inbox_run(run) for run in approvals],
            failures=[_inbox_run(run) for run in failures],
            accounts=await self._inbox_accounts(platform_admin, accounts),
        )

    async def _inbox_accounts(self, platform_admin: bool, accounts: Any) -> list[InboxAccount]:
        """Accounts in cooldown or expired, or still inside a cooldown clock. `disabled`
        is deliberate, so it never appears; no cookie, cookie name or proxy data leaves
        the store (spec G5, operator decision 2)."""
        if not platform_admin or accounts is None:
            return []
        try:
            views = await asyncio.to_thread(accounts.accounts)
        except Exception as error:
            logger.warning("inbox accounts unavailable reason=%s", type(error).__name__)
            return []
        now = datetime.now(UTC)
        listed: list[InboxAccount] = []
        for view in views:
            if view.status == "disabled":
                continue
            cooling = view.cooldown_until is not None and view.cooldown_until > now
            if view.status not in ("cooldown", "expired") and not cooling:
                continue
            listed.append(
                InboxAccount(
                    account_id=view.id,
                    platform=view.platform,
                    label=view.label,
                    status=view.status,
                    cooldown_until=view.cooldown_until,
                )
            )
        return listed

    async def get_artifact(
        self, workflow_id: str, artifact_id: str, *, actor: Actor
    ) -> ArtifactRef:
        summary = await self.get(workflow_id, actor=actor)
        for artifact in summary.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise ArtifactNotFound

    async def assign(self, workflow_id: str, project_id: str, *, actor: Actor) -> WorkflowRun:
        store = self._store()
        await self._require_project(project_id, actor)
        run = await asyncio.to_thread(store.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        moved = await asyncio.to_thread(store.assign, workflow_id, project_id)
        if moved is None:
            raise WorkflowNotFound
        return moved.to_run()
