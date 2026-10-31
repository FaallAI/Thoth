"""A thin command-line client for the public control-plane HTTP API."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from pydantic import ValidationError

from thoth_control_plane import metering
from thoth_control_plane.application import ApprovalSubmission
from thoth_control_plane.auth.models import ALL_SCOPES, CreateToken, Principal
from thoth_control_plane.auth.service import SignInService
from thoth_control_plane.billing import InvalidPlan, UnknownPlan, UnknownWorkspace
from thoth_control_plane.config import Settings, SettingsValidationError
from thoth_control_plane.domain import WorkflowEvent, WorkflowRequest
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.infrastructure.media_store import MediaStoreUnavailable
from thoth_control_plane.infrastructure.project_store import ProjectStore, ProjectStoreUnavailable
from thoth_control_plane.infrastructure.report_store import ReportStore, ReportStoreUnavailable
from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore
from thoth_control_plane.infrastructure.usage_store import UsageStore
from thoth_control_plane.infrastructure.workflow_run_store import (
    WorkflowRunStore,
    WorkflowRunsUnavailable,
)
from thoth_control_plane.operations.editor_migrations import apply_editor_migrations
from thoth_control_plane.operations.media_import import import_media, remove_local_media
from thoth_control_plane.operations.report_import import import_reports
from thoth_control_plane.operations.run_backfill import (
    backfill_runs,
    temporal_start_times,
    workflows_needing_rows,
)
from thoth_control_plane.operations.stage1_local_preflight import (
    Stage1PreflightError,
    check_stage1_local_environment,
    load_stage1_local_environment,
)
from thoth_control_plane.operations.stage1_provider_preflight import (
    check_stage1_provider_file,
)
from thoth_control_plane.operations.tiktok_soak import TikTokSoakDatasetError, evaluate_tiktok_soak
from thoth_control_plane.operations.tiktok_soak_cli import (
    TikTokSoakInputError,
    load_tiktok_soak_observations,
    write_tiktok_soak_report,
)
from thoth_control_plane.voice.factory import build_voice
from thoth_control_plane.voice.ports import (
    VoiceNotConfigured,
    VoiceRejected,
    VoiceRequest,
    VoiceUnavailable,
)

app = typer.Typer(no_args_is_help=True)
workflow_app = typer.Typer(no_args_is_help=True)
app.add_typer(workflow_app, name="workflow")
operations_app = typer.Typer(no_args_is_help=True)
app.add_typer(operations_app, name="operations")
editor_app = typer.Typer(no_args_is_help=True)
app.add_typer(editor_app, name="editor")


@editor_app.command("migrate")
def editor_migrate() -> None:
    """Apply explicit Creator Studio editor schema migrations."""
    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    root = Path(__file__).resolve().parents[2] / "migrations" / "editor"
    typer.echo(apply_editor_migrations(database_url.get_secret_value(), root))


reports_app = typer.Typer(no_args_is_help=True)
app.add_typer(reports_app, name="reports")


@reports_app.command("import")
def reports_import(
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
) -> None:
    """Import existing report files into PostgreSQL once; counts only."""
    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    if not artifact_root.is_dir():
        typer.echo("artifact root not found")
        raise typer.Exit(1)
    try:
        counts = import_reports(artifact_root, ReportStore.connect(database_url.get_secret_value()))
    except ReportStoreUnavailable:
        typer.echo("report store unavailable")
        raise typer.Exit(1) from None
    typer.echo(f"imported={counts.imported} present={counts.present} invalid={counts.invalid}")
    if counts.invalid:
        raise typer.Exit(1)


projects_app = typer.Typer(no_args_is_help=True)
app.add_typer(projects_app, name="projects")


@projects_app.command("import")
def projects_import(
    source: Annotated[str, typer.Argument(help="JSON from Rust /api/projects, or - for stdin")],
) -> None:
    """Insert the Rust server's projects with their IDs; never overwrite. Counts only."""
    import sys

    from pydantic import ValidationError

    from thoth_control_plane.domain.projects import Project

    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    store = ProjectStore.connect(database_url.get_secret_value())
    imported = present = invalid = 0
    for item in json.loads(text):
        try:
            # StrictModel accepts ISO timestamps only through JSON validation.
            project = Project.model_validate_json(
                json.dumps(
                    {
                        "project_id": item["id"],
                        "name": str(item["name"]).strip(),
                        "created_at": item["created_at"],
                        "updated_at": item["updated_at"],
                    }
                )
            )
        except (KeyError, TypeError, ValidationError):
            invalid += 1
            continue
        try:
            inserted = store.insert_missing(project)
        except ProjectStoreUnavailable:
            typer.echo("project store unavailable")
            raise typer.Exit(1) from None
        imported += inserted
        present += not inserted
    typer.echo(f"imported={imported} present={present} invalid={invalid}")
    if invalid:
        raise typer.Exit(1)


tokens_app = typer.Typer(no_args_is_help=True)
app.add_typer(tokens_app, name="tokens")


@tokens_app.command("create")
def tokens_create(
    email: Annotated[
        str, typer.Option(help="The developer's email; the user is created if missing")
    ],
    name: Annotated[str, typer.Option(help="What the token is for, e.g. vite or ci")],
    scope: Annotated[str, typer.Option(help="read, write or admin")] = "write",
    days: Annotated[int, typer.Option(help="Lifetime in days, 1 to 365")] = 90,
) -> None:
    """Create a personal developer token (spec 3.3). Prints the token once and nothing else."""
    from pydantic import ValidationError

    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    address = email.strip().lower()
    try:
        request = CreateToken.model_validate({"name": name, "scope": scope, "days": days})
        if "@" not in address:
            raise ValueError("email")
    except (ValidationError, ValueError):
        typer.echo("invalid_request")
        raise typer.Exit(1) from None
    store = AccountStore.connect(database_url.get_secret_value())
    account = store.ensure_user(address, address.partition("@")[0])
    principal = Principal(
        account.user_id, account.workspace_id, ALL_SCOPES, "session", account.email
    )
    created = asyncio.run(SignInService(store, None, None).create_token(principal, request))
    typer.echo(created.secret)


quotas_app = typer.Typer(no_args_is_help=True)
app.add_typer(quotas_app, name="quotas")
prices_app = typer.Typer(no_args_is_help=True)
app.add_typer(prices_app, name="prices")


def _usage_store() -> UsageStore:
    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    return UsageStore.connect(database_url.get_secret_value())


@quotas_app.command("set")
def quotas_set(workspace_id: str, platform: str, daily_leases: int) -> None:
    """Override a workspace's daily lease quota for one platform (spec 2026-10-20, 1.5)."""
    try:
        _usage_store().set_quota(workspace_id, platform, daily_leases)
    except ValueError:
        typer.echo("invalid_quota")
        raise typer.Exit(1) from None
    except LookupError:
        typer.echo("unknown_workspace")
        raise typer.Exit(1) from None
    typer.echo(f"workspace={workspace_id} platform={platform} daily_leases={daily_leases}")


@quotas_app.command("clear")
def quotas_clear(workspace_id: str, platform: str) -> None:
    """Return a workspace to the platform default."""
    _usage_store().clear_quota(workspace_id, platform)
    typer.echo(f"workspace={workspace_id} platform={platform} default")


@quotas_app.command("show")
def quotas_show(workspace_id: str) -> None:
    """A workspace's daily lease quota and today's use, per platform."""
    store = _usage_store()
    today = store.leases_today(workspace_id)
    for platform, limit in store.quotas(workspace_id).items():
        typer.echo(f"platform={platform} daily_leases={limit} used_today={today.get(platform, 0)}")


@quotas_app.command("reserve")
def quotas_reserve(platform: str, percent: int) -> None:
    """Set the share of a platform's daily capacity kept for the operator (spec 1.4)."""
    from thoth_control_plane.acquisition.accounts.cookies import PLATFORMS
    from thoth_control_plane.acquisition.accounts.vault import Vault
    from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

    settings = Settings()
    vault = Vault.from_key(settings.account_vault_key)
    if vault is None or settings.THOTH_EDITOR_DATABASE_URL is None:
        raise typer.BadParameter("the account vault key and the editor database are required")
    if platform not in PLATFORMS:
        typer.echo("invalid_reserve")
        raise typer.Exit(1)
    store = SourceAccountStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value(), vault)
    policy = store.policy(platform)  # type: ignore[arg-type]
    try:
        store.set_policy(
            policy.platform,
            policy.mode,
            policy.min_spacing_seconds,
            operator_reserve_percent=percent,
        )
    except ValueError:
        typer.echo("invalid_reserve")
        raise typer.Exit(1) from None
    typer.echo(f"platform={platform} operator_reserve_percent={percent}")


@prices_app.command("set")
def prices_set(kind: str, key: str, unit: str, usd_per_unit: float) -> None:
    """Set a unit price in USD; key `*` prices every key of the kind and unit (spec 2.3)."""
    try:
        _usage_store().set_price(kind, key, unit, usd_per_unit)
    except ValueError:
        typer.echo("invalid_price")
        raise typer.Exit(1) from None
    typer.echo(f"{kind} {key} {unit} {usd_per_unit}")


@prices_app.command("list")
def prices_list() -> None:
    """Every unit price, one per line: kind key unit usd."""
    for price in _usage_store().prices():
        typer.echo(f"{price.kind} {price.key} {price.unit} {price.usd_per_unit}")


plans_app = typer.Typer(no_args_is_help=True)
app.add_typer(plans_app, name="plans")
subscriptions_app = typer.Typer(no_args_is_help=True)
app.add_typer(subscriptions_app, name="subscriptions")


def _billing_store() -> BillingStore:
    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    return BillingStore.connect(database_url.get_secret_value())


@plans_app.command("set")
def plans_set(
    plan_id: str,
    name: Annotated[str, typer.Option()],
    price_idr: Annotated[int, typer.Option()],
    workflows: Annotated[int, typer.Option()],
    videos: Annotated[int, typer.Option()],
    period_days: Annotated[int | None, typer.Option()] = None,
    active: Annotated[bool | None, typer.Option("--active/--inactive")] = None,
) -> None:
    """Create or change a plan (spec 2026-10-20 billing, 1.1); no deploy needed."""
    try:
        _billing_store().set_plan(
            plan_id,
            name=name,
            price_idr=price_idr,
            workflows=workflows,
            videos=videos,
            period_days=period_days,
            active=active,
        )
    except InvalidPlan:
        typer.echo("invalid_plan")
        raise typer.Exit(1) from None
    typer.echo(f"plan={plan_id} saved")


@plans_app.command("list")
def plans_list() -> None:
    """Every plan, one per line: id name price allowance days state."""
    for p in _billing_store().plans():
        typer.echo(
            f"{p.plan_id} {p.name} {p.price_idr} workflows={p.workflows_per_period} "
            f"videos={p.videos_per_period} days={p.period_days} "
            f"{'active' if p.active else 'inactive'}"
        )


@plans_app.command("rate")
def plans_rate(idr_per_usd: float) -> None:
    """Rupiah per US dollar for the margin report (spec 1.5)."""
    try:
        rate = _billing_store().set_usd_idr_rate(idr_per_usd)
    except InvalidPlan:
        typer.echo("invalid_rate")
        raise typer.Exit(1) from None
    typer.echo(f"idr_per_usd={rate}")


@subscriptions_app.command("set")
def subscriptions_set(workspace_id: str, plan_id: str, days: int) -> None:
    """Grant a plan for `days` from now, with no payment (spec 1.2)."""
    try:
        sub = _billing_store().grant(workspace_id, plan_id, days)
    except UnknownWorkspace:
        typer.echo("unknown_workspace")
        raise typer.Exit(1) from None
    except UnknownPlan:
        typer.echo("unknown_plan")
        raise typer.Exit(1) from None
    typer.echo(f"workspace={workspace_id} plan={sub.plan_id} until={sub.period_end.isoformat()}")


voice_app = typer.Typer(no_args_is_help=True)
app.add_typer(voice_app, name="voice")


@voice_app.command("say")
def voice_say(
    voice: Annotated[str, typer.Option("--voice")],
    out: Annotated[Path, typer.Option("--out")],
    provider: Annotated[str, typer.Option("--provider")] = "elevenlabs",
    model: Annotated[str | None, typer.Option("--model")] = None,
    speed: Annotated[float, typer.Option("--speed")] = 1.0,
    language: Annotated[str, typer.Option("--language")] = "id",
    text: Annotated[str | None, typer.Option("--text")] = None,
    file: Annotated[Path | None, typer.Option("--file")] = None,
) -> None:
    """Synthesize one script with a live provider (operator only; no test calls a provider)."""
    if (text is None) == (file is None):
        raise typer.BadParameter("give exactly one of --text or --file")
    if provider not in ("elevenlabs", "openai-compatible"):
        raise typer.BadParameter("provider must be elevenlabs or openai-compatible")
    script = text if text is not None else file.read_text(encoding="utf-8")  # type: ignore[union-attr]
    try:
        request = VoiceRequest(
            text=script, voice_id=voice, model=model, speed=speed, language=language
        )
    except ValidationError:
        typer.echo("VoiceRejected: invalid_request")
        raise typer.Exit(1) from None
    settings = Settings()
    if settings.THOTH_EDITOR_DATABASE_URL is not None:
        # An operator call outside any workspace: metered for the bootstrap (spec 2026-10-20, 3.1).
        metering.install(UsageStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value()))
    try:
        synthesizer = build_voice(settings, provider.replace("-", "_"))  # type: ignore[arg-type]
        result = asyncio.run(synthesizer.synthesize(request))
    except (VoiceNotConfigured, VoiceRejected, VoiceUnavailable) as error:
        typer.echo(f"{type(error).__name__}: {error}")
        raise typer.Exit(1) from None
    out.write_bytes(result.audio)
    words = [word.model_dump() for word in result.word_timings or []]
    Path(f"{out}.words.json").write_text(json.dumps(words), encoding="utf-8")
    typer.echo(
        f"provider={provider} duration_seconds={result.duration_seconds:.2f} words={len(words)}"
    )


media_app = typer.Typer(no_args_is_help=True)
app.add_typer(media_app, name="media")


@media_app.command("import")
def media_import(
    artifact_root: Annotated[Path, typer.Option("--artifact-root")],
    remove_local: Annotated[bool, typer.Option("--remove-local")] = False,
    archive: Annotated[bool, typer.Option("--archive")] = False,
) -> None:
    """Copy the volume's media into the S3 store and verify it; counts only."""
    settings = Settings()
    if not settings.THOTH_MEDIA_S3_ENDPOINT:
        typer.echo("media store is not configured")
        raise typer.Exit(1)
    if not artifact_root.is_dir():
        typer.echo("artifact root not found")
        raise typer.Exit(1)
    try:
        store = S3MediaStore.from_settings(settings)
    except SettingsValidationError:
        typer.echo("media store is not configured")
        raise typer.Exit(1) from None
    try:
        store.ensure_bucket()
        if remove_local:
            removal = remove_local_media(artifact_root, store, archive=archive)
            typer.echo(f"removed={removal.removed} kept={removal.kept}")
            if removal.kept:
                raise typer.Exit(1)
            return
        counts = import_media(artifact_root, store, archive=archive)
    except MediaStoreUnavailable:
        typer.echo("media store unavailable")
        raise typer.Exit(1) from None
    except OSError:
        # A full or unwritable local disk while verifying: one line, never a path or traceback.
        typer.echo("media import failed: local disk error")
        raise typer.Exit(1) from None
    typer.echo(
        f"imported={counts.imported} present={counts.present} "
        f"invalid={counts.invalid} mismatch={counts.mismatch}"
    )
    if counts.invalid or counts.mismatch:
        raise typer.Exit(1)


def _settings() -> tuple[str, str]:
    base_url = os.environ.get("THOTH_CONTROL_PLANE_URL", "http://localhost:8000").rstrip("/")
    api_key = os.environ.get("THOTH_CONTROL_PLANE_API_KEY", "")
    if not api_key:
        raise typer.BadParameter("THOTH_CONTROL_PLANE_API_KEY must be set")
    return base_url, api_key


def _request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    base_url, api_key = _settings()
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    response = httpx.request(method, f"{base_url}{path}", headers=headers, json=payload, timeout=30)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        detail = error.response.text or str(error)
        raise typer.Exit(code=1) from typer.BadParameter(detail)
    return response.json()


def _stream_events(path: str) -> Iterator[WorkflowEvent]:
    """Read only typed SSE data from the public workflow API."""
    base_url, api_key = _settings()
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.stream("GET", f"{base_url}{path}", headers=headers, timeout=30) as response:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text or str(error)
            raise typer.Exit(code=1) from typer.BadParameter(detail)
        for line in response.iter_lines():
            if line.startswith("data:"):
                yield WorkflowEvent.model_validate_json(line.removeprefix("data:").strip())


def _render(summary: dict[str, Any]) -> None:
    typer.echo(json.dumps(summary, indent=2, sort_keys=True, default=str))


@workflow_app.command("backfill")
def workflows_backfill() -> None:
    """Create run rows for workflows that already have reports; idempotent; counts only."""
    database_url = Settings().THOTH_EDITOR_DATABASE_URL
    if database_url is None:
        raise typer.BadParameter("THOTH_EDITOR_DATABASE_URL must be configured")
    settings = Settings()
    store = WorkflowRunStore.connect(database_url.get_secret_value())
    try:
        ids = workflows_needing_rows(store)
        start_times = asyncio.run(_backfill_start_times(settings, ids))
        counts = backfill_runs(store, start_times=start_times)
    except WorkflowRunsUnavailable:
        typer.echo("workflow run store unavailable")
        raise typer.Exit(1) from None
    typer.echo(
        f"inserted={counts.inserted} present={counts.present} invalid={counts.invalid}"
        f" start_times={len(start_times)}"
    )


async def _backfill_start_times(settings: Settings, workflow_ids: list[str]) -> dict[str, Any]:
    """Temporal start times for the backfill; Temporal down means report times for all."""
    from temporalio.client import Client

    try:
        client = await Client.connect(
            settings.THOTH_TEMPORAL_TARGET, namespace=settings.THOTH_TEMPORAL_NAMESPACE
        )
    except Exception as error:
        typer.echo(f"temporal unavailable ({type(error).__name__}); using report times")
        return {}
    return await temporal_start_times(client, workflow_ids)


@workflow_app.command("start")
def start(
    url: Annotated[str, typer.Option("--url")],
    style: Annotated[str, typer.Option("--style")],
    format_: Annotated[str, typer.Option("--format")] = "mp4",
    language: Annotated[str, typer.Option("--language")] = "id",
    require_publish_approval: Annotated[bool, typer.Option("--review/--no-review")] = True,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    """Start one video workflow through the v1 API."""
    request = WorkflowRequest.model_validate(
        {
            "source": {"url": url, "intent": "produce_video"},
            "style": {"preset_id": style},
            "output": {"format": format_, "language": language},
            "review": {"require_publish_approval": require_publish_approval},
        }
    )
    key = idempotency_key or str(uuid.uuid4())
    try:
        summary = _request(
            "POST",
            "/api/v1/workflows",
            payload=request.model_dump(mode="json"),
            idempotency_key=key,
        )
    except typer.Exit:
        # A failed start may still have started the workflow; the same key reaches it, a new
        # one would start a second.
        typer.echo(f"Retry with --idempotency-key {key} to reach the same workflow.", err=True)
        raise
    _render(summary)


@workflow_app.command("watch")
def watch(workflow_id: str) -> None:
    """Stream typed v1 workflow events until the API closes the SSE connection."""
    for event in _stream_events(f"/api/v1/workflows/{workflow_id}/events"):
        _render(event.model_dump(mode="json"))


@workflow_app.command("approve")
def approve(
    workflow_id: str,
    approval_id: Annotated[str, typer.Option("--approval-id")],
    decision: Annotated[str, typer.Option("--decision")] = "approve",
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    """Record a publish decision."""
    approval = ApprovalSubmission.model_validate(
        {"approval_id": approval_id, "decision": decision, "note": note}
    )
    _render(
        _request(
            "POST",
            f"/api/v1/workflows/{workflow_id}/approve",
            payload=approval.model_dump(mode="json", exclude_none=True),
        )
    )


@workflow_app.command("cancel")
def cancel(workflow_id: str) -> None:
    """Cancel a workflow."""
    _render(_request("POST", f"/api/v1/workflows/{workflow_id}/cancel"))


@operations_app.command("tiktok-stage1-soak")
def tiktok_stage1_soak(
    observations: Annotated[Path, typer.Option("--observations")],
    output_directory: Annotated[Path, typer.Option("--output-directory")] = Path("."),
) -> None:
    """Load a Stage 1 TikTok soak dataset and write the aggregate report."""
    try:
        items = load_tiktok_soak_observations(observations)
        report = evaluate_tiktok_soak(items, generated_at=datetime.now(UTC))
        write_tiktok_soak_report(report, output_directory)
    except (TikTokSoakInputError, TikTokSoakDatasetError, OSError):
        typer.echo("tiktok stage 1 soak evaluation failed", err=True)
        raise typer.Exit(code=1) from None
    typer.echo("tiktok stage 1 soak report written")


@operations_app.command("stage1-local-preflight")
def stage1_local_preflight(
    env_file: Annotated[Path, typer.Option("--env-file")] = Path(".env.stage1.local"),
    provider_env_file: Annotated[Path | None, typer.Option("--provider-env-file")] = None,
) -> None:
    """Validate the local Stage 1 deployment environment before pulling images.

    Run from the repository root: the working directory is the repository the
    data root must stay outside of. Output names variables only, never values.

    `--provider-env-file` additionally validates the restricted Scout provider file
    required for a fallback-ready deployment. Omitting it preserves the existing
    non-live behaviour.
    """
    try:
        values = load_stage1_local_environment(env_file)
        check_stage1_local_environment(values, repository_root=Path.cwd())
        if provider_env_file is not None:
            check_stage1_provider_file(provider_env_file, repository_root=Path.cwd())
    except Stage1PreflightError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo("stage 1 local preflight passed")


sfx_app = typer.Typer(no_args_is_help=True)
app.add_typer(sfx_app, name="sfx")


@sfx_app.command("seed")
def sfx_seed(
    directory: Annotated[Path, typer.Option("--dir")] = Path("/opt/thoth/assets/sfx"),
    catalog: Annotated[Path, typer.Option("--catalog")] = Path(
        "/opt/thoth/assets/asset_catalog.json"
    ),
) -> None:
    """Seed the licensed bundled SFX into object storage and the library (idempotent)."""
    from thoth_control_plane.application.sfx_library import seed_sfx
    from thoth_control_plane.infrastructure.media_store import build_media_store
    from thoth_control_plane.infrastructure.narration_store import NarrationStore

    settings = Settings()
    if settings.THOTH_EDITOR_DATABASE_URL is None:
        typer.echo("editor_database_not_configured")
        raise typer.Exit(1)
    store = NarrationStore(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value())
    report = asyncio.run(
        seed_sfx(
            store, build_media_store(settings), catalog, directory, Path(settings.THOTH_FFMPEG)
        )
    )
    typer.echo(f"added={report.added} unchanged={report.unchanged} skipped={len(report.skipped)}")
