"""X URL identity and the pure syndication and page parsers; no network."""

from __future__ import annotations

from typing import Any

import pytest

from thoth_control_plane.acquisition.adapters.x import (
    XPageParse,
    XPostIdentity,
    XUrlError,
    canonicalize_x_post_url,
    parse_page,
    parse_syndication,
    post_url,
    with_page,
)

POST_ID = "1800000000000000001"
PARENT_ID = "1700000000000000001"
C1, C2, C3 = "1800000000000000101", "1800000000000000102", "1800000000000000103"
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


def _tweet(
    rest_id: str,
    author: str = "fan_001",
    text: str = "a reply",
    reply_to: str | None = POST_ID,
    likes: int = 3,
    **extra: Any,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "__typename": "Tweet",
        "rest_id": rest_id,
        "core": {"user_results": {"result": {"core": {"screen_name": author}}}},
        "details": {"full_text": text, "created_at_ms": 1_714_566_896_000},
        "counts": {"favorite_count": likes, "reply_count": 1, "retweet_count": 2},
        "views": {"count": "4500"},
    }
    if reply_to is not None:
        node["reply_to_results"] = {"rest_id": reply_to}
    node.update(extra)
    return node


def _video_entity(url: str) -> dict[str, Any]:
    return {
        "type": "video",
        "video_info": {"variants": [{"content_type": "video/mp4", "url": url}]},
    }


POST_NODE = _tweet(
    POST_ID,
    author="user_001",
    text="@parent_01 hello world https://t.co/abc",
    reply_to=PARENT_ID,
    likes=1300,
    media_entities2=[_video_entity("https://video.twimg.com/vid/avc1/640x360/p.mp4")],
)


def _roots(*tweets: dict[str, Any]) -> list[object]:
    return [{"data": {"entries": [{"content": {"tweet": tweet}} for tweet in tweets]}}]


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


def test_page_takes_replies_to_the_post_never_the_parent() -> None:
    parent = _tweet(PARENT_ID, author="parent_01", text="the parent", reply_to=None)
    first = _tweet(C1, text="@user_001 a reply")
    second = _tweet(C2, author="fan_002", text="@user_001 @fan_001 thanks https://t.co/q")
    nested = _tweet(C3, author="fan_003", text="reply to a reply", reply_to=C1)
    page = parse_page(_roots(parent, POST_NODE, first, second, nested), IDENTITY)
    assert [(c.comment_id, c.author, c.text, c.likes) for c in page.comments] == [
        (C1, "fan_001", "a reply", 3),
        (C2, "fan_002", "thanks", 3),
    ]
    assert page.engagement == {"like": 1300, "comment": 1, "share": 2, "play": 4500}
    assert page.text == "hello world"
    assert page.videos == ["https://video.twimg.com/vid/avc1/640x360/p.mp4"]


def test_a_repeated_tweet_is_read_once() -> None:
    first = _tweet(C1)
    page = parse_page(_roots(POST_NODE, first, POST_NODE, _tweet(C1)), IDENTITY)
    assert [c.comment_id for c in page.comments] == [C1]


def test_cyclic_data_is_walked_once() -> None:
    root: dict[str, Any] = {"post": POST_NODE, "reply": _tweet(C1)}
    root["self"] = root
    page = parse_page([root], IDENTITY)
    assert [c.comment_id for c in page.comments] == [C1]
    assert page.engagement["like"] == 1300


def test_invalid_replies_are_dropped_and_counted() -> None:
    bad_author = _tweet(C1, author="bad name")
    only_mentions = _tweet(C2, text="@user_001 ")
    good = _tweet(C3, author="fan_003")
    page = parse_page(_roots(POST_NODE, bad_author, only_mentions, good), IDENTITY)
    assert [c.comment_id for c in page.comments] == [C3]
    assert page.dropped_comments == 2


def test_replies_cap_at_fifty() -> None:
    replies = [_tweet(str(1_800_000_000_000_001_000 + n)) for n in range(55)]
    page = parse_page(_roots(POST_NODE, *replies), IDENTITY)
    assert len(page.comments) == 50


def test_a_page_without_the_post_keeps_its_replies_only() -> None:
    assert parse_page([], IDENTITY) == XPageParse()
    page = parse_page(_roots(_tweet(C1)), IDENTITY)
    assert [c.comment_id for c in page.comments] == [C1]
    assert (page.engagement, page.text, page.videos) == ({}, None, [])


def test_a_long_tweet_on_the_page_uses_its_note_text() -> None:
    note = {"note_tweet_results": {"result": {"text": "the whole long text"}}}
    post = _tweet(POST_ID, author="user_001", text="the whole lo", reply_to=None, note_tweet=note)
    assert parse_page(_roots(post), IDENTITY).text == "the whole long text"


def test_unreadable_page_counters_are_skipped() -> None:
    post = _tweet(POST_ID, author="user_001", reply_to=None, views={"count": "n/a"})
    assert "play" not in parse_page(_roots(post), IDENTITY).engagement


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
    reply = _tweet(C1, text="@user_001 salt &amp; vinegar")
    assert parse_page(_roots(reply), IDENTITY).comments[0].text == "salt & vinegar"


def test_a_reply_with_a_non_numeric_id_is_dropped() -> None:
    # The report's comment id admits YouTube's string ids; X ids stay numeric.
    page = parse_page(_roots(POST_NODE, _tweet("abc12345")), IDENTITY)
    assert (page.comments, page.dropped_comments) == ([], 1)
