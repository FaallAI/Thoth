"""An API request runs inside its caller's meter scope (spec 2026-10-20, 2.2)."""

from typing import Annotated

import httpx
from fastapi import Depends

from thoth_control_plane import metering
from thoth_control_plane.api import create_app
from thoth_control_plane.api.dependencies import current_actor
from thoth_control_plane.config import Settings
from thoth_control_plane.domain import Actor


async def test_a_request_scope_names_the_callers_workspace(gateway) -> None:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), gateway)

    async def probe(actor: Annotated[Actor, Depends(current_actor)]) -> dict:
        scope = metering.current_scope()
        return {"workspace_id": scope.workspace_id, "project_id": scope.project_id}

    app.add_api_route("/api/v1/scope-probe", probe)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/scope-probe", headers={"Authorization": "Bearer test-key"}
        )
    assert response.json() == {"workspace_id": "ws_bootstrap", "project_id": None}


def test_the_app_installs_the_usage_store_it_is_given(gateway) -> None:
    sink = object()
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), gateway, usage_store=sink)
    assert metering.installed() is sink
    assert app.state.usage_store is sink
