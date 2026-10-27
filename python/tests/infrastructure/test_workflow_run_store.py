"""Workflow runs per project, on in-memory SQLite."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.sqlite_support import sqlite_engine
from thoth_control_plane.domain import Actor, WorkflowSummary
from thoth_control_plane.domain.models import StageSummary
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.report_store import ReportStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

OWNER = Actor(actor_id="owner", actor_type="user")
OTHER = Actor(actor_id="someone", actor_type="user")
T0 = datetime(2026, 10, 18, 8, tzinfo=UTC)


def summary(workflow_id: str, status: str = "queued") -> WorkflowSummary:
    """StrictModel takes timestamps only through JSON validation."""
    return WorkflowSummary.model_validate_json(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "status": status,
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
                "source": {"display_url": "https://example.test/post", "platform": "example"},
                "stages": [],
            }
        )
    )


@pytest.fixture
def stores():
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    ticks = iter(T0 + timedelta(seconds=n) for n in range(1000))
    return (
        ProjectStore(engine),
        WorkflowRunStore(engine, clock=lambda: next(ticks)),
        ReportStore(engine),
    )


def test_record_start_is_an_upsert_that_never_moves_the_project(stores) -> None:
    projects, runs, _ = stores
    project = projects.create("News", "ws_bootstrap")
    runs.record_start(summary("wf_a"), project_id=project.project_id, actor=OWNER)
    runs.record_start(summary("wf_a", "running"), project_id=None, actor=OWNER)
    stored = runs.get("wf_a")
    assert stored is not None
    assert stored.project_id == project.project_id
    assert stored.status == "running"
    assert stored.summary is not None and stored.summary.status.value == "running"


def test_pages_are_per_project_newest_first_with_a_cursor(stores) -> None:
    projects, runs, _ = stores
    project = projects.create("News", "ws_bootstrap")
    for name in ("wf_a", "wf_b", "wf_c"):
        runs.record_start(summary(name), project_id=project.project_id, actor=OWNER)
    runs.record_start(summary("wf_x"), project_id=None, actor=OWNER)
    first, cursor = runs.page(
        project_id=project.project_id, unassigned=False, actor=OWNER, cursor=None, limit=2
    )
    assert [r.workflow_id for r in first] == ["wf_c", "wf_b"]
    assert cursor
    rest, end = runs.page(
        project_id=project.project_id, unassigned=False, actor=OWNER, cursor=cursor, limit=2
    )
    assert [r.workflow_id for r in rest] == ["wf_a"]
    assert end is None
    loose, _ = runs.page(project_id=None, unassigned=True, actor=OWNER, cursor=None, limit=50)
    assert [r.workflow_id for r in loose] == ["wf_x"]


def test_another_actor_sees_nothing(stores) -> None:
    _, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    other = Actor(actor_id="someone", actor_type="user")
    page = runs.page(project_id=None, unassigned=True, actor=other, cursor=None, limit=50)
    assert page == ([], None)


def test_settle_and_assign(stores) -> None:
    projects, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    runs.settle(
        "wf_a", status="succeeded", summary=summary("wf_a", "succeeded"), history_expired=False
    )
    project = projects.create("News", "ws_bootstrap")
    moved = runs.assign("wf_a", project.project_id)
    assert moved is not None
    assert moved.project_id == project.project_id
    assert moved.status == "succeeded"
    assert moved.to_run().artifact_count == 0
    assert runs.assign("wf_missing", project.project_id) is None


def test_report_artifacts_and_source_rows_come_from_workflow_reports(stores) -> None:
    _, runs, reports = stores
    reports.put(
        "reports/wf_a/source-report.json",
        "source_report",
        b'{"source": {"canonical_url": "https://x.test/v?a=1", "platform": "tiktok"}}',
    )
    reports.put("reports/wf_a/content-set.json", "content_set", b"{}")
    artifacts = runs.report_artifacts("wf_a")
    assert {a.artifact_id for a in artifacts} == {"source_report", "content_set"}
    assert all(a.media_type == "application/json" for a in artifacts)
    assert all(a.checksum and a.checksum.startswith("sha256:") for a in artifacts)
    [(workflow_id, content, first_seen)] = runs.source_report_rows()
    assert workflow_id == "wf_a"
    assert "canonical_url" in content
    assert first_seen.tzinfo is not None


def test_settle_takes_the_summary_time_and_ignores_unchanged_reads(stores) -> None:
    _, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    finished = summary("wf_a", "succeeded").model_copy(
        update={"updated_at": datetime(2026, 9, 30, 12, tzinfo=UTC)}
    )
    runs.settle("wf_a", status="succeeded", summary=finished, history_expired=False)
    first = runs.get("wf_a")
    assert first is not None and first.updated_at == datetime(2026, 9, 30, 12, tzinfo=UTC)
    # Re-reading the same summary (a detail page refresh) changes nothing, the time included.
    runs.settle("wf_a", status="succeeded", summary=finished, history_expired=False)
    again = runs.get("wf_a")
    assert again is not None and again.updated_at == first.updated_at


def test_claim_assigns_only_an_unassigned_run(stores) -> None:
    projects, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    first = projects.create("A", "ws_bootstrap").project_id
    second = projects.create("B", "ws_bootstrap").project_id

    claimed = runs.claim("wf_a", first)
    again = runs.claim("wf_a", second)

    assert claimed is not None and claimed.project_id == first
    assert again is not None and again.project_id == first  # never moved
    assert runs.claim("wf_missing", first) is None


def _succeeded(
    workflow_id: str, *, source_seconds: float, updated_at: datetime, platform: str = "example"
) -> WorkflowSummary:
    started = updated_at - timedelta(hours=1)
    return WorkflowSummary(
        workflow_id=workflow_id,
        status="succeeded",
        created_at=started,
        updated_at=updated_at,
        source={"display_url": "https://example.test/post", "platform": platform},
        stages=[
            StageSummary(
                id="source",
                label="Source",
                status="completed",
                started_at=started,
                finished_at=started + timedelta(seconds=source_seconds),
            )
        ],
    )


def _seed_succeeded(runs: WorkflowRunStore, workflow_id: str, **changes: object) -> None:
    runs.record_start(summary(workflow_id), project_id=None, actor=OWNER)
    runs.settle(
        workflow_id,
        status="succeeded",
        summary=_succeeded(workflow_id, **changes),
        history_expired=False,
    )


def test_recent_succeeded_lists_newest_summaries_for_the_actor_and_platform(stores) -> None:
    _, runs, _ = stores
    for n in range(3):
        _seed_succeeded(runs, f"wf_{n}", source_seconds=60.0, updated_at=T0 + timedelta(hours=n))
    # A queued run, another platform, a foreign actor, and a succeeded row without a
    # summary are all invisible to the estimate input.
    runs.record_start(
        _succeeded("wf_other_platform", source_seconds=60.0, updated_at=T0, platform="tiktok"),
        project_id=None,
        actor=OWNER,
    )
    runs.record_start(summary("wf_queued"), project_id=None, actor=OWNER)
    runs.record_start(
        _succeeded("wf_foreign", source_seconds=60.0, updated_at=T0), project_id=None, actor=OTHER
    )
    runs.insert_missing(
        StoredRun(
            workflow_id="wf_no_summary",
            project_id=None,
            actor_type=OWNER.actor_type,
            actor_id=OWNER.actor_id,
            display_url="https://example.test/post",
            platform="example",
            status="succeeded",
            history_expired=False,
            summary=None,
            created_at=T0,
            updated_at=T0,
        )
    )

    histories = runs.recent_succeeded(OWNER, "example")

    assert [history.workflow_id for history in histories] == ["wf_2", "wf_1", "wf_0"]
    assert [stage.finished_at - stage.started_at for stage in histories[0].stages] == [
        timedelta(seconds=60)
    ]


def test_recent_succeeded_is_capped_at_twenty_newest(stores) -> None:
    _, runs, _ = stores
    for n in range(25):
        _seed_succeeded(
            runs, f"wf_{n:02d}", source_seconds=60.0, updated_at=T0 + timedelta(hours=n)
        )

    histories = runs.recent_succeeded(OWNER, "example")

    assert len(histories) == 20
    assert histories[0].workflow_id == "wf_24" and histories[-1].workflow_id == "wf_05"


def test_acknowledge_stamps_a_failed_run_once_and_keeps_the_first_time(stores) -> None:
    _, runs, _ = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    runs.settle("wf_a", status="failed", summary=None, history_expired=False)

    first = runs.acknowledge("wf_a")
    assert first is not None and first.acknowledged_at is not None

    runs.acknowledge("wf_a")  # the store clock ticks between calls; the stamp survives
    again = runs.get("wf_a")
    assert again is not None and again.acknowledged_at == first.acknowledged_at
    assert runs.acknowledge("wf_missing") is None


def _run(workflow_id: str, *, platform: str = "example", url: str = "https://example.test/post"):
    return WorkflowSummary.model_validate_json(
        json.dumps(
            {
                "workflow_id": workflow_id,
                "status": "running",
                "created_at": T0.isoformat(),
                "updated_at": T0.isoformat(),
                "source": {"display_url": url, "platform": platform},
                "stages": [],
            }
        )
    )


def test_the_list_across_projects_holds_every_project_and_the_unassigned_runs(stores) -> None:
    projects, runs, _ = stores
    news = projects.create("News", "ws_bootstrap")
    haze = projects.create("Haze", "ws_bootstrap")
    runs.record_start(summary("wf_a"), project_id=news.project_id, actor=OWNER)
    runs.record_start(summary("wf_b"), project_id=haze.project_id, actor=OWNER)
    runs.record_start(summary("wf_c"), project_id=None, actor=OWNER)
    runs.record_start(summary("wf_foreign"), project_id=None, actor=OTHER)

    every, _ = runs.page(project_id=None, unassigned=False, actor=OWNER, cursor=None, limit=50)

    assert [r.workflow_id for r in every] == ["wf_c", "wf_b", "wf_a"]


def test_lists_filter_by_status_platform_and_text(stores) -> None:
    _, runs, reports = stores
    runs.record_start(
        _run("wf_x", platform="x", url="https://x.com/a/status/1"), project_id=None, actor=OWNER
    )
    runs.record_start(
        _run("wf_tt", platform="tiktok", url="https://vt.tiktok.com/ZS1/"),
        project_id=None,
        actor=OWNER,
    )
    runs.record_start(
        _run("wf_done", platform="x", url="https://x.com/b/status/2"), project_id=None, actor=OWNER
    )
    runs.settle("wf_done", status="succeeded", summary=None, history_expired=False)
    reports.put(
        "reports/wf_tt/source-report.json",
        "source_report",
        json.dumps(
            {
                "schema_version": 3,
                "post": {"text": "Haze 50% worse in Palangka", "owner_handle": "kalteng"},
            }
        ).encode(),
    )
    runs.fill_listing(["wf_tt"])

    def ids(**filters) -> list[str]:
        page, _ = runs.page(
            project_id=None, unassigned=False, actor=OWNER, cursor=None, limit=50, **filters
        )
        return [r.workflow_id for r in page]

    assert ids(statuses=["running", "queued"]) == ["wf_tt", "wf_x"]
    assert ids(platform="x") == ["wf_done", "wf_x"]
    assert ids(text="HAZE") == ["wf_tt"]  # the title, any case
    assert ids(text="b/status") == ["wf_done"]  # the link
    assert ids(text="50%") == ["wf_tt"]  # a literal percent, not a wildcard
    assert ids(text="5_%") == []


def test_listing_details_come_once_from_the_source_report(stores) -> None:
    _, runs, reports = stores
    for name in ("wf_new", "wf_old", "wf_blank", "wf_none"):
        runs.record_start(summary(name), project_id=None, actor=OWNER)
    reports.put(
        "reports/wf_new/source-report.json",
        "source_report",
        json.dumps(
            {
                "schema_version": 3,
                "post": {
                    "text": "\n  Gojek driver returns\n a lost wallet  \nmore",
                    "owner_handle": "kind.id",
                },
                "post_card": {"location": "reports/wf_new/cards/post.png"},
            }
        ).encode(),
    )
    reports.put(
        "reports/wf_old/source-report.json",
        "source_report",
        json.dumps(
            {"schema_version": 2, "post": {"caption": "x" * 300, "owner_handle": "old"}}
        ).encode(),
    )
    reports.put(
        "reports/wf_blank/source-report.json",
        "source_report",
        json.dumps({"schema_version": 3, "post": {"text": "", "owner_handle": "quiet"}}).encode(),
    )

    runs.fill_listing(["wf_new", "wf_old", "wf_blank", "wf_none"])

    new, old, blank, none = (runs.get(name) for name in ("wf_new", "wf_old", "wf_blank", "wf_none"))
    assert (new.title, new.owner_handle, new.post_card_location) == (
        "Gojek driver returns",
        "kind.id",
        "reports/wf_new/cards/post.png",
    )
    assert old.title == "x" * 139 + "…" and old.owner_handle == "old"
    assert old.post_card_location is None
    # Read, but the post has no text: never read again.
    assert (blank.title, blank.owner_handle) == ("", "quiet")
    # No report yet: stays unread, so a later listing tries again.
    assert none.title is None
    assert new.to_run().has_post_card and not old.to_run().has_post_card


def test_a_broken_source_report_never_breaks_the_listing(stores) -> None:
    _, runs, reports = stores
    runs.record_start(summary("wf_a"), project_id=None, actor=OWNER)
    reports.put("reports/wf_a/source-report.json", "source_report", b"[1, 2]")

    runs.fill_listing(["wf_a"])

    stored = runs.get("wf_a")
    assert stored is not None and stored.title == ""


def test_metric_rows_are_the_callers_runs_since_a_time(stores) -> None:
    projects, runs, _ = stores
    news = projects.create("News", "ws_bootstrap")
    runs.record_start(summary("wf_early"), project_id=news.project_id, actor=OWNER)
    runs.record_start(summary("wf_a"), project_id=news.project_id, actor=OWNER)
    runs.record_start(summary("wf_b"), project_id=None, actor=OWNER)
    runs.record_start(summary("wf_foreign"), project_id=None, actor=OTHER)
    since = runs.get("wf_a").created_at

    assert {r.workflow_id for r in runs.since(OWNER, since, project_id=None)} == {"wf_a", "wf_b"}
    assert [r.workflow_id for r in runs.since(OWNER, since, project_id=news.project_id)] == ["wf_a"]
