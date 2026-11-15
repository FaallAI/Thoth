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


X_MAIN = "https://x.com/akun/status/1800000000000000001"


def _report(*, slides: int = 0, platform: str = "instagram") -> SourceReport:
    """A TikTok main without media, or a carousel-shaped main with `slides` videos: an
    Instagram /p/ post, or an X post (`platform="x"`)."""
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
        "platform": platform,
        "canonical_url": X_MAIN if platform == "x" else "https://www.instagram.com/p/MAIN1/",
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
    context_enabled: bool = False,
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
        context_enabled=context_enabled,
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

        assert kwargs["follow"] is False  # a rejected candidate is not read every half second
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


def _slides(tmp_path: Path, count: int) -> None:
    for index in range(1, count + 1):
        location = tmp_path / f"reports/wf_a/media/slide-{index}.mp4"
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_bytes(bytes([index]) * 20_000)


async def test_an_x_main_with_two_videos_uses_its_other_videos(
    store: FootageStore, tmp_path: Path
) -> None:
    # Spec 2026-10-23 G6: a multi-video X post follows 5b F2 like an Instagram carousel.
    _slides(tmp_path, 2)
    search = Search()
    result = await _builder(store, search=search).build(
        _inputs(tmp_path, _report(slides=2, platform="x"))
    )
    assert result.admitted == 1 and search.calls == []
    admitted = store.admitted("wf_a")
    assert {c.source for c in admitted} == {"carousel"}
    assert {c.platform for c in admitted} == {"x"}
    assert all(c.url.startswith(f"{X_MAIN}#slide") for c in admitted)


async def test_an_x_main_with_one_video_searches(store: FootageStore, tmp_path: Path) -> None:
    _slides(tmp_path, 1)
    search = Search(_hits(_video(1)))
    await _builder(store, search=search).build(_inputs(tmp_path, _report(slides=1, platform="x")))
    assert search.calls != []


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


# The context path (footage library spec 2026-11-15, 4.1-4.3).

CONTEXT = Path(__file__).resolve().parents[1] / "fixtures" / "footage" / "context"


def _card(name: str = "mutant_card") -> Any:
    from thoth_control_plane.footage.context import ContextCard

    return ContextCard.model_validate_json((CONTEXT / f"{name}.json").read_text(encoding="utf-8"))


class Cards:
    """The card model: the card for the first prompt, `refined` for round two."""

    def __init__(self, card: Any, refined: Any = None) -> None:
        self.answer, self.refined = card, refined
        self.calls: list[str] = []
        self.materials: list[str] = []

    async def card(self, system: str, material: str) -> Any:
        from thoth_control_plane.footage.context import CARD_PROMPT

        self.calls.append("card" if system == CARD_PROMPT else "refine")
        self.materials.append(material)
        return self.answer if system == CARD_PROMPT else self.refined


def _searched(search: Search) -> set[str]:
    return {query for platform, query in search.calls if platform == "tiktok"}


async def test_the_context_path_searches_people_queries(
    store: FootageStore, tmp_path: Path
) -> None:
    search = Search()
    await _builder(store, search=search, card=Cards(_card()), context_enabled=True).build(
        _inputs(tmp_path)
    )
    assert _searched(search) == set(_card().queries[:4])
    run = store.run("wf_a")
    assert run is not None and run.context is not None
    assert [p["name"] for p in run.context["people"]] == ["Mutant", "Denny Sumargo"]


async def test_sneakers_are_rejected_and_saiful_passes(store: FootageStore, tmp_path: Path) -> None:
    card = _card()
    refined = card.model_copy(deep=True)
    refined.people[0].aliases.append("Saiful")
    refined.queries = []
    search = Search(
        _hits(
            _video(1, caption="Master Saiful ngamuk di USS"),
            _video(2, caption="Sneakers hitam putih yang simpel"),
            query="Mutant USS Denny Sumargo",
        )
    )
    await _builder(store, search=search, card=Cards(card, refined), context_enabled=True).build(
        _inputs(tmp_path)
    )
    by_caption = {c.caption: c for c in store.candidates("wf_a")}
    assert by_caption["Master Saiful ngamuk di USS"].status == "admitted"
    sneakers = by_caption["Sneakers hitam putih yang simpel"]
    assert (sneakers.status, sneakers.reason) == ("rejected", "story")


async def test_round_two_adds_queries_from_titles(store: FootageStore, tmp_path: Path) -> None:
    card = _card()
    refined = card.model_copy(deep=True)
    refined.queries = ["saiful denny sumargo", "Mutant USS Denny Sumargo"]
    cards = Cards(card, refined)
    search = Search(
        _hits(
            _video(1, caption="Master Saiful Ngamuk di Depan Denny Sumargo"),
            query="Mutant USS Denny Sumargo",
        )
    )
    await _builder(store, search=search, card=cards, context_enabled=True).build(_inputs(tmp_path))
    assert cards.calls == ["card", "refine"]
    assert "Master Saiful Ngamuk di Depan Denny Sumargo" in cards.materials[1]
    assert "saiful denny sumargo" in _searched(search)
    run = store.run("wf_a")
    assert run is not None
    assert [o.query for o in run.objects][-1] == "saiful denny sumargo"
    assert len(run.objects) == 5  # the repeated query is not added twice


async def test_own_account_candidates_are_screened_first(
    store: FootageStore, tmp_path: Path
) -> None:
    card = _card()
    card.people[1].accounts = ["@curhatbang"]
    downloader = Downloader()
    search = Search(
        _hits(
            _video(1, caption="Mutant viral, Densu bereaksi", owner="tribunnews"),
            _video(2, caption="Mutant datang ke podcast Densu", owner="curhatbang"),
            query="Mutant USS Denny Sumargo",
        )
    )
    await _builder(
        store, search=search, downloader=downloader, card=Cards(card), context_enabled=True
    ).build(_inputs(tmp_path))
    assert "curhatbang" in downloader.calls[0][0]


async def test_no_card_falls_back_to_object_queries(store: FootageStore, tmp_path: Path) -> None:
    queries, search = Queries(TWO_OBJECTS), Search()
    await _builder(
        store, queries=queries, search=search, card=Cards(None), context_enabled=True
    ).build(_inputs(tmp_path))
    assert queries.calls == 1
    assert "banjir kemang" in _searched(search)
    run = store.run("wf_a")
    assert run is not None and run.context is None


async def test_a_retry_reuses_the_stored_card(store: FootageStore, tmp_path: Path) -> None:
    from thoth_control_plane.footage.context import context_objects

    card = _card()
    store.start_run("wf_a", context_objects(card, card.queries[:4]))
    store.set_context("wf_a", {**card.model_dump(), "refined": True})
    cards, search = Cards(card), Search()
    await _builder(store, search=search, card=cards, context_enabled=True).build(_inputs(tmp_path))
    assert cards.calls == []
    assert _searched(search) == set(card.queries[:4])


async def test_context_disabled_runs_today(store: FootageStore, tmp_path: Path) -> None:
    cards, queries = Cards(_card()), Queries(TWO_OBJECTS)
    await _builder(store, queries=queries, card=cards).build(_inputs(tmp_path))
    assert cards.calls == [] and queries.calls == 1


async def test_creator_posts_pass_the_context_gate(store: FootageStore, tmp_path: Path) -> None:
    ports = _creator(
        CreatorListing(
            videos=[
                _own(1, "Urban Sneaker Society #densu #Dennysumargo Mutant datang"),
                _own(2, "Kuta beach sunset today"),
            ],
            photos=[],
        )
    )
    await _builder(store, card=Cards(_card()), context_enabled=True, **ports).build(
        _creator_inputs(tmp_path)
    )
    by_caption = {c.caption: c for c in store.candidates("wf_a")}
    assert (
        by_caption["Urban Sneaker Society #densu #Dennysumargo Mutant datang"].status != "rejected"
    )
    sunset = by_caption["Kuta beach sunset today"]
    assert (sunset.status, sunset.reason) == ("rejected", "story")


# Long videos and reposts on the context path (spec 2026-11-15, 4.4-4.5).

PODCAST = "https://www.youtube.com/watch?v=Sy_S4TgvKbY"
PODCAST_TITLE = (
    "MASTER SAIFUL MENGAMUK⁉️ JANGAN PANGGIL AKU MUTANT‼️ - AKHIRNYA BERTEMU TRETAN MUSLIM"
)


def _podcast(caption: str = PODCAST_TITLE) -> DiscoveredVideo:
    return DiscoveredVideo(
        post_id="Sy_S4TgvKbY",
        owner_handle="curhatbang",
        canonical_url=PODCAST,
        caption=caption,
        duration_seconds=3219.0,
    )


class Captions:
    def __init__(self, data: bytes | None) -> None:
        self.data = data
        self.calls: list[tuple[str, str]] = []

    async def captions(self, url: str, language: str) -> bytes | None:
        self.calls.append((url, language))
        return self.data


CAPTIONS = (CONTEXT / "podcast_captions.json3").read_bytes()


def _yt(query: str, *videos: DiscoveredVideo) -> Search:
    return Search({("youtube", query): list(videos)})


async def test_a_long_video_becomes_sections_at_its_moments(
    store: FootageStore, tmp_path: Path
) -> None:
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", _podcast()),
        card=Cards(_card()),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert (rows[PODCAST].status, rows[PODCAST].reason) == ("rejected", "duration")
    sections = [c for c in rows.values() if c.source == "section"]
    assert 1 <= len(sections) <= 3
    starts = [float(c.url.split("#t=")[1]) for c in sections]
    assert all(c.url.startswith(PODCAST + "#t=") for c in sections)
    assert all(start >= 30 for start in starts)


async def test_a_long_video_without_a_named_line_downloads_nothing(  # Review Focus 3
    store: FootageStore, tmp_path: Path
) -> None:
    from thoth_control_plane.footage.context import CardPerson, ContextCard

    rocky = ContextCard(people=[CardPerson(name="Rocky Gerung")], queries=["Rocky Gerung bicara"])
    downloader = Downloader()
    await _builder(
        store,
        search=_yt("Rocky Gerung bicara", _podcast("Rocky Gerung bicara soal Wantimpres")),
        downloader=downloader,
        card=Cards(rocky),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert (rows[PODCAST].status, rows[PODCAST].reason) == ("rejected", "duration")
    assert not [c for c in rows.values() if c.source == "section"]
    assert downloader.calls == []


async def test_a_section_downloads_its_window(store: FootageStore, tmp_path: Path) -> None:
    from thoth_control_plane.footage.moments import section

    downloader = Downloader()
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", _podcast()),
        downloader=downloader,
        card=Cards(_card()),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    assert downloader.calls
    for url, _window in downloader.calls:
        assert url == PODCAST
    admitted = store.admitted("wf_a")
    assert admitted
    for clip in admitted:
        moment = float(clip.url.split("#t=")[1])
        assert clip.clip_start == section(moment)[0]
        assert (PODCAST, section(moment)) in downloader.calls


class TraceCreator:
    """Lists only the credited account; the main creator's own listing is empty."""

    def __init__(self, videos: list[DiscoveredVideo]) -> None:
        self.videos = videos
        self.calls: list[tuple[str, str]] = []

    async def listing_of(self, platform: str, handle: str, limit: int) -> CreatorListing | None:
        self.calls.append((platform, handle))
        return CreatorListing(videos=self.videos if handle == "curhatbang" else [], photos=[])


REPOST = "Master Saiful Ngamuk di depan Denny Sumargo | Sumber: YouTube curhatbang"


async def test_a_credited_repost_is_replaced_by_its_original(
    store: FootageStore, tmp_path: Path
) -> None:
    creator = TraceCreator([_podcast()])
    search = Search(
        _hits(_video(1, caption=REPOST, owner="tribunbanten"), query="Mutant USS Denny Sumargo")
    )
    await _builder(
        store,
        search=search,
        card=Cards(_card()),
        captions_text=Captions(CAPTIONS),
        creator=creator,
        photos=Photos(),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    rows = {c.caption: c for c in store.candidates("wf_a")}
    assert (rows[REPOST].status, rows[REPOST].reason) == ("rejected", "repost")
    assert any(c.source == "trace" and c.url == PODCAST for c in store.candidates("wf_a"))
    assert ("youtube", "curhatbang") in creator.calls


async def test_a_traced_original_that_is_the_main_post_is_rejected_main(  # Review Focus 5
    store: FootageStore, tmp_path: Path
) -> None:
    main = _report()
    own = DiscoveredVideo(
        post_id="7499999999999999999",
        owner_handle="akun",
        canonical_url=str(main.source.canonical_url),
        caption="Banjir besar di Kemang pagi ini",
        duration_seconds=20.0,
    )
    search = Search(
        _hits(_video(1, caption=REPOST, owner="tribunbanten"), query="Mutant USS Denny Sumargo")
    )
    await _builder(
        store,
        search=search,
        card=Cards(_card()),
        creator=TraceCreator([own]),
        photos=Photos(),
        context_enabled=True,
    ).build(_inputs(tmp_path, main))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert rows[str(main.source.canonical_url)].reason == "main"
    assert rows[str(_video(1, owner="tribunbanten").canonical_url)].reason != "repost"


# The library across runs (spec 2026-11-15, 4.6).


def _in_workspace(store: FootageStore, workspace: str, *workflows: str) -> None:
    from thoth_control_plane.infrastructure.run_models import ProjectRow, WorkflowRunRow

    with store._sessions.begin() as session:
        for workflow in workflows:
            session.add(
                ProjectRow(
                    project_id=f"p_{workflow}",
                    name="p",
                    created_at=NOW,
                    updated_at=NOW,
                    workspace_id=workspace,
                )
            )
            session.add(
                WorkflowRunRow(
                    workflow_id=workflow,
                    project_id=f"p_{workflow}",
                    actor_type="user",
                    actor_id="u",
                    display_url="https://example.com",
                    platform="tiktok",
                    status="running",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


class Media:
    """The media store's fetch: copies a stored location into the run."""

    def __init__(self, root: Path, fail: bool = False) -> None:
        self.root, self.fail = root, fail
        self.calls: list[str] = []

    async def __call__(self, location: str, target: Path) -> None:
        self.calls.append(location)
        if self.fail:
            raise OSError("gone")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((self.root / location).read_bytes())


SHOWN = "Mutant datang ke podcast Densu"


async def _run_a(store: FootageStore, tmp_path: Path) -> None:
    search = Search(_hits(_video(1, caption=SHOWN), query="Mutant USS Denny Sumargo"))
    await _builder(store, search=search, card=Cards(_card()), context_enabled=True).build(
        _inputs(tmp_path)
    )


def _inputs_b(tmp_path: Path) -> FootageInputs:
    return FootageInputs(
        workflow_id="wf_b",
        report=_report(),
        attribution=None,
        original=None,
        artifact_root=tmp_path,
    )


async def test_an_admit_writes_the_library_with_the_card_names(
    store: FootageStore, tmp_path: Path
) -> None:
    _in_workspace(store, "ws1", "wf_a")
    await _run_a(store, tmp_path)
    since, until = datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
    kept = store.library("ws1", ["mutant"], since, until)
    assert [c.url for c in kept] == [str(_video(1).canonical_url)]
    assert {"mutant", "denny sumargo"} <= set(kept[0].names)
    assert kept[0].event == f"{_card().event} {_card().place}" and kept[0].ocr


async def test_a_second_run_on_the_story_reuses_the_library(
    store: FootageStore, tmp_path: Path
) -> None:
    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _run_a(store, tmp_path)
    downloader, search, media = Downloader(), Search(), Media(tmp_path)
    card_b = _card()
    card_b.queries = ["Mutant podcast Densu terbaru"]  # run A's queries are cached for 24 h
    await _builder(
        store,
        search=search,
        downloader=downloader,
        card=Cards(card_b),
        library_media=media,
        context_enabled=True,
    ).build(_inputs_b(tmp_path))
    reused = [c for c in store.admitted("wf_b") if c.source == "library"]
    assert [c.url for c in reused] == [str(_video(1).canonical_url)]
    assert downloader.calls == []
    assert media.calls
    assert "Mutant podcast Densu terbaru" in _searched(search)  # the rest is still searched


async def test_a_library_copy_failure_is_one_reject(store: FootageStore, tmp_path: Path) -> None:
    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _run_a(store, tmp_path)
    result = await _builder(
        store, card=Cards(_card()), library_media=Media(tmp_path, fail=True), context_enabled=True
    ).build(_inputs_b(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_b")}
    assert rows[str(_video(1).canonical_url)].reason == "media_failed"
    assert result.status == "none"


async def test_a_library_clip_that_is_the_main_post_is_not_reused(  # final review, Important 4
    store: FootageStore, tmp_path: Path
) -> None:
    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _run_a(store, tmp_path)
    kept = _video(1, caption=SHOWN)
    main = support_report(url=str(kept.canonical_url), owner="kreator", text=SHOWN, media="none")
    card_b = _card()
    card_b.queries = ["Mutant podcast Densu terbaru"]
    await _builder(
        store, card=Cards(card_b), library_media=Media(tmp_path), context_enabled=True
    ).build(
        FootageInputs(
            workflow_id="wf_b", report=main, attribution=None, original=None, artifact_root=tmp_path
        )
    )
    rows = {c.url: c for c in store.candidates("wf_b")}
    assert rows[str(kept.canonical_url)].reason == "main"
    assert not store.admitted("wf_b")


class AnyCreator:
    """Lists the same videos for every account but the main creator's."""

    def __init__(self, videos: list[DiscoveredVideo]) -> None:
        self.videos = videos
        self.calls: list[tuple[str, str]] = []

    async def listing_of(self, platform: str, handle: str, limit: int) -> CreatorListing | None:
        self.calls.append((platform, handle))
        return CreatorListing(videos=[] if handle == "akun" else self.videos, photos=[])


async def test_an_own_account_clip_tagging_someone_is_not_a_repost(  # final review, Important 6
    store: FootageStore, tmp_path: Path
) -> None:
    card = _card()
    card.people[1].accounts = ["@curhatbang"]
    own = _video(1, caption="Mutant bareng @tretanmuslim di podcast Densu", owner="curhatbang")
    other = _video(2, caption="Mutant di podcast tretan", owner="tretanmuslim")
    creator = AnyCreator([other])
    await _builder(
        store,
        search=Search(_hits(own, query="Mutant USS Denny Sumargo")),
        card=Cards(card),
        creator=creator,
        photos=Photos(),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert rows[str(own.canonical_url)].reason != "repost"
    assert ("tiktok", "tretanmuslim") not in creator.calls


async def test_trace_lists_at_most_three_accounts(  # final review, Important 7
    store: FootageStore, tmp_path: Path
) -> None:
    reposts = [
        _video(n, caption=f"Mutant ngamuk di depan Densu cr: @sumber{n}", owner=f"repost{n}")
        for n in range(1, 6)
    ]
    creator = AnyCreator([])
    await _builder(
        store,
        search=Search(_hits(*reposts, query="Mutant USS Denny Sumargo")),
        card=Cards(_card()),
        creator=creator,
        photos=Photos(),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    traced = [call for call in creator.calls if call[1].startswith("sumber")]
    assert len(traced) == 3


async def test_library_clips_survive_a_search_outage(  # final review, Important 7
    store: FootageStore, tmp_path: Path
) -> None:
    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _run_a(store, tmp_path)
    card_b = _card()
    card_b.queries = ["Mutant podcast Densu terbaru"]
    result = await _builder(
        store,
        search=Search(fail={"tiktok", "youtube", "x"}),
        card=Cards(card_b),
        library_media=Media(tmp_path),
        context_enabled=True,
    ).build(_inputs_b(tmp_path))
    assert result.status == "ok" and result.admitted == 1


async def test_own_long_videos_get_their_captions_first(  # final review, Important 8
    store: FootageStore, tmp_path: Path
) -> None:
    card = _card()
    card.people[1].accounts = ["@curhatbang"]

    def long(video_id: str, owner: str) -> DiscoveredVideo:
        return DiscoveredVideo(
            post_id=video_id,
            owner_handle=owner,
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            caption="Mutant ngamuk di depan Denny Sumargo",
            duration_seconds=3000.0,
        )

    videos = [long(f"AAAAAAAAAA{n}", f"recap{n}") for n in range(3)] + [
        long("zzzzzzzzzzz", "curhatbang")
    ]
    captions = Captions(CAPTIONS)
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", *videos),
        card=Cards(card),
        captions_text=captions,
        context_enabled=True,
    ).build(_inputs(tmp_path))
    assert captions.calls[0][0] == "https://www.youtube.com/watch?v=zzzzzzzzzzz"


async def test_a_library_clip_from_another_story_of_the_same_person_is_not_reused(
    store: FootageStore, tmp_path: Path
) -> None:  # operator, 2026-11-15: the event must match too
    from thoth_control_plane.footage.context import CardPerson, ContextCard

    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _run_a(store, tmp_path)
    other = ContextCard(
        people=[CardPerson(name="Denny Sumargo", aliases=["Densu"]), CardPerson(name="Vior")],
        event="Vior curhat soal pernikahan di podcast Curhat Bang",
        place="Jakarta",
        queries=["Vior Denny Sumargo podcast"],
    )
    media = Media(tmp_path)
    await _builder(store, card=Cards(other), library_media=media, context_enabled=True).build(
        _inputs_b(tmp_path)
    )
    assert media.calls == []
    assert not [c for c in store.candidates("wf_b") if c.source == "library"]


async def test_the_same_pair_of_people_reuses_the_library_without_event_words(
    store: FootageStore, tmp_path: Path
) -> None:  # operator, 2026-11-15: two people in common mark the same story
    from thoth_control_plane.footage.context import CardPerson, ContextCard

    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _run_a(store, tmp_path)
    saiful = ContextCard(
        people=[
            CardPerson(name="Saiful", aliases=["Mutant", "Master Saiful"]),
            CardPerson(name="Denny Sumargo", aliases=["Densu"]),
        ],
        event="Saiful marah di podcast Curhat Bang",
        queries=["Saiful marah Denny Sumargo"],
    )
    media = Media(tmp_path)
    await _builder(store, card=Cards(saiful), library_media=media, context_enabled=True).build(
        _inputs_b(tmp_path)
    )
    assert [c.source for c in store.admitted("wf_b")] == ["library"]


def test_one_person_under_several_names_counts_once() -> None:
    from thoth_control_plane.footage.context import CardPerson, ContextCard, same_event

    densu = ContextCard(people=[CardPerson(name="Denny Sumargo", aliases=["Densu", "Bang Densu"])])
    assert not same_event(densu, "Vior curhat", ["denny sumargo", "densu", "bang densu", "vior"])


async def test_a_section_keeps_what_is_said_around_it(  # spec 2026-11-15, 9.3
    store: FootageStore, tmp_path: Path
) -> None:
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", _podcast()),
        card=Cards(_card()),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    sections = [c for c in store.candidates("wf_a") if c.source == "section"]
    assert sections and all(c.said for c in sections)
    assert any("pedang" in " ".join(str(s["text"]) for s in c.said).lower() for c in sections)


async def test_a_long_video_naming_only_people_gives_no_section(
    store: FootageStore, tmp_path: Path
) -> None:
    from thoth_control_plane.footage.context import CardPerson, ContextCard

    names_only = ContextCard(
        people=[
            CardPerson(name="Mutant", aliases=["Mutan"]),
            CardPerson(name="Denny Sumargo", aliases=["Densu"]),
        ],
        queries=["Mutant USS Denny Sumargo"],
    )
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", _podcast()),
        card=Cards(names_only),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert (rows[PODCAST].status, rows[PODCAST].reason) == ("rejected", "duration")
    assert not [c for c in rows.values() if c.source == "section"]


async def test_a_library_clip_brings_its_said(store: FootageStore, tmp_path: Path) -> None:
    _in_workspace(store, "ws1", "wf_a", "wf_b")
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", _podcast()),
        card=Cards(_card()),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
    ).build(_inputs(tmp_path))
    since, until = datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
    kept = store.library("ws1", ["mutant"], since, until)
    assert kept and all(clip.said for clip in kept)
    card_b = _card()
    card_b.queries = ["Mutant podcast Densu terbaru"]
    await _builder(
        store,
        search=Search(),
        card=Cards(card_b),
        library_media=Media(tmp_path),
        context_enabled=True,
    ).build(_inputs_b(tmp_path))
    reused = {c.url: c for c in store.admitted("wf_b") if c.source == "library"}
    assert reused
    for clip in kept:
        if clip.url in reused:
            assert reused[clip.url].said == clip.said


# One copy of a recording (spec 2026-11-15, 9.4 and 9.9).


class RecFrames:
    """1 fps recording frames: files whose bytes start with a `tags` key show one recording, so
    frame i of one copy is frame i of the other; others are their own recording."""

    def __init__(self, tags: dict[str, str], cluttered: frozenset[str] = frozenset()) -> None:
        self.tags, self.cluttered = tags, cluttered

    async def frames(self, video: Path, *, fps: float, seconds: float | None = None) -> list[Frame]:
        content = video.read_bytes() if video.exists() else b""
        key = next((k for k in self.tags if content.startswith(k.encode())), None)
        tag = self.tags[key] if key else hashlib.sha256(content).hexdigest()[:12]
        marks = "clutter" if key in self.cluttered else "clean"
        return [Frame(second=float(i), jpeg=f"{tag}:{i}:{marks}".encode()) for i in range(10)]


class Matcher:
    """OrbMatcher's contract over RecFrames frames: the same recording frame matches."""

    async def prepare(self, frames: Sequence[Frame]) -> list[bytes]:
        return [frame.jpeg.rsplit(b":", 1)[0] for frame in frames]

    async def compare(self, a: list[bytes], b: list[bytes]) -> list[int]:
        return [40 if x in set(b) else 0 for x in a]

    async def matrix(self, a: list[bytes], b: list[bytes]) -> list[list[int]]:
        return [[40 if x == y else 3 for y in b] for x in a]


class Clutter(Text):
    """A watermark band on every frame of a cluttered recording."""

    async def read(self, frame: Frame) -> list[Any]:
        from thoth_control_plane.attribution.matching import TextBox

        if frame.jpeg.endswith(b"clutter"):
            return [TextBox(text="JawaPos", top=0.0, bottom=0.3, left=0.0, right=1.0)]
        return []


def _url(n: int, owner: str = "kreator") -> str:
    return str(_video(n, owner=owner).canonical_url)


def _copies(cluttered: frozenset[str] = frozenset(), **extra: str) -> dict[str, Any]:
    tags = {_url(1): "rec1", _url(2): "rec1", **extra}
    return {"recording_frames": RecFrames(tags, cluttered), "matcher": Matcher(), "text": Clutter()}


async def test_a_cleaner_copy_wins_whatever_the_order(store: FootageStore, tmp_path: Path) -> None:
    search = Search(_hits(_video(1), _video(2)))
    await _builder(store, search=search, **_copies(frozenset({_url(1)}))).build(_inputs(tmp_path))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert [c.url for c in store.admitted("wf_a")] == [_url(2)]
    assert (rows[_url(1)].status, rows[_url(1)].reason) == ("rejected", "duplicate")


async def test_two_equal_copies_checked_together_leave_one(  # Review Focus 2
    store: FootageStore, tmp_path: Path
) -> None:
    search = Search(_hits(_video(1), _video(2)))
    await _builder(store, search=search, **_copies()).build(_inputs(tmp_path))
    assert len(store.admitted("wf_a")) == 1
    assert [c.reason for c in store.candidates("wf_a") if c.status == "rejected"] == ["duplicate"]


async def test_no_matcher_no_copy_check(store: FootageStore, tmp_path: Path) -> None:
    search = Search(_hits(_video(1), _video(2)))
    await _builder(store, search=search).build(_inputs(tmp_path))
    assert len(store.admitted("wf_a")) == 2


async def test_a_copy_of_the_main_is_rejected_duplicate(
    store: FootageStore, tmp_path: Path
) -> None:
    main = support_report(
        url="https://www.tiktok.com/@akun/video/7499999999999999999",
        owner="akun",
        text="Banjir besar di Kemang pagi ini",
        media="video",
    )
    video = tmp_path / "reports" / "wf_a" / "media" / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"MAINREC" * 50)
    search = Search(_hits(_video(3)))
    ports = _copies(MAINREC="rec3", **{_url(3): "rec3"})
    await _builder(store, search=search, **ports).build(_inputs(tmp_path, main))
    rows = {c.url: c for c in store.candidates("wf_a")}
    assert (rows[_url(3)].status, rows[_url(3)].reason) == ("rejected", "duplicate")


async def test_a_photo_main_skips_the_main_comparison(  # Review Focus 3
    store: FootageStore, tmp_path: Path
) -> None:
    search = Search(_hits(_video(3)))
    await _builder(store, search=search, **_copies()).build(_inputs(tmp_path))
    assert [c.url for c in store.admitted("wf_a")] == [_url(3)]


async def test_an_original_stays_over_a_cleaner_repost(store: FootageStore, tmp_path: Path) -> None:
    own, repost = _video(1, caption=SHOWN, owner="dennysumargo"), _video(2, caption=SHOWN)
    search = Search(_hits(own, repost, query="Mutant USS Denny Sumargo"))
    ports = _copies(frozenset({_url(1, "dennysumargo")}), **{_url(1, "dennysumargo"): "rec1"})
    await _builder(store, search=search, card=Cards(_card()), context_enabled=True, **ports).build(
        _inputs(tmp_path)
    )
    assert [c.url for c in store.admitted("wf_a")] == [_url(1, "dennysumargo")]


async def test_the_losing_copy_leaves_the_library(store: FootageStore, tmp_path: Path) -> None:
    _in_workspace(store, "ws1", "wf_a")
    one, two = _video(1, caption=SHOWN), _video(2, caption=SHOWN)
    search = Search(_hits(one, two, query="Mutant USS Denny Sumargo"))
    await _builder(
        store,
        search=search,
        card=Cards(_card()),
        context_enabled=True,
        **_copies(frozenset({_url(1)})),
    ).build(_inputs(tmp_path))
    since, until = datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
    assert [c.url for c in store.library("ws1", ["mutant"], since, until)] == [_url(2)]


class WindowDownloader(Downloader):
    """Each section's own bytes, so two sections of one video are two files."""

    async def download(self, url: str, window: Any, target: Path) -> Path:
        await super().download(url, window, target)
        target.write_bytes(url.encode() * 50 + repr(window).encode())
        return target


async def test_sections_of_one_video_are_not_compared(store: FootageStore, tmp_path: Path) -> None:
    await _builder(
        store,
        search=_yt("Mutant USS Denny Sumargo", _podcast()),
        downloader=WindowDownloader(),
        card=Cards(_card()),
        captions_text=Captions(CAPTIONS),
        context_enabled=True,
        **_copies(**{PODCAST: "studio"}),
    ).build(_inputs(tmp_path))
    sections = [c for c in store.candidates("wf_a") if c.source == "section"]
    assert len(sections) >= 2  # the fixture's captions hold two discussions
    assert all(c.status == "admitted" for c in sections)


async def test_copies_kept_in_the_library_come_back_once(
    store: FootageStore, tmp_path: Path
) -> None:
    _in_workspace(store, "ws1", "wf_a", "wf_b")
    one, two = _video(1, caption=SHOWN), _video(2, caption=SHOWN)
    await _builder(
        store,
        search=Search(_hits(one, two, query="Mutant USS Denny Sumargo")),
        card=Cards(_card()),
        context_enabled=True,
    ).build(_inputs(tmp_path))  # no matcher: both copies were kept
    card_b = _card()
    card_b.queries = ["Mutant podcast Densu terbaru"]
    await _builder(
        store,
        search=Search(),
        card=Cards(card_b),
        library_media=Media(tmp_path),
        context_enabled=True,
        **_copies(),
    ).build(_inputs_b(tmp_path))
    assert len([c for c in store.admitted("wf_b") if c.source == "library"]) == 1
