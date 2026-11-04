"""The narration script: its prompt, the answer it must be, and the evidence check (Task 6)."""

from __future__ import annotations

import pytest

from thoth_control_plane.application.narration_script import (
    ScriptFacts,
    ScriptInvalid,
    build_script_request,
    parse_script,
    unsupported_tokens,
)
from thoth_control_plane.domain.narration import (
    NarrationPreset,
    NarrationScript,
    ScriptBeat,
    SfxEntry,
    TranscriptSegment,
)

FACTS = ScriptFacts(
    title="Kucing oren viral di pasar",
    description="Video kucing oren mencuri ikan https://example.com/x di Pasar Minggu",
    owner_handle="pecintakucing.id",
    platform="TikTok",
    figures=["Budi Santoso"],
    comments=["lucu banget 😂", "itu kucing saya!"],
)
TRANSCRIPT = [
    TranscriptSegment(text="Lihat itu, 3 ekor ikan diambil", start_seconds=0.0, end_seconds=2.0)
]
SFX = [
    SfxEntry(
        sfx_id="whoosh",
        file_name="whoosh.mp3",
        location="sfx/a.mp3",
        checksum="sha256:a",
        duration_seconds=1.0,
        labels={"description": "Swipe whoosh", "moments": ["comment_appear"]},
    )
]
BEATS = ["hook", "main", "reactions"]


def answer(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "beats": [
            {"beat": "hook", "text": "Kucing ini bikin satu pasar heboh."},
            {"beat": "main", "text": "Tiga ekor ikan diambil dalam sekejap."},
            {"beat": "reactions", "text": "Warganet malah tertawa."},
        ],
        "sfx_cues": [
            {"sfx_id": "whoosh", "beat": "reactions", "moment": "comment_appear", "word_index": 0}
        ],
    }
    value.update(overrides)
    return value


def test_the_prompt_carries_the_facts_transcript_and_sfx_but_no_url() -> None:
    system, user = build_script_request(
        prompt="Tulis naskah.",
        beats=BEATS,  # type: ignore[arg-type]
        facts=FACTS,
        transcript=TRANSCRIPT,
        preset=NarrationPreset(),
        sfx=SFX,
        note="Hook kurang tajam",
    )
    assert system.startswith("Tulis naskah.") and '"beats"' in system
    for expected in (
        "Kucing oren viral",
        "Budi Santoso",
        "3 ekor ikan",
        "whoosh",
        "Hook kurang tajam",
        "135",
    ):
        assert expected in user
    assert "http" not in user
    assert "hook, main, reactions" in user


def _user_message(beats: list[str]) -> str:
    _system, user = build_script_request(
        prompt="Tulis naskah.",
        beats=beats,  # type: ignore[arg-type]
        facts=FACTS,
        transcript=TRANSCRIPT,
        preset=NarrationPreset(),
        sfx=[],
    )
    return user


def test_each_requested_beat_says_what_is_on_screen() -> None:
    user = _user_message(["main", "reactions"])
    assert "- main: " in user and "- reactions: " in user
    # A beat this draft lacks is not described, so the model is not led to write about it.
    assert "- footage: " not in user and "- hook: " not in user


def test_comments_and_the_transcript_are_told_apart_by_who_said_them() -> None:
    user = _user_message(["main"])
    assert "Comments written by viewers, not said in the video:" in user
    assert "Machine transcript of the people in the video, may be misheard:" in user


def test_the_source_rules_hold_whatever_prompt_the_project_saved() -> None:
    system, _user = build_script_request(
        prompt="Prompt tersimpan.",
        beats=BEATS,  # type: ignore[arg-type]
        facts=FACTS,
        transcript=TRANSCRIPT,
        preset=NarrationPreset(),
        sfx=[],
    )
    assert system.startswith("Prompt tersimpan.")
    for rule in ("viewers", "handle", "misheard", "word for word"):
        assert rule in system


def test_the_model_is_not_given_the_account_so_the_voice_cannot_read_it() -> None:
    assert "pecintakucing" not in _user_message(["main"])


def test_the_attribution_verdict_is_not_offered_to_the_model() -> None:
    assert not hasattr(FACTS, "verdict")
    assert "Attribution" not in _user_message(["main"])


def test_a_handle_loses_its_at_sign_before_the_voice_reads_it() -> None:
    beats = [{"beat": "main", "text": "Kritik dari @syarieffaid (@warga.jogja) ini keras."}]
    script = parse_script(
        answer(beats=beats, sfx_cues=[]), beats=BEATS, preset=NarrationPreset(), sfx_ids=set()
    )  # type: ignore[arg-type]
    assert script.beats[0].text == "Kritik dari syarieffaid (warga.jogja) ini keras."


def test_a_valid_answer_becomes_a_script_in_story_order() -> None:
    shuffled = answer(beats=list(reversed(answer()["beats"])))  # type: ignore[arg-type]
    script = parse_script(shuffled, beats=BEATS, preset=NarrationPreset(), sfx_ids={"whoosh"})  # type: ignore[arg-type]
    assert [beat.beat for beat in script.beats] == BEATS
    assert script.sfx_cues[0].sfx_id == "whoosh"


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        answer(beats=[{"beat": "outro", "text": "Bukan beat draft ini."}]),
        answer(beats=[{"beat": "main", "text": ""}]),
        answer(beats=[{"beat": "main", "text": "kata " * 200}]),
    ],
    ids=[
        "not-an-object",
        "unknown-beat",
        "empty-text",
        "too-long",
    ],
)
def test_an_answer_the_draft_cannot_use_is_refused(bad: object) -> None:
    with pytest.raises(ScriptInvalid):
        parse_script(bad, beats=BEATS, preset=NarrationPreset(), sfx_ids={"whoosh"})  # type: ignore[arg-type]


def test_tokens_the_evidence_lacks_are_listed_per_beat() -> None:
    script = NarrationScript(
        beats=[
            ScriptBeat(
                beat="hook", text="Budi Santoso kaget. Ada 3 ikan dan 12 kucing di Pasar Minggu."
            ),
            ScriptBeat(beat="main", text="Kata @pecintakucing.id, Andi yang menolong."),
        ],
        sfx_cues=[],
    )
    found = unsupported_tokens(script, FACTS, TRANSCRIPT)
    assert found == {"hook": ["12"], "main": ["Andi"]}


def test_the_facts_come_from_the_materials_and_the_run_context() -> None:
    from thoth_control_plane.application.narration_script import facts_from_materials
    from thoth_control_plane.domain.studio_imports import (
        MaterialFigure,
        StudioMaterial,
        StudioMaterials,
    )

    materials = StudioMaterials(
        document_id="edoc_1",
        provenance_available=True,
        items=[
            StudioMaterial(
                item_id="main",
                role="main",
                label="Main",
                media_kind="video",
                disposition="attached",
                owner_handle="pecintakucing.id",
                platform="tiktok",
                verdict="original",
            ),
            # A card's label names its author: what the author wrote comes from the run.
            StudioMaterial(
                item_id="comment_card_000",
                role="comment_card",
                label="@andi",
                media_kind="image",
                disposition="attached",
            ),
        ],
        figures=[MaterialFigure(name="Budi Santoso", type="person", role="owner")],
    )

    facts = facts_from_materials(materials, ("Judul", "Deskripsi"), ["itu kucing saya!"])

    assert (facts.title, facts.description, facts.owner_handle, facts.platform) == (
        "Judul",
        "Deskripsi",
        "pecintakucing.id",
        "tiktok",
    )
    assert (facts.figures, facts.comments) == (["Budi Santoso"], ["itu kucing saya!"])


def test_a_stored_quote_reaches_the_script_without_emote_tokens() -> None:
    # Older runs stored comments raw; the voice must not read "[Terkekeh]" aloud.
    from thoth_control_plane.application.narration_script import facts_from_materials
    from thoth_control_plane.domain.studio_imports import StudioMaterials

    comments = ["kasihan [Terkekeh] warganya [Sedih]", "[Terkekeh][Tertawa]", "[2024] banjir lagi"]
    materials = StudioMaterials(document_id="edoc_1", provenance_available=True, items=[])

    assert facts_from_materials(materials, None, comments).comments == [
        "kasihan warganya",
        "[2024] banjir lagi",
    ]


def test_sound_effects_the_draft_cannot_use_are_dropped_not_fatal() -> None:
    """An optional SFX never costs the whole script (final review, minor 11 re-graded)."""
    cues = [
        {"sfx_id": "airhorn", "beat": "main", "moment": "x"},
        {"sfx_id": "whoosh", "beat": "footage", "moment": "x"},
    ] + [{"sfx_id": "whoosh", "beat": "main", "moment": "x"}] * 4
    script = parse_script(
        answer(sfx_cues=cues), beats=BEATS, preset=NarrationPreset(), sfx_ids={"whoosh"}
    )  # type: ignore[arg-type]
    assert [cue.sfx_id for cue in script.sfx_cues] == ["whoosh"] * 3


@pytest.mark.parametrize(
    "broken",
    [
        {"sfx_id": "whoosh", "beat": "main"},
        {"sfx_id": "whoosh", "beat": "main", "moment": ""},
        {"sfx_id": "whoosh", "beat": "main", "moment": "x", "word_index": "3"},
        {"sfx_id": "whoosh", "beat": "main", "moment": "x", "word_index": -1},
        {"sfx_id": "whoosh", "beat": "main", "moment": "x", "why": "extra field"},
    ],
)
def test_a_badly_written_cue_is_dropped_and_the_script_stands(broken: dict[str, object]) -> None:
    good = {"sfx_id": "whoosh", "beat": "main", "moment": "x"}
    script = parse_script(
        answer(sfx_cues=[broken, good]), beats=BEATS, preset=NarrationPreset(), sfx_ids={"whoosh"}
    )  # type: ignore[arg-type]
    assert [(cue.moment, cue.word_index) for cue in script.sfx_cues] == [("x", None)]


def test_a_long_reason_for_a_cue_keeps_the_cue() -> None:
    # The contract asks the model why it plays, and the stored field holds 60 characters.
    cue = {"sfx_id": "whoosh", "beat": "main", "moment": "y" * 200}
    script = parse_script(
        answer(sfx_cues=[cue]), beats=BEATS, preset=NarrationPreset(), sfx_ids={"whoosh"}
    )  # type: ignore[arg-type]
    assert [cue.moment for cue in script.sfx_cues] == ["y" * 60]


def test_an_empty_library_asks_for_no_sound_effects() -> None:
    _system, user = build_script_request(
        prompt="Tulis naskah.",
        beats=BEATS,
        facts=FACTS,
        transcript=TRANSCRIPT,  # type: ignore[arg-type]
        preset=NarrationPreset(),
        sfx=[],
    )
    assert "sfx_cues must be []" in user


def test_a_beat_the_model_leaves_empty_is_dropped_not_fatal() -> None:
    """Review Focus 2: an empty beat keeps its visuals and simply has no voice."""
    beats = [*answer()["beats"], {"beat": "main", "text": "   "}]  # type: ignore[misc]
    beats = [beats[0], {"beat": "main", "text": "  "}, beats[2]]
    script = parse_script(
        answer(beats=beats), beats=BEATS, preset=NarrationPreset(), sfx_ids={"whoosh"}
    )  # type: ignore[arg-type]
    assert [beat.beat for beat in script.beats] == ["hook", "reactions"]
