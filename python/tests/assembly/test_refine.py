"""Corrections after Scout's verdict (spec amendment 2026-10-12): overlays, scene text, trims."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thoth_control_plane.assembly.refine import (
    EdgeGap,
    edge_gaps,
    edge_seconds,
    follow_captions,
    follow_seconds,
    holds_caption,
    retrim,
    settle,
    sort_windows,
    without_trim,
)
from thoth_control_plane.assembly.subtitles import OcrBox, OcrFrame, Region, Verdict

TIMES = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 10.7, 16.3, 22.0, 27.7, 33.3, 38.7)


def frames(*boxes_by_frame: tuple[OcrBox, ...]) -> list[OcrFrame]:
    return [OcrFrame(t, boxes) for t, boxes in zip(TIMES, boxes_by_frame, strict=True)]


def verdict(*regions: Region, trim: float = 0.0) -> Verdict:
    return Verdict("subtitle", trim, True, tuple(regions))


CAPTIONS = (
    "Kecelakaan bermula saat",
    "ENR melaju dari arah selatan",
    "Bukannya berhenti, ENR",
    "melanjutkan perjalanan menuju",
    "Saat itu, korban sedang",
    "menaikkan barang ke pikap",
    "RPK mengalami luka berat",
    "dan dinyatakan meninggal",
    "Saat berada di lokasi,",
    "ENR juga sempat marah-marah",
    "Polisi menetapkan ENR",
    "sebagai tersangka",
)
BAND = (
    OcrBox("DETIK-DETIK NENEK 61 TAHUN", 0.05, 0.59, 0.93, 0.63),
    OcrBox("ASAL KANADA PECAHKAN REKOR", 0.05, 0.64, 0.94, 0.68),
)
BAND_REGION = Region(0.03, 0.58, 0.93, 0.15, 0.0, 39.1)


def test_a_band_in_every_sample_is_an_overlay() -> None:
    windows = sort_windows(frames(*[BAND] * 12), verdict(BAND_REGION))

    assert windows.overlays == (BAND_REGION,)
    assert not windows.captions and not windows.dropped


def test_constant_text_in_part_of_the_video_is_scene_text() -> None:
    sign = (OcrBox("OFFICIAL", 0.63, 0.88, 0.83, 0.92), OcrBox("ATTEMPT", 0.63, 0.92, 0.83, 0.96))
    region = Region(0.59, 0.86, 0.26, 0.12, 0.0, 7.8)

    windows = sort_windows(frames(*[sign] * 6, *[()] * 6), verdict(region))

    assert windows.dropped == (region,)


def test_text_cut_by_the_frame_edge_is_scene_text() -> None:
    led = [
        (OcrBox("est", 0.0, 0.29, 0.1, 0.33), OcrBox("tomorrow", 0.15, 0.29, 0.46, 0.33)),
        (
            OcrBox("ating growth", 0.0, 0.31, 0.37, 0.35),
            OcrBox("vest in tomorrow", 0.41, 0.31, 0.93, 0.35),
        ),
        (OcrBox("eating", 0.8, 0.33, 1.0, 0.38),),
    ]
    region = Region(0.0, 0.28, 1.0, 0.12, 1.5, 3.5)

    windows = sort_windows(frames((), *led, *[()] * 8), verdict(region))

    assert windows.dropped == (region,)


def test_changing_centred_text_is_a_caption() -> None:
    lines = [(OcrBox(text, 0.2, 0.7, 0.8, 0.74),) for text in CAPTIONS]
    region = Region(0.18, 0.68, 0.64, 0.08, 0.0, 39.1)

    windows = sort_windows(frames(*lines), verdict(region))

    assert windows.captions == (region,)


def test_a_one_sample_window_is_a_caption_for_the_judge() -> None:
    region = Region(0.71, 0.27, 0.23, 0.06, 1.5, 2.5)
    sign = (OcrBox("Danantara", 0.73, 0.29, 0.92, 0.32),)

    windows = sort_windows(frames((), (), sign, *[()] * 9), verdict(region))

    assert windows.captions == (region,)


def test_settle_keeps_the_audio_for_overlays_only() -> None:
    windows = sort_windows(frames(*[BAND] * 12), verdict(BAND_REGION))

    settled = settle(verdict(BAND_REGION), windows, confirmed=None)

    assert (settled.outcome, settled.mute_audio, settled.subtitle_blur) == (
        "overlay",
        False,
        (BAND_REGION,),
    )


def test_settle_drops_captions_the_judge_rejects() -> None:
    caption = Region(0.18, 0.68, 0.64, 0.08, 0.0, 39.1)
    lines = [(OcrBox(text, 0.2, 0.7, 0.8, 0.74),) for text in CAPTIONS]
    windows = sort_windows(frames(*lines), verdict(caption))

    assert settle(verdict(caption), windows, confirmed=False).outcome == "clean"
    assert settle(verdict(caption, trim=2.5), windows, confirmed=False).outcome == "cover"
    kept = settle(verdict(caption), windows, confirmed=True)
    assert (kept.outcome, kept.mute_audio, kept.subtitle_blur) == ("subtitle", True, (caption,))
    # No answer (no key, provider error): the rule-based result stands.
    assert settle(verdict(caption), windows, confirmed=None).outcome == "subtitle"


def test_without_trim_keeps_an_original_intact() -> None:
    cover = Verdict("cover", 4.0, False, ())
    caption = Region(0.2, 0.7, 0.6, 0.1, 4.0, 9.0)

    assert without_trim(cover) == Verdict("clean", 0.0, False, ())
    assert without_trim(verdict(caption, trim=4.0)).trim_start == 0.0


def test_retrim_moves_the_first_caption_window_with_the_trim() -> None:
    first = Region(0.17, 0.67, 0.66, 0.21, 12.075, 26.2)
    later = Region(0.2, 0.3, 0.5, 0.1, 30.0, 40.0)

    moved = retrim(verdict(first, later, trim=12.075), 6.5)

    assert moved.trim_start == 6.5
    assert moved.subtitle_blur == (Region(0.17, 0.67, 0.66, 0.21, 6.5, 26.2), later)


def test_headline_span_brackets_the_trim_with_the_lines_that_left() -> None:
    from thoth_control_plane.assembly.refine import headline_span

    headline = (
        OcrBox("Ferdy Sambo Tunjukkan Ruangan", 0.09, 0.19, 0.91, 0.23),
        OcrBox("yang Dituding Kamar Mewah", 0.15, 0.23, 0.86, 0.26),
        OcrBox("iNews", 0.09, 0.09, 0.39, 0.15),
    )
    later = (OcrBox("iNews", 0.09, 0.09, 0.39, 0.15),)
    shot = frames(*[headline] * 6, *[later] * 6)

    span = headline_span(shot, Verdict("cover", 7.85, False, ()))

    assert span is not None
    box, present, absent = span
    assert (present, absent) == (5.0, 10.7)
    assert (box.x0, box.y0, box.x1, box.y1) == (0.09, 0.19, 0.91, 0.26)
    assert headline_span(shot, Verdict("clean", 0.0, False, ())) is None


def test_headline_span_ignores_boxes_that_were_not_part_of_the_headline() -> None:
    # officialinews, 2026-10-12: a wide box seen only at 5 s, far below the headline, widened the
    # envelope into moving footage and the tracker cut at 5.1 s instead of 9.6 s.
    from thoth_control_plane.assembly.refine import headline_span

    headline = (
        OcrBox("Ferdy Sambo Tunjukkan Ruangan", 0.09, 0.19, 0.91, 0.23),
        OcrBox("yang Dituding Kamar Mewah", 0.15, 0.23, 0.86, 0.26),
    )
    stray = OcrBox("teks lain di bawah", 0.1, 0.74, 0.7, 0.79)
    shot = frames(*[headline] * 5, (*headline, stray), *[()] * 6)

    span = headline_span(shot, Verdict("cover", 7.85, False, ()))

    assert span is not None
    assert (span[0].y0, span[0].y1) == (0.19, 0.26)


def test_a_band_after_the_trim_is_an_overlay() -> None:
    # Review 2026-10-13: coverage counted the trimmed intro, so no trimmed repost had an overlay.
    after = Region(0.03, 0.58, 0.93, 0.15, 7.85, 39.1)

    windows = sort_windows(frames(*[BAND] * 12), verdict(after, trim=7.85))

    assert windows.overlays == (after,)


def test_without_trim_starts_the_windows_at_zero() -> None:
    # Review 2026-10-13: the trim went to 0 but the captions of the kept intro stayed unblurred.
    caption = Region(0.2, 0.7, 0.6, 0.1, 10.44, 70.38)

    kept = without_trim(verdict(caption, trim=10.44))

    assert kept.subtitle_blur == (Region(0.2, 0.7, 0.6, 0.1, 0.0, 70.38),)


# --- Blur follows the text (operator, rev 19, 2026-11-02) ---

WORDS = ("rocky", "bung", "apapun", "makanannya", "paling", "minumnya", "ludah", "sendiri")


def word(text: str) -> OcrBox:
    return OcrBox(text, 0.5 - len(text) * 0.02, 0.84, 0.5 + len(text) * 0.02, 0.89)


def half_seconds(*boxes_by_frame: tuple[OcrBox, ...]) -> list[OcrFrame]:
    return [OcrFrame((i + 1) * 0.5, boxes) for i, boxes in enumerate(boxes_by_frame)]


def spans(regions: tuple[Region, ...]) -> list[tuple[float, float]]:
    return [(region.start, region.end) for region in regions]


def test_a_caption_window_closes_when_the_text_is_gone() -> None:
    read = half_seconds(*((word(text),) for text in WORDS), (), (), ())

    followed = follow_captions(read, 0.0, 5.5)

    assert spans(followed) == [(0.0, 4.25)]


def test_a_caption_window_opens_when_the_text_arrives_and_again_after_a_pause() -> None:
    before = ((word(text),) for text in WORDS[:4])
    after = ((word(text),) for text in WORDS[4:])
    read = half_seconds((), (), *before, (), (), *after)

    followed = follow_captions(read, 0.0, 6.0)

    assert spans(followed) == [(1.25, 3.25), (4.25, 6.0)]


def test_the_window_covers_the_text_it_follows_and_no_more() -> None:
    read = half_seconds(*((word(text),) for text in WORDS))

    region = follow_captions(read, 0.0, 4.0)[0]

    widest = word("makanannya")
    assert region.x <= widest.x0 and region.x + region.w >= widest.x1
    assert region.y <= widest.y0 and region.y + region.h >= widest.y1
    assert region.h < 0.1


def test_a_word_too_narrow_for_the_sampled_rule_still_belongs_to_the_caption() -> None:
    short = OcrBox("ege", 0.43, 0.85, 0.57, 0.89)
    read = half_seconds(*((word(text),) for text in WORDS), (short,), ())

    assert spans(follow_captions(read, 0.0, 5.0)) == [(0.0, 4.75)]


def test_a_watermark_is_no_caption_though_the_reader_misreads_it() -> None:
    # The reader saw "Kabinet Rakyat" in every frame, a different way in some (rev 18 source).
    misreads = ("Kabinet", "Kahinet", "Kubinet", "Kqbinet", "Kabinet", "Kdbinet", "Kobinet")
    read = half_seconds(*((OcrBox(text, 0.32, 0.47, 0.68, 0.52),) for text in misreads))

    assert follow_captions(read, 0.0, 4.0) == ()


def test_scene_text_that_moves_with_the_shot_is_no_caption() -> None:
    shirts = (
        OcrBox("METARUN", 0.75, 0.76, 0.98, 0.80),
        OcrBox("POCARI", 0.48, 0.74, 0.66, 0.77),
        OcrBox("SIVE.", 0.65, 0.76, 0.77, 0.79),
        OcrBox("SWEAT", 0.34, 0.76, 0.51, 0.79),
    )

    assert follow_captions(half_seconds(*((box,) for box in shirts)), 0.0, 2.0) == ()


def test_small_scene_text_inside_the_caption_band_is_not_part_of_it() -> None:
    logo = OcrBox("DIY", 0.57, 0.84, 0.61, 0.86)
    read = half_seconds(*((word(text),) for text in WORDS), (logo,), (logo,))

    assert spans(follow_captions(read, 0.0, 5.0)) == [(0.0, 4.25)]


def test_text_cut_by_the_frame_edge_is_no_caption() -> None:
    read = half_seconds(*((OcrBox(text, 0.0, 0.7, 0.3, 0.74),) for text in WORDS))

    assert follow_captions(read, 0.0, 4.0) == ()


def test_an_editorial_chyron_beside_its_badge_is_no_caption() -> None:
    # The classifier keeps a chyron anchored by a badge; following must not bring it back.
    badge = OcrBox("LIVE NEWS", 0.02, 0.72, 0.12, 0.76)
    read = half_seconds(*((badge, OcrBox(text, 0.2, 0.72, 0.8, 0.76)) for text in WORDS))

    assert follow_captions(read, 0.0, 4.0) == ()


def test_both_lines_of_a_two_line_caption_are_followed() -> None:
    # Long lines of one language look alike to the bigram score (ig_DebN5MbiGXK, 2026-11-03).
    first = ("tapi saya kira memang benar", "bahwa langkah nanti yang paling")
    second = ("ujungnya ya hanya hujan air ya", "utama adalah pencegahan presisi")
    frames_of_one = [
        (OcrBox(top, 0.15, 0.67, 0.85, 0.70), OcrBox(low, 0.15, 0.70, 0.85, 0.73))
        for top, low in zip(first, second, strict=True)
        for _ in range(4)
    ]

    followed = follow_captions(half_seconds(*frames_of_one), 0.0, 4.0)

    assert spans(followed) == [(0.0, 4.0), (0.0, 4.0)]
    assert {round(region.y, 3) for region in followed} == {0.655, 0.685}


def test_a_line_with_two_sentences_of_a_longer_caption_is_followed() -> None:
    lines = ("kecantikan miliknya fenty beauty", "ternama")
    read = half_seconds(*((OcrBox(t, 0.09, 0.8, 0.88, 0.84),) for t in lines for _ in range(4)))

    assert spans(follow_captions(read, 0.0, 4.0)) == [(0.0, 4.0)]


def test_a_sign_read_in_pieces_is_no_caption() -> None:
    pieces = ("kritik", "kritik pesan kepada", "kritik", "pesan kepada", "kritik pesan", "kritik")
    read = half_seconds(*((OcrBox(t, 0.4, 0.54, 0.7, 0.57),) for t in pieces))

    assert follow_captions(read, 0.0, 3.0) == ()


def test_two_watermark_lines_read_as_one_spot_are_no_caption() -> None:
    # A small watermark on a board in the shot: two lines 0.015 apart (rev 18 source).
    read = half_seconds(
        *(
            (OcrBox("Kabinet", 0.46, 0.27, 0.66, 0.30), OcrBox("Rakyat", 0.46, 0.285, 0.66, 0.315))
            for _ in range(6)
        )
    )

    assert follow_captions(read, 0.0, 3.0) == ()


def test_changing_scene_text_narrower_than_a_caption_is_no_caption() -> None:
    labels = ("erecam", "relam", "sratis", "peat", "gratis", "paikan")
    read = half_seconds(*((OcrBox(t, 0.53, 0.49, 0.64, 0.53),) for t in labels))

    assert follow_captions(read, 0.0, 3.0) == ()


def test_a_trimmed_intro_stays_out_of_the_window() -> None:
    read = half_seconds(*((word(text),) for text in WORDS))

    assert spans(follow_captions(read, 1.2, 4.0)) == [(1.2, 4.0)]


@pytest.mark.parametrize(
    ("trim", "duration", "expected"),
    [
        (0.0, 2.0, [0.5, 1.0, 1.5]),
        (1.2, 3.0, [1.5, 2.0, 2.5]),
    ],
)
def test_the_text_is_read_every_half_second(
    trim: float, duration: float, expected: list[float]
) -> None:
    assert follow_seconds(trim, duration) == expected


def test_a_long_video_is_read_thinner_rather_than_for_ever() -> None:
    seconds = follow_seconds(0.0, 3600.0)

    assert 300 <= len(seconds) <= 360
    assert seconds[-1] > 3500


def recorded(name: str) -> tuple[list[OcrFrame], float]:
    path = Path(__file__).parents[1] / "fixtures/assembly/ocr_follow" / f"{name}.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    return (
        [
            OcrFrame(frame["t"], tuple(OcrBox(*box) for box in frame["boxes"]))
            for frame in case["frames"]
        ],
        case["duration"],
    )


def test_a_two_line_caption_over_a_whole_video_leaves_the_credit_and_the_end_card() -> None:
    # Judged against the frames (2026-11-03): both lines to 42.75 s, then the end card.
    read, duration = recorded("instagram_DebN5MbiGXK")

    followed = follow_captions(read, 6.8, duration)

    assert spans(followed) == pytest.approx([(6.8, 42.75), (6.8, 42.75)])
    assert all(region.y >= 0.64 and region.y + region.h <= 0.75 for region in followed)


def test_captions_the_samples_missed_are_blurred_and_their_gaps_are_not() -> None:
    # Twelve samples called a brand strip at the top captions and missed these (2026-11-03).
    read, duration = recorded("instagram_DeOfMJJz6hL")

    followed = follow_captions(read, 5.3, duration)

    assert sorted(set(spans(followed))) == pytest.approx(
        [(5.3, 5.75), (15.25, 20.75), (30.25, 35.75), (42.75, 48.25)]
    )
    assert len(followed) == 14  # every line of each caption, the short last lines too
    assert all(region.y >= 0.68 for region in followed)


def test_a_sign_the_camera_carries_across_the_frame_is_no_caption() -> None:
    # Its lines pass the same spot in turn, which looks like changing text (ig_DeeQRrRTLdq).
    lines = ("ROCKY GERUNG", "Wantimpres", "Kritik Kepada", "GRATIS", "SNACK", "ROCKY GERUNG")
    passing = [
        (OcrBox(line, 0.36, 0.56, 0.73, 0.61), OcrBox(line, 0.15, 0.72, 0.52, 0.77))
        for line in lines
    ]

    assert follow_captions(half_seconds(*passing), 0.0, 3.0) == ()


def test_a_caption_word_read_taller_on_the_same_line_is_not_another_spot() -> None:
    # Short words repeat, and a taller read starts a track of its own (ig_Dc5ZNTtSxeH).
    tall = tuple((OcrBox(text, 0.4, 0.52, 0.6, 0.62),) for text in ("iya", "apa", "ini", "pak"))
    usual = tuple((OcrBox(text, 0.4, 0.54, 0.6, 0.59),) for text in ("iya", "apa", "ini", "pak"))

    followed = follow_captions(half_seconds(*tall, *usual), 0.0, 4.0)

    assert spans(followed) == [(0.0, 2.25), (2.25, 4.0)]


def test_a_handheld_shot_of_a_sign_has_no_caption_windows() -> None:
    # The first draft of this rule gave it 17 patches on the sign (2026-11-03).
    read, duration = recorded("instagram_DeeQRrRTLdq")

    assert follow_captions(read, 4.1, duration) == ()


# --- Exact edges (operator, revision 20, 2026-11-03) ---

LINE = OcrBox("kata", 0.3, 0.7, 0.7, 0.75)
LINE_REGION = Region(0.3, 0.7, 0.4, 0.05, 0.75, 1.75)


def test_a_window_edge_lies_between_the_reads_around_it() -> None:
    read = [OcrFrame(0.5), OcrFrame(1.0, (LINE,)), OcrFrame(1.5, (LINE,)), OcrFrame(2.0)]

    assert edge_gaps(read, LINE_REGION, 0.0) == (EdgeGap(LINE, 0.5, 1.0), EdgeGap(LINE, 2.0, 1.5))


def test_a_window_at_the_trim_or_the_end_has_no_edge_to_measure() -> None:
    read = [OcrFrame(0.5), OcrFrame(1.0, (LINE,)), OcrFrame(1.5, (LINE,))]
    region = Region(0.3, 0.7, 0.4, 0.05, 1.0, 2.0)

    assert edge_gaps(read, region, 1.0) == (None, None)


def test_an_edge_needs_a_read_of_the_window_text() -> None:
    # A read that failed or holds other text cannot say what to look for.
    elsewhere = OcrBox("papan", 0.3, 0.2, 0.7, 0.25)
    read = [OcrFrame(0.5), OcrFrame(1.0, (elsewhere,)), OcrFrame(1.5, (LINE,)), OcrFrame(2.0)]

    opening, closing = edge_gaps(read, LINE_REGION, 0.0)

    assert opening is None
    assert closing == EdgeGap(LINE, 2.0, 1.5)


def test_a_lost_read_is_not_taken_for_a_read_without_text() -> None:
    read = [
        OcrFrame(0.5),
        OcrFrame(0.75, error="ocr_failed"),
        OcrFrame(1.0, (LINE,)),
        OcrFrame(1.5, (LINE,)),
        OcrFrame(2.0),
    ]

    opening, _ = edge_gaps(read, LINE_REGION, 0.0)

    assert opening == EdgeGap(LINE, 0.5, 1.0)


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        (OcrBox("berikutnya", 0.25, 0.7, 0.75, 0.75), True),  # the next words of the line
        (OcrBox("kata", 0.3, 0.2, 0.7, 0.25), False),  # another height
        (OcrBox("DIY", 0.3, 0.71, 0.34, 0.72), False),  # small text in the shot
        (OcrBox("kata", 0.0, 0.7, 0.6, 0.75), False),  # cut by the frame edge
        (OcrBox("2026", 0.3, 0.7, 0.7, 0.75), False),  # digits alone
    ],
)
def test_a_read_holds_the_caption_only_on_its_line(box: OcrBox, expected: bool) -> None:
    assert holds_caption(LINE, OcrFrame(1.0, (box,))) is expected


def test_a_gap_names_every_second_its_halving_can_ask_for() -> None:
    gap = EdgeGap(LINE, 2.0, 1.5)

    assert edge_seconds(gap, 2) == {1.75, 1.625, 1.875}
    assert len(edge_seconds(gap, 3)) == 7
    assert min(edge_seconds(gap, 3)) > 1.5 and max(edge_seconds(gap, 3)) < 2.0
