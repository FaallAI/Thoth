"""Run metrics count only Content Sets that were made (restyle spec §6, B4)."""

import json
from datetime import UTC, datetime

from thoth_control_plane.domain import WorkflowSummary
from thoth_control_plane.domain.workflow_runs import StoredRun, run_metrics

T0 = datetime(2026, 10, 26, 8, tzinfo=UTC)


def run(workflow_id: str, artifact_kinds: list[str]) -> StoredRun:
    summary = WorkflowSummary.model_validate_json(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "status": "succeeded",
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
                "source": {"display_url": "https://x.test/v", "platform": "tiktok"},
                "stages": [],
                "artifacts": [
                    {
                        "artifact_id": f"art_{kind}",
                        "kind": kind,
                        "label": kind,
                        "media_type": "application/json",
                        "location": f"reports/{workflow_id}/{kind}.json",
                    }
                    for kind in artifact_kinds
                ],
            }
        )
    )
    return StoredRun(
        workflow_id=workflow_id,
        project_id=None,
        actor_type="user",
        actor_id="owner",
        display_url="https://x.test/v",
        platform="tiktok",
        status="succeeded",
        history_expired=False,
        summary=summary,
        created_at=T0,
        updated_at=T0,
    )


def test_content_sets_count_runs_that_made_one() -> None:
    metrics = run_metrics(
        [
            run("wf_a", ["source_report", "content_set"]),
            run("wf_b", ["source_report"]),
            run("wf_c", ["content_set"]),
        ]
    )

    assert metrics.content_sets == 2
    assert metrics.runs_this_week == 3 and metrics.success_rate == 1.0
