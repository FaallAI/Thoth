"""Safe Python source-investigation activity boundary."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from pathlib import Path, PurePosixPath

import httpx
from pydantic import HttpUrl, TypeAdapter
from temporalio import activity

from thoth_control_plane.acquisition.accounts.access import SessionAccess
from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles
from thoth_control_plane.acquisition.accounts.runner import account_runner
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.acquisition.browser import (
    ScraplingCapability,
    active_scrapling_session_count,
)
from thoth_control_plane.acquisition.materializer import (
    MediaMaterializer,
    resolve_host_via_getaddrinfo,
)
from thoth_control_plane.acquisition.models import (
    AccountUse,
    AcquisitionAttempt,
    AcquisitionResult,
    AcquisitionStrategy,
    AttemptStatus,
    SourceReport,
)
from thoth_control_plane.acquisition.platforms import platform_of
from thoth_control_plane.acquisition.registry import acquirer_for
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import (
    ArtifactRef,
    SourceInvestigationActivityResult,
)
from thoth_control_plane.domain.models import (
    OpaqueId,
    SafeActivityError,
    SourceProgressEvent,
    StrictModel,
)
from thoth_control_plane.infrastructure.report_store import (
    ReportInvalid,
    Reports,
    ReportStoreUnavailable,
    connect_reports,
)
from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

AcquisitionRunner = Callable[[str, str, Path], Awaitable[AcquisitionResult]]

_CAPABILITY_ADAPTER = TypeAdapter(ScraplingCapability)
logger = logging.getLogger(__name__)

_STAGE_SUFFIXES: dict[AcquisitionStrategy, str] = {
    AcquisitionStrategy.SCRAPLING_HEADLESS: "headless",
    AcquisitionStrategy.TIKWM_CDN: "cdn",
    AcquisitionStrategy.SCRAPLING_REQUEST: "request",
}


class SourceInvestigationActivityInput(StrictModel):
    """Small typed activity input carried in Temporal history."""

    workflow_id: OpaqueId
    request_snapshot_id: OpaqueId
    canonical_source_url: HttpUrl


def _coerce_capability(
    capability: ScraplingCapability | Mapping[str, object] | None,
) -> ScraplingCapability:
    """Accept a real capability, a plain mapping (e.g. from a test double), or None."""
    if capability is None:
        return ScraplingCapability(available=True, code=None)
    return _CAPABILITY_ADAPTER.validate_python(capability)


def _account_store(settings: Settings) -> SourceAccountStore | None:
    vault = Vault.from_key(settings.account_vault_key)
    if vault is None or settings.THOTH_EDITOR_DATABASE_URL is None:
        logger.warning("source accounts unavailable; acquisition runs anonymously")
        return None
    return SourceAccountStore.connect(settings.THOTH_EDITOR_DATABASE_URL.get_secret_value(), vault)


def _account_profiles(settings: Settings) -> AccountProfiles | None:
    vault = Vault.from_key(settings.account_vault_key)
    return None if vault is None else AccountProfiles(vault, settings.THOTH_ACCOUNT_PROFILE_DIR)


def build_production_acquisition_runner(settings: Settings) -> AcquisitionRunner:
    """Build a fresh HTTP client and materializer per acquisition; the acquirer owns its browser.

    Source accounts wrap the acquisition when the vault key and the editor database are
    configured; otherwise every acquisition runs anonymously.
    """

    async def acquire(
        workflow_id: str, source_url: str, artifact_root: Path, access: SessionAccess | None
    ) -> AcquisitionResult:
        with contextlib.ExitStack() as stack:
            # A private directory for yt-dlp's cookie file, removed with everything in it.
            scratch = (
                Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="thoth-session-")))
                if access is not None
                else None
            )
            async with httpx.AsyncClient(follow_redirects=False) as client:
                materializer = MediaMaterializer(client, resolve_host_via_getaddrinfo)
                acquirer = acquirer_for(
                    source_url,
                    client=client,
                    materializer=materializer,
                    access=access,
                    scratch=scratch,
                )
                return await acquirer.inspect(
                    workflow_id=workflow_id, source_url=source_url, artifact_root=artifact_root
                )

    return account_runner(_account_store(settings), acquire, _account_profiles(settings))


def _attempt_events(attempts: list[AcquisitionAttempt], platform: str) -> list[SourceProgressEvent]:
    """Reduce acquisition attempts to safe, fixed-taxonomy progress events.

    Only enum values and elapsed milliseconds cross this boundary; no raw
    diagnostic, URL, or provider response ever reaches Temporal history.
    """
    events: list[SourceProgressEvent] = []
    for attempt in attempts:
        stage = f"{platform}_{_STAGE_SUFFIXES[attempt.strategy]}"
        events.append(SourceProgressEvent(kind="stage.started", payload={"stage": stage}))
        completion_kind = (
            "stage.failed" if attempt.status == AttemptStatus.FAILED else "stage.completed"
        )
        payload: dict[str, str | int | float | bool | None] = {
            "stage": stage,
            "status": attempt.status.value,
            "elapsed_ms": attempt.elapsed_ms,
        }
        if attempt.reason is not None:
            payload["reason"] = attempt.reason.value
        events.append(SourceProgressEvent(kind=completion_kind, payload=payload))
    return events


def _cleanup_event(artifact_root: Path, workflow_id: str, platform: str) -> SourceProgressEvent:
    """Inspect and report cleanup evidence as booleans and safe codes only.

    Never includes the report directory path, an exception, or any other
    diagnostic text -- only whether the two safety invariants held.
    """
    try:
        # Resolution is part of the probe, not a preamble to it: it touches the
        # filesystem and can raise. Outside this guard an OSError escapes the
        # activity, which returns no cleanup evidence at all and drops the run
        # from the soak denominator -- the exact outcome the zero-tolerance
        # cleanup blockers exist to catch. Fail closed instead.
        report_dir = (artifact_root / "reports" / workflow_id).resolve()
        partial_cleanup_passed = not report_dir.exists() or not any(report_dir.rglob("*.part"))
    except OSError:
        partial_cleanup_passed = False
    browser_cleanup_passed = active_scrapling_session_count() == 0
    passed = partial_cleanup_passed and browser_cleanup_passed
    return SourceProgressEvent(
        kind="stage.completed" if passed else "stage.failed",
        payload={
            "stage": f"{platform}_cleanup",
            "status": "succeeded" if passed else "failed",
            "partial_cleanup_passed": partial_cleanup_passed,
            "browser_cleanup_passed": browser_cleanup_passed,
        },
    )


def _account_events(account: AccountUse | None, platform: str) -> list[SourceProgressEvent]:
    """One enum-only event when source accounts took part; never an account or a label."""
    if account is None:
        return []
    payload: dict[str, str | int | float | bool | None] = {
        "stage": f"{platform}_account",
        "account_used": account.used,
        "no_account_available": account.no_account_available,
    }
    if account.outcome is not None:
        payload["account_outcome"] = account.outcome
    return [SourceProgressEvent(kind="stage.progress", payload=payload)]


def _terminal_events(
    attempts: list[AcquisitionAttempt],
    artifact_root: Path,
    workflow_id: str,
    platform: str,
    account: AccountUse | None = None,
) -> list[SourceProgressEvent]:
    """Compose the full history-safe event trail for a terminal activity result.

    Always attempt events followed by exactly one cleanup event, so every
    path that enters the runner boundary leaves matching evidence behind.
    """
    return [
        *_attempt_events(attempts, platform),
        *_account_events(account, platform),
        _cleanup_event(artifact_root, workflow_id, platform),
    ]


def _cleanup_after_persistence_failure(report: SourceReport, artifact_root: Path) -> None:
    """Remove every media and card file the report recorded.

    Artifact locations are validated as `PurePosixPath` (POSIX separators only),
    but a Windows-style backslash string can slip past that check as a single
    opaque segment and then, once joined with a real `Path`, resolve to an
    absolute path or a `..` escape outside `artifact_root`. Only unlink
    candidates that resolve inside the artifact root; skip anything else.
    """
    resolved_root = artifact_root.resolve()
    locations = [media.location for media in report.media]
    locations += [comment.card.location for comment in report.comments if comment.card]
    if report.profile_card is not None:
        locations.append(report.profile_card.location)
    if report.post_card is not None:
        locations.append(report.post_card.location)
    for location in locations:
        candidate = (artifact_root / location).resolve()
        if not candidate.is_relative_to(resolved_root):
            continue
        with contextlib.suppress(OSError):
            candidate.unlink(missing_ok=True)


async def _run(
    input_: SourceInvestigationActivityInput,
    artifact_root: Path,
    runner: AcquisitionRunner,
    capability: ScraplingCapability,
    reports: Reports,
) -> SourceInvestigationActivityResult:
    """Run the injected acquisition runner and store its report in PostgreSQL."""
    platform = platform_of(str(input_.canonical_source_url))
    if platform is None:
        # The workflow guard routes only Python platforms here; anything else is
        # refused before the capability gate and never enters the runner.
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(code="unsupported_platform", retryable=False)
        )

    if not capability.available:
        # A capability-unavailable result is terminal, and the soak contract
        # requires cleanup evidence for every terminal route -- so this branch
        # owes a cleanup event even though the runner boundary was never
        # entered and nothing could have been left behind. Without it an
        # observation cannot be formed from activity evidence at all, which
        # would make `ACQUISITION_DEPENDENCY_FAILURE_PRESENT` unreachable and
        # silently drop these runs from the terminal-failure denominator:
        # a partial Scrapling outage would hide from the readiness gate by
        # losing exactly the runs that should block it. The booleans are
        # trivially true here, but they are measured by the same helper as
        # every other route rather than assumed.
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(
                code=capability.code or "acquisition_dependency_unavailable", retryable=False
            ),
            events=_terminal_events([], artifact_root, input_.workflow_id, platform),
        )

    try:
        acquisition_result = await runner(
            input_.workflow_id, str(input_.canonical_source_url), artifact_root
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Defense in depth: if the capability gate above is ever bypassed, a
        # raw exception (e.g. the lazy Scrapling ImportError) must not carry
        # its message into Temporal history. Nothing derived from the
        # exception crosses this boundary -- only a fixed, safe code. The
        # runner boundary was still entered, so cleanup evidence is owed
        # even though no acquisition attempt ever completed.
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(code="acquisition_runner_failed", retryable=False),
            events=_terminal_events([], artifact_root, input_.workflow_id, platform),
        )

    if acquisition_result.failure is not None:
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(
                code=acquisition_result.failure.code,
                retryable=acquisition_result.failure.retryable,
            ),
            events=_terminal_events(
                acquisition_result.failure.attempts,
                artifact_root,
                input_.workflow_id,
                platform,
                acquisition_result.account,
            ),
        )

    report = acquisition_result.report
    assert report is not None  # AcquisitionResult guarantees exactly one outcome

    # Ruling F-4a: the report artifact location is derived solely from the
    # activity input's workflow_id, never from the report body.
    location = PurePosixPath("reports") / input_.workflow_id / "source-report.json"
    content = report.model_dump_json(indent=2, exclude_none=False).encode("utf-8")

    try:
        await asyncio.to_thread(reports.put, location.as_posix(), "source_report", content)
    except asyncio.CancelledError:
        _cleanup_after_persistence_failure(report, artifact_root)
        raise
    except (ReportStoreUnavailable, ReportInvalid):
        _cleanup_after_persistence_failure(report, artifact_root)
        return SourceInvestigationActivityResult(
            failure=SafeActivityError(code="artifact_persistence_failed", retryable=True),
            events=_terminal_events(
                report.outcome.attempts,
                artifact_root,
                input_.workflow_id,
                platform,
                acquisition_result.account,
            ),
        )

    digest = sha256(content).hexdigest()
    artifact = ArtifactRef(
        artifact_id=f"art_source_{digest[:20]}",
        kind="source_report",
        label="Source investigation report",
        media_type="application/json",
        location=location.as_posix(),
        checksum=f"sha256:{digest}",
        size_bytes=len(content),
    )
    events = _terminal_events(
        report.outcome.attempts,
        artifact_root,
        input_.workflow_id,
        platform,
        acquisition_result.account,
    )
    return SourceInvestigationActivityResult(report=artifact, events=events)


@activity.defn(name="inspect_source_candidates")
async def inspect_source_candidates(
    input_: SourceInvestigationActivityInput,
) -> SourceInvestigationActivityResult:
    """Activity-name reference for workflow definitions and direct local use."""
    configured = build_source_investigation_activity(Settings())  # type: ignore[call-arg]
    return await configured(input_)


def build_source_investigation_activity(
    settings: Settings,
    *,
    runner: AcquisitionRunner | None = None,
    capability: ScraplingCapability | Mapping[str, object] | None = None,
    reports: Reports | None = None,
) -> Callable[
    [SourceInvestigationActivityInput],
    Awaitable[SourceInvestigationActivityResult],
]:
    """Bind the production activity to the same configured root used by FastAPI."""

    artifact_root = settings.THOTH_CONTROL_PLANE_ARTIFACT_ROOT.resolve()
    selected_runner = runner or build_production_acquisition_runner(settings)
    selected_capability = _coerce_capability(capability)
    selected_reports = reports or connect_reports(settings)

    @activity.defn(name="inspect_source_candidates")
    async def configured_source_investigation_activity(
        input_: SourceInvestigationActivityInput,
    ) -> SourceInvestigationActivityResult:
        return await _run(
            input_, artifact_root, selected_runner, selected_capability, selected_reports
        )

    return configured_source_investigation_activity
