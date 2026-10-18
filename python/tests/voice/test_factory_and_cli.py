"""The voice factory and the operator-only `voice say` CLI, with fake providers."""

import json

import pytest
from typer.testing import CliRunner

from thoth_control_plane import cli
from thoth_control_plane.config import Settings
from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice
from thoth_control_plane.voice.adapters.openai_compatible import OpenAICompatibleVoice
from thoth_control_plane.voice.factory import build_voice
from thoth_control_plane.voice.ports import SynthesizedVoice, VoiceNotConfigured, WordTiming


@pytest.mark.parametrize("provider", ["elevenlabs", "openai_compatible"])
def test_unconfigured_providers_refuse(provider) -> None:
    with pytest.raises(VoiceNotConfigured):
        build_voice(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), provider)


def test_configured_providers_build() -> None:
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_ELEVENLABS_API_KEY="e",
        THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL="http://voices.test/v1",
    )
    assert isinstance(build_voice(settings, "elevenlabs"), ElevenLabsVoice)
    assert isinstance(build_voice(settings, "openai_compatible"), OpenAICompatibleVoice)


def test_voice_say_writes_audio_and_words(monkeypatch, tmp_path) -> None:
    class Fake:
        async def synthesize(self, request):
            return SynthesizedVoice(
                audio=b"MP3",
                media_type="audio/mpeg",
                duration_seconds=1.0,
                word_timings=[WordTiming(text="Halo", start_seconds=0.0, end_seconds=0.4)],
            )

    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setattr(cli, "build_voice", lambda settings, provider: Fake())
    out = tmp_path / "say.mp3"
    result = CliRunner().invoke(
        cli.app, ["voice", "say", "--voice", "v", "--text", "Halo", "--out", str(out)]
    )
    assert result.exit_code == 0
    assert result.output.strip() == "provider=elevenlabs duration_seconds=1.00 words=1"
    assert out.read_bytes() == b"MP3"
    words = json.loads((tmp_path / "say.mp3.words.json").read_text())
    assert words == [{"text": "Halo", "start_seconds": 0.0, "end_seconds": 0.4}]


def test_voice_say_reports_an_unconfigured_provider(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.delenv("THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL", raising=False)
    result = CliRunner().invoke(
        cli.app,
        [
            "voice", "say", "--provider", "openai-compatible", "--voice", "v",
            "--text", "a", "--out", str(tmp_path / "x.wav"),
        ],
    )
    assert result.exit_code == 1
    assert "VoiceNotConfigured" in result.output
