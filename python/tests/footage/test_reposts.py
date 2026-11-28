"""Originals before reposts: credits, own accounts, credit labels (footage library spec 4.5)."""

from __future__ import annotations

import pytest

from thoth_control_plane.footage.context import CardPerson, ContextCard
from thoth_control_plane.footage.reposts import (
    CreditRef,
    credit_label,
    credited_account,
    credited_source,
    frame_credited_source,
    is_own_account,
)


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


# Footage sourcing v2 (spec 2026-11-27, 4.1): Indonesian credit prefixes and their platform.


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("Sumber YT : Ernest Prakasa", CreditRef("ernestprakasa", "Ernest Prakasa", "youtube")),
        ("Source YT: Rhenald Kasali", CreditRef("rhenaldkasali", "Rhenald Kasali", "youtube")),
        (
            "Sumber: YouTube Kompas TV | FFI 2026",
            CreditRef("kompastv", "Kompas TV", "youtube"),
        ),
        ("sc: KompasTV", CreditRef("kompastv", "KompasTV", None)),
        ("kredit: TVR Parlemen", CreditRef("tvrparlemen", "TVR Parlemen", None)),
        ("yt: DPR RI", CreditRef("dprri", "DPR RI", "youtube")),
        (
            "Master Saiful ngamuk cr: @denny.sumargo",
            CreditRef("denny.sumargo", "denny.sumargo", None),
        ),
        (
            "via YouTube/CURHAT BANG Denny Sumargo",
            CreditRef("curhatbangdennysumargo", "CURHAT BANG Denny Sumargo", "youtube"),
        ),
        ("via @kompastv", CreditRef("kompastv", "kompastv", None)),
    ],
)
def test_credited_source_reads_the_prefix_and_its_platform(
    caption: str, expected: CreditRef
) -> None:
    assert credited_source(caption) == expected


def test_a_named_youtube_credit_beats_an_earlier_handle() -> None:
    assert credited_source("@ernestprakasa Sumber: YouTube Kompas TV") == CreditRef(
        "kompastv", "Kompas TV", "youtube"
    )


def test_a_bare_handle_takes_youtube_from_the_caption() -> None:
    assert credited_source("Full di yt @kompastv") == CreditRef("kompastv", "kompastv", "youtube")
    assert credited_source("ikuti @kompastv") == CreditRef("kompastv", "kompastv", None)


@pytest.mark.parametrize(
    "caption",
    [
        "Model Source: https://makerworld.com/en/models/123",
        "Sumber: www.kompas.com",
        "Merbabu via Tekhelan — jalur bersahabat",
        "Pesan via WA atau via chat atau via transfer atau via link",
        "cr: @akun",
    ],
)
def test_urls_prose_and_placeholders_are_not_credits(caption: str) -> None:
    assert credited_source(caption) is None
    assert credited_account(caption) is None


# Burned-in credits read by OCR on a repost's frames (spec 2026-11-27 ocr video credit, 3.2).

FFI = CreditRef("festivalfilmindonesia", "Festival Film Indonesia", "youtube")


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("Dok: YouTube/Festival Film Indonesia", FFI),
        ("Dok. YouTube Festival Film Indonesia", FFI),
        ("Dok.: KompasTV", CreditRef("kompastv", "KompasTV", None)),
        ("Dok. @festivalfilm_id", CreditRef("festivalfilm_id", "festivalfilm_id", None)),
    ],
)
def test_dok_credits_name_their_source(caption: str, expected: CreditRef) -> None:
    assert credited_source(caption) == expected
    assert frame_credited_source([[caption]]) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Dokter memeriksa pasien",
        "Dokumen resmi negara",
        "Film dokumenter FFI",
        "Dok. Pribadi",
        "Dok. Istimewa",
    ],
)
def test_dok_words_and_personal_labels_are_not_credits(text: str) -> None:
    assert credited_source(text) is None
    assert frame_credited_source([[text]]) is None


@pytest.mark.parametrize(
    "frames",
    [
        [["Breaking News", "Sumber: YouTube / Festival Film Indonesia"]],
        [["Sumber:", "YouTube Festival Film Indonesia"]],
        [["Sumber", "YouTube Festival Film Indonesia"]],
        [["YouTube", "Festival Film Indonesia"]],
        [["Pidato pemenang", "Dok.", "YouTube Festival Film Indonesia"]],
    ],
)
def test_a_frame_credit_is_read_from_one_box_or_a_prefix_and_its_neighbour(
    frames: list[list[str]],
) -> None:
    assert frame_credited_source(frames) == FFI


def test_a_youtube_frame_credit_beats_an_earlier_other_credit() -> None:
    frames = [["Cr: @newsacct"], ["Sumber: YT/KompasTV"]]
    assert frame_credited_source(frames) == CreditRef("kompastv", "KompasTV", "youtube")
    assert frame_credited_source([["Cr: @newsacct"]]) == CreditRef("newsacct", "newsacct", None)


def test_a_bare_uploader_watermark_is_no_frame_credit() -> None:
    assert frame_credited_source([["@jawaposofficial", "Pidato FFI 2026"]]) is None
    assert frame_credited_source([]) is None


@pytest.mark.parametrize(
    "line",
    [
        "Sumber: Istimewa",
        "Dok: Pribadi",
        "Sumber: Dokumentasi",
        "Sumber: Arsip",
        "Sumber: Internet",
        "Sumber: https://example.com",
    ],
)
def test_non_account_frame_labels_are_refused(line: str) -> None:
    assert frame_credited_source([[line]]) is None


def test_a_split_credit_stays_inside_its_own_frame() -> None:
    frames = [["Sumber:", "blur"], ["Sumber:", "YouTube/FFI"]]
    assert frame_credited_source(frames) == CreditRef("ffi", "FFI", "youtube")
    assert frame_credited_source([["Sumber:"], ["YouTube Festival Film Indonesia"]]) is None


@pytest.mark.parametrize(
    "frames",
    [
        [["kata dia via YouTube kemarin"]],
        [["via YouTube kemarin malam"]],
        [["via", "YouTube Festival Film Indonesia"]],
        [["Sumber", "masalahnya ada di pemerintah"]],
        [["Sumber: kemarin dia bilang begitu"]],
        [["Sumber: Festival Film Indonesia penuh kritik pedas soal kebijakan"]],
    ],
)
def test_a_subtitle_line_is_no_frame_credit(frames: list[list[str]]) -> None:  # final minors
    assert frame_credited_source(frames) is None


def test_a_frame_via_credit_still_reads_a_handle() -> None:
    assert frame_credited_source([["via @kompastv"]]) == CreditRef("kompastv", "kompastv", None)
