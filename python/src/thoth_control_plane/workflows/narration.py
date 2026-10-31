"""A draft's narration as one durable workflow, and one beat's re-voice (spec 2026-10-31, 4).

transcribe -> write the script -> wait for the operator -> voice -> write the draft. Nothing is
voiced before an approval; a rejection writes the script again with the operator's note, and a
cancel at any point spends nothing further. The script step runs on the prompt queue, where the
provider credentials are.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from thoth_control_plane.domain.narration import (
        NarrationDecision,
        NarrationMark,
        NarrationRevoiceInput,
        NarrationScriptInput,
        NarrationStepInput,
        NarrationStepResult,
    )
    from thoth_control_plane.workflows.prompt_proposal import PROMPT_PROPOSAL_TASK_QUEUE

#: Per step: (activity name, timeout, attempts). The script makes one provider call per try.
_STEPS = {
    "narration_transcribe": (timedelta(minutes=15), 3),
    "narration_write_script": (timedelta(minutes=3), 1),
    "narration_voice": (timedelta(minutes=10), 3),
    "narration_write_draft": (timedelta(minutes=5), 3),
    "narration_revoice": (timedelta(minutes=5), 3),
}


async def _step(name: str, argument: object, *, queue: str | None = None) -> NarrationStepResult:
    timeout, attempts = _STEPS[name]
    return await workflow.execute_activity(
        name,
        argument,
        result_type=NarrationStepResult,
        start_to_close_timeout=timeout,
        retry_policy=RetryPolicy(maximum_attempts=attempts),
        task_queue=queue,
    )


async def _mark(document_id: str, status: str, code: str | None = None) -> None:
    await workflow.execute_activity(
        "narration_mark",
        NarrationMark(document_id=document_id, status=status, failure_code=code),  # type: ignore[arg-type]
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=RetryPolicy(maximum_attempts=5),
    )


@workflow.defn
class NarrationWorkflow:
    def __init__(self) -> None:
        self._awaiting = False
        self._decision: NarrationDecision | None = None
        self._cancel = False

    @workflow.run
    async def run(self, step: NarrationStepInput) -> str:
        try:
            return await self._narrate(step)
        except ActivityError:
            await _mark(step.document_id, "failed", "narration_failed")
            return "failed"

    async def _narrate(self, step: NarrationStepInput) -> str:
        if (await _step("narration_transcribe", step)).code:
            return "failed"
        note: str | None = None
        while True:
            if self._cancel:
                return await self._cancelled(step)
            script = await _step(
                "narration_write_script",
                NarrationScriptInput(**step.model_dump(), note=note),
                queue=PROMPT_PROPOSAL_TASK_QUEUE,
            )
            if script.code:
                return "failed"
            self._decision, self._awaiting = None, True
            await workflow.wait_condition(lambda: self._cancel or self._decision is not None)
            self._awaiting = False
            if self._cancel:
                return await self._cancelled(step)
            assert self._decision is not None
            if self._decision.decision == "approve":
                break
            note = self._decision.note
        if (await _step("narration_voice", step)).code:
            return "failed"
        if self._cancel:
            return await self._cancelled(step)
        await _step("narration_write_draft", step)
        return "completed"

    async def _cancelled(self, step: NarrationStepInput) -> str:
        await _mark(step.document_id, "cancelled")
        return "cancelled"

    @workflow.signal
    def decide(self, decision: NarrationDecision) -> None:
        # Only the first decision on a waiting script counts; a late or repeated one is ignored.
        if self._awaiting and self._decision is None:
            self._decision = decision

    @workflow.signal
    def cancel(self) -> None:
        self._cancel = True


@workflow.defn
class NarrationRevoiceWorkflow:
    @workflow.run
    async def run(self, step: NarrationRevoiceInput) -> str:
        result = await _step("narration_revoice", step)
        return "failed" if result.code else "completed"
