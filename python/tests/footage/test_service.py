"""FootageBuilder: order, quota, rejections, resume (spec 2026-10-14, F1-F9 and section 8)."""

from __future__ import annotations

import copy
import json
import zlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from tests.assembly.support import FIXTURE
from tests.assembly.support import report as support_report
from thoth_control_plane.acquisition.models import DiscoveredVideo, SourceReport
from thoth_control_plane.assembly.ports import AssemblyError
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

    async def judge(self, frames: Sequence[Frame], visual: str) -> FootageAnswer:
        key = visual
        self.calls.append(key)
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


def _builder(store: FootageStore, **ports: Any) -> FootageBuilder:
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
    assert [c.url for c in batch] == ["a1", "b1"]  # a holds one admitted: one more slot only
    assert [c.url for c in queues["a"]] == ["a2", "a3"]
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

    search.calls.clear()
    judge = Judge()
    result = await _builder(store, search=search, queries=queries, judge=judge).build(
        _inputs(tmp_path)
    )
    assert queries.calls == 1  # the objects were reused
    assert search.calls == []  # the cache answered
    assert result.status == "ok"
    assert len(judge.calls) == 1  # only the reopened candidate was checked again
    assert not stale.exists()


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
