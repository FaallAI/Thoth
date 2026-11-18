"""Originals before reposts: credits, own accounts, credit labels (footage library spec 4.5)."""

from __future__ import annotations

from thoth_control_plane.footage.context import CardPerson, ContextCard
from thoth_control_plane.footage.reposts import credit_label, credited_account, is_own_account


def test_credits_are_read_from_common_forms() -> None:
    assert credited_account("Sumber: YouTube Curhat Bang | Tribun") == "curhatbang"
    assert credited_account("Master Saiful ngamuk cr: @curhatbang") == "curhatbang"
    assert credited_account("via YouTube/CURHAT BANG Denny Sumargo") == "curhatbangdennysumargo"
    assert credited_account("Detik-detik Pria Mengamuk di Depan Denny Sumargo") is None


def test_own_accounts_come_from_the_card() -> None:
    card = ContextCard(
        people=[
            CardPerson(name="Mutant"),
            CardPerson(name="Denny Sumargo", aliases=["Densu"], accounts=["@curhatbang"]),
        ]
    )
    assert is_own_account("curhatbang", card)
    assert is_own_account("@DennySumargo", card)
    assert not is_own_account("tribunnewsbogor", card)
    assert not is_own_account("tribunmutan", card)


def test_credit_labels() -> None:
    assert credit_label("youtube", "@curhatbang") == "YouTube/curhatbang"
    assert credit_label("tiktok", "jnrksn") == "@jnrksn"
    assert credit_label("x", "@akun") == "@akun"
    assert credit_label(None, "@kompascomreport") == "@kompascomreport"
    assert credit_label(None, None) is None


def test_a_credited_handle_keeps_its_dots_for_the_listing() -> None:  # final review, Important 5
    assert credited_account("Master Saiful ngamuk cr: @denny.sumargo") == "denny.sumargo"
    assert credited_account("tt/@tretan_muslim.") == "tretan_muslim"
