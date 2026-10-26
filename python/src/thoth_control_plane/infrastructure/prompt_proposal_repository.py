"""Project-scoped PostgreSQL persistence for Prompt Lab AI proposals (C2).

SQLAlchemy ORM on the shared editor pool (ORM spec 2026-10-26); async callers reach the
synchronous session through `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.orm import Session

from thoth_control_plane.application.ports import PromptTemplateNotFound
from thoth_control_plane.application.prompt_proposal_ports import (
    PromptIdempotencyConflict,
    PromptLockRevisionConflict,
    PromptPreferenceRevisionConflict,
    PromptProposalActiveGeneration,
    PromptProposalApplyResult,
    PromptProposalInvalidSelection,
    PromptProposalInvalidTransition,
    PromptProposalLayerLocked,
    PromptProposalNotFound,
    PromptProposalStale,
    PromptProposalStoreUnavailable,
)
from thoth_control_plane.domain.prompt_proposals import (
    PROMPT_PROPOSAL_FAILURE_CODES,
    ProjectPromptLayerLock,
    ProjectPromptModelPreference,
    PromptProposal,
    PromptProposalChange,
    PromptProposalPage,
    SavePromptLayerLockRequest,
    SavePromptModelPreferenceRequest,
    apply_prompt_changes,
    build_prompt_changes,
    is_legal_transition,
)
from thoth_control_plane.infrastructure.editor_database import advisory_xact_lock, editor_sessions
from thoth_control_plane.infrastructure.editor_models import (
    ProjectPromptBindingRow,
    PromptLayerLockRow,
    PromptProposalApplicationRow,
    PromptProposalChangeRow,
    PromptProposalIdempotencyRow,
    PromptProposalRow,
    PromptProviderPreferenceRow,
    PromptTemplateRevisionRow,
)

T = TypeVar("T")

HISTORY_LIMIT_MAX = 50

#: Typed outcomes the application maps to fixed safe codes; never redacted. Each operation
#: passes through exactly the ones the psycopg repository passed through.
_RESERVE = (PromptIdempotencyConflict, PromptProposalActiveGeneration, PromptProposalNotFound)
_APPLY = (
    PromptProposalInvalidTransition,
    PromptProposalStale,
    PromptProposalLayerLocked,
    PromptProposalInvalidSelection,
    PromptProposalNotFound,
    PromptTemplateNotFound,
)


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _proposal(row: PromptProposalRow) -> PromptProposal:
    return PromptProposal.model_validate(
        {
            "proposal_id": row.proposal_id,
            "project_id": row.project_id,
            "stage_id": row.stage_id,
            "kind": row.kind,
            "status": row.status,
            "target_layers": row.target_layers,
            "source": {
                "template_id": row.source_template_id,
                "template_revision": row.source_template_revision,
                "binding_revision": row.source_binding_revision,
                "template_language": row.source_language,
                "template_body": row.source_template_body,
                "project_override": row.source_project_override,
            },
            "target_language": row.target_language,
            "improvement_instructions": row.improvement_instructions,
            "provider_id": row.provider_id,
            "model_id": row.model_id,
            "translated_template_body": row.translated_template_body,
            "translated_project_override": row.translated_project_override,
            "failure_code": row.failure_code,
            "created_at": _as_datetime(row.created_at),
            "started_at": _as_datetime(row.started_at),
            "finished_at": _as_datetime(row.finished_at),
        }
    )


def _preference(row: PromptProviderPreferenceRow) -> ProjectPromptModelPreference:
    return ProjectPromptModelPreference.model_validate(
        {
            "project_id": row.project_id,
            "stage_id": row.stage_id,
            "provider_id": row.provider_id,
            "model_id": row.model_id,
            "revision": row.revision,
            "updated_at": _as_datetime(row.updated_at),
        }
    )


def _lock(row: PromptLayerLockRow) -> ProjectPromptLayerLock:
    return ProjectPromptLayerLock.model_validate(
        {
            "project_id": row.project_id,
            "stage_id": row.stage_id,
            "layer": row.layer,
            "locked": row.locked,
            "revision": row.revision,
            "updated_at": _as_datetime(row.updated_at),
        }
    )


def _cursor_token(created_at: datetime, proposal_id: str) -> str:
    raw = f"{created_at.isoformat()}|{proposal_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    created_at_raw, proposal_id = raw.split("|", 1)
    return datetime.fromisoformat(created_at_raw), proposal_id


def _proposal_row(
    session: Session, proposal_id: str, project_id: str | None = None
) -> PromptProposalRow | None:
    """One proposal, row-locked; scoped to a project unless the caller is the worker."""
    query = select(PromptProposalRow).where(PromptProposalRow.proposal_id == proposal_id)
    if project_id is not None:
        query = query.where(PromptProposalRow.project_id == project_id)
    return session.scalar(query.with_for_update())


def _worker_row(session: Session, proposal_id: str) -> PromptProposalRow:
    row = _proposal_row(session, proposal_id)
    if row is None:
        raise PromptProposalNotFound()
    return row


def _finish(row: PromptProposalRow, status: str) -> None:
    row.status = status
    row.finished_at = func.current_timestamp()  # type: ignore[assignment]


class PostgresPromptProposalRepository:
    """One short project-scoped transaction per operation, on the shared editor pool."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def _run(
        self,
        work: Callable[[Session], T],
        passthrough: tuple[type[Exception], ...] = (),
    ) -> T:
        """Run `work(session)` in one transaction. The listed typed outcomes pass through;
        any other failure is the safe store error."""

        def unit() -> T:
            with editor_sessions(self._database_url).begin() as session:
                return work(session)

        try:
            return await asyncio.to_thread(unit)
        except passthrough:
            raise
        except Exception as error:
            raise PromptProposalStoreUnavailable() from error

    async def get_preference(
        self, project_id: str, stage_id: str
    ) -> ProjectPromptModelPreference | None:
        def read(session: Session) -> ProjectPromptModelPreference | None:
            row = session.get(PromptProviderPreferenceRow, (project_id, stage_id))
            return None if row is None else _preference(row)

        return await self._run(read)

    async def save_preference(
        self, project_id: str, stage_id: str, request: SavePromptModelPreferenceRequest
    ) -> ProjectPromptModelPreference:
        def write(session: Session) -> ProjectPromptModelPreference:
            row = session.scalar(
                select(PromptProviderPreferenceRow)
                .where(
                    PromptProviderPreferenceRow.project_id == project_id,
                    PromptProviderPreferenceRow.stage_id == stage_id,
                )
                .with_for_update()
            )
            if row is None:
                preference = ProjectPromptModelPreference.model_validate(
                    {
                        "project_id": project_id,
                        "stage_id": stage_id,
                        "provider_id": request.provider_id,
                        "model_id": request.model_id,
                        "revision": 1,
                        "updated_at": datetime.now(UTC),
                    }
                )
                session.add(
                    PromptProviderPreferenceRow(
                        project_id=project_id,
                        stage_id=stage_id,
                        provider_id=request.provider_id,
                        model_id=request.model_id,
                        revision=1,
                    )
                )
                return preference
            latest = _preference(row)
            if request.base_revision is None or request.base_revision != latest.revision:
                raise PromptPreferenceRevisionConflict(latest)
            next_revision = latest.revision + 1
            row.provider_id = request.provider_id
            row.model_id = request.model_id
            row.revision = next_revision
            row.updated_at = func.current_timestamp()  # type: ignore[assignment]
            return latest.model_copy(
                update={
                    "provider_id": request.provider_id,
                    "model_id": request.model_id,
                    "revision": next_revision,
                }
            )

        return await self._run(write, (PromptPreferenceRevisionConflict,))

    async def get_locks(self, project_id: str, stage_id: str) -> tuple[ProjectPromptLayerLock, ...]:
        def read(session: Session) -> tuple[ProjectPromptLayerLock, ...]:
            rows = session.scalars(
                select(PromptLayerLockRow)
                .where(
                    PromptLayerLockRow.project_id == project_id,
                    PromptLayerLockRow.stage_id == stage_id,
                )
                .order_by(PromptLayerLockRow.layer)
            )
            locks = [_lock(row) for row in rows]
            locks.sort(key=lambda lock: (lock.layer != "template", lock.layer))
            return tuple(locks)

        return await self._run(read)

    async def save_lock(
        self, project_id: str, stage_id: str, layer: str, request: SavePromptLayerLockRequest
    ) -> ProjectPromptLayerLock:
        def write(session: Session) -> ProjectPromptLayerLock:
            advisory_xact_lock(session, project_id, stage_id)
            row = session.scalar(
                select(PromptLayerLockRow)
                .where(
                    PromptLayerLockRow.project_id == project_id,
                    PromptLayerLockRow.stage_id == stage_id,
                    PromptLayerLockRow.layer == layer,
                )
                .with_for_update()
            )
            if row is None:
                lock = ProjectPromptLayerLock.model_validate(
                    {
                        "project_id": project_id,
                        "stage_id": stage_id,
                        "layer": layer,
                        "locked": request.locked,
                        "revision": 1,
                        "updated_at": datetime.now(UTC),
                    }
                )
                session.add(
                    PromptLayerLockRow(
                        project_id=project_id,
                        stage_id=stage_id,
                        layer=layer,
                        locked=request.locked,
                        revision=1,
                    )
                )
                return lock
            latest = _lock(row)
            if request.base_revision is None or request.base_revision != latest.revision:
                raise PromptLockRevisionConflict(latest)
            next_revision = latest.revision + 1
            row.locked = request.locked
            row.revision = next_revision
            row.updated_at = func.current_timestamp()  # type: ignore[assignment]
            return latest.model_copy(update={"locked": request.locked, "revision": next_revision})

        return await self._run(write, (PromptLockRevisionConflict,))

    async def reserve_proposal(
        self, proposal: PromptProposal, idempotency_key: str, payload_hash: str
    ) -> PromptProposal:
        def write(session: Session) -> PromptProposal:
            advisory_xact_lock(session, proposal.project_id, proposal.stage_id)
            existing = session.get(
                PromptProposalIdempotencyRow, (proposal.project_id, idempotency_key)
            )
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise PromptIdempotencyConflict(existing.proposal_id)
                replayed = _proposal_row(session, existing.proposal_id, proposal.project_id)
                if replayed is None:
                    raise PromptProposalNotFound()
                return _proposal(replayed)
            active = session.scalar(
                select(PromptProposalRow.proposal_id).where(
                    PromptProposalRow.project_id == proposal.project_id,
                    PromptProposalRow.stage_id == proposal.stage_id,
                    PromptProposalRow.status.in_(("queued", "running")),
                )
            )
            if active is not None:
                raise PromptProposalActiveGeneration(active)
            # The returned stamp is this clock's; the row takes the database's.
            saved = proposal.model_copy(update={"created_at": datetime.now(UTC)})
            session.add(
                PromptProposalRow(
                    proposal_id=saved.proposal_id,
                    project_id=saved.project_id,
                    stage_id=saved.stage_id,
                    kind=saved.kind,
                    status=saved.status,
                    target_layers=list(saved.target_layers),
                    source_template_id=saved.source.template_id,
                    source_template_revision=saved.source.template_revision,
                    source_binding_revision=saved.source.binding_revision,
                    source_language=saved.source.template_language,
                    source_template_body=saved.source.template_body,
                    source_project_override=saved.source.project_override,
                    target_language=saved.target_language,
                    improvement_instructions=saved.improvement_instructions,
                    provider_id=saved.provider_id,
                    model_id=saved.model_id,
                )
            )
            session.flush()
            session.execute(
                update(PromptProposalRow)
                .where(
                    PromptProposalRow.project_id == saved.project_id,
                    PromptProposalRow.stage_id == saved.stage_id,
                    PromptProposalRow.status == "succeeded",
                )
                .values(status="superseded", finished_at=func.current_timestamp())
                .execution_options(synchronize_session=False)
            )
            session.add(
                PromptProposalIdempotencyRow(
                    project_id=saved.project_id,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    proposal_id=saved.proposal_id,
                )
            )
            return saved

        return await self._run(write, _RESERVE)

    async def get_proposal_for_worker(self, proposal_id: str) -> PromptProposal | None:
        """Worker-only lookup by proposal ID; never project-scoped."""
        return await self._run(lambda session: _proposal(_worker_row(session, proposal_id)))

    async def get_proposal(self, project_id: str, proposal_id: str) -> PromptProposal | None:
        def read(session: Session) -> PromptProposal | None:
            row = _proposal_row(session, proposal_id, project_id)
            return None if row is None else _proposal(row)

        return await self._run(read)

    async def list_proposals(
        self, project_id: str, stage_id: str, cursor_token: str | None, limit: int
    ) -> PromptProposalPage:
        def read(session: Session) -> PromptProposalPage:
            clamped = max(1, min(int(limit), HISTORY_LIMIT_MAX))
            query = select(PromptProposalRow).where(
                PromptProposalRow.project_id == project_id,
                PromptProposalRow.stage_id == stage_id,
            )
            if cursor_token:
                created_at, proposal_id = _decode_cursor(cursor_token)
                query = query.where(
                    tuple_(PromptProposalRow.created_at, PromptProposalRow.proposal_id)
                    < tuple_(created_at, proposal_id)
                )
            rows = list(
                session.scalars(
                    query.order_by(
                        PromptProposalRow.created_at.desc(), PromptProposalRow.proposal_id.desc()
                    ).limit(clamped + 1)
                )
            )
            next_cursor = None
            if len(rows) > clamped:
                rows = rows[:clamped]
                next_cursor = _cursor_token(rows[-1].created_at, rows[-1].proposal_id)
            return PromptProposalPage.model_validate(
                {"proposals": [_proposal(row) for row in rows], "next_cursor": next_cursor}
            )

        return await self._run(read)

    async def mark_running(self, proposal_id: str) -> PromptProposal:
        def write(session: Session) -> PromptProposal:
            row = _worker_row(session, proposal_id)
            current = _proposal(row)
            if not is_legal_transition(current.status, "running"):
                raise PromptProposalInvalidTransition()
            row.status = "running"
            row.started_at = func.current_timestamp()  # type: ignore[assignment]
            return current.model_copy(update={"status": "running"})

        return await self._run(write, (PromptProposalInvalidTransition,))

    async def record_success(
        self, proposal_id: str, text_by_layer: dict[str, str]
    ) -> PromptProposal:
        def write(session: Session) -> PromptProposal:
            row = _worker_row(session, proposal_id)
            current = _proposal(row)
            if not is_legal_transition(current.status, "succeeded"):
                raise PromptProposalInvalidTransition()
            if current.kind == "translate":
                row.translated_template_body = text_by_layer.get("template")
                row.translated_project_override = text_by_layer.get("project_override")
                _finish(row, "succeeded")
                return current.model_copy(
                    update={
                        "status": "succeeded",
                        "translated_template_body": text_by_layer.get("template"),
                        "translated_project_override": text_by_layer.get("project_override"),
                    }
                )
            if not text_by_layer or set(text_by_layer) - set(current.target_layers):
                raise PromptProposalInvalidTransition()
            layer = current.target_layers[0]
            source_text = (
                current.source.template_body
                if layer == "template"
                else current.source.project_override or ""
            )
            changes = build_prompt_changes(layer, source_text, text_by_layer[layer])
            for ordinal, change in enumerate(changes):
                session.add(
                    PromptProposalChangeRow(
                        proposal_id=proposal_id,
                        change_id=change.change_id,
                        ordinal=ordinal,
                        layer=change.layer,
                        before_text=change.before_text,
                        after_text=change.after_text,
                        start_line=change.start_line,
                        end_line=change.end_line,
                    )
                )
            _finish(row, "succeeded")
            return current.model_copy(update={"status": "succeeded"})

        return await self._run(write, (PromptProposalInvalidTransition,))

    async def record_failure(self, proposal_id: str, failure_code: str) -> PromptProposal:
        if failure_code not in PROMPT_PROPOSAL_FAILURE_CODES:
            raise ValueError("unsafe failure code")

        def write(session: Session) -> PromptProposal:
            row = _worker_row(session, proposal_id)
            current = _proposal(row)
            if not is_legal_transition(current.status, "failed"):
                raise PromptProposalInvalidTransition()
            row.failure_code = failure_code
            _finish(row, "failed")
            return current.model_copy(update={"status": "failed", "failure_code": failure_code})

        return await self._run(write, (PromptProposalInvalidTransition,))

    async def reject_proposal(self, project_id: str, proposal_id: str) -> PromptProposal:
        def write(session: Session) -> PromptProposal:
            row = _proposal_row(session, proposal_id, project_id)
            if row is None:
                raise PromptProposalNotFound()
            current = _proposal(row)
            if not is_legal_transition(current.status, "rejected"):
                raise PromptProposalInvalidTransition()
            _finish(row, "rejected")
            return current.model_copy(update={"status": "rejected"})

        return await self._run(write, (PromptProposalNotFound, PromptProposalInvalidTransition))

    async def apply_improvement(
        self, project_id: str, proposal_id: str, change_ids: list[str], actor: str
    ) -> PromptProposalApplyResult:
        def write(session: Session) -> PromptProposalApplyResult:
            row, current, binding, locks = self._lock_for_apply(session, project_id, proposal_id)
            if current.kind != "improve" or len(current.target_layers) != 1:
                raise PromptProposalInvalidTransition()
            layer = current.target_layers[0]
            self._require_unlocked(locks, layer)
            stored = self._select_changes(session, proposal_id)
            selected = [stored[change_id] for change_id in change_ids if change_id in stored]
            if len(selected) != len(change_ids):
                raise PromptProposalInvalidSelection()
            source_text = (
                current.source.template_body
                if layer == "template"
                else current.source.project_override or ""
            )
            new_text = apply_prompt_changes(source_text, tuple(stored.values()), set(change_ids))
            if layer == "template":
                resulting_template_id = current.source.template_id
                resulting_template_revision = binding.template_revision + 1
                session.add(
                    PromptTemplateRevisionRow(
                        project_id=project_id,
                        template_id=resulting_template_id,
                        revision=resulting_template_revision,
                        stage_id=current.stage_id,
                        language=current.source.template_language,
                        body=new_text,
                    )
                )
                # The binding references the new template revision, so it goes first.
                session.flush()
                resulting_binding_revision = binding.revision + 1
                binding.template_revision = resulting_template_revision
            else:
                resulting_template_id = binding.template_id
                resulting_template_revision = binding.template_revision
                resulting_binding_revision = binding.revision + 1
                binding.project_override = new_text
            binding.revision = resulting_binding_revision
            binding.updated_at = func.current_timestamp()  # type: ignore[assignment]
            self._record_application(
                session,
                current,
                list(change_ids),
                actor,
                resulting_template_id,
                resulting_template_revision,
                resulting_binding_revision,
            )
            _finish(row, "applied")
            return PromptProposalApplyResult.model_validate(
                {
                    "proposal": current.model_copy(update={"status": "applied"}),
                    "resulting_template_id": resulting_template_id,
                    "resulting_template_revision": resulting_template_revision,
                    "resulting_binding_revision": resulting_binding_revision,
                }
            )

        return await self._run(write, _APPLY)

    async def apply_translation(
        self, project_id: str, proposal_id: str, actor: str
    ) -> PromptProposalApplyResult:
        def write(session: Session) -> PromptProposalApplyResult:
            row, current, binding, locks = self._lock_for_apply(session, project_id, proposal_id)
            if current.kind != "translate" or current.translated_template_body is None:
                raise PromptProposalInvalidTransition()
            for layer in current.target_layers:
                self._require_unlocked(locks, layer)
            resulting_template_id = f"ptpl_{uuid4().hex}"
            resulting_template_revision = 1
            resulting_binding_revision = binding.revision + 1
            session.add(
                PromptTemplateRevisionRow(
                    project_id=project_id,
                    template_id=resulting_template_id,
                    revision=resulting_template_revision,
                    stage_id=current.stage_id,
                    language=current.target_language,
                    body=current.translated_template_body,
                )
            )
            # The binding references the new template revision, so it goes first.
            session.flush()
            binding.template_id = resulting_template_id
            binding.template_revision = resulting_template_revision
            binding.project_override = current.translated_project_override
            binding.revision = resulting_binding_revision
            binding.updated_at = func.current_timestamp()  # type: ignore[assignment]
            self._record_application(
                session,
                current,
                [],
                actor,
                resulting_template_id,
                resulting_template_revision,
                resulting_binding_revision,
            )
            _finish(row, "applied")
            return PromptProposalApplyResult.model_validate(
                {
                    "proposal": current.model_copy(update={"status": "applied"}),
                    "resulting_template_id": resulting_template_id,
                    "resulting_template_revision": resulting_template_revision,
                    "resulting_binding_revision": resulting_binding_revision,
                }
            )

        passthrough = tuple(
            error for error in _APPLY if error is not PromptProposalInvalidSelection
        )
        return await self._run(write, passthrough)

    @staticmethod
    def _lock_for_apply(
        session: Session, project_id: str, proposal_id: str
    ) -> tuple[
        PromptProposalRow, PromptProposal, ProjectPromptBindingRow, list[ProjectPromptLayerLock]
    ]:
        # Reserve acquires the project-stage advisory lock before superseding the
        # prior succeeded proposal row. Apply must acquire that same lock before
        # taking any row lock on the proposal, or the two transactions can each
        # hold what the other is waiting for. The stage is immutable for a given
        # proposal, so reading it without FOR UPDATE first is safe.
        stage_id = session.scalar(
            select(PromptProposalRow.stage_id).where(
                PromptProposalRow.project_id == project_id,
                PromptProposalRow.proposal_id == proposal_id,
            )
        )
        if stage_id is None:
            raise PromptProposalNotFound()
        advisory_xact_lock(session, project_id, stage_id)
        row = _proposal_row(session, proposal_id, project_id)
        if row is None:
            raise PromptProposalNotFound()
        current = _proposal(row)
        if current.status != "succeeded":
            raise PromptProposalInvalidTransition()
        binding = session.scalar(
            select(ProjectPromptBindingRow)
            .where(
                ProjectPromptBindingRow.project_id == project_id,
                ProjectPromptBindingRow.stage_id == current.stage_id,
            )
            .with_for_update()
        )
        if binding is None:
            raise PromptProposalStale()
        if (
            binding.template_id != current.source.template_id
            or binding.template_revision != current.source.template_revision
            or binding.revision != current.source.binding_revision
        ):
            raise PromptProposalStale()
        locks = [
            _lock(lock)
            for lock in session.scalars(
                select(PromptLayerLockRow)
                .where(
                    PromptLayerLockRow.project_id == project_id,
                    PromptLayerLockRow.stage_id == current.stage_id,
                )
                .with_for_update()
            )
        ]
        return row, current, binding, locks

    @staticmethod
    def _record_application(
        session: Session,
        current: PromptProposal,
        change_ids: list[str],
        actor: str,
        template_id: str,
        template_revision: int,
        binding_revision: int,
    ) -> None:
        session.add(
            PromptProposalApplicationRow(
                proposal_id=current.proposal_id,
                project_id=current.project_id,
                stage_id=current.stage_id,
                accepted_change_ids=change_ids,
                approving_actor=actor,
                resulting_template_id=template_id,
                resulting_template_revision=template_revision,
                resulting_binding_revision=binding_revision,
                ownership="ai_assisted",
                approval_mode="user_approved",
            )
        )

    @staticmethod
    def _require_unlocked(locks: list[ProjectPromptLayerLock], layer: str) -> None:
        for lock in locks:
            if lock.layer == layer and lock.locked:
                raise PromptProposalLayerLocked()

    @staticmethod
    def _select_changes(session: Session, proposal_id: str) -> dict[str, PromptProposalChange]:
        rows = session.scalars(
            select(PromptProposalChangeRow)
            .where(PromptProposalChangeRow.proposal_id == proposal_id)
            .order_by(PromptProposalChangeRow.ordinal)
        )
        return {
            row.change_id: PromptProposalChange.model_validate(
                {
                    "change_id": row.change_id,
                    "layer": row.layer,
                    "before_text": row.before_text,
                    "after_text": row.after_text,
                    "start_line": row.start_line,
                    "end_line": row.end_line,
                }
            )
            for row in rows
        }
