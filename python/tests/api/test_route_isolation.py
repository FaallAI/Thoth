"""Every project route is guarded and every platform route needs a platform admin (spec 1.4)."""

from datetime import UTC, datetime

import httpx
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.api.test_auth_principal import SERVICE, bearer_for
from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models, run_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.project_store import ProjectStore
from thoth_control_plane.infrastructure.source_account_models import Base

#: Routes outside /api/v1 that need no caller, and the one /api/v1 route a capability opens.
PUBLIC = {"/healthz", "/readyz"}
CAPABILITY_ONLY = {"/api/v1/projects/{project_id}/editor-assets/{asset_id}/preview"}
#: Values for path parameters other than project_id; the guard answers before they are validated.
FILLERS = {"source_key": "a" * 64}


def _walk(routes, prefix=""):
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            inner = route.original_router.routes
            yield from _walk(inner, prefix + (route.include_context.prefix or ""))
        elif hasattr(route, "routes"):
            yield from _walk(route.routes, prefix + getattr(route, "path", ""))


def _dependencies(dependant, names=None) -> set[str]:
    names = set() if names is None else names
    for dependency in dependant.dependencies:
        names.add(getattr(dependency.call, "__name__", ""))
        _dependencies(dependency, names)
    return names


def _routes(gateway) -> list[tuple[str, APIRoute, set[str]]]:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), gateway)
    found = [(path, route, _dependencies(route.dependant)) for path, route in _walk(app.routes)]
    assert len(found) >= 80, "the route walk found too few routes; the FastAPI layout changed"
    return found


def test_every_project_route_is_guarded(gateway) -> None:
    unguarded = [
        path
        for path, _route, names in _routes(gateway)
        if "{project_id}" in path and path not in CAPABILITY_ONLY and "current_actor" not in names
    ]
    assert unguarded == []


def test_every_platform_route_needs_a_platform_admin(gateway) -> None:
    platform = [
        (path, names)
        for path, _route, names in _routes(gateway)
        if path.startswith(("/api/v1/source-accounts", "/api/v1/source-proxies"))
    ]
    assert platform, "no platform route found"
    assert [path for path, names in platform if "platform_actor" not in names] == []


def test_every_other_route_has_a_caller(gateway) -> None:
    open_routes = []
    for path, _route, names in _routes(gateway):
        if path.startswith("/auth/") or path in PUBLIC or path in CAPABILITY_ONLY:
            continue
        if path.startswith("/internal/"):
            if "internal_renderer" not in names:
                open_routes.append(path)
        elif "current_principal" not in names:
            open_routes.append(path)
    assert open_routes == []


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=datetime.now(UTC)
            )
        )
    return engine


@pytest.mark.asyncio
async def test_no_project_route_opens_another_workspaces_project(gateway, engine) -> None:
    accounts = AccountStore(engine)
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        gateway,
        project_store=ProjectStore(engine),
        account_store=accounts,
    )
    accounts.ensure_user("alice@acme.test", "Alice")  # the bootstrap owner
    bob = bearer_for(accounts, "bob@acme.test")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project = (
            await client.post("/api/v1/projects", json={"name": "Alice"}, headers=SERVICE)
        ).json()["project_id"]
        leaks, guarded = [], 0
        for path, route, _names in _routes(gateway):
            if "{project_id}" not in path or path in CAPABILITY_ONLY:
                continue
            url = path.replace("{project_id}", project)
            while "{" in url:
                name = url[url.index("{") + 1 : url.index("}")]
                url = url.replace("{" + name + "}", FILLERS.get(name, "x1"))
            for method in route.methods - {"HEAD", "OPTIONS"}:
                body = None if method in {"GET", "DELETE"} else {}
                response = await client.request(method, url, json=body, headers=bob)
                if response.status_code < 400:
                    leaks.append((method, path, response.status_code))
                elif response.json() == {"detail": "project_not_found"}:
                    guarded += 1
    # This app configures only the project and account stores. A route whose own service
    # dependency is declared before `current_actor` may answer 503 first; that reads nothing.
    # What must never happen is a success on another workspace's project.
    assert leaks == []
    assert guarded >= 20, f"only {guarded} project calls reached the guard"
