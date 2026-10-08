"""Sentinel cookie and proxy secrets never reach a log, a response, a result, or an event."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from tests.activities.test_source_investigation import INPUT, _load_fixture_report, _settings
from thoth_control_plane.acquisition.accounts.runner import account_runner
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.acquisition.models import (
    AcquisitionAttempt,
    AcquisitionFailure,
    AcquisitionReason,
    AcquisitionResult,
    AcquisitionStrategy,
    AttemptStatus,
)
from thoth_control_plane.activities.source_investigation import (
    build_source_investigation_activity,
)
from thoth_control_plane.api import create_app
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

COOKIE_SENTINEL = "cookie-sentinel-7f3a"
PROXY_SENTINEL = "proxy-sentinel-9b1c"
SENTINELS = (COOKIE_SENTINEL, PROXY_SENTINEL)
AUTH = {"Authorization": "Bearer test-key"}


def _cookies(platform: str, domain: str, name: str) -> str:
    return "\t".join([domain, "TRUE", "/", "TRUE", "1893456000", name, COOKIE_SENTINEL]) + "\n"


def _store() -> SourceAccountStore:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return SourceAccountStore(engine, Vault(Fernet.generate_key().decode()))


def _assert_clean(*texts: str) -> None:
    for text in texts:
        for sentinel in SENTINELS:
            assert sentinel not in text


@pytest.mark.asyncio
async def test_secrets_never_leave_the_vault(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store()
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), source_account_store=store)

    async def checker(platform: str, access: object) -> str:
        logging.getLogger("test").info("checking %r", access)
        return "valid"

    app.state.session_checker = checker
    responses: list[str] = []
    caplog.set_level(logging.DEBUG)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    ) as api:
        cookies = _cookies("tiktok", ".tiktok.com", "sessionid")
        imported = await api.post(
            "/source-proxies/import",
            headers=AUTH,
            json={"text": f"http://user:{PROXY_SENTINEL}@1.2.3.4:8080\n{PROXY_SENTINEL}"},
        )
        proxy_id = (await api.get("/source-proxies", headers=AUTH)).json()[0]["id"]
        validated = await api.post(
            "/source-accounts/validate",
            headers=AUTH,
            json={"platform": "tiktok", "cookies": cookies},
        )
        created = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "tiktok", "label": "a", "cookies": cookies, "proxy_id": proxy_id},
        )
        account_id = created.json()["id"]
        refused = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "x", "label": "b", "cookies": cookies},
        )
        malformed = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "tiktok", "label": "c", "cookies": cookies, "x": COOKIE_SENTINEL},
        )
        reimported = await api.put(
            f"/source-accounts/{account_id}/cookies", headers=AUTH, json={"cookies": cookies}
        )
        checked = await api.post(f"/source-accounts/{account_id}/test", headers=AUTH)
        listed = await api.get("/source-accounts", headers=AUTH)
        pool = await api.get("/source-proxies", headers=AUTH)
        responses += [
            r.text
            for r in (
                imported,
                validated,
                created,
                refused,
                malformed,
                reimported,
                checked,
                listed,
                pool,
            )
        ]

    store.set_policy("tiktok", "always", 0)

    async def acquire(workflow_id, source_url, artifact_root, access):
        logging.getLogger("test").info("acquiring with %s", access)
        if access is None:
            return AcquisitionResult(report=_load_fixture_report())
        return AcquisitionResult(
            failure=AcquisitionFailure(
                code="request_blocked",
                retryable=True,
                attempts=[
                    AcquisitionAttempt(
                        strategy=AcquisitionStrategy.SCRAPLING_HEADLESS,
                        status=AttemptStatus.FAILED,
                        reason=AcquisitionReason.LOGIN_WALL,
                        attempt_count=1,
                        elapsed_ms=3,
                    )
                ],
            )
        )

    activity = build_source_investigation_activity(
        _settings(tmp_path), runner=account_runner(store, acquire)
    )
    result = await activity(INPUT)

    assert created.status_code == 201 and checked.json()["result"] == "valid"
    assert [event.payload["stage"] for event in result.events][-2:] == [
        "tiktok_account",
        "tiktok_cleanup",
    ]
    _assert_clean(caplog.text, *responses, result.model_dump_json())
