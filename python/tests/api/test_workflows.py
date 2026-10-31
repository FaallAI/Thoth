import re
from pathlib import Path

import httpx
import pytest

from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import ArtifactRef, EventKind

VALID_REQUEST = {
    "source": {
        "url": "https://www.tiktok.com/@creator/video/1234567890",
        "intent": "identify_original",
    },
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}
AUTH_HEADERS = {"Authorization": "Bearer test-key"}


def test_zero_argument_factory_loads_production_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "factory-key")

    app = create_app()

    assert app.state.settings.THOTH_CONTROL_PLANE_API_KEY.get_secret_value() == "factory-key"


@pytest.mark.asyncio
async def test_cors_preflight_allows_configured_dashboard_origin(gateway) -> None:
    app = create_app(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="test-key",
            THOTH_CONTROL_PLANE_CORS_ORIGINS=["http://localhost:5173"],
        ),
        gateway,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.options(
            "/api/v1/workflows",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,idempotency-key,content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://m.facebook.com/story.php?id=1",
        "https://www.reddit.com/r/x/comments/abc/",
        "https://vimeo.com/123",
    ],
)
async def test_unsupported_platform_is_rejected_before_any_workflow_starts(
    client: httpx.AsyncClient, gateway, url: str
) -> None:
    response = await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-unsupported"},
        json={**VALID_REQUEST, "source": {**VALID_REQUEST["source"], "url": url}},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "unsupported_platform"}}
    assert gateway.workflows == {}


@pytest.mark.asyncio
async def test_create_workflow_returns_accepted_v1_summary(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )

    assert response.status_code == 202
    assert response.headers["X-Thoth-Contract-Version"] == "1"
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_style_presets_expose_display_data_not_executor_options(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/style-presets", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == [
        {
            "preset_id": "news-vertical",
            "label": "News vertical",
            "description": "Fast-paced vertical news treatment",
        }
    ]


@pytest.mark.asyncio
async def test_get_workflow_returns_the_current_summary(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )

    response = await client.get(
        f"/api/v1/workflows/{created.json()['workflow_id']}",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["workflow_id"] == "wf_001"


@pytest.mark.asyncio
async def test_workflow_events_are_authorized_and_replay_after_last_event_id(
    client: httpx.AsyncClient,
    gateway,
) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )

    forbidden = await client.get("/api/v1/workflows/wf_001/events")
    fresh = await client.get("/api/v1/workflows/wf_001/events", headers=AUTH_HEADERS)
    replay = await client.get(
        "/api/v1/workflows/wf_001/events",
        headers={**AUTH_HEADERS, "Last-Event-ID": "1"},
    )
    replay_from_zero = await client.get(
        "/api/v1/workflows/wf_001/events",
        headers={**AUTH_HEADERS, "Last-Event-ID": "0"},
    )

    assert forbidden.status_code == 403
    assert fresh.status_code == 200
    assert fresh.headers["content-type"].startswith("text/event-stream")
    assert fresh.text.startswith("event: workflow.snapshot\n")
    assert "id: 1\nevent: workflow.queued\n" in fresh.text
    assert "id: 2\nevent: workflow.started\n" in fresh.text
    assert "id: 1" not in replay.text
    assert "id: 2\nevent: workflow.started\n" in replay.text
    assert "workflow.snapshot" not in replay.text
    assert "workflow.snapshot" not in replay_from_zero.text
    assert "id: 1\nevent: workflow.queued\n" in replay_from_zero.text
    assert "id: 2\nevent: workflow.started\n" in replay_from_zero.text
    assert gateway.last_event_cursor == 0


@pytest.mark.asyncio
async def test_workflow_events_emit_an_initial_snapshot_when_no_events_are_available(
    client: httpx.AsyncClient,
    gateway,
) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )
    gateway.events = []

    response = await client.get("/api/v1/workflows/wf_001/events", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert "event: workflow.snapshot" in response.text
    assert '"workflow_id":"wf_001"' in response.text


@pytest.mark.asyncio
async def test_fresh_event_stream_precedes_original_replay_with_current_snapshot(
    client: httpx.AsyncClient,
    gateway,
) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )
    gateway.workflows["wf_001"] = gateway.workflows["wf_001"].model_copy(
        update={"status": "succeeded"}
    )
    gateway.events[1] = gateway.events[1].model_copy(update={"kind": EventKind.WORKFLOW_COMPLETED})

    fresh = await client.get("/api/v1/workflows/wf_001/events", headers=AUTH_HEADERS)
    replay = await client.get(
        "/api/v1/workflows/wf_001/events",
        headers={**AUTH_HEADERS, "Last-Event-ID": "1"},
    )

    frames = [frame for frame in fresh.text.split("\n\n") if frame]
    assert "event: workflow.snapshot" in frames[0]
    assert '"kind":"workflow.completed"' in frames[0]
    assert "event: workflow.queued" in frames[1]
    assert "event: workflow.completed" in frames[2]
    assert "workflow.snapshot" not in replay.text
    assert "event: workflow.completed" in replay.text


@pytest.mark.asyncio
async def test_cancel_workflow_returns_the_latest_summary(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )

    response = await client.post("/api/v1/workflows/wf_001/cancel", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_approve_workflow_records_the_authenticated_actor(
    client: httpx.AsyncClient,
    gateway,
) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )

    response = await client.post(
        "/api/v1/workflows/wf_001/approve",
        headers=AUTH_HEADERS,
        json={"approval_id": "apr_001", "decision": "approve", "note": "Continue"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert gateway.last_approval.approval_id == "apr_001"
    assert gateway.actors[-1].actor_id == "owner"


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_a_different_body_returns_conflict(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )
    changed = {
        **VALID_REQUEST,
        "output": {"format": "vertical_video", "language": "en"},
    }

    response = await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=changed,
    )

    assert response.status_code == 409
    assert response.headers["X-Thoth-Contract-Version"] == "1"


@pytest.mark.asyncio
async def test_missing_workflow_returns_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/wf_missing", headers=AUTH_HEADERS)

    assert response.status_code == 404
    assert response.json() == {"detail": "Workflow not found"}


@pytest.mark.asyncio
async def test_artifact_download_is_workflow_authorized_and_resolves_only_safe_locations(
    gateway,
    tmp_path: Path,
    report_store,
) -> None:
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key",
        THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path,
    )
    app = create_app(settings, gateway, report_store=report_store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        created = await test_client.post(
            "/api/v1/workflows",
            headers={**AUTH_HEADERS, "Idempotency-Key": "artifact-auth-001"},
            json=VALID_REQUEST,
        )
        workflow_id = created.json()["workflow_id"]
        artifact_location = f"reports/{workflow_id}/source-report.json"
        binary_location = f"reports/{workflow_id}/source-archive.bin"
        gateway.workflows[workflow_id] = gateway.workflows[workflow_id].model_copy(
            update={
                "artifacts": [
                    ArtifactRef(
                        artifact_id="art_source_001",
                        kind="source_report",
                        label="Source investigation report",
                        media_type="application/json",
                        location=artifact_location,
                        checksum="sha256:" + "a" * 64,
                    ),
                    ArtifactRef(
                        artifact_id="art_source_002",
                        kind="source_archive",
                        label="Source investigation archive",
                        media_type="application/octet-stream",
                        location=binary_location,
                        checksum="sha256:" + "b" * 64,
                    ),
                ]
            }
        )
        report_store.put(artifact_location, "source_report", b'{"safe":true}')
        (tmp_path / binary_location).parent.mkdir(parents=True)
        (tmp_path / binary_location).write_bytes(b"safe-bytes")

        authorized = await test_client.get(
            f"/api/v1/workflows/{workflow_id}/artifacts/art_source_001",
            headers=AUTH_HEADERS,
        )
        binary = await test_client.get(
            f"/api/v1/workflows/{workflow_id}/artifacts/art_source_002",
            headers=AUTH_HEADERS,
        )
        forbidden = await test_client.get(
            f"/api/v1/workflows/{workflow_id}/artifacts/art_source_001",
            headers={"Authorization": "Bearer wrong-key"},
        )
        missing = await test_client.get(
            f"/api/v1/workflows/{workflow_id}/artifacts/art_missing",
            headers=AUTH_HEADERS,
        )

    assert authorized.status_code == 200
    assert authorized.json() == {"safe": True}
    assert str(tmp_path) not in authorized.text
    assert authorized.headers["content-type"] == "application/json"
    assert binary.status_code == 200
    assert binary.content == b"safe-bytes"
    assert binary.headers["content-type"] == "application/octet-stream"
    assert forbidden.status_code == 403
    assert missing.status_code == 404


async def _download_report(gateway, tmp_path: Path, reports, *, key: str = "test-key"):
    """Create a workflow owning one source-report artifact, then download it."""
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path
    )
    app = create_app(settings, gateway, report_store=reports)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        created = await test_client.post(
            "/api/v1/workflows",
            headers={**AUTH_HEADERS, "Idempotency-Key": "report-001"},
            json=VALID_REQUEST,
        )
        workflow_id = created.json()["workflow_id"]
        gateway.workflows[workflow_id] = gateway.workflows[workflow_id].model_copy(
            update={
                "artifacts": [
                    ArtifactRef(
                        artifact_id="art_report",
                        kind="source_report",
                        label="Source investigation report",
                        media_type="application/json",
                        location=f"reports/{workflow_id}/source-report.json",
                        checksum="sha256:" + "a" * 64,
                    )
                ]
            }
        )
        response = await test_client.get(
            f"/api/v1/workflows/{workflow_id}/artifacts/art_report",
            headers={"Authorization": f"Bearer {key}"},
        )
    return workflow_id, response


@pytest.mark.asyncio
async def test_a_report_artifact_is_served_from_the_store(gateway, tmp_path: Path) -> None:
    content = b'{"schema_version": 3}'
    asked: list[str] = []

    class Echo:
        def get(self, location: str) -> bytes | None:
            asked.append(location)
            return content

    workflow_id, response = await _download_report(gateway, tmp_path, Echo())

    assert asked == [f"reports/{workflow_id}/source-report.json"]
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"] == 'attachment; filename="art_report.json"'
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_a_missing_report_row_is_404(gateway, tmp_path: Path, report_store) -> None:
    _, response = await _download_report(gateway, tmp_path, report_store)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_report_without_a_store_is_503(gateway, tmp_path: Path) -> None:
    _, response = await _download_report(gateway, tmp_path, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "report_store_unavailable"}


@pytest.mark.asyncio
async def test_a_report_store_outage_is_503_not_404(gateway, tmp_path: Path) -> None:
    from tests.conftest import DownReports

    _, response = await _download_report(gateway, tmp_path, DownReports())

    assert response.status_code == 503
    assert response.json() == {"detail": "report_store_unavailable"}


@pytest.mark.asyncio
async def test_a_report_of_another_owner_is_still_refused(gateway, tmp_path: Path) -> None:
    class Spy:
        reads = 0

        def get(self, location: str) -> bytes | None:
            Spy.reads += 1
            return b"{}"

    _, response = await _download_report(gateway, tmp_path, Spy(), key="wrong-key")

    assert response.status_code == 403
    assert Spy.reads == 0


@pytest.mark.asyncio
async def test_disallowed_approval_returns_conflict(client: httpx.AsyncClient, gateway) -> None:
    await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json=VALID_REQUEST,
    )
    gateway.approval_allowed = False

    response = await client.post(
        "/api/v1/workflows/wf_001/approve",
        headers=AUTH_HEADERS,
        json={"approval_id": "apr_001", "decision": "approve"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Approval is not allowed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-key"}, {"Authorization": "Basic test-key"}],
)
async def test_unauthorized_actor_is_forbidden(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> None:
    response = await client.get("/api/v1/style-presets", headers=headers)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_request_validation_rejects_actor_identity_in_json(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/workflows",
        headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
        json={**VALID_REQUEST, "actor_id": "forged-owner"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_approval_input_rejects_provider_payloads(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows/wf_001/approve",
        headers=AUTH_HEADERS,
        json={
            "approval_id": "apr_001",
            "decision": "approve",
            "provider_payload": {"token": "must-not-enter-contract"},
        },
    )

    assert response.status_code == 422


def test_route_modules_do_not_depend_on_a_process_runner() -> None:
    # Anchored to this file: a cwd-relative path globs nothing when pytest runs elsewhere.
    routes = Path(__file__).resolve().parents[2] / "src/thoth_control_plane/api/routes"
    modules = sorted(routes.glob("*.py"))
    assert modules
    source = "\n".join(path.read_text(encoding="utf-8") for path in modules)
    lowered = source.lower()

    assert "Command(" not in source
    assert "subprocess" not in lowered
    # A word match: render "bundle" routes are not the Bun runtime.
    assert re.search(r"\bbun\b", lowered) is None
    assert "scout" not in lowered
    assert "stdout" not in lowered
    assert '"thoth"' not in lowered
    assert "'thoth'" not in lowered
    assert "thoth.exe" not in lowered


def test_openapi_exposes_exact_required_path_method_pairs(gateway) -> None:
    document = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway).openapi()
    http_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    actual = {
        (path, method)
        for path, item in document["paths"].items()
        for method in item
        if method in http_methods
    }

    assert actual == {
        ("/api/v1/projects", "get"),
        ("/api/v1/me", "get"),
        ("/api/v1/me", "patch"),
        ("/api/v1/workflows/{workflow_id}/cards/{card}", "get"),
        ("/api/v1/workflows/metrics", "get"),
        ("/api/v1/workflows/{workflow_id}/media/{location}", "get"),
        ("/api/v1/usage", "get"),
        ("/api/v1/billing/checkout", "post"),
        ("/api/v1/billing", "get"),
        ("/api/v1/admin/plans", "get"),
        ("/api/v1/admin/plans/{plan_id}", "put"),
        ("/api/v1/admin/plans/margin", "get"),
        ("/api/v1/admin/plans/rate", "put"),
        ("/api/v1/admin/usage", "get"),
        ("/api/v1/admin/prices", "get"),
        ("/api/v1/admin/prices", "put"),
        ("/api/v1/admin/workspaces/{workspace_id}/quotas", "get"),
        ("/api/v1/admin/workspaces/{workspace_id}/quotas", "put"),
        ("/api/v1/me/tokens", "get"),
        ("/api/v1/me/tokens", "post"),
        ("/api/v1/me/tokens/{token_id}", "delete"),
        ("/api/v1/workspace/tokens", "post"),
        ("/api/v1/workspace/tokens", "get"),
        ("/api/v1/workspace/tokens/{token_id}", "delete"),
        ("/api/v1/projects", "post"),
        ("/api/v1/projects/{project_id}", "get"),
        ("/api/v1/projects/{project_id}/workflows", "get"),
        ("/api/v1/projects/{project_id}/workflows", "post"),
        ("/api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import", "get"),
        ("/api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import", "post"),
        ("/api/v1/workflows", "get"),
        ("/api/v1/workflows/{workflow_id}", "patch"),
        ("/api/v1/projects/{project_id}/edit-documents", "get"),
        ("/api/v1/projects/{project_id}/edit-documents/import-content-set", "post"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}", "get"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}", "patch"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/assist", "post"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/narration", "post"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/narration", "get"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/narration/decision", "post"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/narration/cancel", "post"),
        (
            "/api/v1/projects/{project_id}/edit-documents/{document_id}/narration/beats/{beat}",
            "put",
        ),
        (
            "/api/v1/projects/{project_id}/edit-documents/{document_id}/narration/beats/{beat}/revoice",
            "post",
        ),
        ("/api/v1/projects/{project_id}/narration-preset", "get"),
        ("/api/v1/projects/{project_id}/narration-preset", "put"),
        ("/api/v1/sfx", "get"),
        (
            "/api/v1/projects/{project_id}/edit-documents/{document_id}/upgrade-timeline",
            "post",
        ),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/review-comments", "get"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/review-comments", "post"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/review-decisions", "get"),
        ("/api/v1/projects/{project_id}/edit-documents/{document_id}/review-decisions", "post"),
        ("/api/v1/projects/{project_id}/studio-imports/inspect", "post"),
        ("/api/v1/projects/{project_id}/studio-imports", "post"),
        ("/api/v1/projects/{project_id}/studio-imports/{source_key}", "get"),
        ("/api/v1/projects/{project_id}/studio-imports/documents/{document_id}", "get"),
        ("/api/v1/projects/{project_id}/studio-imports/documents/{document_id}/materials", "get"),
        (
            "/api/v1/projects/{project_id}/studio-imports/documents/{document_id}/materials/{item_id}/asset",
            "post",
        ),
        (
            "/api/v1/projects/{project_id}/studio-imports/documents/{document_id}/items/{item_id}"
            "/resolve",
            "post",
        ),
        ("/api/v1/source-accounts", "get"),
        ("/api/v1/source-accounts", "post"),
        ("/api/v1/source-accounts/policies/{platform}", "put"),
        ("/api/v1/source-accounts/validate", "post"),
        ("/api/v1/source-accounts/{account_id}/cookies", "put"),
        ("/api/v1/source-accounts/{account_id}", "patch"),
        ("/api/v1/source-accounts/{account_id}", "delete"),
        ("/api/v1/source-accounts/{account_id}/test", "post"),
        ("/api/v1/source-proxies", "get"),
        ("/api/v1/source-proxies/import", "post"),
        ("/api/v1/source-proxies/{proxy_id}", "delete"),
        ("/api/v1/projects/{project_id}/editor-assets", "get"),
        ("/api/v1/projects/{project_id}/editor-assets", "post"),
        ("/api/v1/projects/{project_id}/editor-assets/{asset_id}/preview", "get"),
        (
            "/api/v1/projects/{project_id}/editor-assets/{asset_id}/preview-capability",
            "post",
        ),
        ("/api/v1/projects/{project_id}/render-capability", "get"),
        ("/api/v1/projects/{project_id}/render-jobs", "get"),
        ("/api/v1/projects/{project_id}/render-jobs", "post"),
        ("/api/v1/projects/{project_id}/render-jobs/{render_job_id}", "get"),
        ("/api/v1/projects/{project_id}/render-jobs/{render_job_id}/cancel", "post"),
        ("/api/v1/projects/{project_id}/render-jobs/{render_job_id}/retry", "post"),
        ("/api/v1/projects/{project_id}/render-jobs/{render_job_id}/output", "get"),
        ("/api/v1/projects/{project_id}/render-jobs/{render_job_id}/artifacts", "delete"),
        ("/api/v1/prompt-providers", "get"),
        ("/api/v1/prompt-stages", "get"),
        ("/api/v1/prompt-stages/{stage_id}/starter", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/preferences/{stage_id}", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/preferences/{stage_id}", "put"),
        ("/api/v1/projects/{project_id}/prompt-lab/locks/{stage_id}", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/locks/{stage_id}/{layer}", "put"),
        ("/api/v1/projects/{project_id}/prompt-lab/proposals", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/proposals", "post"),
        ("/api/v1/projects/{project_id}/prompt-lab/proposals/{proposal_id}", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/proposals/{proposal_id}/apply", "post"),
        ("/api/v1/projects/{project_id}/prompt-lab/proposals/{proposal_id}/reject", "post"),
        ("/api/v1/projects/{project_id}/prompt-lab/templates", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/templates", "post"),
        ("/api/v1/projects/{project_id}/prompt-lab/bindings/{stage_id}", "get"),
        ("/api/v1/projects/{project_id}/prompt-lab/bindings/{stage_id}", "put"),
        ("/api/v1/projects/{project_id}/prompt-lab/resolved/{stage_id}", "get"),
        ("/api/v1/style-presets", "get"),
        ("/api/v1/inbox", "get"),
        ("/api/v1/workflows", "post"),
        ("/api/v1/workflows/{workflow_id}", "get"),
        ("/api/v1/workflows/{workflow_id}/artifacts/{artifact_id}", "get"),
        ("/api/v1/workflows/{workflow_id}/events", "get"),
        ("/api/v1/workflows/{workflow_id}/steps", "get"),
        ("/api/v1/workflows/{workflow_id}/cancel", "post"),
        ("/api/v1/workflows/{workflow_id}/approve", "post"),
        ("/api/v1/workflows/{workflow_id}/acknowledge", "post"),
        ("/healthz", "get"),
        ("/readyz", "get"),
    }


def test_openapi_declares_artifact_download_media_types(gateway) -> None:
    document = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway).openapi()

    response = document["paths"]["/api/v1/workflows/{workflow_id}/artifacts/{artifact_id}"]["get"][
        "responses"
    ]["200"]

    assert response["content"] == {
        "application/json": {"schema": {}},
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    }


def test_openapi_declares_workflow_create_as_accepted(gateway) -> None:
    document = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway).openapi()
    responses = document["paths"]["/api/v1/workflows"]["post"]["responses"]

    assert "202" in responses
    assert "200" not in responses


def test_openapi_declares_typed_workflow_event_stream(gateway) -> None:
    document = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway).openapi()
    operation = document["paths"]["/api/v1/workflows/{workflow_id}/events"]["get"]

    assert operation["responses"]["200"]["content"]["text/event-stream"]["schema"] == {
        "$ref": "#/components/schemas/WorkflowEvent"
    }
    assert "WorkflowEvent" in document["components"]["schemas"]


def test_openapi_approval_input_is_narrow_and_no_workflow_retry_is_offered(gateway) -> None:
    document = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway).openapi()
    schemas = document["components"]["schemas"]
    approval_operation = document["paths"]["/api/v1/workflows/{workflow_id}/approve"]["post"]

    assert approval_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApprovalSubmission"
    }
    assert set(schemas["ApprovalSubmission"]["properties"]) == {
        "approval_id",
        "decision",
        "note",
    }
    assert schemas["ApprovalSubmission"]["additionalProperties"] is False
    assert set(schemas["ApprovalSubmission"]["required"]) == {"approval_id", "decision"}
    # Audit B3: every gateway answered retry with WorkflowNotReady and no screen called it.
    assert "/api/v1/workflows/{workflow_id}/retry" not in document["paths"]
    assert "RetryRequest" not in schemas


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints_emit_the_v1_contract_header(
    client: httpx.AsyncClient,
) -> None:
    health = await client.get("/healthz")
    readiness = await client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready"}
    assert health.headers["X-Thoth-Contract-Version"] == "1"
    assert readiness.headers["X-Thoth-Contract-Version"] == "1"


@pytest.mark.asyncio
async def test_readiness_checks_the_current_temporal_connection(
    client: httpx.AsyncClient,
    gateway,
) -> None:
    gateway.connection_available = False

    readiness = await client.get("/readyz")

    assert readiness.status_code == 503


@pytest.mark.asyncio
async def test_unbound_production_wiring_is_not_ready_and_cannot_start_work() -> None:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        readiness = await client.get("/readyz")
        started = await client.post(
            "/api/v1/workflows",
            headers={**AUTH_HEADERS, "Idempotency-Key": "create-001"},
            json=VALID_REQUEST,
        )

    assert readiness.status_code == 503
    assert started.status_code == 503
