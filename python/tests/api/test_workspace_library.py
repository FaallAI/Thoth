"""The workspace library routes: one workspace's items never reach another (spec 2026-11-13)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.application.test_workspace_library import (
    MP4,
    VIDEO_REPORT,
    Assets,
    MemoryLibrary,
    canned,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.application.sfx_library import SfxAssets
from thoth_control_plane.application.workspace_library import WorkspaceLibraryService
from thoth_control_plane.auth.models import Principal
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.artifact_root import LocalArtifactRoot
from thoth_control_plane.infrastructure.media_store import LocalMediaStore

UPLOAD = {"Content-Type": "video/mp4", "X-File-Name": "Yea%20Boi.mp4"}


class Projects:
    """project_a lives in ws_a, project_b in ws_b."""

    def get(self, project_id: str, workspace_id: str) -> object | None:
        return object() if project_id == f"project_{workspace_id[-1]}" else None


def caller(workspace: str, *scopes: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {workspace}:{','.join(scopes or ('read', 'write'))}"}


A, B = caller("ws_a"), caller("ws_b")


@pytest.fixture
def api(gateway, tmp_path: Path, monkeypatch):
    from thoth_control_plane.api import dependencies

    async def principal(request, authorization):
        workspace, _, scopes = authorization.removeprefix("Bearer ").partition(":")
        return Principal("u1", workspace, frozenset(scopes.split(",")), "token", role="owner")

    monkeypatch.setattr(dependencies, "resolve_principal", principal)
    root = tmp_path / "root"
    root.mkdir()
    media = LocalMediaStore(root)
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=root),
        gateway,
        None,
        project_store=Projects(),
    )
    app.state.workspace_library_service = WorkspaceLibraryService(
        MemoryLibrary(),
        LocalArtifactRoot(root, media),
        canned(VIDEO_REPORT),
        media,
        SfxAssets(assets=Assets(), media=media, probe=canned(VIDEO_REPORT)),
        Path("ffmpeg"),
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_upload_list_patch_delete_round_trip(api) -> None:
    async with api:
        made = await api.post("/api/v1/library", content=MP4, headers=A | UPLOAD)
        assert made.status_code == 201
        item = made.json()
        assert (item["kind"], item["name"]) == ("clip", "Yea Boi")
        assert "location" not in made.text and "library/" not in made.text
        listed = (await api.get("/api/v1/library", headers=A)).json()
        assert [entry["asset_id"] for entry in listed] == [item["asset_id"]]
        patched = await api.patch(
            f"/api/v1/library/{item['asset_id']}",
            json={"name": "Boom", "labels": {"mood": "hype"}, "kind": "backsound"},
            headers=A,
        )
        assert patched.status_code == 200
        assert (patched.json()["name"], patched.json()["kind"]) == ("Boom", "backsound")
        gone = await api.delete(f"/api/v1/library/{item['asset_id']}", headers=A)
        assert gone.status_code == 204
        assert (await api.get("/api/v1/library", headers=A)).json() == []


@pytest.mark.asyncio
async def test_a_second_workspace_sees_nothing_and_gets_404(api) -> None:
    async with api:
        item = (await api.post("/api/v1/library", content=MP4, headers=A | UPLOAD)).json()
        path = f"/api/v1/library/{item['asset_id']}"
        assert (await api.get("/api/v1/library", headers=B)).json() == []
        assert (await api.patch(path, json={"name": "x"}, headers=B)).status_code == 404
        assert (await api.get(f"{path}/media", headers=B)).status_code == 404
        added = await api.post(
            f"/api/v1/projects/project_b/library/{item['asset_id']}/asset", headers=B
        )
        assert added.status_code == 404
        assert (await api.delete(path, headers=B)).status_code == 404
        assert len((await api.get("/api/v1/library", headers=A)).json()) == 1


@pytest.mark.asyncio
async def test_a_draft_gets_its_own_copy(api) -> None:
    async with api:
        item = (await api.post("/api/v1/library", content=MP4, headers=A | UPLOAD)).json()
        added = await api.post(
            f"/api/v1/projects/project_a/library/{item['asset_id']}/asset", headers=A
        )
        assert added.status_code == 201
        assert (added.json()["project_id"], added.json()["kind"]) == ("project_a", "video")
        # A project of another workspace answers like a missing one.
        foreign = await api.post(
            f"/api/v1/projects/project_b/library/{item['asset_id']}/asset", headers=A
        )
        assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_read_scope_cannot_upload_or_delete(api) -> None:
    reader = caller("ws_a", "read")
    async with api:
        refused = await api.post("/api/v1/library", content=MP4, headers=reader | UPLOAD)
        assert refused.status_code == 403
        assert (await api.get("/api/v1/library", headers=reader)).status_code == 200
        assert (await api.delete("/api/v1/library/lib_x", headers=reader)).status_code == 403


@pytest.mark.asyncio
async def test_media_answers_a_range_request(api) -> None:
    async with api:
        item = (await api.post("/api/v1/library", content=MP4, headers=A | UPLOAD)).json()
        whole = await api.get(f"/api/v1/library/{item['asset_id']}/media", headers=A)
        assert whole.status_code == 200 and whole.content == MP4
        assert whole.headers["content-type"] == "video/mp4"
        part = await api.get(
            f"/api/v1/library/{item['asset_id']}/media", headers=A | {"Range": "bytes=0-3"}
        )
        assert part.status_code == 206 and part.content == MP4[:4]
        assert part.headers["content-range"] == f"bytes 0-3/{len(MP4)}"


@pytest.mark.asyncio
async def test_a_refused_upload_names_its_code(api) -> None:
    async with api:
        text = await api.post(
            "/api/v1/library", content=b"hello", headers=A | {"Content-Type": "text/plain"}
        )
        assert text.status_code == 415 and text.json()["detail"]["code"] == "unsupported_media_type"
        fake = await api.post("/api/v1/library", content=b"not a video", headers=A | UPLOAD)
        assert fake.status_code == 422 and fake.json()["detail"]["code"] == "media_type_mismatch"


@pytest.mark.asyncio
async def test_library_unavailable_answers_503(api) -> None:
    api._transport.app.state.workspace_library_service = WorkspaceLibraryService(  # type: ignore[attr-defined]
        None, None, canned(VIDEO_REPORT), None, None, Path("ffmpeg")
    )
    async with api:
        listed = await api.get("/api/v1/library", headers=A)
        assert (
            listed.status_code == 503 and listed.json()["detail"]["code"] == "library_unavailable"
        )
        made = await api.post("/api/v1/library", content=MP4, headers=A | UPLOAD)
        assert made.status_code == 503
