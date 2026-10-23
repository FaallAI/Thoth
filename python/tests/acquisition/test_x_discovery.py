"""X profile discovery over a fake FxEmbed client: no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thoth_control_plane.acquisition.models import (
    AcquisitionReason,
    DiscoveryReason,
    ProfileDiscovery,
)
from thoth_control_plane.acquisition.threads_service import RequestFetchError
from thoth_control_plane.acquisition.x_discovery import XProfileDiscovery

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "x_fxembed"
MEDIA = json.loads((FIXTURES / "profile_media.json").read_text(encoding="utf-8"))


class FakeFx:
    def __init__(self, payload: object = MEDIA, error: AcquisitionReason | None = None) -> None:
        self.payload, self.error = payload, error
        self.calls: list[tuple[str, int]] = []

    async def profile_media(self, handle: str, count: int) -> Any:
        self.calls.append((handle, count))
        if self.error is not None:
            raise RequestFetchError(self.error)
        return self.payload


async def _discover(fx: FakeFx, handle: str = "InFebriyan128", limit: int = 30):
    return await XProfileDiscovery(fx).discover(ProfileDiscovery(handle=handle, limit=limit))


@pytest.mark.asyncio
async def test_x_profile_discovery_lists_fxembed_media() -> None:
    fx = FakeFx()
    result = await _discover(fx)
    assert result.reason is None
    assert (len(result.videos), len(result.photos)) == (10, 6)
    assert fx.calls == [("InFebriyan128", 30)]


@pytest.mark.asyncio
async def test_the_limit_is_the_fxembed_count_and_the_cap() -> None:
    fx = FakeFx()
    result = await _discover(fx, limit=2)
    assert len(result.videos) == 2
    assert fx.calls == [("InFebriyan128", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AcquisitionReason.REQUEST_BLOCKED, DiscoveryReason.BLOCKED),
        (AcquisitionReason.REQUEST_TIMEOUT, DiscoveryReason.TIMEOUT),
    ],
)
async def test_x_profile_discovery_maps_a_refusal_to_a_reason(
    error: AcquisitionReason, reason: DiscoveryReason
) -> None:
    result = await _discover(FakeFx(error=error))
    assert (result.videos, result.pages, result.reason) == ([], 0, reason)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, {"code": 200, "results": []}])
async def test_nothing_listed_is_no_data(payload: object) -> None:
    result = await _discover(FakeFx(payload))
    assert (result.videos, result.reason) == ([], DiscoveryReason.NO_DATA)


@pytest.mark.asyncio
@pytest.mark.parametrize("handle", ["a.b", "has-dash", "x" * 16])
async def test_a_handle_x_cannot_have_is_no_data_without_a_fetch(handle: str) -> None:
    fx = FakeFx()
    result = await _discover(fx, handle=handle)
    assert (result.videos, result.reason, fx.calls) == ([], DiscoveryReason.NO_DATA, [])


@pytest.mark.asyncio
async def test_an_unexpected_answer_shape_is_no_data() -> None:
    result = await _discover(FakeFx({"code": 200, "results": "not a list"}))
    assert result.reason is DiscoveryReason.NO_DATA
