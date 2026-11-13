"""Planner stage 1: the service that builds and keeps a draft's plan (spec 2026-11-13, 5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.assembly.test_narration_timeline import draft
from thoth_control_plane.assembly.adapters.planner_model import (
    PhraseAnswer,
    PlannerUnavailable,
)
from thoth_control_plane.assembly.narration_timeline import VoicedBeat
from thoth_control_plane.assembly.planner_service import Planner
from thoth_control_plane.domain.edit_document_v2 import AssetRef
from thoth_control_plane.domain.narration import TranscriptSegment
from thoth_control_plane.domain.planner import BeatPlan, DraftPlan, PlanPhrase, words_key
from thoth_control_plane.domain.studio_imports import StudioMaterial, StudioMaterials
from thoth_control_plane.voice.ports import WordTiming

DOC = "edoc_planner"


def words(text: str, step: float = 0.5, start: float = 0.0) -> list[WordTiming]:
    return [
        WordTiming(text=token, start_seconds=start + i * step, end_seconds=start + i * step + 0.4)
        for i, token in enumerate(text.split())
    ]


def voice(beat: str, text: str, step: float = 0.5) -> VoicedBeat:
    spoken = words(text, step)
    return VoicedBeat(
        beat=beat,  # type: ignore[arg-type]
        asset=AssetRef(
            asset_id=f"asset_voice_{beat}",
            project_id="project_001",
            kind="audio",
            duration_in_frames=300,
            has_audio=True,
            validation_state="ready",
        ),
        duration_seconds=spoken[-1].end_seconds,
        words=spoken,
    )


class Store:
    def __init__(self, plan: DraftPlan | None = None, shots: dict[str, Any] | None = None) -> None:
        self.plan = plan
        self.shots = shots or {}
        self.saved: list[DraftPlan] = []
        self.transcript = [
            TranscriptSegment(text="Penjilat nasional.", start_seconds=0.0, end_seconds=3.0)
        ]

    async def get_plan(self, _doc: str) -> DraftPlan | None:
        return self.plan

    async def set_plan(self, _doc: str, plan: DraftPlan) -> None:
        self.saved.append(plan)
        self.plan = plan

    async def get_shots(self, checksum: str) -> list[tuple[float, float]] | None:
        return self.shots.get(checksum)

    async def put_shots(self, checksum: str, spans: list[tuple[float, float]]) -> None:
        self.shots.setdefault(checksum, spans)

    async def get_transcript(self, _doc: str) -> list[TranscriptSegment]:
        return self.transcript


def ref(asset_id: str, kind: str = "video", frames: int | None = 900) -> AssetRef:
    return AssetRef(
        asset_id=asset_id,
        project_id="project_001",
        kind=kind,  # type: ignore[arg-type]
        duration_in_frames=frames if kind == "video" else None,
        has_audio=kind == "video",
        validation_state="ready",
        checksum="sha256:" + (asset_id.encode().hex() + "0" * 64)[:64],
    )


class Fetcher:
    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def __call__(
        self, _project: str, asset_id: str, directory: Path
    ) -> tuple[Path, AssetRef]:
        from PIL import Image

        self.fetched.append(asset_id)
        kind = "image" if asset_id.startswith(("asset_card", "asset_post")) else "video"
        path = directory / f"{asset_id}.{'png' if kind == 'image' else 'mp4'}"
        if kind == "image":
            Image.new("RGB", (60, 40), (200, 200, 200)).save(path)
        else:
            path.write_bytes(b"x")
        return path, ref(asset_id, kind)


class Model:
    def __init__(self, answers: list[PhraseAnswer] | None = None, fail: bool = False) -> None:
        self.answers = answers or []
        self.fail = fail
        self.calls: list[dict[str, Any]] = []
        self.model_used: str | None = None

    async def ask(self, sources, sheets, cards, script, phrases, shot_ids, card_ids):  # type: ignore[no-untyped-def]
        self.calls.append({"phrases": phrases, "shot_ids": shot_ids, "card_ids": card_ids})
        if self.fail:
            raise PlannerUnavailable()
        self.model_used = "cheap/model"
        return self.answers


class Detect:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self, _video: Path, _ffmpeg: str, _ffprobe: str
    ) -> list[tuple[float, float]]:
        self.calls += 1
        return [(0.0, 3.0), (3.0, 6.0)]


async def frames(_video: Path, spans, _ffmpeg: str, directory: Path) -> list[Path]:  # type: ignore[no-untyped-def]
    out = []
    for index, _ in enumerate(spans):
        path = directory / f"f{index}.jpg"
        from PIL import Image

        Image.new("RGB", (40, 60), (10, 20, 30)).save(path)
        out.append(path)
    return out


MATERIALS = StudioMaterials(
    document_id=DOC,
    provenance_available=True,
    items=[
        StudioMaterial(
            item_id="footage_000",
            role="footage",
            label="@kompas",
            media_kind="video",
            disposition="attached",
            asset_id="asset_vid_long",
            owner_handle="@kompascomreport",
        ),
        StudioMaterial(
            item_id="post_card_000",
            role="post_card",
            label="post",
            media_kind="image",
            disposition="attached",
            asset_id="asset_post",
        ),
    ],
)


def planner(store: Store, model: Model | None, detect: Detect | None = None) -> Planner:
    return Planner(
        store, Fetcher(), model, "ffmpeg", "ffprobe", detect=detect or Detect(), frames=frames
    )


async def make(store: Store, model: Model | None, voices: list[VoicedBeat], detect=None):  # type: ignore[no-untyped-def]
    return await planner(store, model, detect).plan("project_001", DOC, draft(), MATERIALS, voices)


async def test_model_answers_fill_the_plan() -> None:
    store = Store()
    model = Model([PhraseAnswer("P1", ["S3"], "C1", "terlihat")])
    plan = await make(store, model, [voice("main", "Rocky kena semprot warga hari ini")])
    assert plan is not None and store.saved == [plan] and plan.model == "cheap/model"
    first = plan.beats[0].phrases[0]
    assert (first.base, first.overlay, first.soundbite) == (["S3"], "C1", False)
    assert {s.source for s in plan.shots} == {"main", "footage"}
    footage = next(s for s in plan.shots if s.source == "footage")
    assert footage.handle == "@kompascomreport"


async def test_unchanged_words_reuse_the_plan_without_a_call() -> None:  # Review Focus 2
    text = "Rocky kena semprot warga hari ini"
    stored = DraftPlan(
        model="cheap/model",
        beats=[
            BeatPlan(
                beat="main",
                words_key=words_key(words(text)),
                phrases=[
                    PlanPhrase(phrase_id="P1", first_word=0, last_word=5, text=text, base=["S3"])
                ],
            )
        ],
    )
    store, model = Store(plan=stored), Model()
    plan = await make(store, model, [voice("main", text, step=0.3)])  # new timing, same words
    assert model.calls == []
    assert plan is not None and plan.beats[0].phrases[0].base == ["S3"]


async def test_model_unavailable_keeps_soundbites() -> None:
    store, model = Store(), Model(fail=True)
    plan = await make(store, model, [voice("main", "dan disebut penjilat nasional. Lalu apa lagi")])
    assert plan is not None and plan.model is None
    phrases = plan.beats[0].phrases
    assert phrases[0].soundbite and phrases[0].base == ["S1"]
    assert all(not p.base for p in phrases[1:])


async def test_no_model_still_plans_soundbites() -> None:
    plan = await make(
        Store(), None, [voice("main", "dan disebut penjilat nasional. Lalu apa lagi")]
    )
    assert plan is not None and plan.beats[0].phrases[0].base == ["S1"]


async def test_shots_come_from_the_cache_by_checksum() -> None:
    cached = {
        ref("asset_main").checksum: [(0.0, 9.0)],
        ref("asset_vid_long").checksum: [(0.0, 4.0)],
    }
    detect = Detect()
    plan = await make(Store(shots=cached), Model(), [voice("main", "satu dua tiga")], detect)
    assert detect.calls == 0
    assert plan is not None and [(s.start_seconds, s.end_seconds) for s in plan.shots] == [
        (0.0, 9.0),
        (0.0, 4.0),
    ]


async def test_the_post_card_from_materials_is_a_candidate() -> None:
    model = Model()
    plan = await make(Store(), model, [voice("main", "satu dua tiga")])
    assert plan is not None
    assert ("post_card_000", "post_card") in {(c.item_id, c.kind) for c in plan.cards}
    assert "asset_post" in {a.asset_id for a in plan.assets}
    assert {c.card_id for c in plan.cards} == model.calls[0]["card_ids"]


async def test_a_failure_inside_the_planner_gives_no_plan() -> None:
    class Broken(Store):
        async def get_transcript(self, _doc: str) -> list[TranscriptSegment]:
            raise RuntimeError("store down")

    assert await make(Broken(), Model(), [voice("main", "satu dua tiga")]) is None


async def test_a_partial_replan_keeps_the_unchanged_beats_picks() -> None:
    hook_text = "Bung Rocky kena semprot"
    first_store, first_model = Store(), Model([PhraseAnswer("P1", ["S3"], None, "a")])
    first = await make(
        first_store, first_model, [voice("hook", hook_text), voice("main", "satu dua tiga")]
    )
    assert first is not None and first.beats[0].phrases[0].base == ["S3"]
    model = Model([PhraseAnswer("P1", ["S4"], None, "b")])
    plan = await make(
        Store(plan=first), model, [voice("hook", hook_text), voice("main", "empat lima enam")]
    )
    assert plan is not None
    assert [p.text for p in model.calls[0]["phrases"]] == ["empat lima enam"]
    hook, main = plan.beats
    assert hook.phrases[0].base == ["S3"] and main.phrases[0].base == ["S4"]
    assert [(s.shot_id, s.asset_id, s.start_seconds) for s in plan.shots] == [
        (s.shot_id, s.asset_id, s.start_seconds) for s in first.shots
    ]


async def test_a_plan_made_without_a_model_is_planned_again_once_one_answers() -> None:
    text = "Rocky kena semprot warga hari ini"
    stored = DraftPlan(
        model=None,
        beats=[
            BeatPlan(
                beat="main",
                words_key=words_key(words(text)),
                phrases=[PlanPhrase(phrase_id="P1", first_word=0, last_word=5, text=text)],
            )
        ],
    )
    model = Model([PhraseAnswer("P1", ["S3"], None, "a")])
    plan = await make(Store(plan=stored), model, [voice("main", text)])
    assert len(model.calls) == 1
    assert plan is not None and plan.beats[0].phrases[0].base == ["S3"]
