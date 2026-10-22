"""FootageBuilder: order, quota, rejections, resume (spec 2026-10-14, F1-F9 and section 8)."""

from __future__ import annotations

import asyncio
import copy
import gc
import hashlib
import json
import logging
import time
import zlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from tests.acquisition.png_fixtures import make_png
from tests.assembly.support import FIXTURE
from tests.assembly.support import report as support_report
from thoth_control_plane.acquisition.models import DiscoveredPhoto, DiscoveredVideo, SourceReport
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.attribution.adapters.discovery import CreatorListing
from thoth_control_plane.attribution.ports import AttributionError, Frame
from thoth_control_plane.footage.adapters.downloader import ClipError
from thoth_control_plane.footage.adapters.vision import FootageAnswer
from thoth_control_plane.footage.models import SearchBatch
from thoth_control_plane.footage.queries import FootageQueryAnswer
from thoth_control_plane.footage.service import (
    FootageBuilder,
    FootageInputs,
    FootagePorts,
    select_batch,
)
from thoth_control_plane.infrastructure.footage_store import FootageStore
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def _report(*, slides: int = 0) -> SourceReport:
    """A TikTok main without media, or an Instagram carousel main with `slides` videos."""
    if not slides:
        return support_report(
            url="https://www.tiktok.com/@akun/video/7499999999999999999",
            owner="akun",
            text="Banjir besar di Kemang pagi ini",
            media="none",
        )
    data = copy.deepcopy(FIXTURE)
    data["workflow_id"] = "wf_a"
    data["source"] = {
        "platform": "instagram",
        "canonical_url": "https://www.instagram.com/p/MAIN1/",
    }
    data["post"].update(owner_handle="akun", text="Banjir besar di Kemang pagi ini")
    video = data["media"][0]
    data["media"] = [
        video
        | {"media_id": f"media_{n}", "index": n, "location": f"reports/wf_a/media/slide-{n}.mp4"}
        for n in range(1, slides + 1)
    ]
    data["comments"] = []
    return SourceReport.model_validate_json(json.dumps(data))


def _video(
    n: int,
    caption: str = "air naik di jalan kemang",
    duration: float = 20.0,
    owner: str = "kreator",
) -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=f"74000000000000000{n:02d}",
        owner_handle=owner,
        canonical_url=f"https://www.tiktok.com/@{owner}/video/74000000000000000{n:02d}",
        caption=caption,
        duration_seconds=duration,
    )


class Queries:
    def __init__(self, answer: FootageQueryAnswer | None) -> None:
        self.answer = answer
        self.calls = 0

    async def read(self, prompt: str) -> FootageQueryAnswer | None:
        self.calls += 1
        return self.answer


TWO_OBJECTS = FootageQueryAnswer.model_validate(
    {
        "subjects": ["kemang"],
        "objects": [
            {"name": "banjir", "visual": "a flooded street"},
            {"name": "mobil terendam", "visual": "cars under water"},
        ],
    }
)


class Search:
    """PlatformSearch's contract: one call per platform with the run's uncached queries."""

    def __init__(
        self,
        results: dict[tuple[str, str], list[DiscoveredVideo]] | None = None,
        fail: set[str] | None = None,
    ) -> None:
        self.results = results or {}
        self.fail = fail or set()
        self.calls: list[tuple[str, str]] = []

    async def search(self, platform: str, queries: Sequence[str], limit: int) -> SearchBatch:
        self.calls.extend((platform, query) for query in queries)
        if platform in self.fail:
            return SearchBatch(found={}, failed=True)
        found = {
            query: self.results.get((platform, query), [])
            for query in queries
            if "\x00" not in query  # PlatformSearch skips a query KeywordDiscovery refuses
        }
        return SearchBatch(found=found, failed=False)


class Embedder:
    """Scores by keyword: a caption with 'kemang' is on the story, else off."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "kemang" in text.lower() else [0.0, 1.0] for text in texts]


class Downloader:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[tuple[str, Any]] = []

    async def download(self, url: str, window: Any, target: Path) -> Path:
        self.calls.append((url, window))
        if url in self.fail:
            raise ClipError("network")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(url.encode() * 50)
        return target


class Frames:
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        return Frame(second=second, jpeg=_jpeg_for(video))


def _jpeg_for(video: Path) -> bytes:
    import cv2
    import numpy as np

    seed = zlib.crc32(video.read_bytes()) if video.exists() else 0
    image = np.random.default_rng(seed).integers(0, 255, (90, 160, 3), dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


class Probe:
    async def duration(self, video: Path) -> float:
        return 20.0


class Text:
    def __init__(self, subtitled: set[str] | None = None) -> None:
        self.subtitled = subtitled or set()

    async def read(self, frame: Frame) -> list[Any]:
        return []


class Judge:
    def __init__(self, answers: dict[str, FootageAnswer | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[str] = []
        self.people: list[bool] = []

    async def judge(
        self, frames: Sequence[Frame], visual: str, *, person: bool = False
    ) -> FootageAnswer:
        key = visual
        self.calls.append(key)
        self.people.append(person)
        answer = self.answers.get(
            key, FootageAnswer(kind="footage", shows_object="yes", description="A flooded street.")
        )
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def store(tmp_path: Path) -> FootageStore:
    # A file database: the builder calls the store from several threads at once (to_thread under
    # gather), which one shared in-memory connection cannot serve; PostgreSQL pools connections.
    engine = create_engine(f"sqlite:///{tmp_path / 'footage.db'}")
    Base.metadata.create_all(engine)
    return FootageStore(engine, clock=lambda: NOW)


def _builder(
    store: FootageStore,
    *,
    deadline_seconds: float = 720.0,
    per_candidate_seconds: float = 90.0,
    grace_seconds: float = 10.0,
    overrun_seconds: float = 120.0,
    **ports: Any,
) -> FootageBuilder:
    values: dict[str, Any] = {
        "queries": Queries(TWO_OBJECTS),
        "search": Search(),
        "embedder": Embedder(),
        "downloader": Downloader(),
        "frames": Frames(),
        "probe": Probe(),
        "text": Text(),
        "judge": Judge(),
        "store": store,
    }
    values.update(ports)
    return FootageBuilder(
        FootagePorts(**values),
        aggregators=frozenset({"kurator"}),
        story_min=0.33,
        max_frames=4,
        clock=lambda: NOW,
        deadline_seconds=deadline_seconds,
        per_candidate_seconds=per_candidate_seconds,
        grace_seconds=grace_seconds,
        overrun_seconds=overrun_seconds,
    )


def _inputs(tmp_path: Path, report: SourceReport | None = None) -> FootageInputs:
    return FootageInputs(
        workflow_id="wf_a",
        report=report or _report(),
        attribution=None,
        original=None,
        artifact_root=tmp_path,
    )


def _hits(
    *videos: DiscoveredVideo, query: str = "banjir kemang"
) -> dict[tuple[str, str], list[DiscoveredVideo]]:
    return {("tiktok", query): list(videos)}


def test_select_batch_rounds_across_queries_and_respects_the_caps() -> None:
    from collections import Counter

    from thoth_control_plane.footage.models import CandidateView

    def view(url: str, query: str) -> CandidateView:
        return CandidateView(
            url=url,
            platform="tiktok",
            source="search",
            query=query,
            visual="v",
            owner_handle="o",
            caption="",
            published_at=None,
            engagement={},
            source_duration=None,
            status="pending",
            reason=None,
            story_score=0.5,
            kind=None,
            shows_object=None,
            description=None,
            media_location=None,
            media_checksum=None,
            media_bytes=None,
            clip_duration=None,
            clip_start=None,
            ocr=None,
            position=None,
        )

    queues = {"a": [view("a1", "a"), view("a2", "a"), view("a3", "a")], "b": [view("b1", "b")]}
    batch = select_batch(queues, Counter({"a": 1}), total=1, size=3)
    # The least-served query goes first; a holds one admitted, so it has one more slot only.
    assert [c.url for c in batch] == ["b1", "a1"]
    assert [c.url for c in queues["a"]] == ["a2", "a3"]
    # Spec F6: every query gets its first turn before any gets a second, across batches too.
    four = {q: [view(f"{q}1", q), view(f"{q}2", q)] for q in "abcd"}
    served = Counter({"a": 1, "b": 1, "c": 1})
    assert [c.url for c in select_batch(four, served, total=3, size=3)] == ["d1", "a1", "b1"]
    assert select_batch({"a": [view("x", "a")]}, Counter(), total=6, size=3) == []


async def test_text_gates_and_story_gate_touch_no_media(
    store: FootageStore, tmp_path: Path
) -> None:
    downloader, judge = Downloader(), Judge()
    search = Search(
        _hits(
            _video(1, caption="reaction banjir kemang"),
            _video(2, caption="https://bit.ly/x kemang"),
            _video(3, caption="resep nasi goreng"),
            _video(4, owner="kurator", caption="banjir kemang"),
            _video(5, caption="banjir kemang", duration=2.0),
        )
    )
    result = await _builder(store, search=search, downloader=downloader, judge=judge).build(
        _inputs(tmp_path)
    )
    assert result.status == "none"
    assert result.rejected == {
        "reaction_text": 1,
        "spam": 1,
        "story": 1,
        "aggregator": 1,
        "duration": 1,
    }
    assert downloader.calls == [] and judge.calls == []


async def test_quota_two_per_query_six_in_total(store: FootageStore, tmp_path: Path) -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": ["kemang"],
            "objects": [{"name": f"objek{n}", "visual": f"visual {n}"} for n in range(4)],
        }
    )
    results = {
        ("tiktok", f"objek{n} kemang"): [_video(n * 10 + k) for k in range(3)] for n in range(4)
    }
    downloader = Downloader()
    result = await _builder(
        store, queries=Queries(answer), search=Search(results), downloader=downloader
    ).build(_inputs(tmp_path))
    assert result.status == "ok" and result.admitted == 6
    admitted = store.admitted("wf_a")
    per_query: dict[str, int] = {}
    for c in admitted:
        per_query[c.query] = per_query.get(c.query, 0) + 1
    assert max(per_query.values()) <= 2
    assert set(per_query) == {f"objek{n} kemang" for n in range(4)}  # no query starved
    assert [c.position for c in admitted] == list(range(6))
    assert len(downloader.calls) == 6  # stopped once six were admitted


async def test_commentary_absent_object_and_vision_failure_are_rejected(
    store: FootageStore, tmp_path: Path
) -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": ["kemang"],
            "objects": [
                {"name": "a", "visual": "talking"},
                {"name": "b", "visual": "absent"},
                {"name": "c", "visual": "broken"},
            ],
        }
    )
    results = {
        ("tiktok", "a kemang"): [_video(1)],
        ("tiktok", "b kemang"): [_video(2)],
        ("tiktok", "c kemang"): [_video(3)],
    }
    judge = Judge(
        {
            "talking": FootageAnswer(
                kind="commentary", shows_object="yes", description="A man talks."
            ),
            "absent": FootageAnswer(kind="footage", shows_object="no", description="A cat."),
            "broken": AttributionError("vision_unavailable"),
        }
    )
    result = await _builder(
        store, queries=Queries(answer), search=Search(results), judge=judge
    ).build(_inputs(tmp_path))
    assert result.status == "none"
    assert result.rejected == {"commentary": 1, "object_absent": 1, "vision_unavailable": 1}
    # Rejected windows are deleted.
    assert list((tmp_path / "reports" / "wf_a" / "footage").glob("*.mp4")) == []


async def test_a_failed_download_is_media_failed(store: FootageStore, tmp_path: Path) -> None:
    video = _video(1)
    result = await _builder(
        store,
        search=Search(_hits(video)),
        downloader=Downloader({str(video.canonical_url)}),
    ).build(_inputs(tmp_path))
    assert result.rejected == {"media_failed": 1}


async def test_a_subtitled_clip_is_rejected_and_deleted(
    store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.footage import service

    async def subtitled(*args: Any, **kwargs: Any) -> Any:
        from thoth_control_plane.assembly.models import MainOcr

        return MainOcr(
            analyzed_at=NOW,
            requested_frames=4,
            valid_frames=4,
            outcome="subtitle",
            trim_start=0.0,
            mute_audio=True,
            subtitle_blur=[{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}],
        )

    monkeypatch.setattr(service, "analyze_main_ocr", subtitled)
    judge = Judge()
    result = await _builder(store, search=Search(_hits(_video(1))), judge=judge).build(
        _inputs(tmp_path)
    )
    assert result.rejected == {"subtitle": 1} and judge.calls == []
    assert list((tmp_path / "reports" / "wf_a" / "footage").glob("*.mp4")) == []


async def test_incomplete_ocr_is_media_failed_but_a_missing_tool_raises(
    store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.footage import service

    async def incomplete(*args: Any, **kwargs: Any) -> Any:
        raise AssemblyError("incomplete_frame_coverage")

    monkeypatch.setattr(service, "analyze_main_ocr", incomplete)
    result = await _builder(store, search=Search(_hits(_video(1)))).build(_inputs(tmp_path))
    assert result.rejected == {"media_failed": 1}

    async def no_ffmpeg(*args: Any, **kwargs: Any) -> Any:
        raise AssemblyError("ffmpeg_missing")

    monkeypatch.setattr(service, "analyze_main_ocr", no_ffmpeg)
    with pytest.raises(AssemblyError, match="ffmpeg_missing"):
        await _builder(store, search=Search(_hits(_video(2)))).build(
            FootageInputs(
                workflow_id="wf_b",
                report=_report(),
                attribution=None,
                original=None,
                artifact_root=tmp_path,
            )
        )


async def test_a_duplicate_of_an_admitted_clip_is_rejected(
    store: FootageStore, tmp_path: Path
) -> None:
    # Two different URLs whose downloaded bytes (and so frames) are identical.
    class Same(Downloader):
        async def download(self, url: str, window: Any, target: Path) -> Path:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"same" * 50)
            return target

    result = await _builder(
        store, search=Search(_hits(_video(1), _video(2))), downloader=Same()
    ).build(_inputs(tmp_path))
    assert result.admitted == 1 and result.rejected == {"duplicate": 1}


async def test_all_platforms_failing_is_unavailable(store: FootageStore, tmp_path: Path) -> None:
    result = await _builder(store, search=Search(fail={"tiktok", "youtube", "x"})).build(
        _inputs(tmp_path)
    )
    assert result.status == "unavailable"


async def test_one_platform_failing_leaves_the_others(store: FootageStore, tmp_path: Path) -> None:
    result = await _builder(store, search=Search(_hits(_video(1)), fail={"x"})).build(
        _inputs(tmp_path)
    )
    assert result.status == "ok"


async def test_no_query_answer_twice_is_unavailable(store: FootageStore, tmp_path: Path) -> None:
    queries = Queries(None)
    result = await _builder(store, queries=queries).build(_inputs(tmp_path))
    assert result.status == "unavailable" and queries.calls == 2


async def test_an_invalid_query_is_skipped(store: FootageStore, tmp_path: Path) -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": [],
            "objects": [
                {"name": "bad\x00query", "visual": "x"},
                {"name": "banjir kemang", "visual": "a flooded street"},
            ],
        }
    )
    result = await _builder(store, queries=Queries(answer), search=Search(_hits(_video(1)))).build(
        _inputs(tmp_path)
    )
    assert result.status == "ok"
    run = store.run("wf_a")
    assert run is not None and [o.query for o in run.objects] == ["banjir kemang"]


async def test_one_url_found_twice_is_one_candidate(store: FootageStore, tmp_path: Path) -> None:
    video = _video(1)
    results = {
        ("tiktok", "banjir kemang"): [video],
        ("youtube", "banjir kemang"): [video],
        ("tiktok", "mobil terendam kemang"): [video],
    }
    await _builder(store, search=Search(results)).build(_inputs(tmp_path))
    assert len(store.candidates("wf_a")) == 1


async def test_a_retry_redoes_pending_and_keeps_admitted(
    store: FootageStore, tmp_path: Path
) -> None:
    search = Search(_hits(_video(1), _video(2)))
    queries = Queries(TWO_OBJECTS)
    await _builder(store, search=search, queries=queries).build(_inputs(tmp_path))
    first = store.admitted("wf_a")

    # Simulate a crash: the run is not done, one admitted file vanished, a .part lingers.
    from thoth_control_plane.infrastructure.footage_models import FootageRunRow

    with store._sessions.begin() as session:  # test-only rewind
        session.get(FootageRunRow, "wf_a").status = "running"
    (tmp_path / first[0].media_location).unlink()
    stale = tmp_path / "reports" / "wf_a" / "footage" / "stale.mp4.part"
    stale.write_bytes(b"x")
    scratch = tmp_path / "reports" / "wf_a" / "footage" / "thoth-footage-abc123"
    scratch.mkdir()
    (scratch / "clip.mp4.part").write_bytes(b"x")

    search.calls.clear()
    judge = Judge()
    result = await _builder(store, search=search, queries=queries, judge=judge).build(
        _inputs(tmp_path)
    )
    assert queries.calls == 1  # the objects were reused
    assert search.calls == []  # the cache answered
    assert result.status == "ok"
    assert len(judge.calls) == 1  # only the reopened candidate was checked again
    assert not stale.exists() and not scratch.exists()


async def test_a_done_run_is_not_redone(store: FootageStore, tmp_path: Path) -> None:
    queries = Queries(TWO_OBJECTS)
    await _builder(store, search=Search(_hits(_video(1))), queries=queries).build(_inputs(tmp_path))
    again = await _builder(store, queries=queries).build(_inputs(tmp_path))
    assert again.status == "ok" and queries.calls == 1


async def test_a_main_without_video_still_gets_footage(store: FootageStore, tmp_path: Path) -> None:
    report = _report()
    assert not [m for m in report.media if m.kind == "video"]
    result = await _builder(store, search=Search(_hits(_video(1)))).build(_inputs(tmp_path, report))
    assert result.status == "ok"


async def test_a_carousel_main_uses_its_own_video_slides(
    store: FootageStore, tmp_path: Path
) -> None:
    for index in (1, 2, 3, 4):
        location = tmp_path / f"reports/wf_a/media/slide-{index}.mp4"
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(bytes([index]) * 20_000)
    search, downloader = Search(), Downloader()
    result = await _builder(store, search=search, downloader=downloader).build(
        _inputs(tmp_path, _report(slides=4))
    )
    # Three slides after the main, all from one "query": the per-query cap of two does not apply.
    assert result.admitted == 3 and search.calls == [] and downloader.calls == []
    admitted = store.admitted("wf_a")
    assert {c.source for c in admitted} == {"carousel"}
    assert all(c.url.startswith("https://www.instagram.com/p/MAIN1/#slide") for c in admitted)
    assert all(c.story_score == 1.0 for c in admitted)


def _window(tmp_path: Path, video: DiscoveredVideo) -> Path:
    name = hashlib.sha256(str(video.canonical_url).encode()).hexdigest()[:20] + ".mp4"
    return tmp_path / "reports" / "wf_a" / "footage" / name


THREE_OBJECTS = FootageQueryAnswer.model_validate(
    {
        "subjects": ["kemang"],
        "objects": [
            {"name": "a", "visual": "fine"},
            {"name": "b", "visual": "blocked"},
            {"name": "c", "visual": "broken tool"},
        ],
    }
)
THREE_HITS = {
    ("tiktok", "a kemang"): [_video(1)],
    ("tiktok", "b kemang"): [_video(2)],
    ("tiktok", "c kemang"): [_video(3)],
}


async def test_a_missing_tool_cancels_the_sibling_checks(
    store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.footage import service

    entered, never = asyncio.Event(), asyncio.Event()
    cancelled: list[str] = []
    real_ocr = service.analyze_main_ocr

    async def ocr(video: Path, *args: Any, **kwargs: Any) -> Any:
        if str(_video(3).canonical_url).encode() in video.read_bytes():
            await entered.wait()  # fail only once the blocked sibling holds its window
            raise AssemblyError("ffmpeg_missing")
        return await real_ocr(video, *args, **kwargs)

    class Blocking(Judge):
        async def judge(
            self, frames: Sequence[Frame], visual: str, *, person: bool = False
        ) -> FootageAnswer:
            if visual != "blocked":
                return await super().judge(frames, visual, person=person)
            entered.set()
            try:
                await never.wait()
            except asyncio.CancelledError:
                cancelled.append(visual)
                raise
            raise AssertionError("unreachable")

    monkeypatch.setattr(service, "analyze_main_ocr", ocr)
    builder = _builder(
        store, queries=Queries(THREE_OBJECTS), search=Search(THREE_HITS), judge=Blocking()
    )
    with pytest.raises(AssemblyError, match="ffmpeg_missing"):
        await builder.build(_inputs(tmp_path))
    assert cancelled == ["blocked"]
    blocked = next(c for c in store.candidates("wf_a") if c.url == str(_video(2).canonical_url))
    assert blocked.status == "pending" and blocked.reason is None  # never admitted or rejected
    assert not _window(tmp_path, _video(2)).exists()


async def test_a_candidate_past_its_time_is_media_failed_and_deleted(
    store: FootageStore, tmp_path: Path
) -> None:
    class Slow(Judge):
        async def judge(
            self, frames: Sequence[Frame], visual: str, *, person: bool = False
        ) -> FootageAnswer:
            await asyncio.sleep(10)
            return await super().judge(frames, visual, person=person)

    result = await _builder(
        store, search=Search(_hits(_video(1))), judge=Slow(), per_candidate_seconds=0.5
    ).build(_inputs(tmp_path))
    assert result.status == "none" and result.rejected == {"media_failed": 1}
    assert not _window(tmp_path, _video(1)).exists()


async def test_the_deadline_stops_after_the_running_batch(
    store: FootageStore, tmp_path: Path
) -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": ["kemang"],
            "objects": [{"name": f"objek{n}", "visual": f"visual {n}"} for n in range(4)],
        }
    )
    results = {("tiktok", f"objek{n} kemang"): [_video(n)] for n in range(4)}

    class Slow(Judge):
        async def judge(
            self, frames: Sequence[Frame], visual: str, *, person: bool = False
        ) -> FootageAnswer:
            await asyncio.sleep(1.2)  # the first batch outlasts the deadline
            return await super().judge(frames, visual, person=person)

    downloader = Downloader()
    result = await _builder(
        store,
        queries=Queries(answer),
        search=Search(results),
        judge=Slow(),
        downloader=downloader,
        deadline_seconds=1.0,
    ).build(_inputs(tmp_path))
    assert result.status == "ok" and result.admitted == 3
    assert len(downloader.calls) == 3  # the fourth query's candidate was never started
    assert [c.status for c in store.candidates("wf_a")].count("pending") == 1


async def test_a_carousel_slide_is_scored_before_it_is_admitted(
    store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in (1, 2):
        location = tmp_path / f"reports/wf_a/media/slide-{index}.mp4"
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(bytes([index]) * 20_000)

    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("worker died")

    monkeypatch.setattr(store, "admit", crash)
    with pytest.raises(RuntimeError):
        await _builder(store).build(_inputs(tmp_path, _report(slides=2)))
    assert [c.story_score for c in store.candidates("wf_a")] == [1.0]


async def test_resume_hashes_an_admitted_clip_at_its_stored_trim(
    store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.assembly.models import MainOcr
    from thoth_control_plane.footage import service
    from thoth_control_plane.infrastructure.footage_models import FootageRunRow

    async def trimmed(*args: Any, **kwargs: Any) -> Any:
        return MainOcr(
            analyzed_at=NOW,
            requested_frames=4,
            valid_frames=4,
            outcome="cover",
            trim_start=5.0,
            mute_audio=False,
        )

    monkeypatch.setattr(service, "analyze_main_ocr", trimmed)
    await _builder(store, search=Search(_hits(_video(1)))).build(_inputs(tmp_path))
    with store._sessions.begin() as session:  # test-only rewind
        session.get(FootageRunRow, "wf_a").status = "running"

    class Recording(Frames):
        def __init__(self) -> None:
            self.seconds: list[float] = []

        async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
            self.seconds.append(second)
            return await super().frame_at(video, second, width=width)

    frames = Recording()
    await _builder(store, frames=frames).build(_inputs(tmp_path))
    assert frames.seconds == [8.0, 12.5, 17.0]  # vision_seconds(5.0, 20.0), as at admission


async def test_a_raising_platform_logs_its_error_class_only(
    store: FootageStore, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Raising(Search):
        async def search(self, platform: str, queries: Sequence[str], limit: int) -> SearchBatch:
            if platform == "x":
                raise RuntimeError("banjir kemang secret detail")
            return await super().search(platform, queries, limit)

    with caplog.at_level(logging.INFO, logger="thoth_control_plane.footage.service"):
        result = await _builder(store, search=Raising(_hits(_video(1)))).build(_inputs(tmp_path))
    assert result.status == "ok"
    text = caplog.text
    assert "platform=x error=RuntimeError" in text and "secret" not in text
    for name, hits in (("tiktok", 1), ("youtube", 0), ("x", 0)):
        assert f"footage search platform={name} hits={hits}" in text


async def test_a_person_query_is_judged_as_a_person(store: FootageStore, tmp_path: Path) -> None:
    answer = FootageQueryAnswer.model_validate(
        {
            "subjects": ["kemang"],
            "objects": [{"name": "banjir", "visual": "a flooded street"}],
            "people": ["Budi Santoso"],
        }
    )
    judge = Judge()
    search = Search(
        {
            ("tiktok", "banjir kemang"): [_video(1)],
            ("tiktok", "budi santoso pidato kemang"): [_video(2)],
        }
    )
    await _builder(store, queries=Queries(answer), search=search, judge=judge).build(
        _inputs(tmp_path)
    )
    by_visual = dict(zip(judge.calls, judge.people, strict=True))
    assert by_visual["a flooded street"] is False
    assert [v for v, p in by_visual.items() if p and "budi santoso" in v]


async def test_an_overlay_band_is_rejected_as_subtitle(
    store: FootageStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.footage import service

    async def overlay(*args: Any, **kwargs: Any) -> Any:
        from thoth_control_plane.assembly.models import MainOcr

        return MainOcr(
            analyzed_at=NOW,
            requested_frames=4,
            valid_frames=4,
            outcome="overlay",
            trim_start=0.0,
            mute_audio=False,
            subtitle_blur=[{"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1}],
        )

    monkeypatch.setattr(service, "analyze_main_ocr", overlay)
    judge = Judge()
    result = await _builder(store, search=Search(_hits(_video(1))), judge=judge).build(
        _inputs(tmp_path)
    )
    assert result.rejected == {"subtitle": 1} and judge.calls == []
    assert list((tmp_path / "reports" / "wf_a" / "footage").glob("*.mp4")) == []


async def _settle(release: asyncio.Event) -> None:
    """Let the deaf stragglers finish so no test leaves a pending task behind."""
    release.set()
    others = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    await asyncio.gather(*others, return_exceptions=True)


async def _deaf(release: asyncio.Event) -> None:
    """The calibration's stuck call: cancellation is caught and the wait goes on."""
    while not release.is_set():
        try:
            await release.wait()
        except asyncio.CancelledError:
            continue


async def test_a_check_that_ignores_cancellation_is_abandoned(
    store: FootageStore, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    release = asyncio.Event()
    stuck: list[asyncio.Task[Any]] = []

    class Deaf(Judge):
        async def judge(
            self, frames: Sequence[Frame], visual: str, *, person: bool = False
        ) -> FootageAnswer:
            task = asyncio.current_task()
            assert task is not None
            stuck.append(task)
            await _deaf(release)
            return await super().judge(frames, visual, person=person)

    builder = _builder(
        store,
        search=Search(_hits(_video(1))),
        judge=Deaf(),
        per_candidate_seconds=0.2,
        grace_seconds=0.1,
    )
    try:
        with caplog.at_level(logging.WARNING, logger="thoth_control_plane.footage.service"):
            started = time.monotonic()
            result = await builder.build(_inputs(tmp_path))
        assert time.monotonic() - started < 1.5
        assert result.status == "none" and result.rejected == {"media_failed": 1}
        assert "platform=tiktok step=vision" in caplog.text
        assert "tiktok.com" not in caplog.text  # no URL in the log
    finally:
        await _settle(release)
    # Released, the abandoned check reached its admit; the closed candidate ignored it.
    assert [task.result() for task in stuck] == [False]
    [candidate] = store.candidates("wf_a")
    assert candidate.status == "rejected" and candidate.reason == "media_failed"
    assert not _window(tmp_path, _video(1)).exists()


async def test_a_search_that_never_returns_ends_at_the_hard_deadline(
    store: FootageStore, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    release = asyncio.Event()

    class Hanging(Search):
        async def search(self, platform: str, queries: Sequence[str], limit: int) -> SearchBatch:
            await _deaf(release)
            return SearchBatch(found={}, failed=True)

    builder = _builder(
        store, search=Hanging(), deadline_seconds=0.1, overrun_seconds=0.2, grace_seconds=0.1
    )
    try:
        with caplog.at_level(logging.WARNING, logger="thoth_control_plane.footage.service"):
            started = time.monotonic()
            result = await builder.build(_inputs(tmp_path))
        assert time.monotonic() - started < 1.5
        assert result.status == "unavailable"
        assert "phase=search" in caplog.text
        run = store.run("wf_a")
        assert run is not None and run.status == "done" and run.footage_status == "unavailable"
    finally:
        await _settle(release)


async def test_a_cancelled_waiter_still_reads_the_exception_of_a_failed_check(
    store: FootageStore,
) -> None:
    loop = asyncio.get_running_loop()
    reported: list[str] = []
    loop.set_exception_handler(lambda _loop, context: reported.append(context["message"]))

    async def fails_when_cancelled() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise RuntimeError("store failed") from None

    builder = _builder(store, grace_seconds=1.0)
    task = asyncio.create_task(fails_when_cancelled())
    waiter = asyncio.create_task(builder._bounded(task, 10))
    await asyncio.sleep(0.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert task.done()
    del task, waiter
    gc.collect()
    await asyncio.sleep(0)
    assert reported == []


def _publishing_inputs(tmp_path: Path, publish) -> FootageInputs:
    return FootageInputs(
        workflow_id="wf_a",
        report=_report(),
        attribution=None,
        original=None,
        artifact_root=tmp_path,
        publish=publish,
    )


async def test_the_admitted_clips_are_published_before_the_run_is_done(
    store: FootageStore, tmp_path: Path
) -> None:
    seen: list[str | None] = []
    published: list[list[str]] = []

    async def publish(locations: list[str]) -> None:
        run = store.run("wf_a")
        seen.append(run.status if run is not None else None)
        published.append(locations)

    result = await _builder(store, search=Search(_hits(_video(1)))).build(
        _publishing_inputs(tmp_path, publish)
    )
    assert result.status == "ok"
    assert seen and seen[-1] != "done"
    assert store.run("wf_a").status == "done"
    # Only the admitted clips go up, never a rejected or abandoned download.
    admitted = [c.media_location for c in store.admitted("wf_a")]
    assert admitted and published[-1] == admitted


async def test_a_failed_publish_leaves_the_run_open_for_the_retry(
    store: FootageStore, tmp_path: Path
) -> None:
    async def publish(locations: list[str]) -> None:
        raise RuntimeError("media store unavailable")

    with pytest.raises(RuntimeError):
        await _builder(store, search=Search(_hits(_video(1)))).build(
            _publishing_inputs(tmp_path, publish)
        )
    assert store.run("wf_a").status != "done"


# --- Stage 5c-2: the creator's own videos and photos (spec 2026-10-22, G3, G3a, G4) ---

MAIN_URL = "https://www.instagram.com/p/MAIN1/"


def _instagram_main() -> SourceReport:
    main = support_report(
        url=MAIN_URL, owner="akun", text="Banjir besar di Kemang pagi ini", media="none"
    )
    return main.model_copy(
        update={"source": main.source.model_copy(update={"platform": "instagram"})}
    )


def _creator_inputs(tmp_path: Path, publish=None) -> FootageInputs:
    return FootageInputs(
        workflow_id="wf_a",
        report=_instagram_main(),
        attribution=None,
        original=None,
        artifact_root=tmp_path,
        publish=publish,
    )


async def test_a_tiktok_main_lists_the_creator(store: FootageStore, tmp_path: Path) -> None:
    # TikTok is back in CREATOR_PLATFORMS: the listing's captcha is solved in the page when
    # its drag subtypes rise, so a TikTok main lists its creator like the other platforms.
    own = [_own(1, "banjir kemang dari sisi lain"), _own(2, "banjir kemang dari sisi lain")]
    ports = _creator(CreatorListing(videos=own, photos=[]))

    result = await _builder(store, **ports).build(_inputs(tmp_path))

    assert ports["creator"].calls == [("tiktok", "akun", 24)]
    assert result.status == "ok"
    assert [c.url for c in store.admitted("wf_a") if c.source == "creator"] == [
        str(video.canonical_url) for video in own
    ]


def _own(n: int, caption: str, published: str = "2026-10-11T08:00:00Z") -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id=f"75000000000000000{n:02d}",
        owner_handle="akun",
        canonical_url=f"https://www.tiktok.com/@akun/video/75000000000000000{n:02d}",
        caption=caption,
        published_at=published,
        duration_seconds=20.0,
    )


def _photo(n: int, caption: str = "banjir kemang lagi") -> DiscoveredPhoto:
    return DiscoveredPhoto(
        post_id=f"76000000000000000{n:02d}",
        owner_handle="akun",
        canonical_url=f"https://www.tiktok.com/@akun/photo/76000000000000000{n:02d}",
        caption=caption,
        published_at="2026-10-11T08:00:00Z",
        image_urls=[f"https://p16.example/{n}.jpeg"],
    )


class Creator:
    def __init__(self, listing: CreatorListing | None) -> None:
        self.listing = listing
        self.calls: list[tuple[str, str, int]] = []

    async def listing_of(self, platform: str, handle: str, limit: int) -> CreatorListing | None:
        self.calls.append((platform, handle, limit))
        return self.listing


class Photos:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, url: str, target: Path) -> Path:
        self.calls.append(url)
        target = target.with_suffix(".jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_jpeg_for(Path(url)) + url.encode())
        return target


def _creator(listing: CreatorListing | None) -> dict[str, Any]:
    return {"creator": Creator(listing), "photos": Photos()}


def _search_four() -> Search:
    return Search(
        {
            ("tiktok", "banjir kemang"): [_video(n) for n in range(1, 5)],
            ("tiktok", "mobil terendam kemang"): [_video(n) for n in range(5, 9)],
        }
    )


async def test_creator_videos_take_at_most_two_slots(store: FootageStore, tmp_path: Path) -> None:
    own = [_own(n, "banjir kemang dari sisi lain") for n in range(1, 5)]
    ports = _creator(CreatorListing(videos=own, photos=[]))
    result = await _builder(store, search=_search_four(), **ports).build(_creator_inputs(tmp_path))
    admitted = store.admitted("wf_a")
    assert result.status == "ok" and len(admitted) == 6
    assert sum(1 for c in admitted if c.source == "creator") == 2
    assert {c.query for c in admitted if c.source == "creator"} == {"creator:@akun"}
    assert ports["creator"].calls == [("instagram", "akun", 24)]


async def test_weak_caption_creator_video_reaches_the_vision_judge(
    store: FootageStore, tmp_path: Path
) -> None:
    near, far = _own(1, "#fyp #viral"), _own(2, "#fyp", published="2026-09-01T08:00:00Z")
    judge = Judge()
    ports = _creator(CreatorListing(videos=[near, far], photos=[]))
    await _builder(store, judge=judge, **ports).build(_creator_inputs(tmp_path))
    admitted = [c.url for c in store.admitted("wf_a") if c.source == "creator"]
    assert admitted == [str(near.canonical_url)]
    rejected = {c.url: c.reason for c in store.candidates("wf_a") if c.status == "rejected"}
    assert rejected[str(far.canonical_url)] == "story"
    assert "a flooded street; cars under water" in judge.calls


async def test_creator_listing_failure_keeps_search_footage(
    store: FootageStore, tmp_path: Path
) -> None:
    result = await _builder(store, search=_search_four(), **_creator(None)).build(
        _creator_inputs(tmp_path)
    )
    assert result.status == "ok" and result.admitted == 4
    assert all(c.source == "search" for c in store.admitted("wf_a"))


async def test_the_main_is_never_creator_footage(store: FootageStore, tmp_path: Path) -> None:
    main = _own(1, "banjir kemang").model_copy(update={"canonical_url": MAIN_URL})
    await _builder(store, **_creator(CreatorListing(videos=[main], photos=[]))).build(
        _creator_inputs(tmp_path)
    )
    reasons = {c.url: c.reason for c in store.candidates("wf_a")}
    assert reasons == {MAIN_URL: "main"}


async def test_search_failing_still_uses_creator_footage(
    store: FootageStore, tmp_path: Path
) -> None:
    ports = _creator(CreatorListing(videos=[_own(1, "banjir kemang")], photos=[]))
    search = Search(fail={"tiktok", "youtube", "x"})
    result = await _builder(store, search=search, **ports).build(_creator_inputs(tmp_path))
    assert result.status == "ok" and result.admitted == 1


async def test_creator_photos_are_capped_at_three(store: FootageStore, tmp_path: Path) -> None:
    photos = [_photo(n) for n in range(1, 6)] + [_photo(9, "resep nasi goreng enak sekali")]
    ports = _creator(CreatorListing(videos=[], photos=photos))
    result = await _builder(store, **ports).build(_creator_inputs(tmp_path))
    images = store.admitted("wf_a", "image")
    assert len(images) == 3 and store.admitted("wf_a") == []
    assert all(c.media_kind == "image" and c.source == "creator" for c in images)
    assert all((tmp_path / str(c.media_location)).is_file() for c in images)
    assert result.photos == 3
    rejected = {c.url: c.reason for c in store.candidates("wf_a") if c.status == "rejected"}
    assert rejected[str(photos[-1].canonical_url)] == "story"


async def test_the_tiktok_page_card_is_kept_on_the_run(store: FootageStore, tmp_path: Path) -> None:
    ports = _creator(CreatorListing(videos=[], photos=[], page_png=make_png(400, 600)))
    await _builder(store, **ports).build(_creator_inputs(tmp_path))
    run = store.run("wf_a")
    assert run is not None and run.profile_page is not None
    assert run.profile_page["location"] == "reports/wf_a/cards/profile-page.png"
    assert (tmp_path / "reports/wf_a/cards/profile-page.png").is_file()


async def test_the_creator_photos_and_page_card_are_published(
    store: FootageStore, tmp_path: Path
) -> None:
    published: list[list[str]] = []

    async def publish(locations: list[str]) -> None:
        published.append(sorted(locations))

    ports = _creator(CreatorListing(videos=[], photos=[_photo(1)], page_png=make_png(400, 600)))
    await _builder(store, **ports).build(_creator_inputs(tmp_path, publish))
    image = store.admitted("wf_a", "image")[0].media_location
    # Published as soon as the photos are judged, and again with the run's end.
    expected = sorted([str(image), "reports/wf_a/cards/profile-page.png"])
    assert published == [expected, expected]


async def test_photos_and_the_page_card_are_published_before_the_clip_checks(
    store: FootageStore, tmp_path: Path
) -> None:
    # Final review I1: a crash in the clip checks must not lose the admitted photos.
    published: list[list[str]] = []

    async def publish(locations: list[str]) -> None:
        published.append(sorted(locations))

    class Crashing(Downloader):
        async def download(self, url: str, window: Any, target: Path) -> Path:
            raise RuntimeError("worker killed")

    ports = _creator(CreatorListing(videos=[], photos=[_photo(1)], page_png=make_png(400, 600)))
    builder = _builder(store, search=_search_four(), downloader=Crashing(), **ports)
    with pytest.raises(RuntimeError):
        await builder.build(_creator_inputs(tmp_path, publish))
    image = store.admitted("wf_a", "image")[0].media_location
    assert published and published[0] == sorted([str(image), "reports/wf_a/cards/profile-page.png"])


async def test_a_retry_drops_photos_and_the_page_card_it_cannot_find(
    store: FootageStore, tmp_path: Path
) -> None:
    # Final review I1: the photo URL cannot be fetched again, so a missing file is media_failed.
    ports = _creator(CreatorListing(videos=[], photos=[_photo(1)], page_png=make_png(400, 600)))
    await _builder(store, **ports).build(_creator_inputs(tmp_path / "first"))
    # A fresh scratch on the retry: the run is reopened as running with the files gone.
    from sqlalchemy.orm import Session

    from thoth_control_plane.infrastructure.footage_models import FootageRunRow

    with Session(store._sessions.kw["bind"]) as session, session.begin():
        session.get(FootageRunRow, "wf_a").status = "running"
    await _builder(store, **_creator(None)).build(_creator_inputs(tmp_path / "second"))
    assert store.admitted("wf_a", "image") == []
    reasons = {c.url: c.reason for c in store.candidates("wf_a")}
    assert reasons[str(_photo(1).canonical_url)] == "media_failed"
    run = store.run("wf_a")
    assert run is not None and run.profile_page is None


async def test_a_search_outage_with_creator_material_is_logged(
    store: FootageStore, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Final review I2: creator material keeps the run, but the outage stays visible.
    ports = _creator(CreatorListing(videos=[_own(1, "banjir kemang")], photos=[]))
    search = Search(fail={"tiktok", "youtube", "x"})
    with caplog.at_level(logging.WARNING):
        result = await _builder(store, search=search, **ports).build(_creator_inputs(tmp_path))
    assert result.status == "ok"
    assert "footage search unavailable; creator material only" in caplog.text
