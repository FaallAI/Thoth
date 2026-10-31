"""Studio's narration of one draft: start, read, decide, edit a beat, re-voice (spec 2026-10-31).

The workflow owns the steps; this service only checks what can be asked now, against the
narration's stored state, and refuses before anything is spent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

from thoth_control_plane.application.narration_script import STAGE
from thoth_control_plane.domain.narration import (
    ACTIVE_STATUSES,
    BeatId,
    NarrationDecision,
    NarrationInProgress,
    NarrationPreset,
    NarrationPresetConflict,
    NarrationRevoiceInput,
    NarrationScript,
    NarrationState,
    NarrationStepInput,
    StoredPreset,
)


class NarrationRefused(Exception):
    """The request cannot be met now; `code` is the safe reason the API returns."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NarrationNotFound(LookupError):
    pass


class NarrationUnavailable(RuntimeError):
    pass


class NarrationGateway(Protocol):
    async def start(self, workflow_id: str, step: NarrationStepInput) -> None: ...
    async def decide(self, workflow_id: str, decision: NarrationDecision) -> None: ...
    async def revoice(self, step: NarrationRevoiceInput) -> None: ...
    async def cancel(self, workflow_id: str) -> None: ...


SourceRun = Callable[[str, str], Awaitable[str | None]]


def _next_workflow_id(document_id: str, previous: NarrationState | None) -> str:
    attempt = 1
    if previous is not None:
        tail = previous.workflow_id.rsplit("/", 1)[-1]
        attempt = int(tail) + 1 if tail.isdigit() else 1
    return f"narration/{document_id}/{attempt}"


def revoice_workflow_id(step: NarrationRevoiceInput) -> str:
    return f"narration-revoice/{step.document_id}/{step.beat}/{uuid4().hex[:12]}"


class NarrationService:
    def __init__(
        self,
        *,
        store: Any | None,
        documents: Any,
        source_run: SourceRun,
        preferences: Any,
        gateway: NarrationGateway | None,
        sfx_assets: Any | None = None,
    ) -> None:
        self._sfx_assets = sfx_assets
        self._store = store
        self._documents = documents
        self._source_run = source_run
        self._preferences = preferences
        self._gateway = gateway

    def _require(self) -> Any:
        if self._store is None:
            raise NarrationUnavailable()
        return self._store

    async def get(self, project_id: str, document_id: str) -> NarrationState:
        state = await self._require().get(project_id, document_id)
        if state is None:
            raise NarrationNotFound()
        return state

    async def is_locked(self, project_id: str, document_id: str) -> bool:
        if self._store is None:
            return False
        state = await self._store.get(project_id, document_id)
        return state is not None and state.status in ACTIVE_STATUSES

    async def start(
        self, project_id: str, document_id: str, *, restart: bool = False
    ) -> NarrationState:
        """Create a narration; `restart` writes a finished one again from the current draft
        (operator, 2026-10-31), with the same approval before any voice."""
        store = self._require()
        await self._documents.get_latest(project_id, document_id)  # 404 for an unknown draft
        try:
            run = await self._source_run(project_id, document_id)
            preference = await self._preferences.get_preference(project_id, STAGE)
        except Exception as error:  # a store outage is not a missing run or model
            raise NarrationUnavailable() from error
        if run is None:
            raise NarrationRefused("narration_not_available")
        if preference is None:
            raise NarrationRefused("prompt_not_configured")
        if self._gateway is None:
            raise NarrationUnavailable()
        previous = await store.get(project_id, document_id)
        if previous is not None and previous.status in ACTIVE_STATUSES:
            raise NarrationRefused("narration_in_progress")
        if previous is not None and previous.status == "completed" and not restart:
            # Spec 5: the button is for a draft with no narration yet; lines are re-voiced.
            raise NarrationRefused("narration_exists")
        workflow_id = _next_workflow_id(document_id, previous)
        preset = (await store.get_preset(project_id)).preset
        try:
            state = await store.start(project_id, document_id, workflow_id, preset)
        except NarrationInProgress as error:
            raise NarrationRefused("narration_in_progress") from error
        try:
            await self._gateway.start(
                workflow_id, NarrationStepInput(project_id=project_id, document_id=document_id)
            )
        except NarrationUnavailable:
            # No workflow will ever move this row: close it so the draft stays editable.
            await store.set_status(document_id, "failed", failure_code="narration_unavailable")
            raise
        return state

    async def decide(
        self, project_id: str, document_id: str, decision: NarrationDecision
    ) -> NarrationState:
        state = await self.get(project_id, document_id)
        if self._gateway is None:
            raise NarrationUnavailable()
        # One decision per script: the claim moves the status, so a second click is refused
        # and an approval can never land on a script the operator has not seen.
        following = "voicing" if decision.decision == "approve" else "scripting"
        if not await self._require().claim(document_id, {"awaiting_approval"}, following):
            raise NarrationRefused("narration_not_awaiting_approval")
        try:
            await self._gateway.decide(state.workflow_id, decision)
        except NarrationUnavailable:
            await self._require().set_status(
                document_id, "failed", failure_code="narration_unavailable"
            )
            raise
        return state.model_copy(update={"status": following})

    async def cancel(self, project_id: str, document_id: str) -> NarrationState:
        state = await self.get(project_id, document_id)
        if state.status not in ACTIVE_STATUSES:
            raise NarrationRefused("narration_not_active")
        if self._gateway is None:
            raise NarrationUnavailable()
        try:
            await self._gateway.cancel(state.workflow_id)
        except NarrationUnavailable:
            # The workflow is gone (terminated, or never ran): nothing else will close it.
            await self._require().set_status(document_id, "cancelled")
            return state.model_copy(update={"status": "cancelled"})
        return state

    async def set_beat_text(
        self, project_id: str, document_id: str, beat: BeatId, text: str
    ) -> NarrationScript:
        state = await self.get(project_id, document_id)
        if state.status != "completed" or state.script is None:
            raise NarrationRefused("narration_not_completed")
        if all(item.beat != beat for item in state.script.beats):
            raise NarrationNotFound()
        return await self._require().set_beat_text(document_id, beat, text)

    async def revoice(self, project_id: str, document_id: str, beat: BeatId) -> NarrationState:
        state = await self.get(project_id, document_id)
        if beat not in state.stale_beats:
            raise NarrationRefused("beat_not_stale")
        if self._gateway is None:
            raise NarrationUnavailable()
        # The claim locks the draft and starts Studio's polling; a second click is refused.
        if not await self._require().claim(document_id, {"completed"}, "voicing"):
            raise NarrationRefused("beat_not_stale")
        try:
            await self._gateway.revoice(
                NarrationRevoiceInput(project_id=project_id, document_id=document_id, beat=beat)
            )
        except NarrationUnavailable:
            await self._require().set_status(document_id, "completed")
            raise
        return state.model_copy(update={"status": "voicing"})

    async def get_preset(self, project_id: str) -> StoredPreset:
        return await self._require().get_preset(project_id)

    async def save_preset(
        self, project_id: str, preset: NarrationPreset, base_revision: int
    ) -> StoredPreset:
        try:
            return await self._require().save_preset(project_id, preset, base_revision)
        except NarrationPresetConflict as error:
            raise NarrationRefused("narration_preset_conflict") from error

    async def list_sfx(self) -> list[Any]:
        return await self._require().list_sfx()

    async def add_sfx(self, project_id: str, sfx_id: str) -> Any:
        """The project's editor asset for one library sound effect, copied on first use."""
        entry = next((item for item in await self.list_sfx() if item.sfx_id == sfx_id), None)
        if entry is None:
            raise NarrationNotFound()
        if self._sfx_assets is None:
            raise NarrationUnavailable()
        try:
            return await self._sfx_assets.ensure_project_asset(project_id, entry)
        except Exception as error:
            raise NarrationUnavailable() from error
