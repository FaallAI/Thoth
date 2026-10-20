"""Temporal implementation of the workflow lifecycle gateway."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, TypeVar

from temporalio.client import (
    Client,
    WorkflowExecutionStatus,
    WorkflowHandle,
    WorkflowQueryFailedError,
)
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from thoth_control_plane.application import (
    ApprovalNotAllowed,
    ApprovalSubmission,
    WorkflowNotFound,
    WorkflowNotReady,
)
from thoth_control_plane.application.ports import RunClosed, RunExpired, RunLive, RunSettlement
from thoth_control_plane.auth.models import actor_workspace_id
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import (
    Actor,
    ActorSnapshot,
    ApprovalDecision,
    ApprovalSignal,
    SourceActivityMode,
    SourceInvestigationWorkflowInput,
    StylePreset,
    WorkflowEvent,
    WorkflowRequest,
    WorkflowSummary,
    request_snapshot_id,
    safe_workflow_source,
)
from thoth_control_plane.workflows.source_investigation import SourceInvestigationWorkflow

logger = logging.getLogger(__name__)
T = TypeVar("T")

TASK_QUEUE = "thoth-control-plane"


class TemporalWorkflowGateway:
    """Run application lifecycle operations against durable Temporal state."""

    def __init__(
        self,
        client: Client,
        *,
        activity_mode: SourceActivityMode = "python",
        attribute_source: bool = False,
        assemble_content: bool = False,
        build_footage: bool = False,
    ) -> None:
        self._client = client
        self._activity_mode = activity_mode
        self._attribute_source = attribute_source
        self._assemble_content = assemble_content
        self._build_footage = build_footage

    @property
    def client(self) -> Client:
        """Expose the connected client for additional task-queue workers/gateways."""
        return self._client

    @classmethod
    async def connect(cls, settings: Settings) -> TemporalWorkflowGateway:
        client = await Client.connect(
            settings.THOTH_TEMPORAL_TARGET,
            namespace=settings.THOTH_TEMPORAL_NAMESPACE,
            data_converter=pydantic_data_converter,
        )
        return cls(
            client,
            activity_mode=settings.source_investigation_activity_mode,
            attribute_source=settings.THOTH_SOURCE_ATTRIBUTION_ENABLED,
            assemble_content=settings.THOTH_CONTENT_ASSEMBLY_ENABLED,
            build_footage=settings.THOTH_FOOTAGE_ENABLED,
        )

    async def check_connection(self) -> bool:
        try:
            return await self._client.service_client.check_health()
        except RPCError:
            return False

    async def list_style_presets(self, *, actor: Actor) -> list[StylePreset]:
        del actor
        return [
            StylePreset(
                preset_id="news-vertical",
                label="News vertical",
                description="Fast-paced vertical news treatment",
            )
        ]

    async def start(
        self,
        request: WorkflowRequest,
        *,
        actor: Actor,
        idempotency_key: str,
    ) -> WorkflowSummary:
        workflow_id = _workflow_id(actor.actor_type, actor.actor_id, idempotency_key)
        requested_snapshot_id = request_snapshot_id(request)
        with suppress(WorkflowAlreadyStartedError):
            await self._client.start_workflow(
                SourceInvestigationWorkflow.run,
                args=[
                    SourceInvestigationWorkflowInput(
                        request_snapshot_id=requested_snapshot_id,
                        source=safe_workflow_source(request),
                        intent=request.source.intent,
                        actor=ActorSnapshot.model_validate(actor.model_dump()),
                        activity_mode=self._activity_mode,
                        attribute_source=self._attribute_source,
                        assemble_content=self._assemble_content,
                        build_footage=self._build_footage,
                    )
                ],
                id=workflow_id,
                task_queue=TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                memo={
                    "idempotency_key": idempotency_key,
                    "request_snapshot_id": requested_snapshot_id,
                    # The meter scope of every activity (spec 2026-10-20 metering, 1.2).
                    "workspace_id": actor_workspace_id(actor.actor_id),
                },
            )

        handle = await self._authorized_handle(workflow_id, actor)
        existing_snapshot_id = await _query(handle, SourceInvestigationWorkflow.request_snapshot_id)
        if existing_snapshot_id != requested_snapshot_id:
            from thoth_control_plane.application import IdempotencyConflict

            raise IdempotencyConflict
        return await _query(handle, SourceInvestigationWorkflow.summary)

    async def get(self, workflow_id: str, *, actor: Actor) -> WorkflowSummary:
        handle = await self._authorized_handle(workflow_id, actor)
        return await _query(handle, SourceInvestigationWorkflow.summary)

    async def settle(self, workflow_id: str) -> RunSettlement:
        """A run's state without the owner query, so a closed run is never replayed (P4).

        The caller authorizes through the stored run's actor before asking.
        """
        handle = self._client.get_workflow_handle(workflow_id, result_type=WorkflowSummary)
        try:
            description = await handle.describe()
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return RunExpired()
            raise WorkflowNotReady() from error
        if description.status == WorkflowExecutionStatus.RUNNING:
            return RunLive(await _query(handle, SourceInvestigationWorkflow.summary))
        if description.status == WorkflowExecutionStatus.COMPLETED:
            try:
                summary = await handle.result()
            except RPCError as error:
                # The history can expire, or Temporal go away, between describe and result.
                if error.status == RPCStatusCode.NOT_FOUND:
                    return RunExpired()
                raise WorkflowNotReady() from error
            return RunClosed(summary, summary.status.value)
        if description.status == WorkflowExecutionStatus.CANCELED:
            return RunClosed(None, "cancelled")
        return RunClosed(None, "failed")

    async def stream_events(
        self, workflow_id: str, *, actor: Actor, after_sequence: int
    ) -> AsyncIterator[WorkflowEvent]:
        """Replay durable lifecycle events only after the caller's cursor."""
        handle = await self._authorized_handle(workflow_id, actor)
        events = await _query(handle, SourceInvestigationWorkflow.workflow_events)
        for event in events:
            if event.sequence > after_sequence:
                yield event

    async def cancel(self, workflow_id: str, *, actor: Actor) -> WorkflowSummary:
        handle = await self._authorized_handle(workflow_id, actor)
        await handle.signal(SourceInvestigationWorkflow.request_cancel)
        return await _query(handle, SourceInvestigationWorkflow.summary)

    async def retry(
        self,
        workflow_id: str,
        *,
        from_stage: str | None,
        actor: Actor,
    ) -> WorkflowSummary:
        del workflow_id, from_stage, actor
        raise WorkflowNotReady("Durable workflow retry is not available")

    async def record_approval(
        self,
        workflow_id: str,
        approval: ApprovalSubmission,
        *,
        actor: Actor,
    ) -> WorkflowSummary:
        handle = await self._authorized_handle(workflow_id, actor)
        current = await _query(handle, SourceInvestigationWorkflow.summary)
        if (
            current.approval is None
            or current.approval.approval_id != approval.approval_id
            or approval.decision not in current.approval.allowed_decisions
        ):
            raise ApprovalNotAllowed
        await handle.signal(
            SourceInvestigationWorkflow.record_approval,
            ApprovalSignal(
                approval_id=approval.approval_id,
                decision=ApprovalDecision(decision=approval.decision, note=approval.note),
                actor=ActorSnapshot.model_validate(actor.model_dump()),
                decided_at=datetime.now(UTC),
            ),
        )
        return await _query(handle, SourceInvestigationWorkflow.summary)

    async def _authorized_handle(
        self, workflow_id: str, actor: Actor
    ) -> WorkflowHandle[WorkflowSummary]:
        handle: WorkflowHandle[WorkflowSummary] = self._client.get_workflow_handle(workflow_id)
        owner_actor = await _query(handle, SourceInvestigationWorkflow.owner_actor)
        if owner_actor.actor_id != actor.actor_id or owner_actor.actor_type != actor.actor_type:
            raise WorkflowNotFound
        return handle


def _workflow_id(actor_type: str, actor_id: str, idempotency_key: str) -> str:
    digest = sha256(f"{actor_type}\0{actor_id}\0{idempotency_key}".encode()).hexdigest()
    return f"wf_{digest[:24]}"


async def _query(handle: WorkflowHandle[Any], query: Callable[..., T]) -> T:
    """A query the worker could not answer (a TMPRL1101 stall, say) is "not ready, retry"."""
    try:
        return await handle.query(query)
    except RPCError as error:
        raise _mapped_rpc_error(error) from error
    except WorkflowQueryFailedError as error:
        logger.warning("workflow query failed workflow_id=%s reason=%s", handle.id, error)
        raise WorkflowNotReady() from error


def _mapped_rpc_error(error: RPCError) -> Exception:
    if error.status == RPCStatusCode.NOT_FOUND:
        return WorkflowNotFound()
    return WorkflowNotReady()
