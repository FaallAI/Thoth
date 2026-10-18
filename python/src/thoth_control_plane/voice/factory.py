"""Build one configured provider; an unconfigured one refuses instead of falling back."""

from __future__ import annotations

from typing import Literal

from thoth_control_plane.config import Settings
from thoth_control_plane.voice.adapters.elevenlabs import ElevenLabsVoice
from thoth_control_plane.voice.adapters.openai_compatible import OpenAICompatibleVoice
from thoth_control_plane.voice.ports import VoiceNotConfigured, VoiceSynthesizer

Provider = Literal["elevenlabs", "openai_compatible"]


def build_voice(settings: Settings, provider: Provider) -> VoiceSynthesizer:
    if provider == "elevenlabs":
        if settings.THOTH_ELEVENLABS_API_KEY is None:
            raise VoiceNotConfigured("elevenlabs")
        return ElevenLabsVoice(settings.THOTH_ELEVENLABS_API_KEY.get_secret_value())
    if settings.THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL is None:
        raise VoiceNotConfigured("openai_compatible")
    key = settings.THOTH_VOICE_OPENAI_COMPATIBLE_API_KEY
    return OpenAICompatibleVoice(
        str(settings.THOTH_VOICE_OPENAI_COMPATIBLE_BASE_URL),
        key.get_secret_value() if key else None,
    )
