"""The ElevenLabs adapter, offline through httpx.MockTransport."""

import base64
import json

import httpx
import pytest

from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice, words_from_alignment
from thoth_control_plane.voice.ports import VoiceRejected, VoiceRequest, VoiceUnavailable

ALIGNMENT = {
    "characters": list("Halo,  dunia!"),
    "character_start_times_seconds": [
        0.0,
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.55,
        0.6,
        0.7,
        0.8,
        0.9,
        1.0,
        1.1,
    ],
    "character_end_times_seconds": [
        0.1,
        0.2,
        0.3,
        0.4,
        0.5,
        0.55,
        0.6,
        0.7,
        0.8,
        0.9,
        1.0,
        1.1,
        1.2,
    ],
}


def test_alignment_groups_runs_of_non_space_characters_into_words() -> None:
    words = words_from_alignment(ALIGNMENT)
    assert [(w.text, w.start_seconds, w.end_seconds) for w in words] == [
        ("Halo,", 0.0, 0.5),
        ("dunia!", 0.6, 1.2),
    ]


async def test_synthesize_posts_with_timestamps_and_decodes_audio() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["xi-api-key"]
        seen["body"] = json.loads(request.content)
        audio = base64.b64encode(b"MP3").decode()
        return httpx.Response(200, json={"audio_base64": audio, "alignment": ALIGNMENT})

    voice = await ElevenLabsVoice("secret-key", transport=httpx.MockTransport(handler)).synthesize(
        VoiceRequest(text="Halo, dunia!", voice_id="plgKUYgnlZ1DCNh54DwJ")
    )
    assert voice.audio == b"MP3"
    assert voice.media_type == "audio/mpeg"
    assert voice.duration_seconds == 1.2
    assert "/v1/text-to-speech/plgKUYgnlZ1DCNh54DwJ/with-timestamps" in seen["url"]
    assert "output_format=mp3_44100_128" in seen["url"]
    assert seen["key"] == "secret-key"
    assert seen["body"]["model_id"] == "eleven_v4"
    assert seen["body"]["language_code"] == "id"
    assert "voice_settings" not in seen["body"]


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, VoiceRejected), (422, VoiceRejected), (429, VoiceUnavailable), (503, VoiceUnavailable)],
)
async def test_errors_map_and_never_carry_the_key(status, error) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"detail": {"status": "x"}})
    )
    with pytest.raises(error) as caught:
        await ElevenLabsVoice("secret-key", transport=transport).synthesize(
            VoiceRequest(text="a", voice_id="v")
        )
    assert "secret-key" not in str(caught.value)
    assert "secret-key" not in repr(caught.value)
    assert str(caught.value) == f"elevenlabs_http_{status}"


async def test_a_connection_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(VoiceUnavailable):
        await ElevenLabsVoice("k", transport=httpx.MockTransport(handler)).synthesize(
            VoiceRequest(text="a", voice_id="v")
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>proxy error</html>"),
        httpx.Response(200, json={"alignment": None}),
    ],
)
async def test_an_unreadable_success_body_is_unavailable(response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    with pytest.raises(VoiceUnavailable) as caught:
        await ElevenLabsVoice("k", transport=transport).synthesize(
            VoiceRequest(text="a", voice_id="v")
        )
    assert str(caught.value) == "elevenlabs_bad_response"


async def test_neighbouring_text_is_sent_for_request_stitching() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        audio = base64.b64encode(b"MP3").decode()
        return httpx.Response(200, json={"audio_base64": audio, "alignment": ALIGNMENT})

    voice = ElevenLabsVoice("secret-key", transport=httpx.MockTransport(handler))
    await voice.synthesize(
        VoiceRequest(text="Tengah.", voice_id="v", previous_text="Awal.", next_text="Akhir.")
    )
    assert (seen["body"]["previous_text"], seen["body"]["next_text"]) == ("Awal.", "Akhir.")  # type: ignore[index]

    await voice.synthesize(VoiceRequest(text="Sendiri.", voice_id="v"))
    assert "previous_text" not in seen["body"] and "next_text" not in seen["body"]  # type: ignore[operator]


async def test_request_ids_stitch_and_the_billed_cost_comes_from_the_header(monkeypatch) -> None:
    """ElevenLabs documents previous_request_ids (max 3) and a character-cost header."""
    from thoth_control_plane import metering

    seen: dict[str, object] = {}
    billed: list[tuple[str, int | None]] = []

    async def record_call(key: str, *, characters: int | None = None, **_: object) -> None:
        billed.append((key, characters))

    monkeypatch.setattr(metering, "record_call", record_call)

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        audio = base64.b64encode(b"MP3").decode()
        return httpx.Response(
            200,
            json={"audio_base64": audio, "alignment": ALIGNMENT},
            headers={"request-id": "req_3", "character-cost": "9"},
        )

    voice = await ElevenLabsVoice("secret-key", transport=httpx.MockTransport(handler)).synthesize(
        VoiceRequest(
            text="Tengah.",
            voice_id="v",
            previous_text="Awal.",
            previous_request_ids=["req_0", "req_1", "req_2", "req_x"],
        )
    )

    assert seen["body"]["previous_request_ids"] == ["req_1", "req_2", "req_x"]  # type: ignore[index]
    assert voice.request_id == "req_3"
    assert billed == [("elevenlabs/eleven_v4", 9)]


def _ok(seen: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["calls"] = int(seen.get("calls", 0)) + 1  # type: ignore[call-overload]
        audio = base64.b64encode(b"MP3").decode()
        return httpx.Response(200, json={"audio_base64": audio, "alignment": ALIGNMENT})

    return httpx.MockTransport(handler)


async def test_v4_sends_stability_keeps_tags_and_strips_neighbor_tags() -> None:
    seen: dict[str, object] = {}
    await ElevenLabsVoice("k", transport=_ok(seen)).synthesize(
        VoiceRequest(
            text="[curious] Halo!",
            voice_id="v",
            model="eleven_v4",
            stability=0.45,
            previous_text="[amused] Awal.",
            next_text="[excited] Akhir.",
        )
    )
    body = seen["body"]
    assert body["text"] == "[curious] Halo!"  # type: ignore[index]
    assert body["language_code"] == "id"  # type: ignore[index]
    assert body["voice_settings"] == {"stability": 0.45}  # type: ignore[index]
    assert (body["previous_text"], body["next_text"]) == ("Awal.", "Akhir.")  # type: ignore[index]


async def test_v2_strips_tags_and_sends_speed() -> None:
    seen: dict[str, object] = {}
    await ElevenLabsVoice("k", transport=_ok(seen)).synthesize(
        VoiceRequest(
            text="[curious] Halo, [amused] dunia!",
            voice_id="v",
            model="eleven_multilingual_v2",
            speed=1.1,
            stability=0.35,
            previous_text="[excited] Awal.",
        )
    )
    body = seen["body"]
    assert body["text"] == "Halo, dunia!"  # type: ignore[index]
    assert body["previous_text"] == "Awal."  # type: ignore[index]
    assert body["voice_settings"] == {"speed": 1.1, "stability": 0.35}  # type: ignore[index]
    assert "language_code" not in body  # type: ignore[operator]


async def test_v2_rejects_text_empty_after_stripping_tags() -> None:
    seen: dict[str, object] = {}
    with pytest.raises(VoiceRejected) as caught:
        await ElevenLabsVoice("k", transport=_ok(seen)).synthesize(
            VoiceRequest(text="[curious] [excited]", voice_id="v", model="eleven_multilingual_v2")
        )
    assert str(caught.value) == "empty_text_after_tag_strip"
    assert "calls" not in seen


def _alignment(text: str, step: float = 0.1) -> dict[str, list]:
    return {
        "characters": list(text),
        "character_start_times_seconds": [round(i * step, 3) for i in range(len(text))],
        "character_end_times_seconds": [round((i + 1) * step, 3) for i in range(len(text))],
    }


def test_alignment_strips_tags_of_every_shape_and_keeps_an_unclosed_bracket() -> None:
    text = "[curious] Halo, [clears throat] [amused]dunia! [sighs]"
    words = words_from_alignment(_alignment(text))
    halo, dunia = text.index("Halo,"), text.index("dunia!")
    assert [(w.text, w.start_seconds, w.end_seconds) for w in words] == [
        ("Halo,", round(halo * 0.1, 3), round((halo + 5) * 0.1, 3)),
        ("dunia!", round(dunia * 0.1, 3), round((dunia + 6) * 0.1, 3)),
    ]

    unclosed = words_from_alignment(_alignment("[curious tanpa tutup"))
    assert [w.text for w in unclosed] == ["[curious", "tanpa", "tutup"]


#: Word timings eleven_v4 returned in the paid listening spike (2026-11-24), tags included.
SPIKE_V4 = [
    ("[curious]", 0.0, 0.107), ("Kelihatannya", 0.133, 0.72), ("sih", 0.8, 0.96),
    ("Mutant", 1.12, 1.44), ("nggak", 1.48, 1.6), ("suka,", 1.68, 2.32),
    ("[amused]", 2.48, 2.544), ("tapi", 2.56, 2.8), ("ternyata", 2.88, 3.36),
    ("ada", 3.48, 3.6), ("maunya!", 3.72, 4.48), ("[excited]", 4.72, 4.827),
    ("Di", 4.853, 4.88), ("video", 5.0, 5.12), ("ini,", 5.2, 5.6), ("Mutant", 5.76, 6.08),
    ("tertangkap", 6.16, 6.48), ("kamera", 6.56, 6.96), ("lagi", 7.04, 7.2),
    ("kasih", 7.28, 7.44), ("kode", 7.56, 7.68), ("keras.", 7.8, 8.4),
]  # fmt: skip


def test_spike_shaped_v4_alignment_yields_only_spoken_words() -> None:
    characters: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    for index, (token, start, end) in enumerate(SPIKE_V4):
        if index:
            characters.append(" ")
            starts.append(start)
            ends.append(start)
        step = (end - start) / len(token)
        for i, char in enumerate(token):
            characters.append(char)
            starts.append(start + i * step)
            ends.append(start + (i + 1) * step)
    words = words_from_alignment(
        {
            "characters": characters,
            "character_start_times_seconds": starts,
            "character_end_times_seconds": ends,
        }
    )
    spoken = [(t, s, e) for t, s, e in SPIKE_V4 if not t.startswith("[")]
    assert len(words) == 19
    assert [w.text for w in words] == [t for t, _, _ in spoken]
    # pytest 9.2's approx refuses nested sequences, so each word's start and end are flattened.
    assert [t for w in words for t in (w.start_seconds, w.end_seconds)] == pytest.approx(
        [t for _, s, e in spoken for t in (s, e)]
    )


# Final review fixes (2026-11-24).
def test_punctuation_right_after_a_tag_stays_on_the_word_before() -> None:
    """`Halo [curious].` is spoken "Halo." : a lone "." would be a caption and shift word_index."""
    text = "Halo [curious]. Lagi [amused]!? ya"
    words = words_from_alignment(_alignment(text))
    dot, marks = text.index("."), text.index("!?")
    assert [(w.text, w.end_seconds) for w in words] == [
        ("Halo.", round((dot + 1) * 0.1, 3)),
        ("Lagi!?", round((marks + 2) * 0.1, 3)),
        ("ya", round(len(text) * 0.1, 3)),
    ]
    assert words[0].start_seconds == 0.0


async def test_v4_rejects_a_beat_of_tags_only_before_any_call() -> None:
    seen: dict[str, object] = {}
    with pytest.raises(VoiceRejected) as caught:
        await ElevenLabsVoice("k", transport=_ok(seen)).synthesize(
            VoiceRequest(text="[curious]", voice_id="v", model="eleven_v4")
        )
    assert str(caught.value) == "empty_text_after_tag_strip"
    assert "calls" not in seen


async def test_v3_never_gets_speed() -> None:
    """Eleven v3 has no speed setting either (spec 2026-11-24, anti-goals); no tags reach it."""
    seen: dict[str, object] = {}
    await ElevenLabsVoice("k", transport=_ok(seen)).synthesize(
        VoiceRequest(text="[curious] Halo.", voice_id="v", model="eleven_v3", speed=1.2)
    )
    body = seen["body"]
    assert body["text"] == "Halo."  # type: ignore[index]
    assert "voice_settings" not in body  # type: ignore[operator]


async def test_without_the_cost_header_v2_is_billed_the_text_it_was_sent(monkeypatch) -> None:
    from thoth_control_plane import metering

    billed: list[tuple[str, int | None]] = []

    async def record_call(key: str, *, characters: int | None = None, **_: object) -> None:
        billed.append((key, characters))

    monkeypatch.setattr(metering, "record_call", record_call)
    await ElevenLabsVoice("k", transport=_ok({})).synthesize(
        VoiceRequest(text="[curious] Halo.", voice_id="v", model="eleven_multilingual_v2")
    )
    assert billed == [("elevenlabs/eleven_multilingual_v2", len("Halo."))]


# Deferred minors, fixed 2026-11-24.
async def test_v4_sends_the_primary_language_subtag() -> None:
    seen: dict[str, object] = {}
    await ElevenLabsVoice("k", transport=_ok(seen)).synthesize(
        VoiceRequest(text="Halo.", voice_id="v", model="eleven_v4", language="id-ID")
    )
    assert seen["body"]["language_code"] == "id"  # type: ignore[index]


async def test_a_trailing_tag_keeps_its_sound_in_the_duration() -> None:
    """`[laughs]` at the end of a beat is heard after the last word: the clip must not cut it."""
    text = "Halo [laughs]"

    def handler(request: httpx.Request) -> httpx.Response:
        audio = base64.b64encode(b"MP3").decode()
        return httpx.Response(200, json={"audio_base64": audio, "alignment": _alignment(text)})

    voice = await ElevenLabsVoice("k", transport=httpx.MockTransport(handler)).synthesize(
        VoiceRequest(text=text, voice_id="v", model="eleven_v4")
    )
    assert [w.text for w in voice.word_timings or []] == ["Halo"]
    assert voice.duration_seconds == pytest.approx(len(text) * 0.1)
