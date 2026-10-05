"""YouTube URL identity and the pure yt-dlp info parsers; no network."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.youtube import (
    MAX_DOWNLOAD_BYTES,
    YouTubeIdentity,
    YouTubeUrlError,
    canonicalize_youtube_url,
    channel_candidates,
    parse_info,
    select_formats,
)

VIDEO_ID = "abcDEF123_-"
IDENTITY = YouTubeIdentity(
    canonical_url=f"https://www.youtube.com/watch?v={VIDEO_ID}", video_id=VIDEO_ID
)
MB = 1024 * 1024


def _comment(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"UgzComment{n:03d}",
        "parent": "root",
        "author": f"@fan_{n:03d}",
        "author_id": f"UCfan{n:03d}",
        "text": f"comment {n}",
        "like_count": n,
        **extra,
    }


def _info(**extra: Any) -> dict[str, Any]:
    return {
        "id": VIDEO_ID,
        "title": "A title",
        "description": "A description",
        "uploader_id": "@user_001",
        "channel_id": "UCuser001abcdefghijklmno",
        "timestamp": 1_714_566_896,
        "view_count": 4_500,
        "like_count": 120,
        "comment_count": 34,
        "duration": 600,
        "live_status": "not_live",
        "comments": [_comment(1), _comment(2)],
        **extra,
    }


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com/watch?v={VIDEO_ID}&t=42s&si=abc",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}/",
        f"https://youtu.be/{VIDEO_ID}?si=abc",
        f"https://WWW.YouTube.COM./watch?v={VIDEO_ID}#frag",
    ],
)
def test_video_url_shapes_canonicalize(url: str) -> None:
    assert canonicalize_youtube_url(url) == IDENTITY


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.youtube.com/watch?v={VIDEO_ID}",
        "https://www.youtube.com/@someone",
        "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
        f"https://www.youtube.com/{VIDEO_ID}",
        "https://www.youtube.com/watch?v=short",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&v=zzzzzzzzzzz",
        f"https://youtu.be/{VIDEO_ID}/extra",
        f"https://evil.example/watch?v={VIDEO_ID}",
        f"https://www.youtube.com:8443/watch?v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}",
        "not a url",
    ],
)
def test_non_video_urls_are_rejected(url: str) -> None:
    with pytest.raises(YouTubeUrlError):
        canonicalize_youtube_url(url)


def test_info_parses_text_counts_date_and_comments() -> None:
    parsed = parse_info(_info(), IDENTITY)
    assert parsed is not None
    assert parsed.post.post_id == VIDEO_ID
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.text == "A title\n\nA description"
    assert parsed.post.engagement == {"play": 4_500, "like": 120, "comment": 34}
    assert parsed.post.published_at == "2024-05-01T12:34:56Z"
    assert parsed.duration_seconds == 600.0
    assert parsed.channel_url == "https://www.youtube.com/channel/UCuser001abcdefghijklmno"


def test_a_channel_without_a_valid_id_is_reached_by_handle() -> None:
    parsed = parse_info(_info(channel_id="not-a-channel"), IDENTITY)
    assert parsed.channel_url == "https://www.youtube.com/@user_001"
    assert [(c.comment_id, c.author, c.text, c.likes) for c in parsed.comments] == [
        ("UgzComment001", "fan_001", "comment 1", 1),
        ("UgzComment002", "fan_002", "comment 2", 2),
    ]


def test_an_owner_without_a_handle_falls_back_to_the_channel_id() -> None:
    parsed = parse_info(_info(uploader_id=None), IDENTITY)
    assert parsed is not None
    assert parsed.post.owner_handle == "UCuser001abcdefghijklmno"


def test_a_comment_author_outside_the_pattern_falls_back_to_the_author_id() -> None:
    parsed = parse_info(_info(comments=[_comment(1, author="@名前")]), IDENTITY)
    assert [c.author for c in parsed.comments] == ["UCfan001"]


def test_replies_duplicates_and_invalid_comments() -> None:
    comments = [
        _comment(1),
        _comment(1),
        _comment(2, parent="UgzComment001"),
        _comment(3, text="   "),
        _comment(4, id="bad id"),
        _comment(5),
    ]
    parsed = parse_info(_info(comments=comments), IDENTITY)
    assert [c.comment_id for c in parsed.comments] == ["UgzComment001", "UgzComment005"]
    assert parsed.dropped_comments == 3


def test_comments_cap_at_fifty() -> None:
    parsed = parse_info(_info(comments=[_comment(n) for n in range(60)]), IDENTITY)
    assert len(parsed.comments) == 50


@pytest.mark.parametrize(
    "info",
    [
        _info(id="otherVideo1"),
        _info(live_status="is_live"),
        _info(live_status="is_upcoming"),
        _info(uploader_id="bad handle", channel_id=None),
        "not a dict",
    ],
)
def test_other_ids_unfinished_streams_and_bad_owners_are_no_parse(info: object) -> None:
    assert parse_info(info, IDENTITY) is None


def test_missing_counts_and_text_are_skipped() -> None:
    parsed = parse_info(
        _info(title=None, description="  ", view_count=None, like_count=-1, timestamp="x"),
        IDENTITY,
    )
    assert parsed is not None
    assert (parsed.post.text, parsed.post.engagement, parsed.post.published_at) == (
        "",
        {"comment": 34},
        None,
    )


def _video(fid: str, width: int, height: int, size: int | None, tbr: float = 1_000.0, **extra):
    return {
        "format_id": fid,
        "protocol": "https",
        "url": f"https://media.example.test/{fid}",
        "ext": "mp4",
        "vcodec": "avc1",
        "acodec": "none",
        "width": width,
        "height": height,
        "tbr": tbr,
        "filesize": size,
        **extra,
    }


AUDIO = {
    "format_id": "140",
    "protocol": "https",
    "url": "https://media.example.test/140",
    "ext": "m4a",
    "vcodec": "none",
    "acodec": "mp4a",
    "tbr": 128.0,
    "filesize": 10 * MB,
}


def test_the_highest_fitting_height_wins() -> None:
    formats = [
        _video("137", 1920, 1080, 200 * MB),
        _video("136", 1280, 720, 100 * MB),
        _video("313", 3840, 2160, 900 * MB),
        AUDIO,
    ]
    choice = select_formats(formats, 600.0)
    assert (choice.video_format, choice.audio_format, choice.short_side) == ("137", "140", 1080)
    assert choice.estimated_bytes == 210 * MB


def test_a_too_large_1080p_steps_down_to_720p_then_480p() -> None:
    formats = [
        _video("137", 1920, 1080, 600 * MB),
        _video("136", 1280, 720, 445 * MB),
        _video("135", 854, 480, 100 * MB),
        AUDIO,
    ]
    assert select_formats(formats, 600.0).video_format == "135"


def test_a_vertical_short_is_classed_by_its_short_side() -> None:
    formats = [_video("137", 1080, 1920, 20 * MB), _video("136", 720, 1280, 10 * MB), AUDIO]
    choice = select_formats(formats, 40.0)
    assert (choice.video_format, choice.short_side) == ("137", 1080)


def test_size_is_estimated_from_bitrate_when_undeclared() -> None:
    # 2,000 kbit/s for 600 s is 150,000,000 bytes; with 10 MB of audio it fits.
    formats = [_video("137", 1920, 1080, None, tbr=2_000.0), AUDIO]
    choice = select_formats(formats, 600.0)
    assert choice.estimated_bytes == 150_000_000 + 10 * MB


def test_hls_webm_and_unsized_formats_are_never_chosen() -> None:
    formats = [
        _video("hls", 1920, 1080, 10 * MB, protocol="m3u8_native"),
        _video("webm", 1920, 1080, 10 * MB, ext="webm"),
        _video("nosize", 1920, 1080, None, tbr=None),
        _video("135", 854, 480, 10 * MB),
        AUDIO,
    ]
    assert select_formats(formats, None).video_format == "135"


def test_nothing_fits_or_no_audio_is_no_choice() -> None:
    too_big = [_video("135", 854, 480, MAX_DOWNLOAD_BYTES), AUDIO]
    assert select_formats(too_big, 600.0) is None
    assert select_formats([_video("135", 854, 480, MB)], 600.0) is None
    assert select_formats("not a list", 600.0) is None


def test_channel_candidates_are_the_most_viewed_each_once() -> None:
    videos = {
        "entries": [{"id": "aaaaaaaaaaa", "view_count": 5}, {"id": "bbbbbbbbbbb", "view_count": 50}]
    }
    shorts = {
        "entries": [
            {"id": "ccccccccccc", "view_count": 500},
            {"id": "aaaaaaaaaaa", "view_count": 999},
            {"id": "bad", "view_count": 1},
            {"id": "ddddddddddd"},
        ]
    }
    assert channel_candidates([videos, shorts], 2) == ["ccccccccccc", "bbbbbbbbbbb"]


def test_an_unsized_top_format_falls_back_to_a_sized_one_at_its_height() -> None:
    # Without a duration, a bitrate alone gives no size; the sized formats still qualify.
    unsized_audio = {**AUDIO, "format_id": "140-drc", "tbr": 256.0, "filesize": None}
    formats = [
        _video("399", 1920, 1080, None, tbr=5_000.0),
        _video("137", 1920, 1080, 100 * MB, tbr=900.0),
        unsized_audio,
        AUDIO,
    ]
    choice = select_formats(formats, None)
    assert choice is not None
    assert (choice.video_format, choice.audio_format, choice.short_side) == ("137", "140", 1080)
