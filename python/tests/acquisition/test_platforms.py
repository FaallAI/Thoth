"""URL-to-platform routing is pure and conservative."""

from __future__ import annotations

import pytest

from thoth_control_plane.acquisition.platforms import platform_of, platform_support


@pytest.mark.parametrize(
    ("url", "support"),
    [
        ("https://www.facebook.com/story.php?id=1", "unsupported"),
        ("https://m.facebook.com/watch/?v=1", "unsupported"),
        ("https://WEB.Facebook.COM./reel/1", "unsupported"),
        ("https://fb.watch/abc/", "unsupported"),
        ("https://fb.com/x", "unsupported"),
        ("https://old.reddit.com/r/x/comments/abc/", "unsupported"),
        ("https://redd.it/abc", "unsupported"),
        ("https://notfacebook.com/x", "legacy"),
        ("https://x.com/a/status/1", "python"),
        ("https://twitter.com/a/status/1", "python"),
        ("https://www.twitter.com/a/status/1", "python"),
        ("https://mobile.twitter.com/a/status/1", "python"),
        ("https://mobile.x.com/a/status/1", "python"),
        ("https://X.COM./a/status/1", "python"),
        ("https://t.co/abc", "legacy"),
        ("https://notx.com/a/status/1", "legacy"),
        ("https://www.youtube.com/watch?v=abc", "python"),
        ("https://m.youtube.com/watch?v=abc", "python"),
        ("https://youtu.be/abc", "python"),
        ("https://music.youtube.com/watch?v=abc", "legacy"),
        ("https://vimeo.com/123", "legacy"),
        ("https://example.test/post", "legacy"),
        ("https://[::1", "legacy"),
        ("https://www.tiktok.com/@a/video/1234567", "python"),
        ("https://m.tiktok.com/@a/video/1234567", "python"),
        ("https://vm.tiktok.com/ZMabc/", "python"),
        ("https://vt.tiktok.com/ZSabc/", "python"),
        ("https://www.threads.net/@a/post/B", "python"),
        ("https://threads.com/@a/post/B", "python"),
        ("https://www.Threads.COM./@a/post/B", "python"),
        ("https://www.instagram.com/p/abc/", "python"),
        ("https://instagram.com/reel/abc/", "python"),
        ("https://m.instagram.com/p/abc/", "python"),
        ("https://WWW.Instagram.COM./p/abc/", "python"),
        ("https://instagr.am/p/abc/", "legacy"),
    ],
)
def test_platform_support_classifies_hosts(url: str, support: str) -> None:
    assert platform_support(url) == support


def test_platform_of_names_python_platforms_only() -> None:
    assert platform_of("https://www.tiktok.com/@a/video/1234567") == "tiktok"
    assert platform_of("https://www.threads.net/@a/post/B") == "threads"
    assert platform_of("https://www.instagram.com/p/abc/") == "instagram"
    assert platform_of("https://x.com/a/status/1") == "x"
    assert platform_of("https://www.youtube.com/watch?v=abc") == "youtube"
    assert platform_of("https://vimeo.com/123") is None
    assert platform_of("https://www.facebook.com/x") is None
    assert platform_of("not a url") is None
