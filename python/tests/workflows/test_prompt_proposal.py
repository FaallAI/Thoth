"""Tests for the ID-only prompt proposal workflow (C2)."""

from __future__ import annotations

from thoth_control_plane.config import Settings
from thoth_control_plane.domain.prompt_proposals import (
    PromptProposalWorkflowInput,
    PromptProposalWorkflowResult,
)
from thoth_control_plane.workflows.prompt_proposal import (
    PROMPT_PROPOSAL_TASK_QUEUE,
    PromptProposalWorkflow,
)


def test_task_queue_is_dedicated() -> None:
    assert PROMPT_PROPOSAL_TASK_QUEUE == "thoth-prompt-proposals"


def test_workflow_input_and_result_carry_only_safe_fields() -> None:
    workflow_input = PromptProposalWorkflowInput(proposal_id="proposal_1")
    assert workflow_input.model_dump(mode="json") == {"proposal_id": "proposal_1"}
    assert PromptProposalWorkflowResult is not None


def test_workflow_activity_invocation_uses_closed_retry_policy_and_timeout() -> None:
    """The workflow must call the activity once with no retry and 135s timeout."""
    import inspect

    source = inspect.getsource(PromptProposalWorkflow)
    assert "start_to_close_timeout=timedelta(seconds=135)" in source
    assert "RetryPolicy(maximum_attempts=1)" in source
    assert "PROMPT_PROPOSAL_TASK_QUEUE" in source
    assert "prompt text" not in source.lower()


def test_worker_builder_registers_the_proposal_worker() -> None:
    from thoth_control_plane.worker import build_prompt_proposal_worker

    assert callable(build_prompt_proposal_worker)


def test_a_provider_without_its_worker_secret_warns_and_keeps_the_worker(
    monkeypatch, caplog
) -> None:
    """The prompt worker shares the main worker's process: a missing key must not stop every run.

    The adapter refuses that provider per call (ProviderUnavailable), so only its proposals fail.
    """
    import logging

    import thoth_control_plane.worker as worker

    runtime_catalog = (
        {
            "provider_id": "novita",
            "label": "Novita",
            "protocol": "openai_compatible",
            "base_url": "https://api.novita.example/v1",
            "credential_id": "novita-main",
            "models": [
                {
                    "model_id": "deepseek/deepseek-v3.1",
                    "label": "DeepSeek V3.1",
                    "capabilities": ["improve", "translate"],
                    "max_input_chars": 12000,
                }
            ],
            "enabled": True,
        },
    )
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key",
        THOTH_PROMPT_PROVIDER_CATALOG=runtime_catalog,
        THOTH_PROMPT_PROVIDER_SECRETS={},
    )
    built: dict = {}
    monkeypatch.setattr(worker, "Worker", lambda client, **options: built.update(options))

    with caplog.at_level(logging.WARNING, logger="thoth_control_plane.worker"):
        worker.build_prompt_proposal_worker(client=None, settings=settings)

    assert built["task_queue"] == "thoth-prompt-proposals"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "novita" not in warnings[0]  # never name the provider or its credential


def test_the_prompt_worker_also_runs_story_assist(monkeypatch) -> None:
    import thoth_control_plane.worker as worker
    from thoth_control_plane.workflows.story_assist import StoryAssistWorkflow

    built: dict = {}
    monkeypatch.setattr(worker, "Worker", lambda client, **options: built.update(options))

    worker.build_prompt_proposal_worker(
        client=None, settings=Settings(THOTH_CONTROL_PLANE_API_KEY="k")
    )

    assert StoryAssistWorkflow in built["workflows"]
    assert "run_story_assist" in {
        activity.__temporal_activity_definition.name for activity in built["activities"]
    }
