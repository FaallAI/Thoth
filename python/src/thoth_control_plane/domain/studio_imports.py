"""Bounded Studio import source projection, its server-side identity, and its public inventory."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from thoth_control_plane.domain.edit_documents import BodyText, ShortText
from thoth_control_plane.domain.models import OpaqueId, ProjectId, StrictModel

SourceRole: TypeAlias = Literal[
    "main",
    "main_footage",
    "slide",
    "post_card",
    "profile_page",
    "creator_footage",
    "creator_photo",
    "footage",
    "profile_card",
    "comment_card",
    "comment",
]
MediaKind: TypeAlias = Literal["video", "image", "none"]
Disposition: TypeAlias = Literal["unresolved", "attached", "excluded"]

ROLE_ORDER: tuple[SourceRole, ...] = (
    "main",
    "main_footage",
    "slide",
    # Style A (spec 2026-10-22 5c-2): the post, who posted it, then the creator's other media.
    "post_card",
    "profile_page",
    "creator_footage",
    "creator_photo",
    "footage",
    "profile_card",
    "comment_card",
    "comment",
)
#: Placed over the main scene, never a scene of their own (spec 2026-10-21 5c-1, 4.1).
OVERLAY_ROLES: frozenset[str] = frozenset({"slide", "post_card", "profile_card", "comment_card"})
#: Roles a Content Set holds at most once.
SINGLE_ROLES: frozenset[str] = frozenset(
    {"main", "main_footage", "post_card", "profile_page", "profile_card"}
)
#: Cards shown for their reading time: the comments, and the post that opens the video.
READ_ROLES: frozenset[str] = frozenset({"comment_card", "post_card"})
#: Stills held SLIDE_SECONDS in their own scene, letterboxed (spec 5c-2, G5).
STILL_ROLES: frozenset[str] = frozenset({"profile_page", "creator_photo"})
NOT_PLACED = "Not placed: no room in the reaction beat"
MAX_SOURCE_ITEMS = 400
MAX_UNSUPPORTED_FIELDS = 400
SCENE_LIMIT = 100
DRAFT_LIST_LIMIT = 20
SourceKey = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ItemOrder = Annotated[int, Field(ge=0, lt=MAX_SOURCE_ITEMS)]
Reason = Annotated[str, Field(min_length=1, max_length=200)]
TrimSeconds = Annotated[float, Field(gt=0, le=86_400)]


def _canonical_web_url(value: str) -> str:
    """Accept only an http(s) address with no credentials, query, or fragment."""
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or "@" in parts.netloc
        or "?" in value
        or "#" in value
        or "\\" in value
    ):
        raise ValueError("source_url must be a canonical http(s) address")
    return value


CanonicalUrl = Annotated[str, Field(max_length=2_048), AfterValidator(_canonical_web_url)]


class SourceBlurRegion(StrictModel):
    """A detected subtitle region: fractions of the source frame, a window in source seconds."""

    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]
    w: Annotated[float, Field(gt=0, le=1)]
    h: Annotated[float, Field(gt=0, le=1)]
    start: Annotated[float, Field(ge=0)] | None = None
    end: Annotated[float, Field(ge=0)] | None = None


class StudioSourceItem(StrictModel):
    """One ordered creative input of a Content Set, without host paths or signed queries."""

    role: SourceRole
    order: ItemOrder
    title: ShortText | None
    text: BodyText | None
    platform: Annotated[str, Field(min_length=1, max_length=64)] | None
    source_url: CanonicalUrl | None
    media_kind: MediaKind
    trim_start_seconds: TrimSeconds | None
    mute_audio: bool = False
    blur_regions: Annotated[list[SourceBlurRegion], Field(max_length=200)] = Field(
        default_factory=list
    )
    # How long a comment card stays up; set on `comment_card` items only.
    reading_seconds: Annotated[float, Field(gt=0, le=60)] | None = None

    @model_validator(mode="after")
    def _trim_needs_video(self) -> StudioSourceItem:
        if self.trim_start_seconds is not None and self.media_kind != "video":
            raise ValueError("only a video item can start at a trim")
        if (self.blur_regions or self.mute_audio) and self.media_kind != "video":
            raise ValueError("only a video item carries blur or mute")
        if (self.reading_seconds is not None) != (self.role in READ_ROLES):
            raise ValueError("a comment or post card, and only those, has a reading time")
        return self


class StudioUnsupportedField(StrictModel):
    """A creative field Studio cannot represent, named by where it came from."""

    field: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
    role: SourceRole | None
    order: ItemOrder | None
    reason: Reason
    # Digest of the dropped value, so distinct choices never share a source_key.
    value_digest: SourceKey | None = None


class StudioSourceProjection(StrictModel):
    """The whole first-mode source: one main item, then main footage, footage, and comments."""

    items: Annotated[list[StudioSourceItem], Field(min_length=1, max_length=MAX_SOURCE_ITEMS)]
    unsupported: Annotated[list[StudioUnsupportedField], Field(max_length=MAX_UNSUPPORTED_FIELDS)]

    @model_validator(mode="after")
    def _ordered_roles(self) -> StudioSourceProjection:
        keys = [(ROLE_ORDER.index(item.role), item.order) for item in self.items]
        if keys[0] != (0, 0) or keys != sorted(keys):
            raise ValueError("items must start with main and follow role order")
        for role in ROLE_ORDER:
            orders = [item.order for item in self.items if item.role == role]
            if orders != list(range(len(orders))) or (role in SINGLE_ROLES and len(orders) > 1):
                raise ValueError(f"{role} items must be numbered from zero without gaps")
        return self


class StudioImportItem(StrictModel):
    """Public inventory entry: a media item to attach or a field to exclude. Never an address."""

    item_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    role: SourceRole | None
    order: ItemOrder | None
    label: Annotated[str, Field(min_length=1, max_length=300)]
    platform: str | None
    media_kind: MediaKind
    scene_id: OpaqueId | None
    reason: Reason | None
    disposition: Disposition
    asset_id: OpaqueId | None = None
    # Seconds of source media to skip when attached; drafts made before trims were kept have none.
    trim_start_seconds: TrimSeconds | None = None
    # Carried from the source item so placement needs only the stored inventory (spec 5c-1, 4.2).
    mute_audio: bool = False
    blur_regions: Annotated[list[SourceBlurRegion], Field(max_length=200)] = Field(
        default_factory=list
    )
    reading_seconds: Annotated[float, Field(gt=0, le=60)] | None = None


class StudioDraft(StrictModel):
    """One Studio draft created from a source, with its latest saved revision."""

    document_id: OpaqueId
    source_key: SourceKey
    revision: Annotated[int, Field(gt=0)]
    created_at: datetime


class StudioSourceInspection(StrictModel):
    """What opening a source in Studio would import, before anything is created."""

    project_id: ProjectId
    source_key: SourceKey
    items: list[StudioImportItem]
    drafts: Annotated[list[StudioDraft], Field(max_length=DRAFT_LIST_LIMIT)] = Field(
        default_factory=list
    )
    more_drafts: bool = False


class StudioDraftList(StrictModel):
    """The newest drafts made from one source; ``more_drafts`` says the list was cut."""

    source_key: SourceKey
    drafts: Annotated[list[StudioDraft], Field(max_length=DRAFT_LIST_LIMIT)]
    more_drafts: bool


class StudioImportInventory(StrictModel):
    """The decisions still owed, and already made, for one draft at its latest revision."""

    document_id: OpaqueId
    source_key: SourceKey
    revision: Annotated[int, Field(gt=0)]
    items: list[StudioImportItem]
    #: The run the draft was opened from (B9); none for a blank or pre-B9 draft.
    source_workflow_id: OpaqueId | None = None


class MaterialFigure(StrictModel):
    """A person or organisation the run named: context for the editor, never media."""

    name: str
    type: str
    role: str


class StudioMaterial(StrictModel):
    """One inventory item and, when the run's Content Set is readable, where it came from.

    Provenance carries a host, never a full address, and never a storage location.
    """

    item_id: str
    role: SourceRole | None
    label: str
    media_kind: MediaKind
    disposition: Disposition
    asset_id: OpaqueId | None = None
    platform: str | None = None
    owner_handle: str | None = None
    published_at: str | None = None
    host: str | None = None
    engagement: dict[str, int] | None = None
    story_score: float | None = None
    shows_object: Literal["yes", "partly"] | None = None
    query: str | None = None
    likes: int | None = None
    author: str | None = None
    verdict: Literal["original", "replaced", "unresolved", "none"] | None = None
    ocr_outcome: Literal["clean", "cover", "subtitle", "overlay"] | None = None
    trim_start_seconds: float | None = None


class StudioMaterials(StrictModel):
    """Story mode's Materials panel (spec 2026-10-27, 6.1); read on every call, never stored."""

    document_id: OpaqueId
    provenance_available: bool
    items: list[StudioMaterial]
    figures: list[MaterialFigure] = Field(default_factory=list)


class CreateStudioImport(StrictModel):
    """Create a draft from a projected source; the server recomputes ``source_key``."""

    source: StudioSourceProjection
    source_key: SourceKey


class ExcludeImportItem(StrictModel):
    kind: Literal["exclude"]
    # Set only by the workflow importer for a comment card the reaction beat had no room for.
    reason: Literal["not_placed"] | None = None


class AttachImportAsset(StrictModel):
    kind: Literal["attach_asset"]
    asset_id: OpaqueId


class ResolveStudioImportItem(StrictModel):
    """One explicit decision for one inventory item, bound to the saved revision."""

    base_revision: Annotated[int, Field(gt=0)]
    decision: Annotated[ExcludeImportItem | AttachImportAsset, Field(discriminator="kind")]


def source_key(projection: StudioSourceProjection) -> str:
    """SHA-256 of the canonical projection: sorted object keys, item order preserved."""
    canonical = json.dumps(
        projection.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def scene_items(projection: StudioSourceProjection) -> list[StudioSourceItem]:
    """Every item that carries text or media, in source order: one scene each.

    Main footage is context for the main scene, never a scene of its own.
    """
    return [
        item
        for item in projection.items
        if item.role != "main_footage"
        and item.role not in OVERLAY_ROLES
        and (item.role == "main" or item.title or item.text or item.media_kind != "none")
    ]


def _media_label(item: StudioSourceItem) -> str:
    if item.title:
        return item.title
    if item.role == "main_footage":
        return "Main footage"
    return f"{item.role.capitalize()} {item.order + 1}"


def inventory(projection: StudioSourceProjection) -> list[StudioImportItem]:
    """Every media item and unsupported field, each awaiting an attach or exclude decision."""
    ordered = scene_items(projection)
    scenes = {
        (item.role, item.order): f"scene_{index:03d}"
        for index, item in enumerate(ordered[:SCENE_LIMIT], start=1)
    }
    scenes[("main_footage", 0)] = "scene_001"
    for item in projection.items:
        if item.role in OVERLAY_ROLES:
            scenes[(item.role, item.order)] = "scene_001"
    media = [
        StudioImportItem(
            item_id=f"{item.role}_{item.order:03d}",
            role=item.role,
            order=item.order,
            label=_media_label(item),
            platform=item.platform,
            media_kind=item.media_kind,
            scene_id=scenes.get((item.role, item.order)),
            reason=None,
            disposition="unresolved",
            trim_start_seconds=item.trim_start_seconds,
            mute_audio=item.mute_audio,
            blur_regions=item.blur_regions,
            reading_seconds=item.reading_seconds,
        )
        for item in projection.items
        if item.media_kind != "none"
    ]
    unsupported = [
        StudioImportItem(
            item_id=f"unsupported_{index:03d}",
            role=field.role,
            order=field.order,
            label=field.field,
            platform=None,
            media_kind="none",
            scene_id=None,
            reason=field.reason,
            disposition="unresolved",
        )
        for index, field in enumerate(projection.unsupported)
    ]
    overflow = len(ordered) - SCENE_LIMIT
    if overflow > 0:
        unsupported.append(
            StudioImportItem(
                item_id="scene_overflow",
                role=None,
                order=None,
                label=f"{overflow} items beyond the {SCENE_LIMIT}-scene limit",
                platform=None,
                media_kind="none",
                scene_id=None,
                reason=f"Studio documents hold at most {SCENE_LIMIT} scenes",
                disposition="unresolved",
            )
        )
    return media + unsupported


def inspect_source(project_id: str, projection: StudioSourceProjection) -> StudioSourceInspection:
    """Compute the source identity on the server and list what needs a decision."""
    return StudioSourceInspection(
        project_id=project_id, source_key=source_key(projection), items=inventory(projection)
    )


ImportOutcome: TypeAlias = Literal["reused", "copied", "unresolved", "decided", "not_placed"]
ImportCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class WorkflowImportItem(StrictModel):
    """What one media item's import did: reused or copied an asset, left it unresolved with a
    fixed reason, or found it already decided (attached or excluded) by an earlier attempt."""

    item_id: ImportCode
    outcome: ImportOutcome
    reason: ImportCode | None = None


class WorkflowStudioImport(StrictModel):
    """The draft a workflow opened into, at its latest revision, and each media item's outcome."""

    draft: StudioDraft
    items: list[WorkflowImportItem]
