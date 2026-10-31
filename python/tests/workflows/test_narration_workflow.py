"""The narration workflow: the approval gate, rejections, cancels and failures (Task 8)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from thoth_control_plane.domain.narration import (
    NarrationDecision,
    NarrationMark,
    NarrationRevoiceInput,
    NarrationScriptInput,
    NarrationStepInput,
    NarrationStepResult,
)
from thoth_control_plane.workflows.narration import NarrationRevoiceWorkflow, NarrationWorkflow
from thoth_control_plane.workflows.prompt_proposal import PROMPT_PROPOSAL_TASK_QUEUE

STEP = NarrationStepInput(project_id="project_001", document_id="edoc_1")


class Calls:
    def __init__(self, voice_fails: bool = False) -> None:
        self.names: list[str] = []
        self.notes: list[str | None] = []
        self.marks: list[NarrationMark] = []
        self.voice_fails = voice_fails
        self.scripted = asyncio.Event()

    def activities(self) -> list[object]:
        @activity.defn(name="narration_transcribe")
        async def transcribe(_: NarrationStepInput) -> NarrationStepResult:
            self.names.append("transcribe")
            return NarrationStepResult()

        @activity.defn(name="narration_write_script")
        async def script(step: NarrationScriptInput) -> NarrationStepResult:
            self.names.append("script")
            self.notes.append(step.note)
            self.scripted.set()
            return NarrationStepResult()

        @activity.defn(name="narration_voice")
        async def voice(_: NarrationStepInput) -> NarrationStepResult:
            self.names.append("voice")
            if self.voice_fails:
                raise RuntimeError("provider down")
            return NarrationStepResult()

        @activity.defn(name="narration_write_draft")
        async def write(_: NarrationStepInput) -> NarrationStepResult:
            self.names.append("write")
            return NarrationStepResult()

        @activity.defn(name="narration_revoice")
        async def revoice(step: NarrationRevoiceInput) -> NarrationStepResult:
            self.names.append(f"revoice:{step.beat}")
            return NarrationStepResult()

        @activity.defn(name="narration_mark")
        async def mark(value: NarrationMark) -> None:
            self.marks.append(value)

        return [transcribe, voice, write, revoice, mark, script]


@pytest_asyncio.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    environment = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    )
    try:
        yield environment
    finally:
        await environment.shutdown()


async def run_with(env: WorkflowEnvironment, calls: Calls, drive) -> str:  # type: ignore[no-untyped-def]
    activities = calls.activities()
    script = activities[-1]
    async with (
        Worker(
            env.client,
            task_queue="main",
            workflows=[NarrationWorkflow, NarrationRevoiceWorkflow],
            activities=activities[:-1],
        ),
        Worker(env.client, task_queue=PROMPT_PROPOSAL_TASK_QUEUE, activities=[script]),
    ):
        handle = await env.client.start_workflow(
            NarrationWorkflow.run, STEP, id="narration/edoc_1/1", task_queue="main"
        )
        await drive(handle)
        return await handle.result()


async def wait_scripted(calls: Calls) -> None:
    await asyncio.wait_for(calls.scripted.wait(), 10)
    calls.scripted.clear()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_nothing_is_voiced_until_the_script_is_approved(env: WorkflowEnvironment) -> None:
    calls = Calls()

    async def drive(handle):  # type: ignore[no-untyped-def]
        await wait_scripted(calls)
        assert "voice" not in calls.names
        await handle.signal(NarrationWorkflow.decide, NarrationDecision(decision="approve"))

    assert await run_with(env, calls, drive) == "completed"
    assert calls.names == ["transcribe", "script", "voice", "write"]


@pytest.mark.asyncio
async def test_a_rejection_writes_the_script_again_with_the_note(env: WorkflowEnvironment) -> None:
    calls = Calls()

    async def drive(handle):  # type: ignore[no-untyped-def]
        await wait_scripted(calls)
        await handle.signal(
            NarrationWorkflow.decide, NarrationDecision(decision="reject", note="Hook kurang tajam")
        )
        await wait_scripted(calls)
        await handle.signal(NarrationWorkflow.decide, NarrationDecision(decision="approve"))
        await handle.signal(NarrationWorkflow.decide, NarrationDecision(decision="approve"))

    assert await run_with(env, calls, drive) == "completed"
    assert calls.notes == [None, "Hook kurang tajam"]
    assert calls.names.count("voice") == 1


@pytest.mark.asyncio
async def test_a_cancel_while_waiting_spends_nothing_further(env: WorkflowEnvironment) -> None:
    calls = Calls()

    async def drive(handle):  # type: ignore[no-untyped-def]
        await wait_scripted(calls)
        await handle.signal(NarrationWorkflow.cancel)
        await handle.signal(NarrationWorkflow.decide, NarrationDecision(decision="approve"))

    assert await run_with(env, calls, drive) == "cancelled"
    assert "voice" not in calls.names
    assert [(mark.status, mark.failure_code) for mark in calls.marks] == [("cancelled", None)]


@pytest.mark.asyncio
async def test_a_voice_that_keeps_failing_ends_failed_without_writing(
    env: WorkflowEnvironment,
) -> None:
    calls = Calls(voice_fails=True)

    async def drive(handle):  # type: ignore[no-untyped-def]
        await wait_scripted(calls)
        await handle.signal(NarrationWorkflow.decide, NarrationDecision(decision="approve"))

    assert await run_with(env, calls, drive) == "failed"
    assert calls.names.count("voice") == 3 and "write" not in calls.names
    assert [(mark.status, mark.failure_code) for mark in calls.marks] == [
        ("failed", "narration_failed")
    ]


# --- Final review fixes (C1, I3, I4) ---


@pytest.mark.asyncio
async def test_a_workflow_cancelled_from_temporal_still_closes_its_narration(
    env: WorkflowEnvironment,
) -> None:
    calls = Calls()

    async def drive(handle):  # type: ignore[no-untyped-def]
        await wait_scripted(calls)
        await handle.cancel()

    with pytest.raises(Exception):  # noqa: B017 - the cancelled result itself raises
        await run_with(env, calls, drive)
    assert [(mark.status, mark.failure_code) for mark in calls.marks] == [("cancelled", None)]


@pytest.mark.asyncio
async def test_a_re_voice_voices_one_beat_then_writes_the_draft(env: WorkflowEnvironment) -> None:
    calls = Calls()
    activities = calls.activities()
    async with Worker(
        env.client,
        task_queue="main",
        workflows=[NarrationRevoiceWorkflow],
        activities=activities[:-1],
    ):
        result = await env.client.execute_workflow(
            NarrationRevoiceWorkflow.run,
            NarrationRevoiceInput(project_id="project_001", document_id="edoc_1", beat="main"),
            id="narration-revoice/edoc_1/main/1",
            task_queue="main",
        )
    assert result == "completed"
    assert calls.names == ["revoice:main", "write"]
