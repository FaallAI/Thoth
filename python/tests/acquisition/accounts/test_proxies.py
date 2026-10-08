"""Proxy list parsing for the pool; no network."""

from __future__ import annotations

import pytest

from thoth_control_plane.acquisition.accounts.proxies import (
    MAX_PROXY_BYTES,
    MAX_PROXY_LINES,
    ProxyImportError,
    parse_proxy,
    parse_proxy_list,
)

PASSWORD = "pr0xy-pa55"


@pytest.mark.parametrize(
    ("line", "url", "display"),
    [
        (
            f"http://user:{PASSWORD}@1.2.3.4:8080",
            f"http://user:{PASSWORD}@1.2.3.4:8080",
            "1.2.3.4:8080",
        ),
        (
            "HTTPS://Proxy.Example.Test:443/",
            "https://proxy.example.test:443",
            "proxy.example.test:443",
        ),
        ("socks5://10.0.0.1:1080", "socks5://10.0.0.1:1080", "10.0.0.1:1080"),
        ("http://[2001:db8::1]:3128", "http://[2001:db8::1]:3128", "[2001:db8::1]:3128"),
        (
            "  http://u:p@gw.example.test:7000  ",
            "http://u:p@gw.example.test:7000",
            "gw.example.test:7000",
        ),
    ],
)
def test_valid_proxies_normalize_and_display_host_and_port_only(
    line: str, url: str, display: str
) -> None:
    entry = parse_proxy(line)
    assert entry is not None
    assert (entry.url, entry.display) == (url, display)
    assert PASSWORD not in entry.display


@pytest.mark.parametrize(
    "line",
    [
        "1.2.3.4:8080",
        "ftp://1.2.3.4:21",
        "http://1.2.3.4",
        "http://1.2.3.4:0",
        "http://1.2.3.4:99999",
        "http://:8080",
        "http://1.2.3.4:8080/path",
        "http://1.2.3.4:8080?x=1",
        "http://user@1.2.3.4:8080",
        "socks5://user:pass@1.2.3.4:1080",
        "not a url",
    ],
)
def test_anything_else_is_invalid(line: str) -> None:
    assert parse_proxy(line) is None


def test_a_list_skips_comments_blanks_and_repeats_and_numbers_bad_lines() -> None:
    text = "\n".join(
        [
            "# my proxies",
            f"http://user:{PASSWORD}@1.2.3.4:8080",
            "",
            f"secret-garbage-{PASSWORD}",
            "socks5://10.0.0.1:1080",
            f"http://user:{PASSWORD}@1.2.3.4:8080",
        ]
    )
    result = parse_proxy_list(text)
    assert [entry.display for entry in result.entries] == ["1.2.3.4:8080", "10.0.0.1:1080"]
    assert result.invalid_lines == (4,)


@pytest.mark.parametrize(
    "text",
    ["x" * (MAX_PROXY_BYTES + 1), "\n".join(["http://1.2.3.4:8080"] * (MAX_PROXY_LINES + 1))],
)
def test_an_oversized_list_is_refused_whole(text: str) -> None:
    with pytest.raises(ProxyImportError) as caught:
        parse_proxy_list(text)
    assert caught.value.code == "invalid_proxy_file"


@pytest.mark.parametrize(
    ("line", "url"),
    [
        ("http://user:p@ss:w@1.2.3.4:8080", "http://user:p%40ss%3Aw@1.2.3.4:8080"),
        ("http://user:p%40ss@1.2.3.4:8080", "http://user:p%40ss@1.2.3.4:8080"),
        ("http://us%3Aer:pass@1.2.3.4:8080", "http://us%3Aer:pass@1.2.3.4:8080"),
    ],
)
def test_credentials_are_percent_encoded_once(line: str, url: str) -> None:
    entry = parse_proxy(line)
    assert entry is not None
    assert (entry.url, entry.display) == (url, "1.2.3.4:8080")
