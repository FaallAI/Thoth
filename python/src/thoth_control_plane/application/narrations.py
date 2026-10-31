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
    ) -> None:
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

    async def start(self, project_id: str, document_id: str) -> NarrationState:
        store = self._require()
        await self._documents.get_latest(project_id, document_id)  # 404 for an unknown draft
        if await self._source_run(project_id, document_id) is None:
            raise NarrationRefused("narration_not_available")
        if await self._preferences.get_preference(project_id, STAGE) is None:
            raise NarrationRefused("prompt_not_configured")
        if self._gateway is None:
            raise NarrationUnavailable()
        previous = await store.get(project_id, document_id)
        if previous is not None and previous.status in ACTIVE_STATUSES:
            raise NarrationRefused("narration_in_progress")
        workflow_id = _next_workflow_id(document_id, previous)
        preset = (await store.get_preset(project_id)).preset
        try:
            state = await store.start(project_id, document_id, workflow_id, preset)
        except NarrationInProgress as error:
            raise NarrationRefused("narration_in_progress") from error
        await self._gateway.start(
            workflow_id, NarrationStepInput(project_id=project_id, document_id=document_id)
        )
        return state

    async def decide(
        self, project_id: str, document_id: str, decision: NarrationDecision
    ) -> NarrationState:
        state = await self.get(project_id, document_id)
        if state.status != "awaiting_approval":
            raise NarrationRefused("narration_not_awaiting_approval")
        if self._gateway is None:
            raise NarrationUnavailable()
        await self._gateway.decide(state.workflow_id, decision)
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
        if state.status != "completed" or beat not in state.stale_beats:
            raise NarrationRefused("beat_not_stale")
        if self._gateway is None:
            raise NarrationUnavailable()
        await self._gateway.revoice(
            NarrationRevoiceInput(project_id=project_id, document_id=document_id, beat=beat)
        )
        return state

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
