"""Discussions in a long video, found by its captions (footage library spec 2026-11-15, 9.3)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from thoth_control_plane.footage.moments import (
    CaptionLine,
    Chapter,
    HeatPoint,
    LongVideoHints,
    parse_chapters,
    parse_heatmap,
    parse_json3,
    pick_discussions,
    section,
)

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
    # "mutannya tretan" at 3:52 names the subject in its "nya" form (spec 10.5)
    assert any(230 <= d.moment <= 300 for d in found)  # mutan + pedang + USS, 3:52-5:00
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
    d = next(d for d in found if 230 <= d.moment <= 300)
    text = " ".join(str(line["text"]) for line in d.said)
    assert "mutannya" in text.lower()
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


def test_sections_are_cut_only_where_the_subject_is_named() -> None:  # spec 10.12, revision 2
    lines = [
        CaptionLine(100.0, "densu marah kursi pedang"),
        CaptionLine(110.0, "densu ngamuk pedang kursi diundang"),
        CaptionLine(200.0, "saiful datang bawa pedang"),
        CaptionLine(210.0, "marah kursi"),
    ]
    found = pick_discussions(lines, SUBJECT, OTHERS, WORDS)
    assert [d.moment for d in found] == [200.0]


# Footage sourcing v2 (spec 2026-11-27, 5.2): chapters and Most Replayed from the same metadata
# call, and a caption track in a nearby language.


def test_chapters_and_heat_points_parse_and_skip_malformed_items() -> None:
    chapters = parse_chapters(
        [
            {"start_time": 0, "end_time": 120.5, "title": "Pembukaan"},
            {"start_time": "x", "end_time": 10, "title": "t"},
            "bad",
            {"start_time": 50, "end_time": 30, "title": "backwards"},
            {"start_time": 10, "end_time": 20, "title": " "},
        ]
    )
    assert chapters == [Chapter(0.0, 120.5, "Pembukaan")]
    heat = parse_heatmap(
        [{"start_time": 0, "end_time": 10, "value": 0.2}, {"start_time": 10, "value": 1}, None]
    )
    assert heat == [HeatPoint(0.0, 10.0, 0.2)]
    assert parse_chapters(None) == [] and parse_heatmap({"a": 1}) == []


def _track(name: str) -> list[dict[str, str]]:
    return [{"ext": "json3", "url": f"https://captions/{name}"}]


def test_a_caption_track_is_chosen_by_language_before_source() -> None:
    from thoth_control_plane.footage.adapters.captions import _json3_url

    both = {"automatic_captions": {"en": _track("auto-en")}, "subtitles": {"id": _track("sub-id")}}
    assert _json3_url(both, "id") == "https://captions/sub-id"
    orig = {"automatic_captions": {"id-orig": _track("id-orig")}, "subtitles": {"en": _track("en")}}
    assert _json3_url(orig, "id") == "https://captions/id-orig"
    assert _json3_url({"automatic_captions": {"en-US": _track("en-US")}}, "id") == (
        "https://captions/en-US"
    )
    english = {"subtitles": {"en": _track("en")}, "automatic_captions": {"en-GB": _track("gb")}}
    assert _json3_url(english, "id") == "https://captions/en"
    assert _json3_url({"automatic_captions": {"fr": _track("fr")}}, "id") is None


class _Counting(_Client):
    def __init__(self, info: dict[str, object]) -> None:
        super().__init__(info)
        self.calls = 0

    async def extract(self, url: str, *, comments: bool) -> dict[str, object]:
        self.calls += 1
        assert comments is False
        return self.info


CHAPTERS = [{"start_time": 5400, "end_time": 5700, "title": "Pidato Pemenang"}]
HEAT = [{"start_time": 5500, "end_time": 5510, "value": 0.95}]


async def test_hints_come_from_one_metadata_call() -> None:
    import httpx

    from thoth_control_plane.footage.adapters.captions import YtDlpCaptionFetcher

    info = {"automatic_captions": {"id": _track("id")}, "chapters": CHAPTERS, "heatmap": HEAT}
    client = _Counting(info)
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=CAPTIONS))
    )
    hints = await YtDlpCaptionFetcher(client, http).hints("https://youtu.be/x", "id")  # type: ignore[arg-type]
    assert hints == LongVideoHints(
        CAPTIONS, [Chapter(5400.0, 5700.0, "Pidato Pemenang")], [HeatPoint(5500.0, 5510.0, 0.95)]
    )
    assert client.calls == 1


async def test_hints_keep_chapters_without_a_caption_track() -> None:
    from thoth_control_plane.footage.adapters.captions import YtDlpCaptionFetcher

    client = _Counting({"chapters": CHAPTERS, "heatmap": HEAT})
    fetcher = YtDlpCaptionFetcher(client)  # type: ignore[arg-type]
    hints = await fetcher.hints("https://youtu.be/x", "id")
    assert hints.captions is None and len(hints.chapters) == 1 and len(hints.heatmap) == 1
    assert await fetcher.captions("https://youtu.be/x", "id") is None
    assert client.calls == 2


def test_a_matching_chapter_lifts_a_window_over_the_score() -> None:
    lines = [CaptionLine(100.0, "pedang marah"), CaptionLine(130.0, "x")]
    assert pick_discussions(lines, [], [], ["pedang", "marah"]) == []
    chapters = [Chapter(90.0, 200.0, "Saat marah di panggung")]
    found = pick_discussions(lines, [], [], ["pedang", "marah"], chapters=chapters)
    assert [d.moment for d in found] == [100.0] and found[0].said


def test_a_replayed_peak_picks_the_moment_inside_a_window() -> None:
    lines = [CaptionLine(100.0, "mutan pedang marah"), CaptionLine(130.0, "mutan pedang marah")]
    words = ["pedang", "marah"]
    assert pick_discussions(lines, ["mutan"], [], words)[0].moment == 100.0
    heat = [HeatPoint(128.0, 135.0, 0.9)]
    assert pick_discussions(lines, ["mutan"], [], words, heatmap=heat)[0].moment == 130.0
    weak = [HeatPoint(128.0, 135.0, 0.5)]
    assert pick_discussions(lines, ["mutan"], [], words, heatmap=weak)[0].moment == 100.0


CEREMONY = [
    Chapter(0.0, 20.0, "Pidato pemenang pembuka"),  # ends inside the intro
    Chapter(3600.0, 3605.0, "Pidato pemenang singkat"),  # under 8 s
    Chapter(5400.0, 5700.0, "Pidato Pemenang Film Terbaik Para Perasuk"),
    Chapter(1200.0, 1500.0, "Pidato pemenang aktris terbaik"),
    Chapter(1230.0, 1400.0, "Pidato pemenang lagi"),  # a moment under a minute from 1206
    Chapter(2000.0, 2300.0, "Jeda iklan"),
]


def test_chapters_alone_give_safe_moments_in_time_order() -> None:
    words = ["pidato", "pemenang"]
    for lines in ([], [CaptionLine(100.0, "tidak ada yang cocok")]):
        found = pick_discussions(lines, [], [], words, chapters=CEREMONY)
        assert [d.moment for d in found] == [1206.0, 5406.0]
        assert all(d.said == [] for d in found)


def test_a_chapter_without_the_subject_is_no_moment() -> None:
    assert pick_discussions([], ["mutan"], [], ["pidato", "pemenang"], chapters=CEREMONY) == []


def test_a_chapter_moment_snaps_to_its_strongest_peak_inside_the_chapter() -> None:
    chapter = [Chapter(5400.0, 5700.0, "Pidato Pemenang")]
    heat = [HeatPoint(5500.0, 5510.0, 0.95), HeatPoint(5600.0, 5610.0, 0.5)]
    found = pick_discussions([], [], [], ["pidato", "pemenang"], chapters=chapter, heatmap=heat)
    assert [d.moment for d in found] == [5505.0]
    edge = [HeatPoint(5690.0, 5720.0, 0.99)]
    found = pick_discussions([], [], [], ["pidato", "pemenang"], chapters=chapter, heatmap=edge)
    assert [d.moment for d in found] == [5693.0]
    start, end = section(found[0].moment)
    assert start >= 5400.0 and end <= 5700.0
