import json

import pytest
import respx
from pydantic import SecretStr
from typer.testing import CliRunner

from thoth_control_plane import cli
from thoth_control_plane.cli import app

runner = CliRunner()

QUEUED_SUMMARY = {
    "workflow_id": "wf_001",
    "status": "queued",
    "created_at": "2026-08-28T08:00:00Z",
    "updated_at": "2026-08-28T08:00:00Z",
    "source": {"display_url": "https://example.test/post/1", "platform": "example"},
    "stages": [],
    "artifacts": [],
    "approval": None,
    "failure": None,
}


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_URL", "http://control-plane.test")
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "test-key")


def test_cli_posts_the_same_v1_request(respx_mock: respx.MockRouter, monkeypatch) -> None:
    _configure(monkeypatch)
    route = respx_mock.post("http://control-plane.test/api/v1/workflows").respond(
        202, json=QUEUED_SUMMARY
    )

    result = runner.invoke(
        app,
        ["workflow", "start", "--url", "https://example.test/post/1", "--style", "news-vertical"],
    )

    assert result.exit_code == 0
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["Idempotency-Key"]
    assert json.loads(request.content) == {
        "source": {"url": "https://example.test/post/1", "intent": "produce_video"},
        "style": {"preset_id": "news-vertical"},
        "output": {"format": "mp4", "language": "id"},
        "review": {"require_publish_approval": True},
    }


def test_a_failed_start_names_its_key_and_a_rerun_can_reuse_it(
    respx_mock: respx.MockRouter, monkeypatch
) -> None:
    _configure(monkeypatch)
    route = respx_mock.post("http://control-plane.test/api/v1/workflows").mock(
        side_effect=[
            respx.MockResponse(503, json={"detail": "not ready"}),
            respx.MockResponse(202, json=QUEUED_SUMMARY),
        ]
    )
    args = ["workflow", "start", "--url", "https://example.test/post/1", "--style", "news-vertical"]

    failed = runner.invoke(app, args)
    key = route.calls[0].request.headers["Idempotency-Key"]
    retried = runner.invoke(app, [*args, "--idempotency-key", key])

    assert failed.exit_code == 1
    assert f"--idempotency-key {key}" in failed.output
    assert retried.exit_code == 0
    assert route.calls[1].request.headers["Idempotency-Key"] == key


def test_cli_watch_streams_and_renders_typed_v1_sse_events(
    respx_mock: respx.MockRouter, monkeypatch
) -> None:
    _configure(monkeypatch)
    route = respx_mock.get("http://control-plane.test/api/v1/workflows/wf_001/events").respond(
        200,
        text=(
            "id: 1\n"
            "event: workflow.queued\n"
            'data: {"workflow_id":"wf_001","event_id":"evt_1","sequence":1,'
            '"kind":"workflow.queued","occurred_at":"2026-08-28T08:00:00Z"}\n\n'
        ),
        headers={"content-type": "text/event-stream"},
    )

    result = runner.invoke(app, ["workflow", "watch", "wf_001"])

    assert result.exit_code == 0
    assert route.called
    assert '"workflow_id": "wf_001"' in result.stdout
    assert '"kind": "workflow.queued"' in result.stdout


@pytest.mark.parametrize(
    ("arguments", "path", "expected_json"),
    [
        (
            [
                "approve",
                "wf_001",
                "--approval-id",
                "approval_001",
                "--decision",
                "approve",
                "--note",
                "Looks good",
            ],
            "/api/v1/workflows/wf_001/approve",
            {"approval_id": "approval_001", "decision": "approve", "note": "Looks good"},
        ),
        (["cancel", "wf_001"], "/api/v1/workflows/wf_001/cancel", None),
        (
            ["retry", "wf_001", "--from-stage", "source"],
            "/api/v1/workflows/wf_001/retry",
            {"from_stage": "source"},
        ),
    ],
)
def test_cli_mutations_use_the_v1_http_api(
    arguments: list[str],
    path: str,
    expected_json: dict[str, str] | None,
    respx_mock: respx.MockRouter,
    monkeypatch,
) -> None:
    _configure(monkeypatch)
    route = respx_mock.post(f"http://control-plane.test{path}").respond(200, json=QUEUED_SUMMARY)

    result = runner.invoke(app, ["workflow", *arguments])

    assert result.exit_code == 0
    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert (
        json.loads(request.content) == expected_json
        if expected_json is not None
        else not request.content
    )


@pytest.mark.parametrize(
    "command",
    ["stage1-controlled-fallback-preflight", "stage1-controlled-fallback-run"],
)
def test_controlled_fallback_help_exits_zero_without_touching_docker(command: str) -> None:
    """`--help` must never require Docker, real digests, or a live gate directory."""
    result = runner.invoke(app, ["operations", command, "--help"])

    assert result.exit_code == 0
    assert "f1" in result.stdout


@pytest.mark.parametrize(("gate_id", "directory"), [("not-f1", "not-f1"), ("f2", "f1")])
def test_controlled_fallback_run_rejects_an_unknown_or_mismatched_gate_id(
    tmp_path, gate_id: str, directory: str
) -> None:
    """`--gate-id` must be a known gate naming its directory; checked before any Docker call."""
    sample = tmp_path / directory
    sample.mkdir()

    result = runner.invoke(
        app,
        [
            "operations",
            "stage1-controlled-fallback-run",
            "--gate-id",
            gate_id,
            "--sample",
            str(sample),
            "--provider",
            str(tmp_path / "provider.env"),
            "--data-root",
            str(tmp_path / "data"),
            "--parity-root",
            str(tmp_path / "parity"),
            "--digest",
            "sha256:" + "a1" * 32,
            "--acquisition-revision",
            "b2" * 20,
            "--harness-revision",
            "c3" * 20,
        ],
    )

    assert result.exit_code != 0
    assert "controlled_fallback_completed" not in result.stdout
    assert "verdict=" not in result.stdout


@pytest.mark.parametrize("gate_id", ["f1", "f2", "f3", "f4"])
def test_controlled_fallback_run_preflights_before_consuming_the_attempt(
    monkeypatch, tmp_path, gate_id: str
) -> None:
    """An input the preflight rejects must never reserve the gate's one attempt."""

    class RefusingExecutor:
        def run(self, *args, **kwargs):
            raise AssertionError("no command may run after a failed preflight")

        def wait_container(self, *args, **kwargs):
            raise AssertionError("no container may start after a failed preflight")

    monkeypatch.setattr(cli, "SubprocessCommandExecutor", RefusingExecutor)
    sample = tmp_path / gate_id
    sample.mkdir()

    result = runner.invoke(
        app,
        [
            "operations",
            "stage1-controlled-fallback-run",
            "--gate-id",
            gate_id,
            "--sample",
            str(sample),
            "--provider",
            str(tmp_path / "provider.env"),
            "--data-root",
            str(tmp_path / "data"),
            "--parity-root",
            str(tmp_path / "parity"),
            "--digest",
            "sha256:" + "a1" * 32,
            "--acquisition-revision",
            "b2" * 20,
            "--harness-revision",
            "c3" * 20,
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == "controlled_fallback_preflight_passed=false\n"
    assert list(sample.iterdir()) == []


def test_editor_migrate_uses_the_runtime_python_migrations_directory(monkeypatch, tmp_path) -> None:
    runtime_root = tmp_path / "python"
    expected_root = runtime_root / "migrations" / "editor"
    expected_root.mkdir(parents=True)
    (expected_root / "0001_edit_document_revisions.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "__file__",
        str(runtime_root / "src" / "thoth_control_plane" / "cli.py"),
    )
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: type(
            "SettingsStub", (), {"THOTH_EDITOR_DATABASE_URL": SecretStr("postgresql://test")}
        )(),
    )
    called_with: list[object] = []

    def migrate(database_url: str, migrations_root) -> int:
        called_with.extend((database_url, migrations_root))
        return 1

    monkeypatch.setattr(cli, "apply_editor_migrations", migrate)

    result = runner.invoke(app, ["editor", "migrate"])

    assert result.exit_code == 0
    assert called_with == ["postgresql://test", expected_root]


RUST_PROJECTS = (
    '[{"id": "db766411-3cb0-47a4-9dc9-b67d22f6f34e", "name": "test", "workspace_path": "x",'
    ' "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}'
)


def test_projects_import_reads_the_rust_json_from_stdin(monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from typer.testing import CliRunner

    from thoth_control_plane import cli
    from thoth_control_plane.infrastructure import run_models  # noqa: F401
    from thoth_control_plane.infrastructure.project_store import ProjectStore
    from thoth_control_plane.infrastructure.source_account_models import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    store = ProjectStore(engine)
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_EDITOR_DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setattr(cli.ProjectStore, "connect", classmethod(lambda cls, url: store))
    runner = CliRunner()
    first = runner.invoke(
        cli.app, ["projects", "import", "-"], input=RUST_PROJECTS + ', {"id": "", "name": "x"}]'
    )
    assert first.output.strip().splitlines()[-1] == "imported=1 present=0 invalid=1"
    assert first.exit_code == 1
    again = runner.invoke(cli.app, ["projects", "import", "-"], input=RUST_PROJECTS + "]")
    assert again.output.strip().splitlines()[-1] == "imported=0 present=1 invalid=0"
    assert again.exit_code == 0


def test_tokens_create_prints_one_working_token_and_creates_the_user(monkeypatch) -> None:
    import asyncio
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from typer.testing import CliRunner

    from thoth_control_plane import cli
    from thoth_control_plane.auth.service import SignInService
    from thoth_control_plane.infrastructure import account_models  # noqa: F401
    from thoth_control_plane.infrastructure.account_models import WorkspaceRow
    from thoth_control_plane.infrastructure.account_store import AccountStore
    from thoth_control_plane.infrastructure.source_account_models import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id="ws_bootstrap", name="Thoth", created_at=datetime.now(UTC)
            )
        )
    store = AccountStore(engine)
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_EDITOR_DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setattr(cli.AccountStore, "connect", classmethod(lambda cls, url: store))
    result = CliRunner().invoke(
        cli.app, ["tokens", "create", "--email", "Dev@Acme.test", "--name", "vite"]
    )
    assert result.exit_code == 0, result.output
    secret = result.output.strip()
    assert secret.startswith("thoth_pat_") and "\n" not in secret
    principal = asyncio.run(SignInService(store, None, None).authenticate_token(secret))
    assert principal.email == "dev@acme.test" and principal.workspace_id == "ws_bootstrap"
    bad = CliRunner().invoke(
        cli.app, ["tokens", "create", "--email", "x@y", "--name", "n", "--scope", "root"]
    )
    assert bad.exit_code == 1 and bad.output.strip() == "invalid_request"


def test_quotas_and_prices_from_the_cli(monkeypatch) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from thoth_control_plane.infrastructure import usage_models  # noqa: F401
    from thoth_control_plane.infrastructure.account_models import WorkspaceRow
    from thoth_control_plane.infrastructure.source_account_models import Base
    from thoth_control_plane.infrastructure.usage_store import UsageStore

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id="ws_a", name="A", created_at=datetime.now(UTC)
            )
        )
    store = UsageStore(engine)
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_EDITOR_DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setattr(cli.UsageStore, "connect", classmethod(lambda cls, url: store))
    assert runner.invoke(app, ["quotas", "set", "ws_a", "instagram", "1"]).exit_code == 0
    shown = runner.invoke(app, ["quotas", "show", "ws_a"]).output
    assert "platform=instagram daily_leases=1 used_today=0" in shown
    assert runner.invoke(app, ["quotas", "set", "ws_a", "myspace", "1"]).exit_code == 1
    unknown = runner.invoke(app, ["quotas", "set", "ws_nope", "instagram", "1"])
    assert (unknown.exit_code, unknown.output.strip()) == (1, "unknown_workspace")
    assert (
        runner.invoke(app, ["prices", "set", "provider_call", "*", "call", "0.002"]).exit_code == 0
    )
    assert "provider_call * call 0.002" in runner.invoke(app, ["prices", "list"]).output
