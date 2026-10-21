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
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from thoth_control_plane.assembly.models import ContentSet, MainOcr, MediaRef
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


@dataclass(frozen=True)
class WorkflowProjection:
    projection: StudioSourceProjection
    media: dict[str, MediaRef]


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
    ) -> None:
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
    )
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
    for order, clip in enumerate(content_set.footage):
        built.add(
            "footage",
            order,
            title=f"@{clip.owner_handle}",
            text=clip.description or None,
            platform=clip.platform,
            url=clip.url,
            media=clip.video,
            trim=_trim(clip.ocr),
            ocr=clip.ocr,
        )
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
        )
    if content_set.figures:
        figures = [figure.model_dump(mode="json") for figure in content_set.figures]
        built.report("figures", None, None, FIGURES, figures)
    projection = StudioSourceProjection(items=built.items, unsupported=built.unsupported)
    return WorkflowProjection(projection=projection, media=built.media)
