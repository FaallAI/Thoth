"""Auto-draft narration: the preset, the script, its state and the voice estimate.

Spec 2026-10-31 (auto-draft, the narrated draft). Every value the Rust engine hard-coded is a
preset field with the Rust value as its default.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from thoth_control_plane.domain.edit_document_v2 import AssetRef
from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.voice.ports import WordTiming

BeatId: TypeAlias = Literal["hook", "main", "evidence", "reactions", "footage", "outro"]
BEAT_ORDER: tuple[BeatId, ...] = ("hook", "main", "evidence", "reactions", "footage", "outro")

NarrationStatus: TypeAlias = Literal[
    "transcribing",
    "scripting",
    "awaiting_approval",
    "voicing",
    "writing",
    "completed",
    "failed",
    "cancelled",
]
#: A narration in one of these states owns the draft: Studio edits wait for it.
ACTIVE_STATUSES: frozenset[str] = frozenset(
    {"transcribing", "scripting", "awaiting_approval", "voicing", "writing"}
)

Level = Annotated[float, Field(ge=0.0, le=1.0)]
ScriptText = Annotated[str, Field(min_length=1, max_length=2000)]


class NarrationPreset(StrictModel):
    """A project's narration settings; the defaults are the Rust `config.toml` values."""

    language: Annotated[str, Field(min_length=2, max_length=8)] = "id"
    target_seconds: Annotated[int, Field(ge=10, le=180)] = 45
    words_per_second: Annotated[float, Field(gt=0.5, le=6.0)] = 3.0
    voice_provider: Literal["elevenlabs"] = "elevenlabs"
    voice_id: Annotated[str, Field(min_length=1, max_length=200)] = "plgKUYgnlZ1DCNh54DwJ"
    voice_model: Annotated[str, Field(min_length=1, max_length=200)] = "eleven_multilingual_v2"
    duck_volume: Level = 0.12
    leak_volume: Level = 0.45
    lead_in_seconds: Annotated[float, Field(ge=0.0, le=10.0)] = 1.6
    max_sfx_cues: Annotated[int, Field(ge=0, le=10)] = 3


class ScriptBeat(StrictModel):
    beat: BeatId
    text: ScriptText


class SfxCue(StrictModel):
    sfx_id: Annotated[str, Field(min_length=1, max_length=120)]
    beat: BeatId
    moment: Annotated[str, Field(min_length=1, max_length=60)]
    #: The word of the beat's text the effect lands on; none means the beat's start.
    word_index: Annotated[int, Field(ge=0)] | None = None


class NarrationScript(StrictModel):
    beats: Annotated[list[ScriptBeat], Field(min_length=1, max_length=len(BEAT_ORDER))]
    sfx_cues: Annotated[list[SfxCue], Field(max_length=10)] = Field(default_factory=list)

    @model_validator(mode="after")
    def beats_in_story_order(self) -> NarrationScript:
        positions = [BEAT_ORDER.index(beat.beat) for beat in self.beats]
        if positions != sorted(set(positions)):
            raise ValueError("script beats must be unique and in story order")
        return self


class TranscriptSegment(StrictModel):
    """What was said in the main video; captions are timed by the voice, not by this."""

    text: str
    start_seconds: Annotated[float, Field(ge=0.0)]
    end_seconds: Annotated[float, Field(ge=0.0)]


class SfxEntry(StrictModel):
    """One sound effect in the shared library; `labels` holds its catalog row."""

    sfx_id: Annotated[str, Field(min_length=1, max_length=120)]
    file_name: Annotated[str, Field(min_length=1, max_length=200)]
    location: Annotated[str, Field(min_length=1, max_length=500)]
    checksum: Annotated[str, Field(min_length=1, max_length=100)]
    duration_seconds: Annotated[float, Field(gt=0.0)]
    labels: dict[str, object] = Field(default_factory=dict)


class VoiceEstimate(StrictModel):
    characters: Annotated[int, Field(ge=0)]
    provider: str
    voice_id: str
    #: None when no price is set (prices stay unset until billing go-live).
    usd: float | None = None


class NarrationState(StrictModel):
    document_id: str
    workflow_id: str
    status: NarrationStatus
    script: NarrationScript | None = None
    estimate: VoiceEstimate | None = None
    #: Per beat, script tokens the evidence does not contain; shown, never a refusal.
    unsupported: dict[BeatId, list[str]] = Field(default_factory=dict)
    stale_beats: list[BeatId] = Field(default_factory=list)
    failure_code: str | None = None


def estimate_voice(
    script: NarrationScript,
    preset: NarrationPreset,
    prices: Mapping[tuple[str, str, str], float],
) -> VoiceEstimate:
    """The characters TTS will bill, priced the way `metering.estimate` prices a key."""
    characters = sum(len(beat.text) for beat in script.beats)
    # The adapter meters `<provider>/<model>` (voice/adapters/elevenlabs.py), so price that key.
    price = prices.get(
        ("provider_call", f"{preset.voice_provider}/{preset.voice_model}", "character")
    )
    if price is None:
        price = prices.get(("provider_call", "*", "character"))
    return VoiceEstimate(
        characters=characters,
        provider=preset.voice_provider,
        voice_id=preset.voice_id,
        usd=None if price is None else characters * price,
    )


class NarrationInProgress(RuntimeError):
    """The draft already has a narration that is not finished."""


class NarrationPresetConflict(RuntimeError):
    """The preset was saved by someone else since the given revision."""


class NarrationStoreUnavailable(RuntimeError):
    """The editor database could not be reached; nothing was written."""


class VoiceRef(StrictModel):
    """One beat's synthesized voice as stored: its asset and the word timings it came with."""

    beat: BeatId
    asset: AssetRef
    duration_seconds: Annotated[float, Field(gt=0.0)]
    words: list[WordTiming] = Field(default_factory=list)


class NarrationStepInput(StrictModel):
    project_id: str
    document_id: str


class NarrationScriptInput(NarrationStepInput):
    #: The operator's note on a rejected script, for the next attempt.
    note: Annotated[str, Field(max_length=500)] | None = None


class NarrationRevoiceInput(NarrationStepInput):
    beat: BeatId


class NarrationStepResult(StrictModel):
    """None when the step succeeded; otherwise the safe failure code already recorded."""

    code: str | None = None


class StoredPreset(StrictModel):
    preset: NarrationPreset
    revision: Annotated[int, Field(ge=0)]
