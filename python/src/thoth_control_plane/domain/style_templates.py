"""Style templates: a style is data, not code (spec 2026-11-10).

A template holds a look per Story beat, the cut rhythm, the caption style and how the narration
speaks. Style A (IsseiNugroho, story explainer) and Style B (WinNews, kinetic-text news) are the
two built-in templates; their values follow the editor readings of the reference videos.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from thoth_control_plane.domain.edit_document_v2 import Background, Dim
from thoth_control_plane.domain.models import OpaqueId, StrictModel
from thoth_control_plane.domain.move_presets import MovePreset
from thoth_control_plane.domain.narration import BEAT_ORDER, BeatId

HeadingPlace = Literal["title_top", "title", "title_lower", "card"]


class BeatLook(StrictModel):
    use: bool = True
    move: MovePreset = "none"
    #: The move for a picture taller than the canvas, a long post or card (spec 5); none: `move`.
    tall_move: MovePreset | None = None
    background: Background = "none"
    dim: Dim = 0.0
    highlight: bool = False
    arrow: bool = False
    heading_place: HeadingPlace | None = None


class CutRules(StrictModel):
    max_shot_seconds: Annotated[float, Field(ge=1.0, le=20.0)]
    min_shot_seconds: Annotated[float, Field(ge=0.2, le=10.0)] = 1.0
    cut_on_sentences: bool = True
    cycle_materials: bool = True
    card_between_facts: bool = False
    #: Planner stage 1 (spec 2026-11-13): cut on phrase starts, each phrase's picture chosen by
    #: what it says; card lines sit over a phrase instead of taking a slot of their own.
    planned: bool = False


class CaptionRules(StrictModel):
    style: Literal["boxed", "kinetic", "word_highlight"]
    words_per_caption: Annotated[int, Field(ge=1, le=8)]


class NarrationRules(StrictModel):
    starter: Annotated[str, Field(min_length=1, max_length=12_000)]
    target_seconds: Annotated[int, Field(ge=10, le=180)] | None = None
    card_lines: bool = False
    card_line_max_words: Annotated[int, Field(ge=1, le=12)] = 6
    card_seconds: Annotated[float, Field(gt=0.0, le=10.0)] = 2.0
    max_sfx_cues: Annotated[int, Field(ge=0, le=10)] | None = None


class StyleTemplate(StrictModel):
    template_id: OpaqueId
    name: Annotated[str, Field(min_length=1, max_length=120)]
    revision: Annotated[int, Field(gt=0)]
    origin: Literal["built_in"]
    beats: dict[BeatId, BeatLook]
    cuts: CutRules
    captions: CaptionRules
    narration: NarrationRules

    @model_validator(mode="after")
    def _every_beat(self) -> StyleTemplate:
        if set(self.beats) != set(BEAT_ORDER):
            raise ValueError("a style template sets a look for every Story beat")
        return self


_STARTER_A = (
    "Kamu menulis narasi voiceover gaya story explainer untuk video vertikal dari sebuah post "
    "media sosial.\n"
    "Alurnya Hook -> Tension -> Solution -> Call-To-Value: Hook menyatakan klaim dan "
    "kejutannya dalam 3 detik pertama; lalu klaim itu, lalu bukti yang mengujinya, lalu twist; "
    "tutup dengan opini singkat tentang kenapa penonton perlu peduli.\n"
    "Bahasa sehari-hari yang santai, kalimat pendek, satu gagasan per kalimat, mudah diucapkan.\n"
    "Pakai hanya fakta yang diberikan: judul, deskripsi, figur, komentar dan transkrip. Jangan "
    "pernah mengarang nama, angka atau kutipan. Sebut figur dengan namanya.\n"
    "Pilih efek suara hanya dari daftar yang diberikan, dan hanya bila benar-benar pas."
)

_STARTER_B = (
    "Kamu menulis narasi komentar berita gaya kinetic-text untuk video vertikal.\n"
    "Buka dengan sebuah metafora yang membingkai beritanya (misalnya level dalam game), dan "
    "kembalikan metafora itu di penutup.\n"
    "Setiap fakta langsung diikuti reaksi atau pertanyaan narator sendiri, seperti orang yang "
    "heran: kalimat pendek, nada bertanya, bahasa sehari-hari.\n"
    "Untuk setiap beat tulis juga satu kalimat kartu: reaksi atau pertanyaan narator, paling "
    "banyak enam kata.\n"
    "Pakai hanya fakta yang diberikan: judul, deskripsi, figur, komentar dan transkrip. Jangan "
    "pernah mengarang nama, angka atau kutipan. Sebut figur dengan namanya.\n"
    "Pilih efek suara hanya dari daftar yang diberikan, dan hanya bila benar-benar pas."
)


def _a() -> StyleTemplate:
    moving = BeatLook(move="push_in", background="blur_fill")
    return StyleTemplate(
        template_id="style_a",
        name="Style A",
        revision=1,
        origin="built_in",
        beats={
            "hook": moving.model_copy(update={"heading_place": "title_top"}),
            "main": moving.model_copy(update={"tall_move": "pan_across"}),
            "evidence": moving.model_copy(update={"highlight": True, "arrow": True}),
            "reactions": moving.model_copy(update={"tall_move": "scroll_down"}),
            "footage": moving,
            "outro": moving,
        },
        cuts=CutRules(max_shot_seconds=5.0),
        captions=CaptionRules(style="boxed", words_per_caption=4),
        narration=NarrationRules(starter=_STARTER_A),
    )


def _b() -> StyleTemplate:
    # Revision 2 (planner stage 1, 2026-11-13): a still camera, as the WinNews references hold.
    dimmed = BeatLook(move="none", dim=0.45)
    return StyleTemplate(
        template_id="style_b",
        name="Style B",
        revision=2,
        origin="built_in",
        beats={
            "hook": dimmed.model_copy(update={"heading_place": "title_top"}),
            "main": dimmed,
            "evidence": dimmed,
            "reactions": dimmed,
            "footage": dimmed,
            "outro": dimmed,
        },
        cuts=CutRules(
            max_shot_seconds=2.4, min_shot_seconds=0.9, card_between_facts=True, planned=True
        ),
        captions=CaptionRules(style="kinetic", words_per_caption=3),
        narration=NarrationRules(starter=_STARTER_B, card_lines=True),
    )


BUILT_IN_STYLES: dict[str, StyleTemplate] = {style.template_id: style for style in (_a(), _b())}
