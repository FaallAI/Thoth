"""yt-dlp freshness: version comparison and the PyPI check over a fake fetch; no network."""

from __future__ import annotations

import logging

import pytest

from thoth_control_plane.operations.yt_dlp_version import (
    check_freshness,
    is_behind,
    latest_from_pypi,
    parse_version,
)


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("2026.8.19", (2026, 8, 19)),
        ("2026.08.19", (2026, 8, 19)),
        ("2026.08.19.1", (2026, 8, 19, 1)),
        ("2026.8", None),
        ("2026.8.19rc1", None),
        ("v2026.8.19", None),
        (None, None),
    ],
)
def test_parse_version(text: object, parsed: tuple[int, ...] | None) -> None:
    assert parse_version(text) == parsed


@pytest.mark.parametrize(
    ("installed", "latest", "behind"),
    [
        ("2026.8.19", "2026.9.1", True),
        ("2026.08.19", "2026.8.19", False),
        ("2026.8.19", "2026.8.19.1", True),
        ("2026.9.1", "2026.8.19", False),
        ("2026.8.19", "garbage", False),
    ],
)
def test_is_behind(installed: str, latest: str, behind: bool) -> None:
    assert is_behind(installed, latest) is behind


def test_latest_from_pypi_reads_info_version() -> None:
    assert latest_from_pypi({"info": {"version": "2026.9.1"}}) == "2026.9.1"
    assert latest_from_pypi({"info": {"version": "nope"}}) is None
    assert latest_from_pypi([]) is None


def _fetch(payload: object):
    async def fetch(url: str) -> object:
        assert url == "https://pypi.org/pypi/yt-dlp/json"
        if isinstance(payload, Exception):
            raise payload
        return payload

    return fetch


@pytest.mark.asyncio
async def test_a_stale_install_warns_with_both_versions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    fetch = _fetch({"info": {"version": "2026.9.1"}})
    assert await check_freshness(fetch, installed="2026.8.19") is True
    assert "installed=2026.8.19 latest=2026.9.1" in caplog.text


@pytest.mark.asyncio
async def test_a_current_install_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    assert await check_freshness(_fetch({"info": {"version": "2026.8.19"}}), "2026.8.19") is False
    assert "behind" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [RuntimeError("offline"), {"info": {}}])
async def test_an_unknown_answer_never_raises(payload: object) -> None:
    assert await check_freshness(_fetch(payload), installed="2026.8.19") is None
