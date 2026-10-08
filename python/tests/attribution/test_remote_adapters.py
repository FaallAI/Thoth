"""Remote adapters over mocked HTTP: Jev decisions, Agno vision, and profile discovery."""

from __future__ import annotations

import io
import json
from typing import Any

import httpx
import pytest
import respx

from thoth_control_plane.acquisition.models import (
    DiscoveredVideo,
    DiscoveryDrops,
    DiscoveryResult,
    ProfileDiscovery,
)
from thoth_control_plane.attribution.adapters.discovery import ProfileDiscoverer
from thoth_control_plane.attribution.adapters.jev import JEV_MODEL, JEV_URL, JevDecisionModel
from thoth_control_plane.attribution.ports import CoverReading, Decisions, Frame

SOURCE = "vincentius.christ76"


def _answers(**answers: Any) -> httpx.Response:
    return httpx.Response(200, json={"model": "jev-1.13.0", "answers": answers})


IS_REPOST = {"type": "noul", "noul": 0.93}
PLATFORM = {
    "type": "choice",
    "choice": "tiktok",
    "probabilities": {"tiktok": 0.9, "unknown": 0.1},
    "confidence": 0.8,
}


@pytest.mark.asyncio
@respx.mock
async def test_jev_asks_typed_questions_and_reads_the_answers() -> None:
    handle = {
        "type": "choice",
        "choice": SOURCE,
        "probabilities": {SOURCE: 0.88, "none": 0.12},
        "confidence": 0.7,
    }
    route = respx.post(JEV_URL).mock(
        return_value=_answers(
            is_repost=IS_REPOST, credited_handle=handle, credited_platform=PLATFORM
        )
    )

    decisions = await JevDecisionModel("synthetic-jev-key").decide({"caption": "x"}, [SOURCE])

    assert decisions == Decisions(
        is_repost=0.93,
        handle=SOURCE,
        handle_probability=0.88,
        platform="tiktok",
        platform_probability=0.9,
    )
    request = route.calls.last.request
    body = json.loads(request.content)
    assert (body["model"], body["state"]) == (JEV_MODEL, {"caption": "x"})
    assert JEV_URL == "https://openrouter.ai/api/alpha/decisions"
    assert JEV_MODEL == "typesafe/jev-1.13"
    assert set(body["questions"]["credited_handle"]["criteria"]) == {SOURCE, "none"}
    assert request.headers["authorization"] == "Bearer synthetic-jev-key"


@pytest.mark.asyncio
@respx.mock
async def test_jev_without_handles_asks_no_handle_question() -> None:
    unknown = {"type": "choice", "choice": "unknown", "probabilities": {"unknown": 1}}
    route = respx.post(JEV_URL).mock(
        return_value=_answers(is_repost=IS_REPOST, credited_platform=unknown)
    )

    decisions = await JevDecisionModel("synthetic-jev-key").decide({}, [])

    assert decisions == Decisions(0.93, None, 0.0, None, 1.0)
    assert "credited_handle" not in json.loads(route.calls.last.request.content)["questions"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"answers": {}}),
    ],
)
async def test_jev_failures_return_none(response: httpx.Response) -> None:
    respx.post(JEV_URL).mock(return_value=response)

    assert await JevDecisionModel("synthetic-jev-key").decide({}, [SOURCE]) is None


def _tiny_jpeg() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(buffer, format="JPEG")
    return buffer.getvalue()


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_vision_reads_the_cover_from_jpeg_frames() -> None:
    pytest.importorskip("openai")
    from thoth_control_plane.attribution.adapters.vision import (
        OPENROUTER_BASE_URL,
        AgnoVisionReader,
    )

    assert OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"
    reading = {"headline": "BANJIR", "scene": "a flooded street", "icon": "a note, bottom left"}
    route = respx.post(f"{OPENROUTER_BASE_URL}/chat/completions").mock(
        return_value=_completion(json.dumps(reading))
    )
    reader = AgnoVisionReader("synthetic-novita-key", "qwen/qwen3-vl-30b-a3b-instruct")

    assert await reader.read_cover([Frame(0.0, _tiny_jpeg())]) == CoverReading(**reading)
    body = route.calls.last.request.content.decode()
    assert "data:image/jpeg;base64" in body
    assert "qwen/qwen3-vl-30b-a3b-instruct" in body


@pytest.mark.asyncio
@respx.mock
async def test_vision_classifies_and_degrades_to_none() -> None:
    pytest.importorskip("openai")
    from thoth_control_plane.attribution.adapters.vision import (
        OPENROUTER_BASE_URL,
        AgnoVisionReader,
    )

    route = respx.post(f"{OPENROUTER_BASE_URL}/chat/completions")
    reader = AgnoVisionReader("synthetic-novita-key", "qwen/qwen3-vl-30b-a3b-instruct")
    frames = [Frame(0.0, _tiny_jpeg())]

    route.mock(return_value=_completion(json.dumps({"kind": "commentary"})))
    assert await reader.classify(frames) == "commentary"
    route.mock(return_value=httpx.Response(500, json={"error": "down"}))
    assert await reader.classify(frames) is None


class _FakeDiscovery:
    def __init__(self, video: DiscoveredVideo) -> None:
        self.requests: list[ProfileDiscovery] = []
        self._video = video

    async def discover(self, request: ProfileDiscovery) -> DiscoveryResult:
        self.requests.append(request)
        return DiscoveryResult(
            kind="profile", videos=[self._video], pages=1, exhausted=True, drops=DiscoveryDrops()
        )


@pytest.mark.asyncio
async def test_profile_discoverer_routes_by_platform() -> None:
    video = DiscoveredVideo(
        post_id="7677137235434687752",
        owner_handle=SOURCE,
        canonical_url=f"https://www.tiktok.com/@{SOURCE}/video/7677137235434687752",
    )
    fake = _FakeDiscovery(video)
    discoverer = ProfileDiscoverer({"tiktok": lambda: fake})

    assert await discoverer.discover("tiktok", SOURCE) == [video]
    assert (fake.requests[0].handle, fake.requests[0].limit) == (SOURCE, 30)
    assert discoverer.supports("tiktok") is True
    production = ProfileDiscoverer()
    assert production.supports("threads") is False
    assert all(production.supports(p) for p in ("tiktok", "instagram", "x", "youtube"))
