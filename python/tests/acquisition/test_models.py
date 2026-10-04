import json
from pathlib import Path, PurePosixPath

import pytest
from pydantic import SecretStr, TypeAdapter, ValidationError

from thoth_control_plane.acquisition.models import (
    MAX_CARD_BYTES,
    AcquisitionAttempt,
    AcquisitionFailure,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    AttemptStatus,
    BrowserSnapshot,
    CardArtifact,
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryReason,
    DiscoveryRequest,
    DiscoveryResult,
    KeywordDiscovery,
    MaterializedMedia,
    ProfileDiscovery,
    ReportComment,
    ResolvedMedia,
    SourceReport,
    TikTokPost,
    TikTokSourceReport,
    TrendingDiscovery,
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
        AcquisitionResult()
    with pytest.raises(ValidationError):
        AcquisitionResult(
            report=SourceReport.model_validate_json(
                (
                    Path(__file__).resolve().parent.parent
                    / "fixtures"
                    / "tiktok"
                    / "source_report_v3.json"
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
    failure = AcquisitionFailure(code="cdn_unavailable", retryable=True, attempts=attempts)

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
        AcquisitionFailure(code="headless_timeout", retryable=True, attempts=[attempt] * 4)


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


DISCOVERY_REQUEST = TypeAdapter(DiscoveryRequest)
VIDEO_URL = "https://www.tiktok.com/@creator/video/1000000001"


def test_discovery_request_is_discriminated_by_kind() -> None:
    profile = DISCOVERY_REQUEST.validate_python({"kind": "profile", "handle": "creator"})
    keyword = DISCOVERY_REQUEST.validate_python({"kind": "keyword", "query": "  cats  "})
    trending = DISCOVERY_REQUEST.validate_python({"kind": "trending", "limit": 5})

    assert isinstance(profile, ProfileDiscovery) and profile.limit == 30
    assert isinstance(keyword, KeywordDiscovery) and keyword.query == "cats"
    assert isinstance(trending, TrendingDiscovery) and trending.limit == 5
    with pytest.raises(ValidationError):
        DISCOVERY_REQUEST.validate_python({"kind": "hashtag"})


@pytest.mark.parametrize("query", ["", "   ", "cats\ndogs", "tab\there", "x" * 101])
def test_keyword_query_rejects_blank_control_and_oversized_text(query: str) -> None:
    with pytest.raises(ValidationError):
        KeywordDiscovery(query=query)


def test_keyword_query_keeps_punctuation_and_emoji() -> None:
    query = "anak & kucing/2 \U0001f63a"
    assert KeywordDiscovery(query=query).query == query


def test_keyword_query_is_stripped_before_its_length_is_checked() -> None:
    assert KeywordDiscovery(query="  " + "x" * 100 + "  ").query == "x" * 100


@pytest.mark.parametrize("field", ["ads", "photo_posts", "invalid"])
def test_discovery_drops_are_never_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveryDrops(**{field: -1})


@pytest.mark.parametrize(
    "published_at", ["", "yesterday", "2024-03-01", "2024-03-01T10:00:00", "2024-03-01 10:00:00Z"]
)
def test_publication_time_must_be_iso_utc_seconds(published_at: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveredVideo(
            post_id="1000000001",
            owner_handle="creator",
            canonical_url=VIDEO_URL,
            published_at=published_at,
        )
    payload = _fixture_report().model_dump(mode="json")
    payload["post"]["published_at"] = published_at
    with pytest.raises(ValidationError):
        TikTokSourceReport.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("limit", [0, 101])
def test_discovery_limit_is_bounded(limit: int) -> None:
    with pytest.raises(ValidationError):
        TrendingDiscovery(limit=limit)


@pytest.mark.parametrize("handle", ["", "bad handle", "a/b", "x" * 65])
def test_profile_discovery_rejects_invalid_handles(handle: str) -> None:
    with pytest.raises(ValidationError):
        ProfileDiscovery(handle=handle)


def test_discovered_video_rejects_unknown_engagement_keys() -> None:
    with pytest.raises(ValidationError):
        DiscoveredVideo(
            post_id="1000000001",
            owner_handle="creator",
            canonical_url=VIDEO_URL,
            engagement={"views": 1},
        )


@pytest.mark.parametrize("hashtag", ["", "x" * 101])
def test_discovered_video_rejects_empty_or_oversized_hashtags(hashtag: str) -> None:
    with pytest.raises(ValidationError):
        DiscoveredVideo(
            post_id="1000000001",
            owner_handle="creator",
            canonical_url=VIDEO_URL,
            hashtags=[hashtag],
        )


def test_partial_discovery_result_round_trips_through_json() -> None:
    video = DiscoveredVideo(
        post_id="1000000001",
        owner_handle="creator",
        canonical_url=VIDEO_URL,
        published_at="2024-03-01T10:00:00Z",
        duration_seconds=15.0,
        engagement={"play": 1, "like": 2},
        hashtags=["cats"],
    )
    result = DiscoveryResult(
        kind="keyword",
        videos=[video],
        pages=1,
        exhausted=False,
        drops=DiscoveryDrops(ads=1),
        reason=DiscoveryReason.CAPTCHA,
    )

    dumped = result.model_dump_json()

    assert json.loads(dumped)["reason"] == "captcha"
    assert DiscoveryResult.model_validate_json(dumped) == result


@pytest.mark.parametrize("schema_version", [1, 2])
def test_reports_carry_publication_time_and_engagement(schema_version: int) -> None:
    payload = _fixture_report().model_dump(mode="json")
    payload["schema_version"] = schema_version
    payload["post"].update(published_at="2024-03-01T10:00:00Z", engagement={"play": 7, "like": 2})

    report = TikTokSourceReport.model_validate_json(json.dumps(payload))

    assert report.post.published_at == "2024-03-01T10:00:00Z"
    assert report.post.engagement == {"play": 7, "like": 2}


_CHECKSUM = "sha256:" + "0" * 64


def _media(index: int, kind: str, media_type: str, bytes_: int) -> MaterializedMedia:
    suffix = {"video/mp4": "mp4", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    return MaterializedMedia(
        media_id=f"media_{index}",
        kind=kind,
        index=index,
        location=PurePosixPath(f"reports/wf_contract_001/media/m{index}.{suffix[media_type]}"),
        media_type=media_type,
        bytes=bytes_,
        checksum=_CHECKSUM,
        # Enum member, not the raw string literal from the plan brief: `StrictModel`
        # (unrelated to this task, out of scope to change) sets `strict=True`, which
        # rejects raw strings for enum-typed fields with an `is_instance_of` error,
        # same substitution already ledgered above for `AcquisitionAttempt`.
        acquisition_strategy=AcquisitionStrategy.SCRAPLING_REQUEST,
    )


def _image(index: int, bytes_: int = 5_000, media_type: str = "image/jpeg") -> MaterializedMedia:
    return _media(index, "image", media_type, bytes_)


def _v3(**overrides: object) -> SourceReport:
    data: dict[str, object] = {
        "workflow_id": "wf_contract_001",
        "source": {
            "platform": "threads",
            "canonical_url": "https://www.threads.com/@user_001/post/code_001",
        },
        "post": {"post_id": "code_001", "owner_handle": "user_001", "text": "hello"},
        "media": [],
        "outcome": {
            "attempts": [
                {
                    # Enum members, not the plan brief's raw string literals; see the
                    # `_media` comment above for why.
                    "strategy": AcquisitionStrategy.SCRAPLING_REQUEST,
                    "status": AttemptStatus.SUCCEEDED,
                    "attempt_count": 1,
                    "elapsed_ms": 5,
                }
            ]
        },
    }
    data.update(overrides)
    return SourceReport.model_validate(data)


def test_v3_accepts_a_text_only_post() -> None:
    report = _v3()
    assert report.schema_version == 3
    assert report.media == []
    assert report.post_card is None


def test_v3_accepts_ordered_images() -> None:
    report = _v3(media=[_image(1), _image(2, media_type="image/png")])
    assert [item.index for item in report.media] == [1, 2]


def test_v3_report_accepts_an_instagram_source() -> None:
    report = _v3(
        source={"platform": "instagram", "canonical_url": "https://www.instagram.com/p/code_001/"}
    )
    assert report.source.platform == "instagram"


def test_v3_report_accepts_an_x_source() -> None:
    report = _v3(source={"platform": "x", "canonical_url": "https://x.com/user_001/status/1"})
    assert report.source.platform == "x"


def test_v3_rejects_a_post_with_neither_text_nor_media() -> None:
    with pytest.raises(ValidationError):
        _v3(post={"post_id": "code_001", "owner_handle": "user_001", "text": "  \n "})


@pytest.mark.parametrize("indexes", [[2], [1, 1], [2, 1]])
def test_v3_rejects_out_of_order_media(indexes: list[int]) -> None:
    with pytest.raises(ValidationError):
        _v3(media=[_image(index) for index in indexes])


def test_v3_rejects_more_than_twenty_media() -> None:
    with pytest.raises(ValidationError):
        _v3(media=[_image(index) for index in range(1, 22)])


@pytest.mark.parametrize(
    "post",
    [
        {"post_id": "code/001", "owner_handle": "user_001", "text": "x"},
        {"post_id": "code_001", "owner_handle": "user_001", "text": "x" * 50_001},
    ],
)
def test_v3_rejects_unsafe_post_fields(post: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _v3(post=post)


@pytest.mark.parametrize(
    ("kind", "media_type", "bytes_"),
    [
        ("image", "image/jpeg", 999),
        ("image", "image/jpeg", 20 * 1024 * 1024 + 1),
        ("image", "video/mp4", 5_000),
        ("video", "image/jpeg", 20_000),
        ("video", "video/mp4", 5_000),
    ],
)
def test_materialized_media_bounds_follow_the_kind(kind: str, media_type: str, bytes_: int) -> None:
    with pytest.raises(ValidationError):
        _media(1, kind, media_type, bytes_)


def test_v1_and_v2_reports_still_reject_images() -> None:
    payload = json.loads(FIXTURE_REPORT.read_text(encoding="utf-8"))
    payload["media"] = [_image(1).model_dump(mode="json")]
    with pytest.raises(ValidationError):
        TikTokSourceReport.model_validate(payload)


@pytest.mark.parametrize(
    "code", ["invalid_source_url", "no_content", "request_blocked", "request_timeout"]
)
def test_neutral_failure_accepts_new_codes(code: str) -> None:
    assert AcquisitionFailure(code=code, retryable=False).code == code


def test_neutral_result_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValidationError):
        AcquisitionResult()
    with pytest.raises(ValidationError):
        AcquisitionResult(
            report=_v3(), failure=AcquisitionFailure(code="no_content", retryable=False)
        )
