import json
from pathlib import Path, PurePosixPath

import pytest
from pydantic import SecretStr, ValidationError

from thoth_control_plane.acquisition.models import (
    MAX_CARD_BYTES,
    AcquisitionAttempt,
    AcquisitionReason,
    AcquisitionStrategy,
    AttemptStatus,
    BrowserSnapshot,
    CardArtifact,
    MaterializedMedia,
    ReportComment,
    ResolvedMedia,
    TikTokAcquisitionFailure,
    TikTokAcquisitionResult,
    TikTokPost,
    TikTokSourceReport,
)


def resolved_media() -> ResolvedMedia:
    return ResolvedMedia(
        kind="video",
        ephemeral_url=SecretStr("https://cdn.example/video.mp4?sig=secret"),
        media_type="video/mp4",
        duration_seconds=None,
    )


def test_ephemeral_media_url_is_excluded_from_dump_and_repr() -> None:
    media = resolved_media()
    assert "ephemeral_url" not in media.model_dump()
    assert "cdn.example" not in repr(media)


def test_report_serializes_only_relative_materialized_media() -> None:
    report = TikTokSourceReport(
        workflow_id="wf_contract_001",
        source={
            "platform": "tiktok",
            "canonical_url": "https://www.tiktok.com/@creator/video/1234567890",
        },
        post={"post_id": "1234567890", "owner_handle": "creator", "caption": ""},
        media=[
            MaterializedMedia(
                media_id="media_1",
                location=PurePosixPath("reports/wf_contract_001/media/tiktok-1234567890.mp4"),
                bytes=10_000,
                checksum="sha256:" + "a" * 64,
                acquisition_strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
            )
        ],
        outcome={
            "status": "resolved",
            "attempts": [
                AcquisitionAttempt(
                    strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
                    status=AttemptStatus.SUCCEEDED,
                    reason=None,
                    attempt_count=1,
                    elapsed_ms=12,
                )
            ],
        },
    )
    serialized = report.model_dump_json()
    assert "https://www.tiktok.com/@creator/video/1234567890" in serialized
    assert "absolute" not in serialized
    assert "signed" not in serialized


def test_result_requires_exactly_one_terminal_outcome() -> None:
    with pytest.raises(ValidationError):
        TikTokAcquisitionResult()
    with pytest.raises(ValidationError):
        TikTokAcquisitionResult(
            report=TikTokSourceReport.model_validate_json(
                (
                    Path(__file__).resolve().parent.parent
                    / "fixtures"
                    / "tiktok"
                    / "normalized_report.json"
                ).read_text(encoding="utf-8")
            ),
            failure={"code": "headless_blocked", "retryable": True},
        )


def test_failure_serializes_safe_ordered_attempts() -> None:
    # Note: strategy/status/reason use enum members rather than the raw string
    # literals shown in the plan brief, because `StrictModel` (unrelated to
    # this task, out of scope to change) sets `strict=True`, which rejects raw
    # strings for enum-typed fields with an `is_instance_of` error. The string
    # *values* below are identical to the brief's literals.
    attempts = [
        AcquisitionAttempt(
            strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
            status=AttemptStatus.FAILED,
            reason=AcquisitionReason.HEADLESS_BLOCKED,
            attempt_count=1,
            elapsed_ms=10,
        ),
        AcquisitionAttempt(
            strategy=AcquisitionStrategy.TIKWM_CDN,
            status=AttemptStatus.FAILED,
            reason=AcquisitionReason.CDN_UNAVAILABLE,
            attempt_count=1,
            elapsed_ms=20,
        ),
    ]
    failure = TikTokAcquisitionFailure(code="cdn_unavailable", retryable=True, attempts=attempts)

    assert failure.model_dump(mode="json") == {
        "code": "cdn_unavailable",
        "retryable": True,
        "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
    }


def test_failure_rejects_more_than_three_attempts() -> None:
    attempt = AcquisitionAttempt(
        strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
        status=AttemptStatus.FAILED,
        reason=AcquisitionReason.HEADLESS_TIMEOUT,
        attempt_count=1,
        elapsed_ms=1,
    )
    with pytest.raises(ValidationError):
        TikTokAcquisitionFailure(code="headless_timeout", retryable=True, attempts=[attempt] * 4)


def test_browser_snapshot_contains_sanitized_candidates_only() -> None:
    snapshot = BrowserSnapshot(
        final_url="https://www.tiktok.com/@creator/video/1234567890",
        post_candidates=[
            TikTokPost(post_id="1234567890", owner_handle="creator", caption="caption")
        ],
        media_candidates=[resolved_media()],
    )
    dumped = snapshot.model_dump_json()
    assert "raw_html" not in dumped
    assert "cookie" not in dumped
    assert "cdn.example" not in dumped


FIXTURE_REPORT = (
    Path(__file__).resolve().parent.parent / "fixtures" / "tiktok" / "normalized_report.json"
)


def _fixture_report() -> TikTokSourceReport:
    return TikTokSourceReport.model_validate_json(FIXTURE_REPORT.read_text(encoding="utf-8"))


def _card(location: str = "reports/wf_contract_001/cards/comment-12345.png") -> CardArtifact:
    return CardArtifact(
        location=PurePosixPath(location),
        bytes=4_000,
        checksum="sha256:" + "b" * 64,
        width=300,
        height=80,
    )


def test_v1_report_still_validates_with_empty_enrichment() -> None:
    report = _fixture_report()
    assert report.schema_version == 1
    assert report.comments == []
    assert report.profile_card is None


def test_new_reports_default_to_schema_v2() -> None:
    assert TikTokSourceReport.model_fields["schema_version"].default == 2


def test_v2_report_round_trips_comments_and_cards() -> None:
    report = _fixture_report().model_copy(
        update={
            "schema_version": 2,
            "comments": [
                ReportComment(
                    comment_id="12345", author="user_001", text="hello 😂", likes=3, card=_card()
                ),
                ReportComment(comment_id="12346", author="user_002", text="no card"),
            ],
            "profile_card": _card("reports/wf_contract_001/cards/profile.png"),
        }
    )
    restored = TikTokSourceReport.model_validate_json(report.model_dump_json())
    assert restored == report
    assert restored.comments[1].card is None


@pytest.mark.parametrize(
    "location", ["/reports/wf/cards/profile.png", "reports/../../outside/profile.png"]
)
def test_card_artifact_rejects_unsafe_locations(location: str) -> None:
    with pytest.raises(ValidationError):
        _card(location)


@pytest.mark.parametrize("size", [0, MAX_CARD_BYTES + 1])
def test_card_artifact_rejects_out_of_range_sizes(size: int) -> None:
    with pytest.raises(ValidationError):
        CardArtifact(
            location=PurePosixPath("reports/wf/cards/profile.png"),
            bytes=size,
            checksum="sha256:" + "b" * 64,
            width=300,
            height=80,
        )


def test_report_rejects_more_than_fifty_comments() -> None:
    payload = json.loads(_fixture_report().model_dump_json())
    payload["comments"] = [
        {"comment_id": str(10_000 + index), "author": "user_001", "text": "x"}
        for index in range(51)
    ]
    with pytest.raises(ValidationError):
        TikTokSourceReport.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("comments", [{"comment_id": "12345", "author": "user_001", "text": "x"}]),
        (
            "profile_card",
            {
                "location": "reports/wf/cards/profile.png",
                "bytes": 4_000,
                "checksum": "sha256:" + "b" * 64,
                "width": 300,
                "height": 80,
            },
        ),
    ],
    ids=["comments", "profile_card"],
)
def test_v1_report_rejects_v2_enrichment(field: str, value: object) -> None:
    payload = json.loads(_fixture_report().model_dump_json())
    assert payload["schema_version"] == 1
    payload[field] = value
    with pytest.raises(ValidationError, match="schema_version 1"):
        TikTokSourceReport.model_validate_json(json.dumps(payload))


def test_report_comment_rejects_image_bytes() -> None:
    with pytest.raises(ValidationError):
        ReportComment.model_validate(
            {"comment_id": "12345", "author": "user_001", "text": "x", "card_png": b"\x89PNG"}
        )
