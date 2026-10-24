"""Comments from every report about the story: filtered, deduplicated, ranked, capped."""

from __future__ import annotations

from tests.assembly.support import comment, report
from thoth_control_plane.assembly.comments import merge_comments


def test_ranks_by_likes_and_caps_at_twelve() -> None:
    many = [comment(f"user{n}", f"komentar ke {n} tentang banjirnya", likes=n) for n in range(20)]

    merged = merge_comments([("input", report(comments=many))])

    assert [c.likes for c in merged] == list(range(19, 7, -1))


def test_drops_empty_sticker_and_link_comments() -> None:
    noisy = [
        comment("a", "[Sticker]", 99),
        comment("b", "[ stiker ]", 98),
        comment("c", "https://kliksumut.com | MEDAN berita", 97),
        comment("d", "beneran ini kejadian kemarin?", 1),
    ]

    assert [c.author for c in merge_comments([("input", report(comments=noisy))])] == ["d"]


def test_deduplicates_across_reports_and_keeps_the_first_source() -> None:
    original = report(comments=[comment("Budi", "Kasihan warganya kebanjiran lagi", 5)])
    repost = report(
        workflow_id="wf_b",
        comments=[
            comment("budi", "kasihan warganya kebanjiran lagi ", 50),
            comment("sari", "semoga cepat surut airnya", 2),
        ],
    )

    merged = merge_comments([("original", original), ("input", repost)])

    assert [(c.author, c.source, c.likes) for c in merged] == [
        ("Budi", "original", 5),
        ("sari", "input", 2),
    ]


def test_ties_keep_source_order() -> None:
    tied = [comment(x, f"{x} komentar yang berisi", 3) for x in ("a", "b", "c")]

    assert [c.author for c in merge_comments([("input", report(comments=tied))])] == ["a", "b", "c"]


def test_keeps_only_real_cards() -> None:
    with_card = comment(
        "a", "ada kartunya di komentar ini", 2, card="reports/wf_a/cards/comment-1.png"
    )
    without = comment("b", "yang ini tanpa kartu sama sekali", 1)

    merged = merge_comments([("input", report(comments=[with_card, without]))])

    assert str(merged[0].card.location) == "reports/wf_a/cards/comment-1.png"  # type: ignore[union-attr]
    assert merged[1].card is None


def test_drops_comments_that_say_nothing() -> None:
    # Operator ruling 2026-10-24: a comment in the video must say something (spec D1).
    noisy = [
        comment("a", "wkwkwkwk", 90),
        comment("b", "first", 80),
        comment("c", "@user_001 @user_002", 70),
        comment("d", "😂😂😂", 60),
        comment("e", "Kondisi udaranya makin parah dari kemarin", 1),
    ]

    assert [c.author for c in merge_comments([("input", report(comments=noisy))])] == ["e"]


def test_the_limit_widens_the_candidates() -> None:
    many = [comment(f"user{n}", f"komentar ke {n} tentang banjirnya", likes=n) for n in range(40)]

    assert len(merge_comments([("input", report(comments=many))], limit=30)) == 30
