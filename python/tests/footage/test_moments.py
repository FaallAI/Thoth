"""Moments in a long video, found by its captions (footage library spec 2026-11-15, 4.4)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from thoth_control_plane.footage.moments import parse_json3, pick_moments, section

CAPTIONS = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "footage"
    / "context"
    / "podcast_captions.json3"
).read_bytes()


def test_the_podcast_captions_parse() -> None:
    lines = parse_json3(CAPTIONS)
    assert len(lines) > 250
    assert lines[0].start < 10
    assert lines[0].text == "Bang Densu pasti ngeremehin gua karena"


def test_moments_need_a_name_and_skip_the_intro() -> None:
    moments = pick_moments(parse_json3(CAPTIONS), ["mutan", "denny sumargo"], ["podcast"])
    assert 1 <= len(moments) <= 3
    assert all(moment >= 30 for moment in moments)
    assert all(b - a >= 60 for a, b in pairwise(moments))
    assert moments == sorted(moments)
    assert abs(moments[0] - 165.4) <= 5


def test_no_name_no_moment() -> None:
    assert pick_moments(parse_json3(CAPTIONS), ["rocky gerung"], ["podcast"]) == []


def test_a_section_is_eight_seconds_from_a_second_before() -> None:
    assert section(165.4) == (164.4, 172.4)
    assert section(0.5) == (0, 8)


def test_broken_captions_give_no_lines() -> None:
    assert parse_json3(b"not json") == []
    assert parse_json3(b'{"events": [{"tStartMs": 1000}]}') == []


class _Client:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info

    async def extract(self, url: str, *, comments: bool) -> dict[str, object]:
        return self.info


async def test_the_fetcher_takes_the_json3_track_in_the_language() -> None:
    import httpx

    from thoth_control_plane.footage.adapters.captions import YtDlpCaptionFetcher

    info = {
        "automatic_captions": {
            "en": [{"ext": "json3", "url": "https://captions/en"}],
            "id": [
                {"ext": "srv1", "url": "https://captions/id-srv1"},
                {"ext": "json3", "url": "https://captions/id"},
            ],
        }
    }
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return httpx.Response(200, content=CAPTIONS)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = YtDlpCaptionFetcher(_Client(info), http)  # type: ignore[arg-type]
    assert await fetcher.captions("https://youtu.be/x", "id") == CAPTIONS
    assert fetched == ["https://captions/id"]
    assert await YtDlpCaptionFetcher(_Client({}), http).captions("u", "id") is None  # type: ignore[arg-type]
