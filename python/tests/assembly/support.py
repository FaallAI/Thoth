"""Source reports for assembly tests, built on the v3 contract fixture."""

from __future__ import annotations

import copy
import json
import zlib
from pathlib import Path
from typing import Any

from thoth_control_plane.acquisition.models import SourceReport

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tiktok" / "source_report_v3.json").read_text(
        encoding="utf-8"
    )
)
CARD = {
    "media_type": "image/png",
    "bytes": 2048,
    "checksum": "sha256:" + "c" * 64,
    "width": 600,
    "height": 120,
}


def comment(author: str, text: str, likes: int = 0, card: str | None = None) -> dict[str, Any]:
    return {
        "comment_id": f"c{zlib.crc32(f'{author}|{text}'.encode()):010d}",
        "author": author,
        "text": text,
        "likes": likes,
        "card": CARD | {"location": card} if card else None,
    }


def report(
    *,
    workflow_id: str = "wf_a",
    owner: str = "creator",
    url: str = "https://www.tiktok.com/@creator/video/1234567890",
    text: str = "Banjir di Jakarta hari ini",
    media: str = "video",
    duration: float | None = 30.0,
    comments: list[dict[str, Any]] | None = None,
    post_card: bool = False,
    profile_card: bool = False,
) -> SourceReport:
    data = copy.deepcopy(FIXTURE)
    data["workflow_id"] = workflow_id
    data["source"]["canonical_url"] = url
    data["post"].update(owner_handle=owner, text=text, published_at="2026-10-10T08:00:00Z")
    video = data["media"][0]
    video["location"] = f"reports/{workflow_id}/media/video.mp4"
    video["duration_seconds"] = duration
    if media == "images":
        data["media"] = [
            video
            | {
                "media_id": f"media_{n}",
                "kind": "image",
                "index": n,
                "location": f"reports/{workflow_id}/media/{n}.jpg",
                "media_type": "image/jpeg",
                "bytes": 5000,
                "duration_seconds": None,
            }
            for n in (1, 2)
        ]
    elif media == "none":
        data["media"] = []
    data["comments"] = comments or []
    data["post_card"] = (
        CARD | {"location": f"reports/{workflow_id}/cards/post.png"} if post_card else None
    )
    data["profile_card"] = (
        CARD | {"location": f"reports/{workflow_id}/cards/profile.png"} if profile_card else None
    )
    return SourceReport.model_validate_json(json.dumps(data))
