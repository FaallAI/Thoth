"""PostgreSQL persistence for narrations, narration presets and the SFX library (migration 0027).

One narration row per Studio draft, read and written by project so a project never sees another's
narration. SQLAlchemy ORM on the shared editor pool; async callers reach the synchronous session
through `asyncio.to_thread`, as the other editor repositories do.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from thoth_control_plane.domain.narration import (
    ACTIVE_STATUSES,
    BeatId,
    NarrationInProgress,
    NarrationPreset,
    NarrationPresetConflict,
    NarrationScript,
    NarrationState,
    NarrationStatus,
    NarrationStoreUnavailable,
    SfxEntry,
    StoredPreset,
    TranscriptSegment,
    VoiceEstimate,
    VoiceRef,
)
from thoth_control_plane.infrastructure.editor_database import editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    NarrationPresetRow,
    NarrationRow,
    SfxLibraryRow,
)

T = TypeVar("T")
_PASSTHROUGH = (NarrationInProgress, NarrationPresetConflict, LookupError)


def _state(row: NarrationRow) -> NarrationState:
    return NarrationState(
        document_id=row.document_id,
        workflow_id=row.workflow_id,
        status=row.status,  # type: ignore[arg-type]
        script=NarrationScript.model_validate(row.script) if row.script else None,
        estimate=VoiceEstimate.model_validate(row.estimate) if row.estimate else None,
        unsupported=row.unsupported or {},
        stale_beats=list(row.stale_beats or []),
        failure_code=row.failure_code,
    )


class NarrationStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(self, work: Callable[[Session], T]) -> T:
        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        try:
            return await asyncio.to_thread(unit)
        except _PASSTHROUGH:
            raise
        except Exception as error:
            raise NarrationStoreUnavailable() from error

    @staticmethod
    def _row(session: Session, document_id: str) -> NarrationRow:
        row = session.get(NarrationRow, document_id, with_for_update=True)
        if row is None:
            raise LookupError(document_id)
        return row

    async def start(
        self, project_id: str, document_id: str, workflow_id: str, preset: NarrationPreset
    ) -> NarrationState:
        def work(session: Session) -> NarrationState:
            row = session.get(NarrationRow, document_id, with_for_update=True)
            if row is not None and (row.status in ACTIVE_STATUSES or row.project_id != project_id):
                raise NarrationInProgress()
            if row is None:
                row = NarrationRow(document_id=document_id)
                session.add(row)
            row.project_id = project_id
            row.workflow_id = workflow_id
            row.status = "transcribing"
            row.preset = preset.model_dump(mode="json")
            row.transcript = row.script = row.estimate = row.voices = None
            row.unsupported = {}
            row.stale_beats = []
            row.failure_code = None
            row.updated_at = func.current_timestamp()
            session.flush()
            return _state(row)

        return await self._run(work)

    async def get(self, project_id: str, document_id: str) -> NarrationState | None:
        def work(session: Session) -> NarrationState | None:
            row = session.get(NarrationRow, document_id)
            return _state(row) if row is not None and row.project_id == project_id else None

        return await self._run(work)

    async def get_preset_of(self, document_id: str) -> NarrationPreset:
        """The preset a running narration started with (a later preset edit never changes it)."""
        return await self._run(
            lambda session: NarrationPreset.model_validate(self._row(session, document_id).preset)
        )

    async def _update(self, document_id: str, **fields: Any) -> None:
        def work(session: Session) -> None:
            row = self._row(session, document_id)
            for name, value in fields.items():
                setattr(row, name, value)
            row.updated_at = func.current_timestamp()

        await self._run(work)

    async def set_status(
        self, document_id: str, status: NarrationStatus, *, failure_code: str | None = None
    ) -> None:
        await self._update(document_id, status=status, failure_code=failure_code)

    async def claim(self, document_id: str, expected: set[str], status: NarrationStatus) -> bool:
        """Move the status only from one of `expected`, atomically; False when it was not."""

        def work(session: Session) -> bool:
            row = session.get(NarrationRow, document_id, with_for_update=True)
            if row is None or row.status not in expected:
                return False
            row.status = status
            row.failure_code = None
            row.updated_at = func.current_timestamp()
            return True

        return await self._run(work)

    async def set_transcript(self, document_id: str, segments: list[TranscriptSegment]) -> None:
        await self._update(
            document_id, transcript=[segment.model_dump(mode="json") for segment in segments]
        )

    async def get_transcript(self, document_id: str) -> list[TranscriptSegment]:
        def work(session: Session) -> list[TranscriptSegment]:
            row = self._row(session, document_id)
            return [TranscriptSegment.model_validate(item) for item in row.transcript or []]

        return await self._run(work)

    async def set_script(
        self,
        document_id: str,
        script: NarrationScript,
        estimate: VoiceEstimate,
        unsupported: dict[BeatId, list[str]],
    ) -> None:
        await self._update(
            document_id,
            status="awaiting_approval",
            script=script.model_dump(mode="json"),
            estimate=estimate.model_dump(mode="json"),
            unsupported=unsupported,
            failure_code=None,
        )

    async def get_script(self, document_id: str) -> NarrationScript | None:
        def work(session: Session) -> NarrationScript | None:
            row = self._row(session, document_id)
            return NarrationScript.model_validate(row.script) if row.script else None

        return await self._run(work)

    async def set_beat_text(self, document_id: str, beat: BeatId, text: str) -> NarrationScript:
        """Replace one beat's text and mark the beat's voice out of date."""

        def work(session: Session) -> NarrationScript:
            row = self._row(session, document_id)
            script = NarrationScript.model_validate(row.script)
            if all(item.beat != beat for item in script.beats):
                raise LookupError(beat)
            beats = [
                item.model_copy(update={"text": text}) if item.beat == beat else item
                for item in script.beats
            ]
            updated = script.model_copy(update={"beats": beats})
            row.script = updated.model_dump(mode="json")
            stale = list(row.stale_beats or [])
            if beat not in stale:
                row.stale_beats = [*stale, beat]
            row.updated_at = func.current_timestamp()
            return updated

        return await self._run(work)

    async def set_voices(self, document_id: str, voices: list[VoiceRef]) -> None:
        await self._update(document_id, voices=[voice.model_dump(mode="json") for voice in voices])

    async def get_voices(self, document_id: str) -> list[VoiceRef]:
        def work(session: Session) -> list[VoiceRef]:
            row = self._row(session, document_id)
            return [VoiceRef.model_validate(item) for item in row.voices or []]

        return await self._run(work)

    async def mark_stale(self, document_id: str, beat: BeatId) -> None:
        def work(session: Session) -> None:
            row = self._row(session, document_id)
            stale = list(row.stale_beats or [])
            if beat not in stale:
                row.stale_beats = [*stale, beat]

        await self._run(work)

    async def clear_stale(self, document_id: str, beat: BeatId) -> None:
        def work(session: Session) -> None:
            row = self._row(session, document_id)
            row.stale_beats = [item for item in row.stale_beats or [] if item != beat]

        await self._run(work)

    async def get_preset(self, project_id: str) -> StoredPreset:
        def work(session: Session) -> StoredPreset:
            row = session.get(NarrationPresetRow, project_id)
            if row is None:
                return StoredPreset(preset=NarrationPreset(), revision=0)
            return StoredPreset(
                preset=NarrationPreset.model_validate(row.preset), revision=row.revision
            )

        return await self._run(work)

    async def save_preset(
        self, project_id: str, preset: NarrationPreset, base_revision: int
    ) -> StoredPreset:
        def work(session: Session) -> StoredPreset:
            row = session.get(NarrationPresetRow, project_id, with_for_update=True)
            current = 0 if row is None else row.revision
            if current != base_revision:
                raise NarrationPresetConflict()
            if row is None:
                row = NarrationPresetRow(project_id=project_id)
                session.add(row)
            row.preset = preset.model_dump(mode="json")
            row.revision = current + 1
            row.updated_at = func.current_timestamp()
            return StoredPreset(preset=preset, revision=row.revision)

        return await self._run(work)

    async def list_sfx(self) -> list[SfxEntry]:
        def work(session: Session) -> list[SfxEntry]:
            rows = session.scalars(select(SfxLibraryRow).order_by(SfxLibraryRow.sfx_id))
            return [
                SfxEntry(
                    sfx_id=row.sfx_id,
                    file_name=row.file_name,
                    location=row.location,
                    checksum=row.checksum,
                    duration_seconds=row.duration_seconds,
                    labels=row.labels or {},
                )
                for row in rows
            ]

        return await self._run(work)

    async def upsert_sfx(self, entry: SfxEntry) -> bool:
        """Insert one library entry; an entry with the same checksum is left as it is."""

        def work(session: Session) -> bool:
            exists = session.scalar(
                select(SfxLibraryRow.sfx_id).where(SfxLibraryRow.checksum == entry.checksum)
            )
            if exists is not None:
                return False
            session.add(SfxLibraryRow(**entry.model_dump(mode="python")))
            return True

        return await self._run(work)
