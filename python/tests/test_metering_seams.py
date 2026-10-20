"""Provider adapters record their calls against the current scope (spec 2026-10-20, 2.1)."""

import base64
from types import SimpleNamespace

import httpx

from tests.test_metering import Sink
from tests.voice.test_elevenlabs import ALIGNMENT
from thoth_control_plane import metering
from thoth_control_plane.metering import MeterScope
from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice
from thoth_control_plane.voice.ports import VoiceRequest


async def test_an_agno_adapter_records_its_call_and_tokens(monkeypatch) -> None:
    from thoth_control_plane.footage.adapters.queries import AgnoQueryModel
    from thoth_control_plane.footage.queries import FootageQueryAnswer

    sink = Sink()
    metering.install(sink)

    class Agent:
        def __init__(self, **kwargs) -> None:
            pass

        async def arun(self, **kwargs):
            return SimpleNamespace(
                content=FootageQueryAnswer.model_construct(),
                metrics=SimpleNamespace(input_tokens=50, output_tokens=7),
            )

    monkeypatch.setattr("agno.agent.Agent", Agent)
    with metering.scoped(MeterScope("ws_a", workflow_id="wf_1")):
        await AgnoQueryModel("key", "qwen/q").read("prompt")
    assert [(e.workspace_id, e.key, e.quantity, e.unit) for e in sink.events] == [
        ("ws_a", "qwen/q", 1.0, "call"),
        ("ws_a", "qwen/q", 50.0, "token_in"),
        ("ws_a", "qwen/q", 7.0, "token_out"),
    ]


async def test_a_failed_agno_call_records_nothing(monkeypatch) -> None:
    from thoth_control_plane.footage.adapters.queries import AgnoQueryModel

    sink = Sink()
    metering.install(sink)

    class Agent:
        def __init__(self, **kwargs) -> None:
            pass

        async def arun(self, **kwargs):
            raise RuntimeError("provider down")

    monkeypatch.setattr("agno.agent.Agent", Agent)
    with metering.scoped(MeterScope("ws_a")):
        assert await AgnoQueryModel("key", "qwen/q").read("prompt") is None
    assert sink.events == []


async def test_elevenlabs_records_the_characters_it_was_asked_to_speak() -> None:
    sink = Sink()
    metering.install(sink)
    audio = base64.b64encode(b"MP3").decode()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"audio_base64": audio, "alignment": ALIGNMENT})
    )
    with metering.scoped(MeterScope("ws_a")):
        await ElevenLabsVoice("k", transport=transport).synthesize(
            VoiceRequest(text="Halo, dunia!", voice_id="v")
        )
    assert [(e.key, e.quantity, e.unit) for e in sink.events] == [
        ("elevenlabs/eleven_multilingual_v2", 1.0, "call"),
        ("elevenlabs/eleven_multilingual_v2", 12.0, "character"),
    ]
