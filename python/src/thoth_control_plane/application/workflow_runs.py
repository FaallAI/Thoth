"""Record, list, settle, and move workflow runs (spec 2026-10-18, sections 3.3 and 3.4).

A run row is written when a workflow starts and settled when it is read, so the workflow code
stays untouched. Store calls run in `asyncio.to_thread`; the stores are synchronous.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
from thoth_control_plane.domain import Actor, ArtifactRef, WorkflowRequest, WorkflowSummary
from thoth_control_plane.domain.workflow_runs import (
    UNSETTLED,
    StoredRun,
    WorkflowRun,
    WorkflowRunPage,
)

logger = logging.getLogger(__name__)

#: At most this many unsettled rows of one page are asked about, concurrently.
SETTLE_LIMIT = 20


class ProjectNotFound(WorkflowApplicationError):
    """The project does not exist in the control plane."""

    default_detail = "project_not_found"


class WorkflowRunService:
    def __init__(
        self, runs: Any, projects: Any, workflows: WorkflowService, gateway: Any
    ) -> None:
        self._runs = runs
        self._projects = projects
        self._workflows = workflows
        self._gateway = gateway

    def _store(self) -> Any:
        if self._runs is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        return self._runs

    async def _require_project(self, project_id: str) -> None:
        if self._projects is None:
            raise WorkflowRunsUnavailable("workflow_runs_unavailable")
        if await asyncio.to_thread(self._projects.get, project_id) is None:
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
            await self._require_project(project_id)
        summary = await self._workflows.start(
            request, actor=actor, idempotency_key=idempotency_key
        )
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
            await self._require_project(project_id)
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
            outcome = await self._gateway.settle(run.workflow_id)
        except (WorkflowNotReady, WorkflowNotFound) as error:
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
            status="succeeded",
            created_at=run.created_at,
            updated_at=run.updated_at,
            source={"display_url": run.display_url, "platform": run.platform},
            stages=[],
            artifacts=artifacts,
            history_expired=True,
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
            return stored.model_copy(update={"history_expired": True})
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
        return summary

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
        await self._require_project(project_id)
        run = await asyncio.to_thread(store.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        moved = await asyncio.to_thread(store.assign, workflow_id, project_id)
        if moved is None:
            raise WorkflowNotFound
        return moved.to_run()
