"""The context card (footage library spec 2026-11-15, 4.1) and its matching (4.2-4.3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tests.assembly.support import report as support_report
from thoth_control_plane.acquisition.models import ReportComment
from thoth_control_plane.footage.context import (
    CARD_PROMPT,
    PERSON_VISUAL,
    PERSON_WINDOW,
    REFINE_PROMPT,
    CardPerson,
    ContextCard,
    RelatedEvent,
    card_material,
    card_names,
    card_objects,
    context_objects,
    context_reason,
    discussed_names,
    event_terms,
    has_event_term,
    in_window,
    names_discussed_with_context,
    names_subject,
    same_event,
    strip_names,
    subject_names,
)

CARDS = Path(__file__).resolve().parents[1] / "fixtures" / "footage" / "context"


def card(name: str) -> ContextCard:
    return ContextCard.model_validate_json((CARDS / f"{name}.json").read_text(encoding="utf-8"))


def test_the_spike_cards_decode() -> None:
    mutant = card("mutant_card")
    assert [p.name for p in mutant.people] == ["Mutant", "Denny Sumargo"]
    assert "Densu" in mutant.people[1].aliases
    for name in ("rocky_card", "persib_card", "erio_card"):
        assert card(name).people


def test_nulls_and_junk_become_empty() -> None:
    empty = ContextCard.model_validate({"people": None, "queries": "x", "event": None})
    assert empty == ContextCard()
    assert ContextCard.model_validate({"model": "m", "people": [{"name": "A", "aliases": None}]})


def test_card_material_takes_the_top_comments_by_likes() -> None:
    main = support_report(
        url="https://www.tiktok.com/@akun/video/7499999999999999999",
        owner="akun",
        text="Mutant pengen diundang podcast Densu",
        media="none",
    )
    comments = [
        ReportComment(comment_id=f"77{n:017d}", author="u", text=f"komen {n}", likes=n)
        for n in range(30)
    ]
    main = main.model_copy(update={"comments": comments})
    material = json.loads(card_material(main, [{"name": "Mutant"}], "halo " * 1000))
    assert len(material["comments"]) == 25
    assert material["comments"][0] == {"text": "komen 29", "likes": 29}
    assert material["caption"] == "Mutant pengen diundang podcast Densu"
    assert material["figures"] == [{"name": "Mutant"}]
    assert len(material["transcript"]) == 1500


def _candidates() -> list[dict[str, object]]:
    return json.loads((CARDS / "mutant_candidates.json").read_text(encoding="utf-8"))


def test_short_and_marked_aliases_are_dropped() -> None:
    rocky = ContextCard(people=[CardPerson(name="Bung Rocky", aliases=["TG", "Rocky?"])])
    assert card_names(rocky) == ["bung rocky", "rocky"]


def test_a_name_matches_whole_words_only() -> None:
    sandy = ContextCard(people=[CardPerson(name="Sandy")])
    assert context_reason("Sandyakala di Bandung", sandy) == "story"
    assert context_reason("Sandy Walsh cetak gol", sandy) is None


def test_the_mutant_candidates_pass_on_the_card() -> None:
    mutant = card("mutant_card")
    mutant.people[0].aliases.append("Saiful")
    by_caption = {str(c["caption"]): c for c in _candidates()}
    for start in (
        "SAIFUL BUKAN MUTAN",
        "Momen Saeful temui Denny Sumargo di acara Urban Sneaker Society",
    ):
        matches = [text for text in by_caption if text.startswith(start)]
        assert matches, start
        assert context_reason(matches[0], mutant) is None, start
    # A news recap naming only Denny Sumargo is off the story (spec 10.12, revision 1).
    (recap,) = [t for t in by_caption if t.startswith("Detik-detik Pria Mengamuk di Depan")]
    assert context_reason(recap, mutant) == "story"
    sneakers = [str(c["caption"]) for c in _candidates() if c["query"] == "sneakers"]
    assert len(sneakers) == 13
    assert all(context_reason(text, mutant) == "story" for text in sneakers)


def test_an_unknown_time_stays_in_the_window() -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    main = "2026-11-10T11:16:32Z"
    assert in_window(None, main, now)
    assert not in_window("2026-10-01T00:00:00Z", main, now)
    assert in_window("2026-11-12T00:00:00Z", main, now)
    assert not in_window("2026-11-15T00:00:00Z", main, now)


def test_context_objects_mark_person_queries() -> None:
    mutant = card("mutant_card")
    person, place = context_objects(
        mutant, ["Mutant USS Denny Sumargo", "Urban Sneaker Society 2026 viral"]
    )
    assert person.person and person.visual == "a person on camera"  # spec 10.12
    assert person.query == "Mutant USS Denny Sumargo"
    assert not place.person and place.visual


def test_english_filler_words_are_not_event_terms() -> None:  # final review, Important 3
    rocky, mutant = card("rocky_card"), card("mutant_card")
    assert context_reason("The best street food and the night market", rocky) == "story"
    assert context_reason("Podcast terbaru di Jakarta bareng komika", mutant) == "story"
    assert context_reason("the sneaker drop event this weekend", mutant) == "story"
    assert context_reason("Keseruan Urban Sneaker Society hari kedua", mutant) is None


def test_spoken_words_are_single_lowercase_words() -> None:  # spec 9.2
    card = ContextCard.model_validate(
        {
            "spoken": [
                "Pedang",
                "marah",
                None,
                {"x": 1},
                "dua kata",
                "marah",
                *[f"w{i}" for i in range(20)],
            ]
        }
    )
    assert card.spoken[:2] == ["pedang", "marah"]
    assert "dua kata" not in card.spoken
    assert len(card.spoken) == 12


def test_an_old_card_decodes_without_spoken() -> None:
    assert ContextCard.model_validate({"event": "x"}).spoken == []


def test_subject_names_are_the_first_persons() -> None:
    card = ContextCard.model_validate(
        {"people": [{"name": "Mutant", "aliases": ["Saiful", "Ipul"]}, {"name": "Denny Sumargo"}]}
    )
    assert subject_names(card) == ["mutant", "saiful", "ipul"]  # longest first, stable
    assert subject_names(ContextCard()) == []


def test_the_prompts_ask_for_the_subject_first_and_spoken_words() -> None:
    assert '"spoken"' in CARD_PROMPT
    assert "people[0]" in CARD_PROMPT
    assert "only in comments" in CARD_PROMPT
    assert "people[0]" in REFINE_PROMPT


def _mutant(**overrides: object) -> ContextCard:
    return card("mutant_card").model_copy(update=overrides)


def test_the_card_reads_related_events() -> None:  # spec 10.4
    read = ContextCard.model_validate(
        {
            "people": [{"name": "Mutant"}],
            "related": [
                {"event": "Mutant at a medical check-up", "query": "Mutant Sekolah Normal"},
                {"event": "no query"},
                "junk",
            ],
        }
    )
    assert [r.query for r in read.related] == ["Mutant Sekolah Normal"]


def test_an_old_card_decodes_without_related() -> None:
    assert card("mutant_card").related == []


def test_card_objects_take_two_incident_queries_and_the_related_ones() -> None:
    mutant = card("mutant_card")
    mutant.people[0].aliases.append("Saiful")
    mutant = mutant.model_copy(
        update={
            "queries": ["a USS", "b USS", "c USS"],
            "related": [
                {"event": "Saiful's clarification with Gofar Hilman", "query": "Saiful Gofar"}
            ],
        }
    )
    mutant = ContextCard.model_validate(mutant.model_dump())
    objects = card_objects(mutant)
    assert [o.query for o in objects] == ["a USS", "b USS", "Saiful Gofar"]
    related = objects[-1]
    assert related.person  # the query names the subject
    assert related.visual == "a person's clarification with Gofar Hilman"  # no card names


def test_a_person_query_visual_names_nobody() -> None:  # spec 10.12, revision 3
    (person,) = context_objects(_mutant(), ["Mutant bawa pedang"])
    assert person.visual == "a person on camera" and person.person


def test_names_match_hashtag_and_nya_forms_only() -> None:  # spec 10.5
    from thoth_control_plane.footage.gates import mentions, norm

    assert mentions(norm("#sekolahnormal #mutan #tretanmuslim"), "tretan muslim")
    assert mentions(norm("Klarifikasi soal mutannya Saiful"), "mutan")
    assert mentions(norm("Tretan Muslimnya datang"), "tretan muslim")
    assert not mentions(norm("#mutantsquad"), "mutant")
    assert not mentions(norm("komutan"), "mutan")


def test_a_subject_clip_may_be_two_years_old() -> None:  # spec 10.5 and 10.12
    now = datetime(2026, 11, 16, tzinfo=UTC)
    old, main = "2024-12-11T08:24:00Z", "2026-11-08T00:00:00Z"
    assert names_subject(norm_text("Mutant diajarin acting Jefri nichol"), _mutant())
    assert not names_subject(norm_text("Podcast Denny Sumargo bareng artis"), _mutant())
    assert in_window(old, main, now, before=PERSON_WINDOW)
    assert not in_window(old, main, now)


def norm_text(text: str) -> str:
    from thoth_control_plane.footage.gates import norm

    return norm(text)


def test_a_name_without_its_title_names_the_subject() -> None:  # live wf_4ac021d9
    titled = ContextCard.model_validate(
        {"people": [{"name": "Saeful", "aliases": ["Master Saiful", "Bang Densu"]}]}
    )
    assert "saiful" in subject_names(titled)
    assert names_subject(norm_text("saiful datang ke podcast"), titled)
    assert "master" not in subject_names(titled)  # a title alone is never a name


def test_the_card_prompt_asks_for_names_without_titles() -> None:
    assert "without titles" in CARD_PROMPT


# Commentary cards (spec 2026-11-26): Ernest Prakasa on FFI 2026, run wf_18344b47.


def test_main_kind_defaults_to_incident_and_reads_commentary() -> None:
    assert ContextCard().main_kind == "incident"
    assert ContextCard.model_validate({"main_kind": " Commentary "}).main_kind == "commentary"
    for odd in (None, "unknown", 123, ["commentary"]):
        assert ContextCard.model_validate({"main_kind": odd}).main_kind == "incident"
    assert card("mutant_card").main_kind == "incident"  # an old stored card


def test_the_prompts_ask_for_the_kind_and_the_post_language() -> None:
    assert '"main_kind"' in CARD_PROMPT and '"commentary"' in CARD_PROMPT
    assert "language of the post" in CARD_PROMPT  # event and place, not English
    assert "people[1:]" in CARD_PROMPT  # the figures a commentary discusses
    assert "visible scene" in CARD_PROMPT  # related[].event is what frames can show
    assert '"main_kind"' in REFINE_PROMPT
    assert "language of the post" in REFINE_PROMPT


def test_event_terms_keep_years_and_drop_indonesian_filler() -> None:
    # Names stay in; the callers drop them ("fadli" is no event word on its own).
    assert event_terms(card("ffi_card")) == ["2026", "citra", "fadli", "ffi", "kemenbud", "piala"]
    filler = ContextCard(
        event="Tanggapan Respons Kritik Soal Tentang Terkait Berita Kasus Momen Aksi Polemik "
        "Pernyataan Panggung Tahun Hari Orang Warga Publik Pemerintah Sosial 1998",
    )
    assert event_terms(filler) == ["1998"]


def test_a_year_and_the_place_alone_are_not_the_event() -> None:
    polemic = ContextCard(event="Polemik FFI 2026", place="Jakarta")
    assert context_reason("Konser musik di Jakarta 2026", polemic) == "story"
    assert context_reason("Sineas acungkan 3 jari di panggung FFI 2026", polemic) is None
    siera = polemic.model_copy(update={"people": [CardPerson(name="Siera")]})
    assert not same_event(siera, "Konser Jakarta 2026", ["siera"])
    assert same_event(siera, "Pidato FFI 2026", ["siera"])


def test_a_commentary_card_admits_the_discussed_events_and_figures() -> None:
    ffi = card("ffi_card")
    for text in (
        "Menang Piala Citra! Produser Film Para Perasuk Kritik Fadli Zon Soal Pemerkosaan Mei 1998",
        "Sentilan Keras Siera Tamihardja untuk Fadli Zon di Panggung FFI 2026 Soal Tragedi 1998",
        "Respons Fadli Zon seusai Dikritik Terang-terangan di Panggung FFI 2026 soal Pemerkosaan "
        "Massal",
        "Sejumlah Sineas Gunakan Panggung FFI 2026 untuk Suarakan Protes, Ini Tanggapan Kemenbud",
        "Fadli Zon bantah pemerkosaan massal Mei 1998",
        "Sineas acungkan 3 jari di panggung FFI 2026",
        "Irini Dewi Wanti tanggapi kritik panggung FFI 2026",
    ):
        assert context_reason(text, ffi) is None, text
    for text in (
        "Fadli Zon kunjungi museum batik di Solo",
        "Berita terbaru panggung musik tahun ini",
        "Tanggapan kasus viral hari ini",
    ):
        assert context_reason(text, ffi) == "story", text


def test_a_discussed_name_needs_a_context_word() -> None:
    ffi = card("ffi_card")
    assert discussed_names(ffi) == ["irini dewi wanti", "fadli zon"]
    assert names_discussed_with_context(norm_text("Fadli Zon bantah soal 1998"), ffi)
    assert not names_discussed_with_context(norm_text("Fadli Zon kunjungi museum batik"), ffi)
    assert not names_discussed_with_context(norm_text("Ernest Prakasa soal 1998"), ffi)
    incident = ffi.model_copy(update={"main_kind": "incident"})
    assert not names_discussed_with_context(norm_text("Fadli Zon bantah soal 1998"), incident)


def test_has_event_term_matches_whole_words_only() -> None:
    ffi, mutant = card("ffi_card"), card("mutant_card")
    assert has_event_term(norm_text("Ernest Prakasa kritik FFI 2026"), ffi)
    assert not has_event_term(norm_text("Ernest Prakasa standup"), ffi)
    assert has_event_term(norm_text("Mutant di USS"), mutant)
    assert not has_event_term(norm_text("Ernest khusus"), mutant)  # "uss" inside a word


def test_an_incident_card_still_needs_the_subject_or_two_event_terms() -> None:
    mutant = card("mutant_card")
    assert context_reason("Podcast Denny Sumargo soal pedang", mutant) == "story"
    assert not names_discussed_with_context(norm_text("Denny Sumargo podcast"), mutant)


# Commentary precision (spec 2026-11-27 ocr video credit, 3.4): live run wf_aea765e4.

WULAN = (
    "Semalam menghadiri Festival Film Indonesia 2026. Sebuah ajang yang selalu punya tempat "
    "istimewa bagi kita semua, insan perfilman Indonesia. Tahun ini terasa lebih spesial, karena "
    "menjadi tahun terakhir kepemimpinan Ario Bayu bersama seluruh Komite FFI. wulanguritno81"
)
IDN = (
    "Damai di hati damai di bumi Peraih penghargaan pemeran utama perempuan terbaik Festival "
    "Film Indonesia 2026 #festivalfilmindonesia #ffi #ffi2026 #festivalfilm theidnpageant"
)
TRIBUN = (
    "Sejumlah Sineas Gunakan Panggung FFI 2026 untuk Suarakan Protes, Ini Tanggapan Kemenbud "
    "tribunnews"
)
STAGE = "Sineas acungkan 3 jari di panggung FFI 2026"


def _aea(**overrides: object) -> ContextCard:
    base = ContextCard(
        main_kind="commentary",
        people=[CardPerson(name="Ernest Prakasa"), CardPerson(name="Irini Dewi Wanti")],
        event="Kritik terhadap pernyataan Irini Dewi Wanti terkait penggunaan panggung FFI 2026 "
        "untuk kritik pemerintah",
        place="Indonesia",
        queries=["Irini Dewi Wanti FFI 2026", "Ernest Prakasa kritik Kemenbud FFI"],
        related=[
            RelatedEvent(
                event="Polemik penggunaan panggung FFI 2026 untuk kritik pemerintah",
                query="FFI 2026 kritik pemerintah",
            )
        ],
        spoken=["kritik", "protes", "panggung"],
    )
    return base.model_copy(update=overrides)


def test_the_card_prompts_read_the_whole_transcript_and_absorb_new_figures() -> None:
    assert "entire transcript" in CARD_PROMPT
    assert "gesture" in CARD_PROMPT
    assert "titles repeat" in REFINE_PROMPT
    assert "award winners" in REFINE_PROMPT and "gestures" in REFINE_PROMPT


def test_a_commentary_figure_query_checks_the_event_scene_not_any_person() -> None:
    aea, ffi = _aea(), card("ffi_card")
    (irini,) = context_objects(aea, ["Irini Dewi Wanti FFI 2026"])
    assert irini.person and irini.visual == " ".join(strip_names(aea.event, aea).split())
    assert irini.visual != PERSON_VISUAL
    (fadli,) = context_objects(ffi, ["Pernyataan Fadli Zon FFI 2026"])
    assert fadli.person and fadli.visual == " ".join(strip_names(ffi.event, ffi).split())


def test_a_commentator_only_or_incident_person_query_still_wants_a_person() -> None:
    (ernest,) = context_objects(_aea(), ["Ernest Prakasa standup"])
    assert ernest.person and ernest.visual == PERSON_VISUAL
    (saiful,) = context_objects(card("mutant_card"), ["Mutant USS Denny Sumargo"])
    assert saiful.person and saiful.visual == PERSON_VISUAL


def test_a_commentary_event_match_needs_a_topic_word_or_three_terms() -> None:
    aea = _aea()
    assert context_reason(WULAN, aea) == "story"
    assert context_reason(IDN, aea) == "story"
    assert context_reason(TRIBUN, aea) is None
    jari = _aea(
        spoken=[],
        related=[RelatedEvent(event="Polemik panggung FFI 2026", query="FFI 2026 3 jari")],
    )
    assert context_reason(STAGE, jari) is None
    assert context_reason(WULAN, jari) == "story"


def test_the_vlog_guard_leaves_incident_and_signal_free_cards_alone() -> None:
    assert context_reason(WULAN, _aea(main_kind="incident")) is None
    bare = _aea(spoken=[], queries=[], related=[])
    assert context_reason(WULAN, bare) is None
