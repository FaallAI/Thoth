"""The assembler end to end over fake ports."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.assembly.support import comment, report
from thoth_control_plane.acquisition.models import SourceReport
from thoth_control_plane.assembly.figures import FigureAnswer
from thoth_control_plane.assembly.ports import AssemblyError
from thoth_control_plane.assembly.service import AssemblyInputs, AssemblyPorts, ContentAssembler
from thoth_control_plane.attribution.matching import TextBox
from thoth_control_plane.attribution.models import SourceAttribution
from thoth_control_plane.attribution.ports import Frame

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
ORIGINAL_URL = "https://www.tiktok.com/@source/video/9999999999"


class Frames:
    async def frame_at(self, video: Path, second: float, *, width: int) -> Frame:
        assert video.is_file()
        return Frame(second, b"jpeg")


class Probe:
    async def duration(self, video: Path) -> float:
        return 30.0


class Clean:
    async def read(self, frame: Frame) -> list[TextBox]:
        return []


class Figures:
    def __init__(self, answer: FigureAnswer | Exception | None = None) -> None:
        self.answer, self.prompts = answer, []

    async def read(self, prompt: str) -> FigureAnswer | None:
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def attribution(verdict: str, headline: str | None = None) -> SourceAttribution:
    data: dict[str, Any] = {
        "workflow_id": "wf_a",
        "input": {
            "platform": "tiktok",
            "canonical_url": "https://www.tiktok.com/@creator/video/1234567890",
            "owner_handle": "creator",
        },
        "verdict": verdict,
        "evidence": [{"kind": "cover_vision", "detail": f"headline: {headline}"}]
        if headline
        else [],
    }
    if verdict == "replaced":
        data["source"] = {
            "platform": "tiktok",
            "canonical_url": ORIGINAL_URL,
            "owner_handle": "source",
        }
    return SourceAttribution.model_validate_json(json.dumps(data))


def touch(root: Path, *reports: SourceReport) -> None:
    for item in reports:
        for media in item.media:
            path = root / media.location
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")


def build(
    tmp_path: Path,
    main: SourceReport,
    *,
    verdict: str | None = None,
    original: SourceReport | None = None,
    figures: Figures | None = None,
    headline: str | None = None,
):
    touch(tmp_path, main, *([original] if original else []))
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Clean(), figures=figures),
        clock=lambda: NOW,
    )
    return asyncio.run(
        assembler.build(
            AssemblyInputs(
                workflow_id="wf_a",
                report=main,
                attribution=attribution(verdict, headline) if verdict else None,
                original=original,
                artifact_root=tmp_path,
            )
        )
    )


def test_an_original_post_is_its_own_main(tmp_path: Path) -> None:
    content = build(tmp_path, report(profile_card=True), verdict="original")

    assert content.attribution_verdict == "original"
    assert content.main.source == "input" and content.main.kind == "video"
    assert content.main.title == "Banjir di Jakarta hari ini"
    assert content.main.ocr is not None and content.main.ocr.outcome == "clean"
    assert content.main.profile_card is not None
    assert content.figures_status == "unavailable"


def test_without_attribution_the_verdict_is_none(tmp_path: Path) -> None:
    assert build(tmp_path, report()).attribution_verdict == "none"


def test_replaced_main_is_the_original_with_both_discussions(tmp_path: Path) -> None:
    repost = report(comments=[comment("a", "ini repost", 9)])
    original = report(
        workflow_id="wf_a-c1",
        owner="source",
        url=ORIGINAL_URL,
        comments=[comment("b", "video asli", 3)],
    )

    content = build(tmp_path, repost, verdict="replaced", original=original)

    assert content.main.source == "original"
    assert str(content.main.url) == ORIGINAL_URL
    assert [(c.author, c.source) for c in content.comments] == [("a", "input"), ("b", "original")]


def test_replaced_without_the_original_report_fails(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError) as raised:
        build(tmp_path, report(), verdict="replaced")
    assert raised.value.code == "original_report_missing"


def test_an_images_post_needs_no_ocr(tmp_path: Path) -> None:
    content = build(tmp_path, report(media="images"))

    assert content.main.kind == "images" and len(content.main.images) == 2
    assert content.main.ocr is None


def test_text_post_uses_its_card(tmp_path: Path) -> None:
    content = build(tmp_path, report(media="none", post_card=True))

    assert content.main.kind == "card" and content.main.card is not None


def test_text_post_without_card_fails(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError) as raised:
        build(tmp_path, report(media="none"))
    assert raised.value.code == "main_media_missing"


def test_a_missing_video_file_fails(tmp_path: Path) -> None:
    assembler = ContentAssembler(
        AssemblyPorts(frames=Frames(), probe=Probe(), text=Clean(), figures=None)
    )
    with pytest.raises(AssemblyError) as raised:
        asyncio.run(
            assembler.build(
                AssemblyInputs("wf_a", report(), None, None, tmp_path)  # no file written
            )
        )
    assert raised.value.code == "main_media_missing"


def test_figures_use_title_description_and_the_cover_headline(tmp_path: Path) -> None:
    figures = Figures(
        FigureAnswer.model_validate({"figures": [{"name": "Pramono Anung", "type": "person"}]})
    )

    content = build(tmp_path, report(), verdict="original", figures=figures, headline="BANJIR LAGI")

    assert content.figures_status == "ok" and content.figures[0].name == "Pramono Anung"
    assert "[HEADLINE]: BANJIR LAGI" in figures.prompts[0]


@pytest.mark.parametrize(
    ("answer", "status"),
    [(FigureAnswer(), "none"), (None, "unavailable"), (RuntimeError("down"), "unavailable")],
)
def test_figure_failures_never_fail_the_set(tmp_path: Path, answer: Any, status: str) -> None:
    assert build(tmp_path, report(), figures=Figures(answer)).figures_status == status
