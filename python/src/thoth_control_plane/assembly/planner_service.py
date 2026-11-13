"""The planner (spec 2026-11-13, 5): a draft's plan, built once and kept.

For each voiced beat the narration is split into phrases. A beat whose words are unchanged keeps
its stored picks without a call. Otherwise the draft's candidates are gathered (the timeline's
videos, the Materials' footage and cards), each video is cut into shots (cached by checksum), the
main video's speech is matched to phrases (soundbites, free), and one model call answers the rest.
Any failure gives no plan, and the narration falls back to the phrase-start rhythm.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from thoth_control_plane.assembly.adapters.planner_model import (
    PhraseAnswer,
    PhraseAsk,
    PlannerUnavailable,
)
from thoth_control_plane.assembly.planner_shots import (
    card_sheet,
    contact_sheets,
    detect_shots,
    keyframes,
)
from thoth_control_plane.domain.edit_document_v2 import AssetRef, EditDocumentV2, TimelineVideoClip
from thoth_control_plane.domain.planner import (
    BeatPlan,
    DraftPlan,
    PlanCard,
    PlanPhrase,
    PlanShot,
    reuse_picks,
    shot_speech,
    soundbite,
    split_phrases,
    words_key,
)
from thoth_control_plane.domain.studio_imports import StudioMaterials

logger = logging.getLogger(__name__)

CARD_ROLES = ("post_card", "comment_card")
FetchAsset = Callable[[str, str, Path], Awaitable[tuple[Path, AssetRef] | None]]


class Planner:
    def __init__(
        self,
        store: Any,
        fetch_asset: FetchAsset,
        model: Any | None,
        ffmpeg: str,
        ffprobe: str,
        *,
        detect: Callable[..., Awaitable[list[tuple[float, float]]]] = detect_shots,
        frames: Callable[..., Awaitable[list[Path]]] = keyframes,
    ) -> None:
        self._store = store
        self._fetch = fetch_asset
        self._model = model
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._detect = detect
        self._frames = frames

    async def plan(
        self,
        project_id: str,
        document_id: str,
        document: EditDocumentV2,
        materials: StudioMaterials,
        voices: Sequence[Any],
    ) -> DraftPlan | None:
        """The draft's plan, stored before it is returned; None when it cannot be made."""
        try:
            return await self._plan(project_id, document_id, document, materials, voices)
        except Exception as error:
            logger.warning(
                "planner unavailable; cutting on phrases only error=%s", type(error).__name__
            )
            return None

    async def _plan(
        self,
        project_id: str,
        document_id: str,
        document: EditDocumentV2,
        materials: StudioMaterials,
        voices: Sequence[Any],
    ) -> DraftPlan:
        stored = await self._store.get_plan(document_id)
        kept = {beat.beat: beat for beat in stored.beats} if stored else {}
        if stored is not None and stored.model is None and self._model is not None:
            # Made while no model answered (busy, or before a key): ask again now one may.
            kept = {}
        reused: dict[str, BeatPlan] = {}
        fresh: list[Any] = []
        for voice in voices:
            key = words_key(voice.words)
            ranges = split_phrases(voice.words)
            old = kept.get(voice.beat)
            if old is not None and old.words_key == key:
                phrases = reuse_picks(old, ranges, voice.words)
                reused[voice.beat] = BeatPlan(beat=voice.beat, words_key=key, phrases=phrases)
            else:
                fresh.append(voice)
        if stored is not None and not fresh:
            plan = stored.model_copy(update={"beats": [reused[v.beat] for v in voices]})
            logger.info("planner reused the stored plan beats=%d", len(reused))
            await self._store.set_plan(document_id, plan)
            return plan

        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            shots, cards, assets, files, sources = await self._candidates(
                project_id, document_id, document, materials, directory, stored if reused else None
            )
            mains = [shot for shot in shots if shot.source == "main"]
            beats: dict[str, BeatPlan] = dict(reused)
            asks: list[tuple[str, PlanPhrase]] = []
            number = 0
            for voice in fresh:
                phrases = []
                for first, last in split_phrases(voice.words):
                    number += 1
                    text = " ".join(word.text for word in voice.words[first : last + 1])
                    heard = soundbite(text, mains)
                    phrase = PlanPhrase(
                        phrase_id=f"P{number}",
                        first_word=first,
                        last_word=last,
                        text=text,
                        base=heard,
                        soundbite=bool(heard),
                    )
                    phrases.append(phrase)
                    asks.append((voice.beat, phrase))
                beats[voice.beat] = BeatPlan(
                    beat=voice.beat, words_key=words_key(voice.words), phrases=phrases
                )
            answers, model_used = await self._ask(
                shots, cards, files, sources, voices, asks, directory
            )
        # Answers belong to this call's phrases only; a reused beat keeps its picks, less any
        # shot or card the draft no longer has (final review, 2026-11-13).
        by_id = {answer.phrase_id: answer for answer in answers}
        fresh_beats = {voice.beat for voice in fresh}
        shot_ids = {shot.shot_id for shot in shots}
        card_ids = {card.card_id for card in cards}
        beats = {
            name: beat.model_copy(
                update={
                    "phrases": [
                        _merged(p, by_id.get(p.phrase_id))
                        if name in fresh_beats
                        else p.model_copy(
                            update={
                                "base": [x for x in p.base if x in shot_ids],
                                "overlay": p.overlay if p.overlay in card_ids else None,
                            }
                        )
                        for p in beat.phrases
                    ]
                }
            )
            for name, beat in beats.items()
        }
        plan = DraftPlan(
            model=model_used,
            shots=shots,
            cards=cards,
            beats=[beats[v.beat] for v in voices if v.beat in beats],
            assets=assets,
        )
        await self._store.set_plan(document_id, plan)
        logger.info(
            "planner planned phrases=%d soundbites=%d model=%s",
            len(asks),
            sum(p.soundbite for _, p in asks),
            model_used,
        )
        return plan

    async def _candidates(
        self,
        project_id: str,
        document_id: str,
        document: EditDocumentV2,
        materials: StudioMaterials,
        directory: Path,
        previous: DraftPlan | None = None,
    ) -> tuple[list[PlanShot], list[PlanCard], list[AssetRef], dict[str, Path], list[str]]:
        """The draft's shots and cards. With `previous` (a partial re-plan), a shot or card the
        stored plan already named keeps its id, so the reused beats' picks still point at it."""
        old_shots = {
            (s.asset_id, round(s.start_seconds, 3), round(s.end_seconds, 3)): s.shot_id
            for s in (previous.shots if previous else [])
        }
        old_cards = {c.asset_id: c.card_id for c in (previous.cards if previous else [])}
        taken_ids = set(old_shots.values()) | set(old_cards.values())

        def new_id(prefix: str) -> str:
            number = 1
            while f"{prefix}{number}" in taken_ids:
                number += 1
            taken_ids.add(f"{prefix}{number}")
            return f"{prefix}{number}"

        main_tracks = {t.track_id for t in document.tracks if t.kind == "main_video"}
        videos = [c for c in document.clips if isinstance(c, TimelineVideoClip)]
        main = next((c.asset_id for c in videos if c.track_id in main_tracks), None)
        handles = {i.asset_id: i.owner_handle for i in materials.items if i.asset_id}
        footage: list[str] = [
            i.asset_id for i in materials.items if i.role == "footage" and i.asset_id
        ]
        footage += [
            c.asset_id
            for c in videos
            if c.track_id not in main_tracks and c.position is None and c.source_role == "footage"
        ]
        card_items: list[tuple[str, str, str]] = [
            (i.asset_id, i.item_id, i.role)
            for i in materials.items
            if i.role in CARD_ROLES and i.asset_id
        ]
        card_items += [
            (c.asset_id, c.clip_id.removeprefix("clip_"), c.source_role)
            for c in videos
            if c.position is not None and c.source_role in CARD_ROLES
        ]
        transcript = await self._store.get_transcript(document_id)
        shots: list[PlanShot] = []
        assets: list[AssetRef] = []
        files: dict[str, Path] = {}
        sources: list[str] = ["SOURCES:"]
        seen: set[str] = set()
        ordered = [("main", main)] if main else []
        ordered += [("footage", asset_id) for asset_id in footage]
        for kind, asset_id in ordered:
            if asset_id in seen:
                continue
            seen.add(asset_id)
            fetched = await self._fetch(project_id, asset_id, directory)
            if fetched is None or fetched[1].kind != "video":
                continue
            path, ref = fetched
            assets.append(ref)
            spans = await self._store.get_shots(ref.checksum) if ref.checksum else None
            if spans is None:
                spans = await self._detect(path, self._ffmpeg, self._ffprobe)
                if ref.checksum:
                    await self._store.put_shots(ref.checksum, spans)
            label = "MAIN" if kind == "main" else f"F{len(files) + (0 if main else 1)}"
            files[label] = path
            handle = handles.get(asset_id) if kind == "footage" else None
            sources.append(f"- {label}: {kind} video" + (f", from {handle}" if handle else ""))
            for start, end in spans:
                key = (asset_id, round(start, 3), round(end, 3))
                shots.append(
                    PlanShot(
                        shot_id=old_shots.get(key) or new_id("S"),
                        asset_id=asset_id,
                        source=kind,  # type: ignore[arg-type]
                        start_seconds=start,
                        end_seconds=end,
                        said=shot_speech(transcript, start, end) if kind == "main" else "",
                        handle=handle,
                    )
                )
        cards: list[PlanCard] = []
        for asset_id, item_id, role in card_items:
            if asset_id in seen:
                continue
            seen.add(asset_id)
            fetched = await self._fetch(project_id, asset_id, directory)
            if fetched is None or fetched[1].kind != "image":
                continue
            card_id = old_cards.get(asset_id) or new_id("C")
            cards.append(PlanCard(card_id=card_id, asset_id=asset_id, item_id=item_id, kind=role))  # type: ignore[arg-type]
            assets.append(fetched[1])
            files[card_id] = fetched[0]
        if cards:
            sources.append(
                "- CARDS: " + ", ".join(f"{c.card_id} = {c.kind.replace('_', ' ')}" for c in cards)
            )
        said = [f"- {s.shot_id}: {s.said}" for s in shots if s.said]
        if said:
            sources += ["", "WHAT THE MAIN VIDEO SAYS DURING EACH SHOT:", *said]
        return shots, cards, assets, files, sources

    async def _ask(
        self,
        shots: list[PlanShot],
        cards: list[PlanCard],
        files: dict[str, Path],
        sources: list[str],
        voices: Sequence[Any],
        asks: list[tuple[str, PlanPhrase]],
        directory: Path,
    ) -> tuple[list[PhraseAnswer], str | None]:
        if self._model is None or not asks:
            return [], None
        sheets = []
        by_asset: dict[str, list[PlanShot]] = {}
        for shot in shots:
            by_asset.setdefault(shot.asset_id, []).append(shot)
        labels = [label for label in files if not label.startswith("C")]
        for label, group in zip(labels, by_asset.values(), strict=False):
            tiles_dir = directory / f"frames_{label}"
            tiles_dir.mkdir()
            spans = [(s.start_seconds, s.end_seconds) for s in group]
            frames = await self._frames(files[label], spans, self._ffmpeg, tiles_dir)
            sheets += contact_sheets(
                label, list(zip([s.shot_id for s in group], frames, strict=True))
            )
        cards_jpeg = card_sheet([(c.card_id, files[c.card_id]) for c in cards])
        script = "\n".join(f"[{v.beat}] " + " ".join(word.text for word in v.words) for v in voices)
        try:
            answers = await self._model.ask(
                "\n".join(sources),
                sheets,
                cards_jpeg,
                script,
                [PhraseAsk(p.phrase_id, beat, p.text) for beat, p in asks],
                {s.shot_id for s in shots},
                {c.card_id for c in cards},
            )
        except PlannerUnavailable:
            logger.warning("planner model unavailable; soundbites only")
            return [], None
        return answers, self._model.model_used


def _merged(phrase: PlanPhrase, answer: PhraseAnswer | None) -> PlanPhrase:
    """A soundbite keeps its base; the model's card still sits on top of it."""
    if answer is None:
        return phrase
    base = phrase.base if phrase.soundbite else answer.base
    return phrase.model_copy(update={"base": base, "overlay": answer.overlay, "why": answer.why})
