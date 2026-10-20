"""The plan limit and an unavailable billing store answer with fixed bodies (spec 3.3)."""

from datetime import UTC, datetime

import httpx

from thoth_control_plane.api import create_app
from thoth_control_plane.billing import BillingUnavailable, PlanLimitReached
from thoth_control_plane.config import Settings

AUTH = {"Authorization": "Bearer k", "Idempotency-Key": "k1"}
REQUEST = {
    "source": {"url": "https://www.tiktok.com/@a/video/1", "intent": "identify_original"},
    "style": {"preset_id": "news-vertical"},
    "output": {"format": "vertical_video", "language": "id"},
    "review": {"require_publish_approval": True},
}


class Refusing:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def consume(self, *args):
        raise self.error

    def release(self, *args):
        pass


async def _start(gateway, billing) -> httpx.Response:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), gateway, billing_store=billing)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post("/api/v1/workflows", json=REQUEST, headers=AUTH)


async def test_the_plan_limit_is_402_with_its_numbers(gateway) -> None:
    end = datetime(2026, 11, 19, tzinfo=UTC)
    response = await _start(gateway, Refusing(PlanLimitReached("workflow", 3, 3, end)))
    assert response.status_code == 402
    assert response.json() == {
        "detail": {
            "code": "plan_limit_reached",
            "kind": "workflow",
            "used": 3,
            "allowance": 3,
            "period_end": "2026-11-19T00:00:00+00:00",
        }
    }


async def test_an_unavailable_billing_store_refuses_the_start(gateway) -> None:
    response = await _start(gateway, Refusing(BillingUnavailable("x")))
    assert (response.status_code, response.json()) == (503, {"detail": "billing_unavailable"})
