"""Discussions in a long video, found by its captions (footage library spec 2026-11-15, 9.3)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from thoth_control_plane.footage.moments import parse_json3, pick_discussions, section

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


SUBJECT = ["mutan", "saiful"]
OTHERS = ["denny sumargo", "densu", "aldi taher"]
WORDS = ["pedang", "marah", "kursi", "diundang", "ngamuk", "uss"]


def test_the_incident_discussion_is_found() -> None:
    found = pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, WORDS)
    assert any(240 <= d.moment <= 300 for d in found)  # mutan + pedang + USS, 4:05-5:00
    assert all(d.moment >= 30 for d in found)
    assert all(b.moment - a.moment >= 60 for a, b in pairwise(found))
    assert len(found) <= 3


def test_a_bare_name_mention_is_no_discussion() -> None:
    found = pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, WORDS)
    assert not any(560 <= d.moment <= 600 for d in found)  # "Aldi Taher" only


def test_names_without_words_give_nothing() -> None:
    assert pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, []) == []


def test_words_alone_work_without_people() -> None:  # Review Focus 1
    assert isinstance(pick_discussions(parse_json3(CAPTIONS), [], [], WORDS), list)


def test_said_holds_the_window_lines() -> None:
    found = pick_discussions(parse_json3(CAPTIONS), SUBJECT, OTHERS, WORDS)
    d = next(d for d in found if 240 <= d.moment <= 300)
    text = " ".join(str(line["text"]) for line in d.said)
    assert "pedang" in text.lower()
    assert len(text) <= 1500
    assert all(float(line["end_seconds"]) >= float(line["start_seconds"]) for line in d.said)


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


async def test_the_fetcher_retries_a_rate_limited_track_once() -> None:  # live wf_a91d3f0f
    import httpx

    from thoth_control_plane.footage.adapters.captions import YtDlpCaptionFetcher

    info = {"automatic_captions": {"id": [{"ext": "json3", "url": "https://captions/id"}]}}
    answers = iter([429, 200, 429, 429])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(answers), content=CAPTIONS)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = YtDlpCaptionFetcher(_Client(info), http, retry_seconds=0.0)  # type: ignore[arg-type]
    assert await fetcher.captions("https://youtu.be/x", "id") == CAPTIONS
    assert await fetcher.captions("https://youtu.be/x", "id") is None  # one retry only


def test_malformed_events_are_skipped() -> None:  # final review, Minor 5 raised to Important
    bad_time = b'{"events": [{"tStartMs": "x", "segs": [{"utf8": "Mutan"}]}]}'
    bad_segs = (
        b'{"events": [{"tStartMs": 1000, "segs": 5}, {"tStartMs": 2000, "segs": [{"utf8": "ok"}]}]}'
    )
    assert parse_json3(bad_time) == []
    assert [line.text for line in parse_json3(bad_segs)] == ["ok"]


def test_chosen_moments_are_a_minute_apart() -> None:  # final review, Important 8
    from thoth_control_plane.footage.moments import CaptionLine

    lines = [
        CaptionLine(121.0, "mutan"),
        CaptionLine(152.0, "mutan"),
        CaptionLine(168.0, "mutan marah kursi"),
        CaptionLine(203.0, "pedang marah"),
        CaptionLine(206.0, "pedang marah"),
        CaptionLine(215.0, "mutan"),
        CaptionLine(227.0, "x"),
    ]
    found = pick_discussions(lines, ["mutan"], [], ["pedang", "marah", "kursi"])
    assert found
    assert all(b.moment - a.moment >= 60 for a, b in pairwise(found))
