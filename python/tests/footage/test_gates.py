"""Footage text gates, ported from Scout's `build_footage.ts` and `footage_queries.ts`."""

from __future__ import annotations

from thoth_control_plane.acquisition.models import DiscoveredVideo
from thoth_control_plane.footage.gates import (
    MainIdentity,
    compose_query,
    looks_reaction,
    looks_spam,
    norm,
    same_as_main,
    text_gate,
    video_id,
)


def test_reaction_and_spam() -> None:
    assert looks_reaction("REACTION video banjir")
    assert looks_reaction("nonton bareng final")
    assert not looks_reaction("nonton banjir")  # bare "nonton" over-filters (Scout)
    assert looks_spam("https://vidku.fun/x lagi viral")
    assert looks_spam("Yang lagi viral di mobil vidku.fun #Gempa")
    assert not looks_spam("banjir di kemang pagi ini")


def test_video_ids_like_scout() -> None:
    assert video_id("https://www.tiktok.com/@a/video/7400000000000000001") == "7400000000000000001"
    assert video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id("https://www.instagram.com/reel/ABC123/") == "ABC123"
    assert video_id("https://x.com/a/status/1") == ""


def test_norm_and_compose_query() -> None:
    assert norm("  Banjir!! di  JAKARTA… ") == "banjir di jakarta"
    assert compose_query("chip ai", "nvidia") == "chip ai nvidia"
    assert compose_query("data center nvidia", "nvidia") == "data center nvidia"
    assert compose_query("longsor", "") == "longsor"


def test_same_as_main_by_id_or_caption() -> None:
    main = MainIdentity.of(
        "https://www.tiktok.com/@a/video/7400000000000000001",
        [],
        "Banjir besar melanda Kemang pagi ini, warga mengungsi ke masjid terdekat",
    )
    assert same_as_main(main, "https://www.tiktok.com/@b/video/7400000000000000001", "")
    assert same_as_main(main, "https://x.com/b/status/9", "banjir besar melanda kemang pagi ini")
    assert not same_as_main(main, "https://x.com/b/status/9", "banjir")  # 20 chars or fewer
    assert not same_as_main(main, "https://x.com/b/status/9", "kebakaran pasar senen tadi malam")


def _video(caption: str, duration: float | None = 40.0, owner: str = "kreator") -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id="7400000000000000009",
        owner_handle=owner,
        canonical_url=f"https://www.tiktok.com/@{owner}/video/7400000000000000009",
        caption=caption,
        duration_seconds=duration,
    )


def test_text_gate_order() -> None:
    main = MainIdentity.of("https://www.instagram.com/p/MAIN1/", [], "banjir kemang")
    url = "https://www.tiktok.com/@kreator/video/7400000000000000009"
    gate = lambda video: text_gate(url, video, main, frozenset({"kurator"}))  # noqa: E731
    assert gate(_video("banjir kemang hari ini", owner="Kurator")) == "aggregator"
    assert gate(_video("https://bit.ly/x banjir")) == "spam"
    assert gate(_video("reaction banjir kemang")) == "reaction_text"
    assert gate(_video("banjir kemang", duration=2.0)) == "duration"
    assert gate(_video("banjir kemang", duration=901.0)) == "duration"
    assert gate(_video("banjir kemang", duration=None)) is None
    assert gate(_video("air naik di jalan")) is None
    assert text_gate("https://www.instagram.com/p/MAIN1/", _video("x"), main, frozenset()) == "main"
