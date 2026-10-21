"""Open a finished workflow in Studio (spec 2026-10-20 workflow to Studio).

The Content Set row is read from the report store, projected on the server, and turned into a
draft under the workflow's own source key. Each media item is then reused by checksum, or probed
in place, copied server side into the project's uploads, registered, and attached. One item's
failure leaves only that item unresolved; replaying the same key finishes what is left.

Store failures are caught as plain exceptions, like the upload service does, so this layer never
imports an infrastructure module.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from typing import Any, Literal, Protocol
from uuid import uuid4

from thoth_control_plane import metering
from thoth_control_plane.application.editor_asset_ports import EditorAssetMediaInvalid
from thoth_control_plane.application.editor_asset_uploads import (
    UPLOAD_TYPES,
    MediaProbe,
    described_asset,
)
from thoth_control_plane.application.ports import (
    EditDocumentRevisionConflict,
    StudioImportDecisionRejected,
    StudioImportItemResolved,
)
from thoth_control_plane.application.studio_imports import StudioImportService
from thoth_control_plane.application.workflows import WorkflowNotFound
from thoth_control_plane.assembly.models import ContentSet, MediaRef
from thoth_control_plane.assembly.studio import (
    WorkflowProjection,
    project_content_set,
    workflow_source_key,
)
from thoth_control_plane.domain.editor_assets import EditorAssetRecord
from thoth_control_plane.domain.models import Actor
from thoth_control_plane.domain.studio_imports import (
    AttachImportAsset,
    ResolveStudioImportItem,
    StudioImportInventory,
    StudioSourceInspection,
    WorkflowImportItem,
    WorkflowStudioImport,
)

logger = logging.getLogger(__name__)
PROVENANCE = "workflow_import"


class WorkflowStudioUnavailable(RuntimeError):
    """A store or tool the import needs could not be used."""


class ContentSetUnavailable(LookupError):
    """The workflow has no stored Content Set."""


class ContentSetInvalid(ValueError):
    """The stored Content Set is not schema 1, or belongs to another workflow."""


class WorkflowInOtherProject(Exception):
    """The run already belongs to another project; moving it is out of scope."""


class _ItemFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkflowMedia(Protocol):
    def size(self, location: str) -> int: ...

    def probe_source(self, location: str) -> str: ...

    def copy(self, source: str, destination: str) -> None: ...

    def delete(self, location: str) -> None: ...

    def check(self) -> None: ...


class WorkflowAssets(Protocol):
    async def find_ready_by_checksum(
        self, *, project_id: str, checksum: str
    ) -> EditorAssetRecord | None: ...

    async def register_ready(self, record: EditorAssetRecord) -> None: ...


def content_set_location(workflow_id: str) -> str:
    return f"reports/{workflow_id}/content-set.json"


class WorkflowStudioImportService:
    def __init__(
        self,
        *,
        runs: Any,
        reports: Any,
        media: WorkflowMedia,
        assets: WorkflowAssets | None,
        imports: StudioImportService,
        probe: MediaProbe,
    ) -> None:
        self._runs = runs
        self._reports = reports
        self._media = media
        self._assets = assets
        self._imports = imports
        self._probe = probe

    async def inspect(
        self, project_id: str, workflow_id: str, actor: Actor
    ) -> StudioSourceInspection:
        """Read-only: neither assigns the run nor copies anything."""
        await self._run(project_id, workflow_id, actor)
        key, source = await self._source(workflow_id)
        return await self._imports.inspect_keyed(project_id, key, source.projection)

    async def open(
        self, project_id: str, workflow_id: str, actor: Actor, idempotency_key: str
    ) -> WorkflowStudioImport:
        run = await self._run(project_id, workflow_id, actor)
        key, source = await self._source(workflow_id)
        if self._assets is None:
            raise WorkflowStudioUnavailable()
        try:
            # Before any draft exists: an outage answers 503 instead of an empty draft.
            await asyncio.to_thread(self._media.check)
        except Exception as error:
            raise WorkflowStudioUnavailable() from error
        if run.project_id is None:
            # Claimed before the draft: of two tabs racing for an unassigned run, the loser
            # leaves no draft behind, and a claimed run never moves to another project.
            claimed = await asyncio.to_thread(self._runs.claim, workflow_id, project_id)
            if claimed is None:
                raise WorkflowNotFound
            if claimed.project_id != project_id:
                raise WorkflowInOtherProject()
        draft = await self._imports.create_keyed(
            project_id, key, source.projection, idempotency_key
        )
        inventory = await self._imports.get_inventory(project_id, draft.document_id)
        items: list[WorkflowImportItem] = []
        for entry in list(inventory.items):
            ref = source.media.get(entry.item_id)
            if ref is None:
                continue
            if entry.disposition != "unresolved":
                items.append(WorkflowImportItem(item_id=entry.item_id, outcome="decided"))
                continue
            item, inventory = await self._import_item(project_id, inventory, entry.item_id, ref)
            items.append(item)
        return WorkflowStudioImport(
            draft=draft.model_copy(update={"revision": inventory.revision}), items=items
        )

    async def _run(self, project_id: str, workflow_id: str, actor: Actor) -> Any:
        if self._runs is None:
            raise WorkflowStudioUnavailable()
        run = await asyncio.to_thread(self._runs.get, workflow_id)
        if run is None or not run.owned_by(actor):
            raise WorkflowNotFound
        if run.project_id not in (None, project_id):
            raise WorkflowInOtherProject()
        return run

    async def _source(self, workflow_id: str) -> tuple[str, WorkflowProjection]:
        """The Content Set row is the only gate: the stored run status lags Temporal."""
        if self._reports is None:
            raise WorkflowStudioUnavailable()
        try:
            content = await asyncio.to_thread(self._reports.get, content_set_location(workflow_id))
        except Exception as error:
            raise WorkflowStudioUnavailable() from error
        if content is None:
            raise ContentSetUnavailable()
        try:
            content_set = ContentSet.model_validate_json(content)
            if content_set.workflow_id != workflow_id:
                raise ValueError("the Content Set names another workflow")
            projected = project_content_set(content_set)
        except ValueError as error:  # a pydantic ValidationError is a ValueError
            raise ContentSetInvalid() from error
        return workflow_source_key(workflow_id, hashlib.sha256(content).hexdigest()), projected

    async def _import_item(
        self,
        project_id: str,
        inventory: StudioImportInventory,
        item_id: str,
        ref: MediaRef,
    ) -> tuple[WorkflowImportItem, StudioImportInventory]:
        try:
            record, outcome = await self._asset_for(project_id, ref)
        except _ItemFailed as failed:
            return self._left(item_id, failed.code), inventory
        for attempt in range(2):
            request = ResolveStudioImportItem(
                base_revision=inventory.revision,
                decision=AttachImportAsset(kind="attach_asset", asset_id=record.asset.asset_id),
            )
            try:
                inventory = await self._imports.resolve(
                    project_id, inventory.document_id, item_id, request
                )
            except StudioImportDecisionRejected as refused:
                return self._left(item_id, refused.code), inventory
            except (EditDocumentRevisionConflict, StudioImportItemResolved):
                inventory = await self._imports.get_inventory(project_id, inventory.document_id)
                entry = next((i for i in inventory.items if i.item_id == item_id), None)
                if entry is None or entry.disposition != "unresolved":
                    # A person decided this item in the gate meanwhile: their decision stands.
                    return WorkflowImportItem(item_id=item_id, outcome="decided"), inventory
                if attempt:  # the draft keeps changing under the import; the gate takes over
                    return self._left(item_id, "draft_changed"), inventory
                continue  # an unrelated edit moved the revision: attach again on the latest
            return WorkflowImportItem(item_id=item_id, outcome=outcome), inventory
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _left(item_id: str, reason: str) -> WorkflowImportItem:
        return WorkflowImportItem(item_id=item_id, outcome="unresolved", reason=reason)

    async def _asset_for(
        self, project_id: str, ref: MediaRef
    ) -> tuple[EditorAssetRecord, Literal["reused", "copied"]]:
        assert self._assets is not None  # checked by open()
        checksum = ref.checksum.lower()  # editor assets keep lower-case hex
        try:
            found = await self._assets.find_ready_by_checksum(
                project_id=project_id, checksum=checksum
            )
        except Exception:
            raise _ItemFailed("asset_unavailable") from None
        if found is not None:
            return found, "reused"
        location = ref.location.as_posix()
        size = await self._store(self._media.size, location)
        if size != ref.bytes:
            raise _ItemFailed("media_mismatch")
        upload = UPLOAD_TYPES[ref.media_type]
        asset_id = f"asset_{uuid4().hex}"
        source = await self._store(self._media.probe_source, location)
        try:
            report = await self._probe(source)
        except EditorAssetMediaInvalid:
            raise _ItemFailed("media_invalid") from None
        except OSError as error:  # ffprobe itself is missing: an installation fault, fail loud
            logger.error("ffprobe could not run")
            raise WorkflowStudioUnavailable("ffprobe_unavailable") from error
        try:
            asset = described_asset(
                asset_id=asset_id,
                project_id=project_id,
                media_type=ref.media_type,
                kind=upload.kind,
                checksum=checksum,
                report=report,
            )
        except EditorAssetMediaInvalid:
            raise _ItemFailed("media_invalid") from None
        destination = f"uploads/{project_id}/{asset_id}{upload.suffix}"
        await self._store(self._media.copy, location, destination)
        record = EditorAssetRecord(
            asset=asset, artifact_location=destination, provenance=PROVENANCE
        )
        try:
            await self._assets.register_ready(record)
        except BaseException as error:
            # Also on cancellation, so an aborted request leaves no orphan upload behind.
            # ponytail: a killed process between copy and register still leaks one object;
            # a sweep of unregistered uploads/ objects would close it.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._media.delete, destination)
            if not isinstance(error, Exception):
                raise
            raise _ItemFailed("asset_unavailable") from None
        # Counted only once registered: a copy rolled back above is never billed as storage.
        await asyncio.to_thread(
            metering.record_sync, "media_stored", "uploads", ref.bytes, "byte", in_scope_only=True
        )
        return record, "copied"

    @staticmethod
    async def _store(call: Any, *args: str) -> Any:
        """One media store call: a missing object or a store outage fails only this item."""
        try:
            return await asyncio.to_thread(call, *args)
        except LookupError:  # MediaUnavailable
            raise _ItemFailed("media_missing") from None
        except Exception:
            raise _ItemFailed("media_store_unavailable") from None
