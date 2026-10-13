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
from thoth_control_plane.attribution.adapters.jev import (
    CONTRIBUTION_LEVELS,
    JEV_MODEL,
    JEV_URL,
    JevDecisionModel,
)
from thoth_control_plane.attribution.ports import (
    Assessment,
    AttributionError,
    CoverReading,
    Decisions,
    Frame,
)

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
async def test_jev_failures_raise_after_one_retry(response: httpx.Response) -> None:
    route = respx.post(JEV_URL).mock(return_value=response)

    with pytest.raises(AttributionError) as raised:
        await JevDecisionModel("synthetic-jev-key").decide({}, [SOURCE])
    assert raised.value.code == "decision_unavailable"
    assert route.call_count == 2


CONTRIBUTION = {
    "type": "score",
    "score": 3.4,
    "confidence": 0.8,
    "probabilities": {"0": 0.0, "1": 0.05, "2": 0.15, "3": 0.5, "4": 0.3},
}


@pytest.mark.asyncio
@respx.mock
async def test_jev_assesses_contribution_and_discussion() -> None:
    route = respx.post(JEV_URL).mock(
        return_value=_answers(
            contribution=CONTRIBUTION,
            comments_discuss_creator={"type": "noul", "noul": 0.7},
        )
    )

    assessment = await JevDecisionModel("synthetic-jev-key").assess(
        {"creator_speech": "x"}, with_comments=True
    )

    assert assessment == Assessment(contribution=pytest.approx(0.8), discussion=0.7)
    questions = json.loads(route.calls.last.request.content)["questions"]
    assert questions["contribution"]["type"] == "score"
    assert questions["contribution"]["criteria"] == list(CONTRIBUTION_LEVELS)


@pytest.mark.asyncio
@respx.mock
async def test_without_comments_jev_is_not_asked_about_them() -> None:
    route = respx.post(JEV_URL).mock(return_value=_answers(contribution=CONTRIBUTION))

    assessment = await JevDecisionModel("synthetic-jev-key").assess({}, with_comments=False)

    assert assessment.discussion is None
    questions = json.loads(route.calls.last.request.content)["questions"]
    assert "comments_discuss_creator" not in questions


@pytest.mark.asyncio
@respx.mock
async def test_a_malformed_score_is_decision_unavailable_after_a_retry() -> None:
    route = respx.post(JEV_URL).mock(return_value=_answers(contribution={"type": "score"}))

    with pytest.raises(AttributionError) as raised:
        await JevDecisionModel("synthetic-jev-key").assess({}, with_comments=False)
    assert raised.value.code == "decision_unavailable"
    assert route.call_count == 2


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
async def test_vision_reads_the_reaction_fields_from_six_frames() -> None:
    pytest.importorskip("openai")
    from thoth_control_plane.attribution.adapters.vision import (
        OPENROUTER_BASE_URL,
        AgnoVisionReader,
    )

    reading = {
        "headline": "",
        "scene": "a woman talks after a clip",
        "icon": "",
        "reaction_shape": "clip_then_talk",
        "subject_media": "video",
        "shows": ["subject", "subject", "creator", "creator", "creator", "creator"],
    }
    route = respx.post(f"{OPENROUTER_BASE_URL}/chat/completions").mock(
        return_value=_completion(json.dumps(reading))
    )
    reader = AgnoVisionReader("synthetic-key", "qwen/qwen3-vl-30b-a3b-instruct")
    frames = [Frame(float(n), _tiny_jpeg()) for n in range(8)]

    result = await reader.read_cover(frames)

    assert (result.reaction_shape, result.subject_media) == ("clip_then_talk", "video")
    assert result.shows == reading["shows"]
    assert route.calls.last.request.content.decode().count("data:image/jpeg;base64") == 6


def test_unknown_reaction_values_are_coerced_not_rejected() -> None:
    reading = CoverReading.model_validate(
        {
            "reaction_shape": "duet",
            "subject_media": "meme",
            "shows": ["creator", "host"] + ["x"] * 6,
        }
    )

    assert (reading.reaction_shape, reading.subject_media) == ("none", "unknown")
    assert reading.shows == ["creator", "other", "other", "other", "other", "other"]


def test_a_cover_reading_without_reaction_fields_is_not_a_reaction() -> None:
    reading = CoverReading(headline="x")

    assert (reading.reaction_shape, reading.subject_media, reading.shows) == ("none", "none", [])


def test_a_long_cover_reading_is_clipped_not_rejected() -> None:
    reading = CoverReading.model_validate(
        {"headline": "x" * 400, "icon": "y" * 250, "handles": [f"akun{n}" for n in range(12)]}
    )

    assert (len(reading.headline), len(reading.icon), len(reading.handles)) == (300, 200, 10)


@pytest.mark.asyncio
@respx.mock
async def test_vision_classifies_and_raises_when_down() -> None:
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
    with pytest.raises(AttributionError) as raised:
        await reader.classify(frames)
    assert raised.value.code == "vision_unavailable"


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
    discoverer = ProfileDiscoverer({"tiktok": lambda access, scratch: fake})

    assert await discoverer.discover("tiktok", SOURCE) == [video]
    assert (fake.requests[0].handle, fake.requests[0].limit) == (SOURCE, 30)
    assert discoverer.supports("tiktok") is True
    production = ProfileDiscoverer()
    assert production.supports("threads") is False
    assert all(production.supports(p) for p in ("tiktok", "instagram", "x", "youtube"))
