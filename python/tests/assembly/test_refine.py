"""Corrections after Scout's verdict (spec amendment 2026-10-12): overlays, scene text, trims."""

from __future__ import annotations

from thoth_control_plane.assembly.refine import retrim, settle, sort_windows, without_trim
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
