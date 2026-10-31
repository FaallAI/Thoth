"""The narration script: the request to the model, the answer it must be, and the evidence check.

Spec 2026-10-31, section 5. The prompt is the project's saved `narration_script` prompt (else the
starter) with the answer contract always appended. The answer is refused when the draft cannot
use it; tokens the evidence does not contain are listed for the approval screen, never refused,
because the operator reads the script before any voice is made.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic import Field, ValidationError

from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.domain.narration import (
    BEAT_ORDER,
    BeatId,
    NarrationPreset,
    NarrationScript,
    SfxEntry,
    TranscriptSegment,
)

STAGE = "narration_script"
#: Always asked for, whatever a project's saved prompt says, so the answer stays parseable.
ANSWER_CONTRACT = (
    'Answer with one JSON object: {"beats": [{"beat": a beat id from the list, "text": the '
    'narration for that beat}], "sfx_cues": [{"sfx_id": an id from the sound effect list, "beat": '
    'a beat id, "moment": why it plays, "word_index": the 0-based word of that beat\'s text it '
    "lands on}]}. Write every listed beat once, in order."
)
#: How far past the target length an answer may run before it is refused.
LENGTH_SLACK = 1.25
DESCRIPTION_LIMIT = 500
COMMENT_LIMIT = 200
COMMENTS_SHOWN = 10
TRANSCRIPT_LIMIT = 3000
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?…]\s*$")
#: Punctuation that wraps a token; the curly quotes are written as escapes.
_QUOTES = "\"'()[],;:\u201c\u201d\u2018\u2019"


class ScriptInvalid(ValueError):
    """The model's answer is not a script this draft can use."""


class ScriptFacts(StrictModel):
    """Everything the script may state, taken from the run's Content Set and attribution."""

    title: str = ""
    description: str = ""
    owner_handle: str = ""
    platform: str = ""
    verdict: str = ""
    figures: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)


def _clean(text: str, limit: int) -> str:
    return " ".join(_URL.sub("", text).split())[:limit]


def build_script_request(
    *,
    prompt: str,
    beats: Sequence[BeatId],
    facts: ScriptFacts,
    transcript: Sequence[TranscriptSegment],
    preset: NarrationPreset,
    sfx: Sequence[SfxEntry],
    note: str | None = None,
) -> tuple[str, str]:
    """The system prompt (the stage's prompt plus the contract) and the user message."""
    words = round(preset.target_seconds * preset.words_per_second)
    lines = [
        f"Beats to write, in order: {', '.join(beats)}",
        f"Language: {preset.language}. Length: about {words} words in total "
        f"({preset.target_seconds} seconds).",
        f"Title: {_clean(facts.title, DESCRIPTION_LIMIT)}" if facts.title else "",
        f"Post description: {_clean(facts.description, DESCRIPTION_LIMIT)}"
        if facts.description
        else "",
        f"Creator: @{facts.owner_handle.lstrip('@')} on {facts.platform}"
        if facts.owner_handle
        else "",
        f"Attribution: {facts.verdict}" if facts.verdict else "",
        f"Figures: {', '.join(_clean(name, 120) for name in facts.figures)}"
        if facts.figures
        else "",
    ]
    comments = [_clean(comment, COMMENT_LIMIT) for comment in facts.comments[:COMMENTS_SHOWN]]
    if comments:
        lines.append("Comments:")
        lines += [f"- {comment}" for comment in comments if comment]
    spoken = _clean(" ".join(segment.text for segment in transcript), TRANSCRIPT_LIMIT)
    if spoken:
        lines.append(f"What is said in the video: {spoken}")
    if sfx:
        lines.append(f"Sound effects (at most {preset.max_sfx_cues}):")
        for entry in sfx:
            description = _clean(str(entry.labels.get("description", "")), 160)
            moments = entry.labels.get("moments") or []
            moment_text = ", ".join(str(moment) for moment in moments)
            lines.append(f"- {entry.sfx_id}: {description} ({moment_text})")
    if note:
        lines.append(f"Operator note on the previous script: {_clean(note, 500)}")
    return f"{prompt}\n\n{ANSWER_CONTRACT}", "\n".join(line for line in lines if line)


def parse_script(
    answer: object,
    *,
    beats: Sequence[BeatId],
    preset: NarrationPreset,
    sfx_ids: set[str],
) -> NarrationScript:
    if not isinstance(answer, dict):
        raise ScriptInvalid("not an object")
    raw_beats = answer.get("beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise ScriptInvalid("no beats")
    allowed = set(beats)
    for item in raw_beats:
        if not isinstance(item, dict) or item.get("beat") not in allowed:
            raise ScriptInvalid("unknown beat")
    ordered = sorted(raw_beats, key=lambda item: BEAT_ORDER.index(item["beat"]))
    cues = answer.get("sfx_cues") or []
    if not isinstance(cues, list) or len(cues) > preset.max_sfx_cues:
        raise ScriptInvalid("too many sound effects")
    try:
        script = NarrationScript.model_validate(
            {
                "beats": [
                    {"beat": item["beat"], "text": str(item.get("text", "")).strip()}
                    for item in ordered
                ],
                "sfx_cues": cues,
            }
        )
    except ValidationError as error:
        raise ScriptInvalid("not a script") from error
    written = {beat.beat for beat in script.beats}
    for cue in script.sfx_cues:
        if cue.sfx_id not in sfx_ids or cue.beat not in written:
            raise ScriptInvalid("unknown sound effect")
    words = sum(len(beat.text.split()) for beat in script.beats)
    if words > preset.target_seconds * preset.words_per_second * LENGTH_SLACK:
        raise ScriptInvalid("too long")
    return script


def _fold(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower().lstrip("@"))


def unsupported_tokens(
    script: NarrationScript, facts: ScriptFacts, transcript: Sequence[TranscriptSegment]
) -> dict[BeatId, list[str]]:
    """Per beat: every number, @handle and mid-sentence capitalised word the evidence lacks."""
    evidence_text = " ".join(
        [
            facts.title,
            facts.description,
            facts.owner_handle,
            facts.platform,
            facts.verdict,
            *facts.figures,
            *facts.comments,
            *(segment.text for segment in transcript),
        ]
    )
    words = {_fold(token) for token in evidence_text.split()} - {""}
    numbers = {re.sub(r"\D", "", token) for token in re.findall(r"\d[\d.,]*", evidence_text)}
    found: dict[BeatId, list[str]] = {}
    for beat in script.beats:
        missing: list[str] = []
        sentence_start = True
        for token in beat.text.split():
            stripped = token.strip(_QUOTES)
            if re.fullmatch(r"\d[\d.,]*", stripped.rstrip(".!?")):
                if re.sub(r"\D", "", stripped) not in numbers:
                    missing.append(stripped.rstrip(".!?"))
            elif stripped.startswith("@"):
                if _fold(stripped.rstrip(".!?")) not in words:
                    missing.append(stripped.rstrip(".!?,"))
            elif stripped[:1].isupper() and not sentence_start:
                name = stripped.rstrip(".!?")
                if _fold(name) not in words:
                    missing.append(name)
            sentence_start = bool(_SENTENCE_END.search(token))
        if missing:
            found[beat.beat] = missing
    return found


def facts_from_materials(materials: Any, context: tuple[str, str] | None) -> ScriptFacts:
    """The script's facts from Story mode's materials and the run's title and description."""
    main = next((item for item in materials.items if item.role == "main"), None)
    comments = [
        item.label
        for item in materials.items
        if item.role in {"comment", "comment_card"} and item.label
    ]
    title, description = context or ("", "")
    return ScriptFacts(
        title=title,
        description=description,
        owner_handle=(main.owner_handle or "") if main else "",
        platform=(main.platform or "") if main else "",
        verdict=(main.verdict or "") if main else "",
        figures=[figure.name for figure in materials.figures],
        comments=comments,
    )
