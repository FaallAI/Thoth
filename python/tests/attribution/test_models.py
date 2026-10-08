"""The attribution artifact: a source exactly when replaced, bounded evidence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from thoth_control_plane.attribution.models import (
    AttributedPost,
    AttributionEvidence,
    SourceAttribution,
)

REPOST = "https://www.tiktok.com/@detikjatim/video/7677496203042360594"


def _post(url: str = REPOST, owner: str = "detikjatim") -> AttributedPost:
    return AttributedPost(platform="tiktok", canonical_url=url, owner_handle=owner)


def test_a_source_is_present_exactly_when_replaced() -> None:
    SourceAttribution(workflow_id="wf_a", input=_post(), verdict="original")
    with pytest.raises(ValidationError):
        SourceAttribution(workflow_id="wf_a", input=_post(), verdict="replaced")
    with pytest.raises(ValidationError):
        SourceAttribution(workflow_id="wf_a", input=_post(), verdict="original", source=_post())


def test_evidence_is_bounded_and_the_artifact_round_trips() -> None:
    attribution = SourceAttribution(
        workflow_id="wf_a",
        input=_post(),
        verdict="unresolved",
        reason="no_credit",
        evidence=[AttributionEvidence(kind="frame_text", detail="@vincentius.christ76")],
        candidates={"discovered": 3},
    )

    assert SourceAttribution.model_validate_json(attribution.model_dump_json()) == attribution
    with pytest.raises(ValidationError):
        AttributionEvidence(kind="caption", detail="x" * 301)
    with pytest.raises(ValidationError):
        SourceAttribution(workflow_id="wf_a", input=_post(), verdict="unresolved", reason="No")
