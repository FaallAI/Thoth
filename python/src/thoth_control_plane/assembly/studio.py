"""A Content Set projected for Studio (spec 2026-10-20 workflow to Studio, section 1).

Pure: no I/O. Each media item keeps the `MediaRef` it came from, keyed by the inventory item id
the import gate gives it (`<role>_<order:03d>`), so the importer copies exactly that object.
Schema 1 bounds a Content Set at one main, six footage and twelve comments, far inside the
gate's item and scene limits, so nothing here truncates.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from thoth_control_plane.assembly.models import ContentSet, Footage, MainOcr, MediaRef
from thoth_control_plane.domain.studio_imports import (
    SourceBlurRegion,
    SourceRole,
    StudioSourceItem,
    StudioSourceProjection,
    StudioUnsupportedField,
)
from thoth_control_plane.domain.studio_layout import reading_seconds

TITLE_LIMIT = 300
TEXT_LIMIT = 2_000
FIGURES = "Figures are context, not scenes"
# Style A materials each platform should yield (spec 2026-10-22 5c-2, G1 and G2).
POST_CARD_PLATFORMS = frozenset({"x", "threads", "instagram", "tiktok"})
PROFILE_PAGE_PLATFORMS = frozenset({"tiktok", "instagram", "x", "youtube"})


@dataclass(frozen=True)
class WorkflowProjection:
    projection: StudioSourceProjection
    media: dict[str, MediaRef]
    #: Story mode's "why" per item id (spec 2026-10-27, 6.1); never part of the source key.
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The people and organisations the run named, as context (name, type, role).
    figures: list[dict[str, str]] = field(default_factory=list)


def workflow_source_key(workflow_id: str, content_sha256: str) -> str:
    """Distinct per workflow, stable for one Content Set, new when it is re-assembled."""
    return hashlib.sha256(f"workflow:{workflow_id}:{content_sha256}".encode()).hexdigest()


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def _canonical(url: object) -> str | None:
    """The gate takes no query, fragment or credentials: keep the scheme, host and path.

    A YouTube watch link carries its video only in the query, so it becomes the equivalent
    `https://youtu.be/<id>` short link instead of a bare `/watch`.
    """
    parts = urlsplit(str(url))
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.hostname in YOUTUBE_HOSTS and parts.path == "/watch":
        video = parse_qs(parts.query).get("v", [""])[0]
        if YOUTUBE_ID.fullmatch(video):
            return f"https://youtu.be/{video}"
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    value = urlunsplit((parts.scheme, host, parts.path or "/", "", ""))
    return value if len(value) <= 2_048 and "\\" not in value else None


def _trim(ocr: MainOcr | None) -> float | None:
    return ocr.trim_start if ocr is not None and ocr.trim_start > 0 else None


class _Builder:
    def __init__(self) -> None:
        self.items: list[StudioSourceItem] = []
        self.unsupported: list[StudioUnsupportedField] = []
        self.media: dict[str, MediaRef] = {}
        self.provenance: dict[str, dict[str, Any]] = {}

    def report(
        self, field: str, role: SourceRole | None, order: int | None, reason: str, value: Any
    ) -> None:
        self.unsupported.append(
            StudioUnsupportedField(
                field=field, role=role, order=order, reason=reason, value_digest=_digest(value)
            )
        )

    def bounded(
        self, field: str, role: SourceRole, order: int, value: str, limit: int
    ) -> str | None:
        if not value:
            return None
        if len(value) > limit:
            self.report(field, role, order, f"Longer than {limit} characters", value)
            return None
        return value

    def add(
        self,
        role: SourceRole,
        order: int,
        *,
        title: str | None,
        text: str | None,
        platform: str | None,
        url: object | None,
        media: MediaRef | None,
        trim: float | None,
        ocr: MainOcr | None = None,
        reading: float | None = None,
        why: dict[str, Any] | None = None,
    ) -> None:
        self.provenance[f"{role}_{order:03d}"] = {
            **({"host": urlsplit(str(url)).hostname} if url is not None else {}),
            **({"ocr_outcome": ocr.outcome, "trim_start_seconds": _trim(ocr)} if ocr else {}),
            **(why or {}),
        }
        if media is None:
            kind = "none"
        else:
            kind = "video" if media.media_type.startswith("video/") else "image"
            self.media[f"{role}_{order:03d}"] = media
        self.items.append(
            StudioSourceItem(
                role=role,
                order=order,
                title=title,
                text=text,
                platform=platform,
                source_url=None if url is None else _canonical(url),
                media_kind=kind,
                trim_start_seconds=trim if kind == "video" else None,
                # Imported as data; the draft keeps both switched off (spec 5c-1, section 6).
                mute_audio=bool(ocr and ocr.mute_audio and kind == "video"),
                blur_regions=[
                    SourceBlurRegion.model_validate(region.model_dump())
                    for region in (ocr.subtitle_blur if ocr and kind == "video" else [])
                ],
                reading_seconds=reading,
            )
        )


def _footage(built: _Builder, role: SourceRole, clips: list[Footage]) -> None:
    for order, clip in enumerate(clips):
        built.add(
            role,
            order,
            title=f"@{clip.owner_handle}",
            text=clip.description or None,
            platform=clip.platform,
            url=clip.url,
            media=clip.video,
            trim=_trim(clip.ocr),
            ocr=clip.ocr,
            why={
                "platform": clip.platform,
                "owner_handle": clip.owner_handle,
                "published_at": clip.published_at,
                "engagement": clip.engagement or None,
                "story_score": clip.story_score,
                "shows_object": clip.shows_object,
                "query": clip.query,
            },
        )


def project_content_set(content_set: ContentSet) -> WorkflowProjection:
    built = _Builder()
    main = content_set.main
    if main.kind == "video":
        media = main.video
    elif main.kind == "images":
        media = main.images[0]
    else:
        media = main.card
    built.add(
        "main",
        0,
        title=built.bounded("main.title", "main", 0, main.title, TITLE_LIMIT),
        text=built.bounded("main.description", "main", 0, main.description, TEXT_LIMIT),
        platform=str(main.platform),
        url=main.url,
        media=media,
        trim=_trim(main.ocr),
        ocr=main.ocr,
        why={
            "platform": str(main.platform),
            "owner_handle": main.owner_handle,
            "published_at": main.published_at,
            "engagement": main.engagement or None,
            "verdict": content_set.attribution_verdict,
        },
    )
    # Posts and profiles show who and where (spec 2026-10-27, 6.3).
    owner = {
        "platform": str(main.platform),
        "owner_handle": main.owner_handle,
        "published_at": main.published_at,
    }
    for order, image in enumerate(main.images[1:]):
        # Slide numbers count the carousel's own images: the first slide item is image 2.
        built.add(
            "slide",
            order,
            title=f"Slide {order + 2}",
            text=None,
            platform=None,
            url=None,
            media=image,
            trim=None,
        )
    if main.post_card is not None and main.kind != "card":
        built.add(
            "post_card",
            0,
            title=f"@{main.owner_handle}",
            text=None,
            platform=str(main.platform),
            url=None,
            media=main.post_card,
            trim=None,
            reading=reading_seconds(main.description),
            why=owner,
        )
    if main.profile_page is not None:
        built.add(
            "profile_page",
            0,
            title=f"@{main.owner_handle}",
            text=None,
            platform=str(main.platform),
            url=None,
            media=main.profile_page,
            trim=None,
            why=owner,
        )
    creator = [clip for clip in content_set.footage if clip.source == "creator"]
    search = [clip for clip in content_set.footage if clip.source != "creator"]
    _footage(built, "creator_footage", creator)
    for order, photo in enumerate(content_set.photos):
        built.add(
            "creator_photo",
            order,
            title=f"@{photo.owner_handle}",
            text=built.bounded("photos.caption", "creator_photo", order, photo.caption, TEXT_LIMIT),
            platform=photo.platform,
            url=photo.url,
            media=photo.image,
            trim=None,
            why={
                "platform": photo.platform,
                "owner_handle": photo.owner_handle,
                "story_score": photo.story_score,
            },
        )
    _footage(built, "footage", search)
    if main.profile_card is not None:
        built.add(
            "profile_card",
            0,
            title=f"@{main.owner_handle}",
            text=None,
            platform=str(main.platform),
            url=None,
            media=main.profile_card,
            trim=None,
            why=owner,
        )
    # Most-liked first: the reaction beat places cards in this order (spec 5c-1, 3.2).
    carded = sorted(
        (comment for comment in content_set.comments if comment.card is not None),
        key=lambda comment: -comment.likes,
    )
    for order, comment in enumerate(carded):
        built.add(
            "comment_card",
            order,
            title=f"@{comment.author}",
            text=comment.text,
            platform=None,
            url=None,
            media=comment.card,
            trim=None,
            reading=reading_seconds(comment.text),
            why={"author": comment.author, "likes": comment.likes},
        )
    plain = [comment for comment in content_set.comments if comment.card is None]
    for order, comment in enumerate(plain):
        built.add(
            "comment",
            order,
            title=f"@{comment.author}",
            text=comment.text,
            platform=None,
            url=None,
            media=None,
            trim=None,
            # Never an inventory item: the Materials panel lists it as a quote.
            why={"author": comment.author, "likes": comment.likes, "label": comment.text[:300]},
        )
    if content_set.figures:
        figures = [figure.model_dump(mode="json") for figure in content_set.figures]
        built.report("figures", None, None, FIGURES, figures)
    if content_set.style_a:
        # A material the platform should yield but the run did not capture is shown, never
        # only logged (spec 5c-2, "no silent gap").
        platform = str(main.platform)
        if main.kind != "card" and main.post_card is None and platform in POST_CARD_PLATFORMS:
            built.report("main.post_card", "post_card", 0, "Not captured: post card", None)
        if main.profile_page is None and platform in PROFILE_PAGE_PLATFORMS:
            built.report("main.profile_page", "profile_page", 0, "Not captured: profile page", None)
    projection = StudioSourceProjection(items=built.items, unsupported=built.unsupported)
    figures = [
        {"name": figure.name, "type": figure.type, "role": figure.role}
        for figure in content_set.figures
    ]
    return WorkflowProjection(
        projection=projection, media=built.media, provenance=built.provenance, figures=figures
    )
