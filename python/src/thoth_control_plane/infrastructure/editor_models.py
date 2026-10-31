"""SQLAlchemy ORM rows for the editor tables (editor migrations 0001-0007, 0017, 0021, 0024, 0027).

They mirror the shipped SQL exactly; the migrations stay the source of truth, and a Postgres
parity test compares every table here with the migrated schema. Constraints the database
enforces (CHECKs, partial unique indexes) are not repeated: the database owns them.

The rows have their own declarative base: their JSONB and array columns exist only on
Postgres, so they must never join a metadata that tests create on SQLite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Double, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class EditorBase(DeclarativeBase):
    pass


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())


class EditDocumentRevisionRow(EditorBase):
    __tablename__ = "edit_document_revisions"

    project_id: Mapped[str] = mapped_column(Text)
    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_json: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class PromptTemplateRevisionRow(EditorBase):
    __tablename__ = "prompt_template_revisions"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    template_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class ProjectPromptBindingRow(EditorBase):
    __tablename__ = "project_prompt_bindings"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    stage_id: Mapped[str] = mapped_column(Text, primary_key=True)
    template_id: Mapped[str] = mapped_column(Text)
    template_revision: Mapped[int] = mapped_column(Integer)
    project_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class PromptProviderPreferenceRow(EditorBase):
    __tablename__ = "prompt_provider_preferences"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    stage_id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_id: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class PromptLayerLockRow(EditorBase):
    __tablename__ = "prompt_layer_locks"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    stage_id: Mapped[str] = mapped_column(Text, primary_key=True)
    layer: Mapped[str] = mapped_column(Text, primary_key=True)
    locked: Mapped[bool] = mapped_column(Boolean)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class PromptProposalRow(EditorBase):
    __tablename__ = "prompt_proposals"

    proposal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text)
    stage_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    target_layers: Mapped[list[str]] = mapped_column(ARRAY(Text))
    source_template_id: Mapped[str] = mapped_column(Text)
    source_template_revision: Mapped[int] = mapped_column(Integer)
    source_binding_revision: Mapped[int] = mapped_column(Integer)
    source_language: Mapped[str] = mapped_column(Text)
    source_template_body: Mapped[str] = mapped_column(Text)
    source_project_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_id: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text)
    translated_template_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_project_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromptProposalChangeRow(EditorBase):
    __tablename__ = "prompt_proposal_changes"

    proposal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    change_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    layer: Mapped[str] = mapped_column(Text)
    before_text: Mapped[str] = mapped_column(Text)
    after_text: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)


class PromptProposalIdempotencyRow(EditorBase):
    __tablename__ = "prompt_proposal_idempotency"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(Text)
    proposal_id: Mapped[str] = mapped_column(Text)


class PromptProposalApplicationRow(EditorBase):
    __tablename__ = "prompt_proposal_applications"

    proposal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text)
    stage_id: Mapped[str] = mapped_column(Text)
    accepted_change_ids: Mapped[list[str]] = mapped_column(ARRAY(Text))
    approving_actor: Mapped[str] = mapped_column(Text)
    resulting_template_id: Mapped[str] = mapped_column(Text)
    resulting_template_revision: Mapped[int] = mapped_column(Integer)
    resulting_binding_revision: Mapped[int] = mapped_column(Integer)
    ownership: Mapped[str] = mapped_column(Text)
    approval_mode: Mapped[str] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp()
    )


class EditorAssetRow(EditorBase):
    __tablename__ = "editor_assets"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    artifact_location: Mapped[str] = mapped_column(Text)
    duration_in_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Double, nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean)
    validation_state: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class EditDocumentUpgradeIdempotencyRow(EditorBase):
    __tablename__ = "edit_document_upgrade_idempotency"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(Text)
    document_id: Mapped[str] = mapped_column(Text)
    result_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class RenderJobRow(EditorBase):
    __tablename__ = "render_jobs"

    render_job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text)
    document_id: Mapped[str] = mapped_column(Text)
    document_revision: Mapped[int] = mapped_column(Integer)
    dispatch_id: Mapped[str] = mapped_column(Text)
    template_id: Mapped[str] = mapped_column(Text)
    template_version: Mapped[int] = mapped_column(Integer)
    preset_id: Mapped[str] = mapped_column(Text)
    renderer_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_event_sequence: Mapped[int] = mapped_column(Integer, server_default="0")
    retry_of_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    artifacts_cleaned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_relative_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_checksum: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[Any] = mapped_column(JSONB)
    # Editor migration 0021 (run-progress spec G6): the renderer's stage and frame counts.
    rendered_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    encoded_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_stage: Mapped[str | None] = mapped_column(Text, nullable=True)


class RenderJobIdempotencyRow(EditorBase):
    __tablename__ = "render_job_idempotency"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(Text)
    render_job_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class StudioReviewEventRow(EditorBase):
    __tablename__ = "studio_review_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text)
    document_id: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    operation_id: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    event_kind: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    frame: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class StudioImportDraftRow(EditorBase):
    __tablename__ = "studio_import_drafts"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    first_revision: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    inventory: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()
    # Editor migration 0024 (restyle B9): the run the draft was opened from.
    source_workflow_id: Mapped[str | None] = mapped_column(Text, nullable=True)


class StudioImportDecisionRow(EditorBase):
    __tablename__ = "studio_import_decisions"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    disposition: Mapped[str] = mapped_column(Text)
    asset_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    # Editor migration 0017: why a workflow import excluded an item it had no room for.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class NarrationRow(EditorBase):
    """Editor migration 0027: one narration per Studio draft (auto-draft, 2026-10-31)."""

    __tablename__ = "narrations"

    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text)
    workflow_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    preset: Mapped[Any] = mapped_column(JSONB)
    transcript: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    script: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    estimate: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    unsupported: Mapped[Any] = mapped_column(JSONB, server_default="{}")
    voices: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    stale_beats: Mapped[Any] = mapped_column(JSONB, server_default="[]")
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class NarrationPresetRow(EditorBase):
    __tablename__ = "narration_presets"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    preset: Mapped[Any] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _created_at()


class SfxLibraryRow(EditorBase):
    __tablename__ = "sfx_library"

    sfx_id: Mapped[str] = mapped_column(Text, primary_key=True)
    file_name: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Double)
    labels: Mapped[Any] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created_at()
