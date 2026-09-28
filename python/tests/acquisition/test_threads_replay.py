"""Sanitized golden fixtures replay through the Threads parser and acquirer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.acquisition import threads_service
from thoth_control_plane.acquisition.adapters.threads import (
    canonicalize_threads_post_url,
    parse_documents,
)
from thoth_control_plane.operations.threads_fixture import decide

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "threads"
FIXTURES = {
    path.stem: json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURE_DIR.glob("*.json"))
}


def _identity(fixture: dict):
    owner, code = fixture["identity"]["owner_handle"], fixture["identity"]["post_id"]
    return canonicalize_threads_post_url(f"https://www.threads.com/@{owner}/post/{code}")


def test_all_three_post_kinds_are_present() -> None:
    assert set(FIXTURES) == {"video", "image", "text"}


@pytest.mark.parametrize("kind", ["video", "image", "text"])
def test_fixture_replays_to_its_expected_parse(kind: str) -> None:
    fixture = FIXTURES[kind]
    parsed = parse_documents([fixture["document"]], _identity(fixture))
    assert parsed is not None
    assert {
        "text": parsed.post.text,
        "media_kinds": [item.kind for item in parsed.media],
        "engagement": parsed.post.engagement,
        "published_at": parsed.post.published_at,
    } == fixture["expected"]


def test_post_kinds_have_their_shape() -> None:
    assert FIXTURES["text"]["expected"]["media_kinds"] == []
    assert FIXTURES["text"]["expected"]["text"].strip()
    assert "video" in FIXTURES["video"]["expected"]["media_kinds"]
    assert FIXTURES["image"]["expected"]["media_kinds"]
    assert set(FIXTURES["image"]["expected"]["media_kinds"]) == {"image"}


def test_content_method_matches_recorded_comparison() -> None:
    pairs = [(f["counts"]["request"], f["counts"]["headless"]) for f in FIXTURES.values()]
    assert decide(pairs) == threads_service.CONTENT_METHOD
