"""The revision-bound render lifecycle: one slot, no queue, no automatic retry.

Creation runs the whole preparation synchronously - resolve the exact saved
revision, stage a verified bundle, claim the single active slot, dispatch once -
and then returns. Nothing here waits for a render: every later status change
arrives as one sequenced internal event, and the only background work is a
bounded scan that closes jobs which outlived their deadline.

A failure closes the job with one fixed safe code and frees the slot. It never
schedules, re-dispatches, or keeps a waiting row, because an installation that
is already rendering must refuse a new request rather than remember it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from pydantic import Field

from thoth_control_plane import metering
from thoth_control_plane.application.editor_asset_ports import EditorAssetRepository
from thoth_control_plane.application.ports import EditDocumentRepository, StudioImportRepository
from thoth_control_plane.application.render_bundles import (
    TRUSTED_TEMPLATE_ID,
    TRUSTED_TEMPLATE_VERSION,
    BuildRenderBundleRequest,
    RenderBundleInvalid,
    RenderBundleV1,
    RenderPresetSettings,
    build_render_bundle,
)
from thoth_control_plane.application.render_job_ports import (
    ArtifactRoot,
    ArtifactUnavailable,
    ReceivedOutput,
    RendererGateway,
    RendererNotConfigured,
    RendererRejected,
    RendererUnavailable,
    RenderImportUnresolved,
    RenderJobNotActive,
    RenderJobNotCancellable,
    RenderJobNotCleanable,
    RenderJobNotFound,
    RenderJobNotRetryable,
    RenderJobRepository,
    RenderPersistenceError,
    RenderRevisionStale,
)
from thoth_control_plane.auth.models import actor_workspace_id
from thoth_control_plane.domain.models import OpaqueId, StrictModel
from thoth_control_plane.domain.render_jobs import (
    ACTIVE_RENDER_STATUSES,
    TERMINAL_RENDER_STATUSES,
    RenderCapability,
    RenderFailureCode,
    RenderJob,
    RenderJobEvent,
    RenderJobPage,
    RenderOutputFacts,
    RenderProvenance,
)

MAX_PAGE_SIZE = 50
#: One reconciliation pass touches a bounded slice of already-active rows.
RECONCILE_BATCH = 20
#: Only one render can ever be active, so a retriable predecessor is terminal.
RETRYABLE_STATUSES = frozenset({"failed", "cancelled"})


class CreateRenderJobRequest(StrictModel):
    """A render request naming one exact saved revision and nothing else."""

    document_id: OpaqueId
    document_revision: Annotated[int, Field(gt=0)]


class ListRenderJobsRequest(StrictModel):
    """One bounded page of a project's render history."""

    limit: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)] = 20
    cursor: Annotated[str, Field(min_length=1, max_length=256)] | None = None


@dataclass(frozen=True)
class DownloadableRender:
    """One completed render resolved to its stored object for streaming."""

    location: str
    media_type: str
    filename: str
    size_bytes: int
    checksum: str


def _default_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _payload_hash(
    project_id: str, request: CreateRenderJobRequest, retry_of_job_id: str | None
) -> str:
    """Hash the canonical request, so one key can only replay the same render."""
    canonical = json.dumps(
        {
            "project_id": project_id,
            "document_id": request.document_id,
            "document_revision": request.document_revision,
            "retry_of_job_id": retry_of_job_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RenderJobService:
    """Own the render lifecycle end to end, holding no renderer state itself."""

    def __init__(
        self,
        *,
        jobs: RenderJobRepository | None,
        documents: EditDocumentRepository | None,
        assets: EditorAssetRepository | None,
        artifacts: ArtifactRoot | None,
        renderer: RendererGateway,
        settings: RenderPresetSettings,
        max_render_seconds: int,
        imports: StudioImportRepository | None = None,
        clock: Callable[[], datetime] = _utcnow,
        new_id: Callable[[str], str] = _default_id,
        billing: Any = None,
    ) -> None:
        self._jobs = jobs
        self._documents = documents
        self._assets = assets
        self._artifacts = artifacts
        self._renderer = renderer
        self._settings = settings
        self._max_render_seconds = max_render_seconds
        self._imports = imports
        self._clock = clock
        self._new_id = new_id
        self._billing = billing

    @property
    def _enabled(self) -> bool:
        return (
            self._jobs is not None
            and self._documents is not None
            and self._assets is not None
            and self._artifacts is not None
            and self._renderer.configured
        )

    def _require_enabled(self) -> RenderJobRepository:
        if not self._enabled or self._jobs is None:
            raise RendererNotConfigured()
        return self._jobs

    # --- reads ------------------------------------------------------------

    async def capability(self, project_id: str) -> RenderCapability:
        """Report whether this installation can start a render right now."""
        if not self._enabled or self._jobs is None:
            return self._capability(False, "renderer_not_configured")
        active = await self._jobs.get_active()
        if active is None:
            return self._capability(True, None)
        # Another project's job identity is not this caller's to see.
        owned = active.render_job_id if active.project_id == project_id else None
        return self._capability(False, "render_busy", owned)

    def _capability(
        self, available: bool, reason: str | None, active_render_job_id: str | None = None
    ) -> RenderCapability:
        return RenderCapability.model_validate(
            {
                "available": available,
                "reason": reason,
                "preset_id": self._settings.preset_id,
                "renderer_version": self._settings.renderer_version,
                "active_render_job_id": active_render_job_id,
            }
        )

    async def get(self, project_id: str, render_job_id: str) -> RenderJob:
        jobs = self._require_enabled()
        job = await jobs.get(project_id=project_id, render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        return job

    async def list(self, project_id: str, request: ListRenderJobsRequest) -> RenderJobPage:
        jobs = self._require_enabled()
        return await jobs.list(project_id=project_id, limit=request.limit, cursor=request.cursor)

    # --- create and retry -------------------------------------------------

    async def create(
        self,
        *,
        project_id: str,
        actor_id: str,
        request: CreateRenderJobRequest,
        idempotency_key: str,
    ) -> RenderJob:
        """Prepare, claim the slot, and dispatch one render, or close it failed."""
        return await self._create(project_id, actor_id, request, idempotency_key, None)

    async def retry(
        self, project_id: str, actor_id: str, render_job_id: str, idempotency_key: str
    ) -> RenderJob:
        """Start a new job for the same immutable revision; never reopen the old one."""
        source = await self.get(project_id, render_job_id)
        if source.status not in RETRYABLE_STATUSES:
            raise RenderJobNotRetryable()
        request = CreateRenderJobRequest(
            document_id=source.document_id, document_revision=source.document_revision
        )
        return await self._create(
            project_id, actor_id, request, idempotency_key, source.render_job_id
        )

    async def _create(
        self,
        project_id: str,
        actor_id: str,
        request: CreateRenderJobRequest,
        idempotency_key: str,
        retry_of_job_id: str | None,
    ) -> RenderJob:
        jobs = self._require_enabled()
        render_job_id = self._new_id("rj")
        dispatch_id = self._new_id("dsp")
        payload_hash = _payload_hash(project_id, request, retry_of_job_id)
        # A retry re-renders a revision that already passed this check when first created.
        if retry_of_job_id is None:
            try:
                await self._require_import_ready(project_id, request)
            except (RenderImportUnresolved, RenderRevisionStale):
                # The draft may have moved on since an identical request succeeded.
                replay = await jobs.find_replay(
                    project_id=project_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                )
                if replay is None:
                    raise
                return replay

        try:
            bundle = await self._stage(render_job_id, dispatch_id, project_id, request)
        except (RenderBundleInvalid, ArtifactUnavailable) as error:
            code: RenderFailureCode = (
                "render_bundle_invalid"
                if isinstance(error, RenderBundleInvalid)
                else "render_asset_unavailable"
            )
            await self._record_closed(
                jobs,
                self._shell(render_job_id, dispatch_id, project_id, actor_id, request),
                retry_of_job_id,
                code,
                idempotency_key,
                payload_hash,
            )
            raise

        job = self._shell(
            render_job_id,
            dispatch_id,
            project_id,
            actor_id,
            request,
            retry_of_job_id=retry_of_job_id,
            asset_checksums=[
                {"asset_id": asset.asset_id, "checksum": asset.checksum} for asset in bundle.assets
            ],
        )
        # A replay of an earlier request returns its render and never takes a second unit.
        try:
            replay = await jobs.find_replay(
                project_id=project_id, idempotency_key=idempotency_key, payload_hash=payload_hash
            )
        except BaseException:
            await asyncio.to_thread(self._discard, render_job_id)
            raise
        if replay is not None:
            await asyncio.to_thread(self._discard, render_job_id)
            return replay
        try:
            await self._consume(actor_id, render_job_id)
        except BaseException:
            await asyncio.to_thread(self._discard, render_job_id)  # refused: nothing staged stays
            raise
        try:
            reserved = await jobs.reserve(
                job, idempotency_key=idempotency_key, payload_hash=payload_hash
            )
        except BaseException:
            # This request never owned a slot: its unit and its workspace go back.
            await self._give_back(job)
            await asyncio.to_thread(self._discard, render_job_id)
            raise
        if reserved.render_job_id != render_job_id:
            # An identical earlier request already owns this key and its render.
            await self._give_back(job)
            return reserved

        try:
            await self._renderer.start(render_job_id=render_job_id, dispatch_id=dispatch_id)
        except (RendererUnavailable, RendererRejected, RendererNotConfigured):
            await self._close(jobs, reserved, "render_dispatch_failed")
            raise
        return reserved

    async def _require_import_ready(self, project_id: str, request: CreateRenderJobRequest) -> None:
        """Refuse a source-linked draft until every import item has a decision.

        Read at creation time, so a checklist the browser showed earlier is never
        the authority. Decisions are final and a rendered revision is immutable,
        so nothing this check passed can become unready before dispatch.
        """
        if self._imports is None:
            return
        try:
            inventory = await self._imports.get_inventory(
                project_id=project_id, document_id=request.document_id
            )
        except Exception as error:
            raise RenderPersistenceError() from error
        if inventory is None:
            return  # not opened from a source: nothing to resolve
        if inventory.revision != request.document_revision:
            raise RenderRevisionStale()
        if any(item.disposition == "unresolved" for item in inventory.items):
            raise RenderImportUnresolved()

    async def _stage(
        self,
        render_job_id: str,
        dispatch_id: str,
        project_id: str,
        request: CreateRenderJobRequest,
    ) -> RenderBundleV1:
        return await build_render_bundle(
            BuildRenderBundleRequest(
                render_job_id=render_job_id,
                project_id=project_id,
                document_id=request.document_id,
                document_revision=request.document_revision,
                dispatch_id=dispatch_id,
            ),
            documents=self._documents,
            assets=self._assets,
            artifacts=self._artifacts,
            settings=self._settings,
        )

    def _shell(
        self,
        render_job_id: str,
        dispatch_id: str,
        project_id: str,
        actor_id: str,
        request: CreateRenderJobRequest,
        *,
        retry_of_job_id: str | None = None,
        asset_checksums: list[dict[str, str]] | None = None,
    ) -> RenderJob:
        """Build the durable row for one render, before anything is dispatched."""
        provenance = RenderProvenance.model_validate(
            {
                "document_revision": request.document_revision,
                "template_id": TRUSTED_TEMPLATE_ID,
                "template_version": TRUSTED_TEMPLATE_VERSION,
                "preset_id": self._settings.preset_id,
                "renderer_version": self._settings.renderer_version,
                "asset_checksums": asset_checksums or [],
            }
        )
        return RenderJob.model_validate(
            {
                "render_job_id": render_job_id,
                "project_id": project_id,
                "document_id": request.document_id,
                "document_revision": request.document_revision,
                "dispatch_id": dispatch_id,
                "template_id": TRUSTED_TEMPLATE_ID,
                "template_version": TRUSTED_TEMPLATE_VERSION,
                "preset_id": self._settings.preset_id,
                "renderer_version": self._settings.renderer_version,
                "status": "preparing",
                "retry_of_job_id": retry_of_job_id,
                "created_by": actor_id,
                "created_at": self._clock(),
                "provenance": provenance,
            }
        )

    def _discard(self, render_job_id: str) -> None:
        """Remove one job's own staged files; failure here is never the answer."""
        if self._artifacts is None:
            return
        try:
            self._artifacts.cleanup(render_job_id)
        except Exception:  # the refusal the caller already has is what matters
            return

    async def _record_closed(
        self,
        jobs: RenderJobRepository,
        shell: RenderJob,
        retry_of_job_id: str | None,
        code: RenderFailureCode,
        idempotency_key: str,
        payload_hash: str,
    ) -> None:
        """Persist the audit row for a render that failed before it was dispatched.

        The row is terminal on arrival, so it never occupies the active slot, and
        the key it consumes replays the same failure instead of a second attempt.
        """
        now = self._clock()
        failed = RenderJob.model_validate(
            {
                **shell.model_dump(),
                "retry_of_job_id": retry_of_job_id,
                "status": "failed",
                "failure_code": code,
                "finished_at": now,
            }
        )
        try:
            await jobs.reserve(failed, idempotency_key=idempotency_key, payload_hash=payload_hash)
        except Exception:  # the original preparation failure is the answer
            return

    async def _consume(self, actor_id: str, render_job_id: str) -> None:
        """One video of the plan allowance (billing spec 1.4), before a job is reserved."""
        if self._billing is not None:
            await asyncio.to_thread(
                self._billing.consume, actor_workspace_id(actor_id), "video", render_job_id
            )

    async def _give_back(self, job: RenderJob) -> None:
        """A render that failed or was cancelled returns its unit (billing spec 1.3)."""
        if self._billing is None:
            return
        try:
            await asyncio.to_thread(
                self._billing.release,
                actor_workspace_id(job.created_by),
                "video",
                job.render_job_id,
            )
        except Exception:  # the render's own outcome stands; a repeated report retries this
            logger.warning("render unit not given back render_job_id=%s", job.render_job_id)

    async def _close(
        self, jobs: RenderJobRepository, job: RenderJob, code: RenderFailureCode
    ) -> RenderJob:
        now = self._clock()
        closed = await self._apply_close(jobs, job, code, now)
        await self._give_back(closed)
        return closed

    async def _apply_close(
        self, jobs: RenderJobRepository, job: RenderJob, code: RenderFailureCode, now: datetime
    ) -> RenderJob:
        return await jobs.apply_event(
            render_job_id=job.render_job_id,
            event=RenderJobEvent(
                render_job_id=job.render_job_id,
                dispatch_id=job.dispatch_id,
                sequence=job.last_event_sequence + 1,
                status="failed",
                failure_code=code,
                occurred_at=now,
            ),
            now=now,
        )

    # --- cancel -----------------------------------------------------------

    async def cancel(self, project_id: str, render_job_id: str) -> RenderJob:
        """Record one cancel request and ask the renderer at most once."""
        jobs = self._require_enabled()
        job = await self.get(project_id, render_job_id)
        if job.status in TERMINAL_RENDER_STATUSES:
            raise RenderJobNotCancellable()
        updated, first_request = await jobs.mark_cancel_requested(
            project_id=project_id, render_job_id=render_job_id, now=self._clock()
        )
        if first_request:
            # The request is recorded either way; the deadline scan closes a job
            # whose renderer never answers.
            with contextlib.suppress(RendererUnavailable, RendererRejected, RendererNotConfigured):
                await self._renderer.cancel(render_job_id=render_job_id)
        return updated

    # --- private reads ----------------------------------------------------

    async def bundle(self, render_job_id: str) -> bytes:
        """Return the staged bundle for the job the renderer says it is running."""
        jobs = self._require_enabled()
        job = await jobs.get_internal(render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        # The bundle is the only thing that lets a render begin, so a job that
        # already completed, failed, or was cancelled must not be able to hand
        # one out again, not even to a renderer that restarted and replayed an
        # old start it no longer remembers settling.
        if job.status not in ACTIVE_RENDER_STATUSES:
            raise RenderJobNotActive()
        if job.artifacts_cleaned_at is not None or self._artifacts is None:
            raise ArtifactUnavailable()
        return await asyncio.to_thread(self._artifacts.read_bundle, job.render_job_id)

    async def asset_location(self, render_job_id: str, asset_id: str) -> str:
        """The stored asset a running job's bundle lists; anything else is not this job's."""
        jobs = self._require_enabled()
        job = await jobs.get_internal(render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        if job.status not in ACTIVE_RENDER_STATUSES or self._artifacts is None:
            raise ArtifactUnavailable()
        bundle = json.loads(await asyncio.to_thread(self._artifacts.read_bundle, render_job_id))
        if asset_id not in {entry.get("asset_id") for entry in bundle.get("assets", [])}:
            raise ArtifactUnavailable()
        assert self._assets is not None  # _require_enabled checked it
        records = await self._assets.get_ready_records(
            project_id=job.project_id, asset_ids=(asset_id,)
        )
        if len(records) != 1:
            raise ArtifactUnavailable()
        return records[0].artifact_location

    async def receive_output(
        self, render_job_id: str, chunks: AsyncIterator[bytes]
    ) -> ReceivedOutput:
        """Take one renderer upload into the store; publish verifies it on `completed`."""
        jobs = self._require_enabled()
        job = await jobs.get_internal(render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        if job.status not in ACTIVE_RENDER_STATUSES or self._artifacts is None:
            raise RenderJobNotActive()
        return await self._artifacts.receive_output(
            render_job_id, chunks, max_bytes=self._settings.max_output_bytes
        )

    def object_size(self, location: str) -> int:
        if self._artifacts is None:
            raise ArtifactUnavailable()
        return self._artifacts.object_size(location)

    def read_object(self, location: str, start: int, end: int | None) -> Iterator[bytes]:
        if self._artifacts is None:
            raise ArtifactUnavailable()
        return self._artifacts.read_object(location, start, end)

    # --- events -----------------------------------------------------------

    async def ingest_event(self, render_job_id: str, event: RenderJobEvent) -> RenderJob:
        """Apply one private renderer report, publishing only a verified output."""
        jobs = self._require_enabled()
        job = await jobs.get_internal(render_job_id=render_job_id)
        if job is None:
            raise RenderJobNotFound()
        if event.status == "completed" and self._is_applicable(job, event):
            # Publication reads, writes, and copies stored objects: off the event loop.
            event = await asyncio.to_thread(self._publish, job, event)
        now = self._clock()
        updated = await jobs.apply_event(render_job_id=render_job_id, event=event, now=now)
        if updated.status == "completed" and job.status != "completed" and updated.output:
            await self._meter_render(updated)
        if updated.status in ("failed", "cancelled"):
            await self._give_back(updated)  # idempotent, so a repeated report retries a failed one
        return updated

    @staticmethod
    async def _meter_render(job: RenderJob) -> None:
        """A completed render's seconds and bytes, for its project's workspace (spec 2.1)."""
        # ponytail: two racing completion reports could both count; the renderer sends one.
        assert job.output is not None
        scope = await asyncio.to_thread(metering.project_scope, job.project_id)
        with metering.scoped(scope):
            await metering.record(
                "video_rendered", job.preset_id, job.output.duration_seconds, "second"
            )
            await metering.record("media_stored", "renders", job.output.size_bytes, "byte")

    @staticmethod
    def _is_applicable(job: RenderJob, event: RenderJobEvent) -> bool:
        """Whether this event would change the job, so a late report publishes nothing."""
        return (
            job.status not in TERMINAL_RENDER_STATUSES
            and event.dispatch_id == job.dispatch_id
            and event.sequence > job.last_event_sequence
        )

    def _publish(self, job: RenderJob, event: RenderJobEvent) -> RenderJobEvent:
        """Publish the verified render atomically, or turn the event into a failure."""
        if event.output is None or self._artifacts is None:
            return self._as_output_failure(event)
        try:
            published = self._artifacts.publish(
                job.render_job_id,
                event.output,
                self._metadata(job, event.output),
                self._diagnostics(job, event),
            )
        except Exception:  # publication detail never leaves this layer
            return self._as_output_failure(event)
        return event.model_copy(update={"output_relative_path": published.relative_path})

    @staticmethod
    def _as_output_failure(event: RenderJobEvent) -> RenderJobEvent:
        return event.model_copy(
            update={
                "status": "failed",
                "failure_code": "render_output_invalid",
                "output": None,
                "output_relative_path": None,
            }
        )

    @staticmethod
    def _metadata(job: RenderJob, output: RenderOutputFacts) -> bytes:
        """Bounded typed record stored beside the render, safe to read back."""
        return json.dumps(
            {
                "render_job_id": job.render_job_id,
                "project_id": job.project_id,
                "document_id": job.document_id,
                "document_revision": job.document_revision,
                "template_id": job.template_id,
                "template_version": job.template_version,
                "preset_id": job.preset_id,
                "renderer_version": job.renderer_version,
                "output": output.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _diagnostics(job: RenderJob, event: RenderJobEvent) -> bytes:
        """Fixed safe fields only: no path, no stream, no raw renderer message."""
        return json.dumps(
            {
                "render_job_id": job.render_job_id,
                "dispatch_id": job.dispatch_id,
                "last_event_sequence": event.sequence,
                "renderer_version": job.renderer_version,
                "occurred_at": event.occurred_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    # --- output and cleanup ----------------------------------------------

    async def output_path(self, project_id: str, render_job_id: str) -> DownloadableRender:
        """Resolve the one published render this project may download."""
        job = await self.get(project_id, render_job_id)
        if (
            job.status != "completed"
            or job.artifacts_cleaned_at is not None
            or job.output is None
            or job.output_relative_path is None
            or self._artifacts is None
        ):
            raise ArtifactUnavailable()
        location = self._artifacts.resolve_download(job.render_job_id, job.output_relative_path)
        return DownloadableRender(
            location=location,
            media_type=job.output.media_type,
            filename=f"{job.render_job_id}.mp4",
            size_bytes=job.output.size_bytes,
            checksum=job.output.checksum,
        )

    async def cleanup(self, project_id: str, render_job_id: str) -> RenderJob:
        """Delete one terminal job's files by hand, keeping its audit row."""
        jobs = self._require_enabled()
        job = await self.get(project_id, render_job_id)
        if job.status not in TERMINAL_RENDER_STATUSES:
            raise RenderJobNotCleanable()
        if job.artifacts_cleaned_at is not None:
            return job
        if self._artifacts is None:
            raise ArtifactUnavailable()
        await asyncio.to_thread(self._artifacts.cleanup, job.render_job_id)
        return await jobs.mark_cleaned(
            project_id=project_id, render_job_id=render_job_id, now=self._clock()
        )

    # --- deadline ---------------------------------------------------------

    async def reconcile_expired(self, now: datetime) -> int:
        """Close already-active jobs that outlived the deadline; never a backlog scan."""
        jobs = self._require_enabled()
        deadline = now - timedelta(seconds=self._max_render_seconds)
        expired = await jobs.list_expired_active(deadline=deadline, limit=RECONCILE_BATCH)
        closed = 0
        for job in expired:
            # One best-effort attempt; the row below is the real close.
            with contextlib.suppress(RendererUnavailable, RendererRejected, RendererNotConfigured):
                await self._renderer.cancel(render_job_id=job.render_job_id)
            await self._close(jobs, job, "render_deadline_exceeded")
            closed += 1
        return closed
