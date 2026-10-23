"""X URL identity and the pure syndication and page parsers; no network."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.x import (
    XPageParse,
    XPostIdentity,
    XUrlError,
    canonicalize_x_post_url,
    parse_syndication,
    post_url,
    with_page,
)

POST_ID = "1800000000000000001"
IDENTITY = XPostIdentity(post_id=POST_ID)


def _synd(**extra: Any) -> dict[str, Any]:
    return {
        "__typename": "Tweet",
        "id_str": POST_ID,
        "text": "@someone hello world https://t.co/abc",
        "display_text_range": [9, 20],
        "created_at": "2024-05-01T12:34:56.000Z",
        "favorite_count": 1200,
        "conversation_count": 34,
        "user": {"screen_name": "user_001"},
        **extra,
    }


def _urls(parsed) -> list[str]:
    return [item.ephemeral_url.get_secret_value() for item in parsed.media]


@pytest.mark.parametrize(
    "url",
    [
        f"https://x.com/user_001/status/{POST_ID}",
        f"https://twitter.com/user_001/status/{POST_ID}?s=20&t=abc",
        f"https://mobile.twitter.com/user_001/statuses/{POST_ID}/",
        f"https://www.x.com/i/web/status/{POST_ID}",
        f"https://x.com/i/status/{POST_ID}#frag",
        f"https://x.com/user_001/status/{POST_ID}/photo/2",
        f"https://X.COM./user_001/status/{POST_ID}/video/1",
        f"https://mobile.x.com/user_001/status/{POST_ID}",
    ],
)
def test_post_url_shapes_canonicalize(url: str) -> None:
    assert canonicalize_x_post_url(url) == IDENTITY


@pytest.mark.parametrize(
    "url",
    [
        f"http://x.com/user_001/status/{POST_ID}",
        "https://x.com/user_001",
        "https://x.com/user_001/status/abc",
        f"https://evil.example/user_001/status/{POST_ID}",
        f"https://x.com:8443/user_001/status/{POST_ID}",
        f"https://user@x.com/user_001/status/{POST_ID}",
        "https://t.co/abc",
        f"https://x.com/a_handle_longer_than_fifteen/status/{POST_ID}",
        f"https://x.com/user_001/status/{POST_ID}/photo/9",
        "https://x.com/user_001/status/12345678901234567890",
        "not a url",
    ],
)
def test_non_post_urls_are_rejected(url: str) -> None:
    with pytest.raises(XUrlError):
        canonicalize_x_post_url(url)


def test_post_url_is_rebuilt_from_the_author() -> None:
    assert post_url("user_001", POST_ID) == f"https://x.com/user_001/status/{POST_ID}"


def test_syndication_parses_text_counts_and_date() -> None:
    parsed = parse_syndication(_synd(), IDENTITY)
    assert parsed is not None
    assert parsed.post.post_id == POST_ID
    assert parsed.post.owner_handle == "user_001"
    assert parsed.post.text == "hello world"
    assert parsed.post.engagement == {"like": 1200, "comment": 34}
    assert parsed.post.published_at == "2024-05-01T12:34:56Z"
    assert parsed.media == []
    assert parsed.long_text is False


def test_photos_keep_order_and_take_the_original() -> None:
    details = [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/a.jpg"},
        {"type": "photo", "media_url_https": "http://pbs.twimg.com/media/skip.jpg"},
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/b.png?format=png"},
        "not a dict",
    ]
    parsed = parse_syndication(_synd(mediaDetails=details), IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["image", "image"]
    assert _urls(parsed) == [
        "https://pbs.twimg.com/media/a.jpg?name=orig",
        "https://pbs.twimg.com/media/b.png?format=png",
    ]


def test_a_single_video_takes_the_largest_syndication_variant() -> None:
    variants = [
        {"type": "application/x-mpegURL", "src": "https://video.twimg.com/a.m3u8"},
        {"type": "video/mp4", "src": "https://video.twimg.com/vid/avc1/480x270/a.mp4"},
        {"type": "video/mp4", "src": "https://video.twimg.com/vid/avc1/1280x720/b.mp4"},
        {"type": "video/mp4", "src": "http://video.twimg.com/vid/avc1/1920x1080/c.mp4"},
    ]
    data = _synd(mediaDetails=[{"type": "video"}], video={"variants": variants})
    parsed = parse_syndication(data, IDENTITY)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["video"]
    assert _urls(parsed) == ["https://video.twimg.com/vid/avc1/1280x720/b.mp4"]


def test_page_videos_fill_several_videos_in_order() -> None:
    details = [
        {"type": "video"},
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/a.jpg"},
        {"type": "animated_gif"},
    ]
    page_videos = ["https://video.twimg.com/1.mp4", "https://video.twimg.com/2.mp4"]
    parsed = parse_syndication(_synd(mediaDetails=details), IDENTITY, page_videos)
    assert parsed is not None
    assert [item.kind for item in parsed.media] == ["video", "image", "video"]
    assert _urls(parsed) == [
        "https://video.twimg.com/1.mp4",
        "https://pbs.twimg.com/media/a.jpg?name=orig",
        "https://video.twimg.com/2.mp4",
    ]


def test_each_video_entry_takes_its_own_variants_without_the_page() -> None:
    # Live 2026-10-23: syndication lists every video's renditions per entry
    # (mediaDetails[].video_info.variants); the top-level `video` carries the first only.
    def entry(name: str) -> dict[str, Any]:
        variants = [
            {
                "content_type": "application/x-mpegURL",
                "url": f"https://video.twimg.com/{name}.m3u8",
            },
            {
                "content_type": "video/mp4",
                "url": f"https://video.twimg.com/{name}/vid/320x568/a.mp4",
            },
            {
                "content_type": "video/mp4",
                "url": f"https://video.twimg.com/{name}/vid/480x852/b.mp4",
            },
        ]
        return {"type": "video", "video_info": {"variants": variants}}

    data = _synd(mediaDetails=[entry("one"), entry("two")])
    urls = _urls(parse_syndication(data, IDENTITY))
    assert urls == [
        "https://video.twimg.com/one/vid/480x852/b.mp4",
        "https://video.twimg.com/two/vid/480x852/b.mp4",
    ]


def test_a_video_with_no_url_is_skipped() -> None:
    lone = {"variants": [{"type": "video/mp4", "src": "https://video.twimg.com/x.mp4"}]}
    data = _synd(mediaDetails=[{"type": "video"}, {"type": "video"}], video=lone)
    # Two videos: the lone syndication variant names neither, so only page URLs count.
    assert parse_syndication(data, IDENTITY).media == []
    one = parse_syndication(data, IDENTITY, ["https://video.twimg.com/1.mp4"])
    assert _urls(one) == ["https://video.twimg.com/1.mp4"]


def test_a_long_tweet_is_flagged() -> None:
    parsed = parse_syndication(_synd(note_tweet={"id": "n1"}), IDENTITY)
    assert parsed is not None
    assert parsed.long_text is True


@pytest.mark.parametrize(
    "data",
    [
        {"__typename": "TweetTombstone"},
        _synd(id_str="1"),
        _synd(user={"screen_name": "bad name"}),
        _synd(user={}),
        "not a dict",
        None,
    ],
)
def test_tombstone_other_id_and_bad_author_are_no_parse(data: object) -> None:
    assert parse_syndication(data, IDENTITY) is None


def test_a_bad_display_range_keeps_the_whole_text() -> None:
    parsed = parse_syndication(_synd(display_text_range=["a", 3]), IDENTITY)
    assert parsed is not None
    assert parsed.post.text == "@someone hello world https://t.co/abc"


def test_bad_dates_and_counts_are_skipped() -> None:
    parsed = parse_syndication(_synd(created_at="nope", favorite_count=-1), IDENTITY)
    assert parsed is not None
    assert parsed.post.published_at is None
    assert parsed.post.engagement == {"comment": 34}


def test_with_page_adds_views_reposts_and_the_long_text() -> None:
    page = XPageParse(
        engagement={"like": 1, "comment": 1, "share": 2, "play": 4500},
        text="the whole long text",
    )
    long_parse = parse_syndication(_synd(note_tweet={"id": "n1"}), IDENTITY)
    merged = with_page(long_parse, page)
    assert merged.post.engagement == {"like": 1200, "comment": 34, "share": 2, "play": 4500}
    assert merged.post.text == "the whole long text"
    short = with_page(parse_syndication(_synd(), IDENTITY), page)
    assert short.post.text == "hello world"


def test_the_display_range_counts_utf16_units() -> None:
    # X counts UTF-16 code units: each emoji is two, so a code-point slice overruns.
    text = "hi 😀😀 there https://t.co/abc"
    data = _synd(text=text, display_text_range=[0, 13])
    assert parse_syndication(data, IDENTITY).post.text == "hi 😀😀 there"


def test_html_entities_are_unescaped_after_slicing() -> None:
    text = "@someone fish &amp; chips &lt;3 https://t.co/abc"
    # The range counts the unescaped text: "fish & chips <3" is 15 units long.
    parsed = parse_syndication(_synd(text=text, display_text_range=[9, 24]), IDENTITY)
    assert parsed.post.text == "fish & chips <3"
