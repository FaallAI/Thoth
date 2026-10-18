"""Projects routes: create, list, get, and the 404 and 503 answers."""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import run_models  # noqa: F401
from thoth_control_plane.infrastructure.project_store import ProjectStore, ProjectStoreUnavailable
from thoth_control_plane.infrastructure.source_account_models import Base

AUTH = {"Authorization": "Bearer test-key"}
SETTINGS = Settings(THOTH_CONTROL_PLANE_API_KEY="test-key")


@pytest_asyncio.fixture
async def api(gateway):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    app = create_app(SETTINGS, gateway, project_store=ProjectStore(engine))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_create_then_list_and_get(api) -> None:
    created = await api.post("/api/v1/projects", json={"name": " News "}, headers=AUTH)
    assert created.status_code == 201
    assert created.json()["name"] == "News"
    listed = await api.get("/api/v1/projects", headers=AUTH)
    assert [p["name"] for p in listed.json()["items"]] == ["News"]
    one = await api.get(f"/api/v1/projects/{created.json()['project_id']}", headers=AUTH)
    assert one.status_code == 200


@pytest.mark.asyncio
async def test_unknown_project_is_404_and_blank_name_is_422(api) -> None:
    missing = await api.get("/api/v1/projects/nope", headers=AUTH)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "project_not_found"}
    blank = await api.post("/api/v1/projects", json={"name": "   "}, headers=AUTH)
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_projects_need_the_bearer(api) -> None:
    assert (await api.get("/api/v1/projects")).status_code == 403


@pytest.mark.asyncio
async def test_no_database_answers_503(gateway) -> None:
    app = create_app(SETTINGS, gateway)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/projects", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": "project_store_unavailable"}


@pytest.mark.asyncio
async def test_a_store_failure_answers_503(gateway) -> None:
    class Down:
        def list(self):
            raise ProjectStoreUnavailable("project_store_unavailable")

    app = create_app(SETTINGS, gateway, project_store=Down())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/projects", headers=AUTH)
    assert response.status_code == 503
