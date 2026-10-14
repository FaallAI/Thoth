"""Contract tests for source accounts, their policy, and the proxy pool; secrets never return."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from thoth_control_plane.acquisition.accounts.cookies import MAX_IMPORT_BYTES, parse_cookies
from thoth_control_plane.acquisition.accounts.proxies import MAX_PROXY_BYTES
from thoth_control_plane.acquisition.accounts.vault import Vault
from thoth_control_plane.api import create_app
from thoth_control_plane.api.routes import source_accounts as source_accounts_routes
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.source_account_store import SourceAccountStore

AUTH = {"Authorization": "Bearer test-key"}
SECRET = "s3cr3t-session-value"
PROXY_PASSWORD = "pr0xy-pa55"
COOKIES = "\t".join([".instagram.com", "TRUE", "/", "TRUE", "1893456000", "sessionid", SECRET])


def _store() -> SourceAccountStore:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return SourceAccountStore(engine, Vault(Fernet.generate_key().decode()))


def client(store: SourceAccountStore | None = None) -> httpx.AsyncClient:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), source_account_store=store)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1")


def _clean(response: httpx.Response) -> httpx.Response:
    assert SECRET not in response.text and PROXY_PASSWORD not in response.text
    return response


@pytest.mark.asyncio
async def test_every_route_needs_the_api_key() -> None:
    async with client(_store()) as api:
        assert (await api.get("/source-accounts")).status_code == 403
        assert (await api.get("/source-proxies")).status_code == 403


@pytest.mark.asyncio
async def test_unavailable_lists_defaults_refuses_writes_and_still_validates() -> None:
    async with client(None) as api:
        overview = (await api.get("/source-accounts", headers=AUTH)).json()
        assert overview["available"] is False
        assert [p["platform"] for p in overview["platforms"]] == [
            "tiktok",
            "threads",
            "instagram",
            "x",
            "youtube",
        ]
        created = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "a", "cookies": COOKIES},
        )
        assert (created.status_code, created.json()["detail"]["code"]) == (
            503,
            "source_accounts_unavailable",
        )
        _clean(created)
        validated = await api.post(
            "/source-accounts/validate",
            headers=AUTH,
            json={"platform": "instagram", "cookies": COOKIES},
        )
        assert _clean(validated).json()["valid"] is True


@pytest.mark.asyncio
async def test_validation_summarizes_without_echoing_a_value() -> None:
    async with client(_store()) as api:
        good = await api.post(
            "/source-accounts/validate",
            headers=AUTH,
            json={"platform": "instagram", "cookies": COOKIES},
        )
        assert _clean(good).json() == {
            "valid": True,
            "count": 1,
            "names": ["sessionid"],
            "earliest_expiry": "2030-01-01T00:00:00Z",
            "error": None,
            "missing": [],
        }
        bad = await api.post(
            "/source-accounts/validate", headers=AUTH, json={"platform": "x", "cookies": COOKIES}
        )
        body = _clean(bad).json()
        assert (body["valid"], body["error"], body["missing"]) == (
            False,
            "missing_required_cookie",
            ["auth_token", "ct0"],
        )


@pytest.mark.asyncio
async def test_an_account_round_trips_with_safe_fields_only() -> None:
    async with client(_store()) as api:
        created = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": " main ", "cookies": COOKIES},
        )
        assert created.status_code == 201
        account = _clean(created).json()
        assert (account["label"], account["status"], account["cookie_names"]) == (
            "main",
            "healthy",
            ["sessionid"],
        )
        overview = _clean(await api.get("/source-accounts", headers=AUTH)).json()
        instagram = next(p for p in overview["platforms"] if p["platform"] == "instagram")
        assert instagram["counts"] == {"healthy": 1, "cooldown": 0, "expired": 0, "disabled": 0}
        assert [a["id"] for a in instagram["accounts"]] == [account["id"]]
        again = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "main", "cookies": COOKIES},
        )
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "label_taken")


@pytest.mark.asyncio
async def test_a_refused_import_names_the_missing_cookie_only() -> None:
    async with client(_store()) as api:
        refused = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "x", "label": "a", "cookies": COOKIES},
        )
        assert refused.status_code == 422
        assert _clean(refused).json()["detail"] == {
            "code": "missing_required_cookie",
            "missing": ["auth_token", "ct0"],
        }


@pytest.mark.asyncio
async def test_a_malformed_body_never_echoes_its_input() -> None:
    async with client(_store()) as api:
        for body in (
            {"platform": "instagram", "label": "x" * 65, "cookies": COOKIES},
            {"platform": "nope", "label": "a", "cookies": COOKIES},
            {"platform": "instagram", "label": "a", "cookies": COOKIES, "extra": SECRET},
        ):
            response = await api.post("/source-accounts", headers=AUTH, json=body)
            assert response.status_code == 422
            assert _clean(response).json()["detail"]["code"] == "invalid_request"
        proxies = await api.post("/source-proxies/import", headers=AUTH, json={"text": 5})
        assert _clean(proxies).json()["detail"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_the_policy_is_set_per_platform() -> None:
    async with client(_store()) as api:
        updated = await api.put(
            "/source-accounts/policies/instagram",
            headers=AUTH,
            json={"mode": "always", "min_spacing_seconds": 120},
        )
        assert updated.json() == {
            "mode": "always",
            "min_spacing_seconds": 120,
            "daily_budget": 20,
            "engine": "patchright",
        }
        overview = (await api.get("/source-accounts", headers=AUTH)).json()
        modes = {p["platform"]: p["mode"] for p in overview["platforms"]}
        assert (modes["instagram"], modes["x"]) == ("always", "fallback")
        refused = await api.put(
            "/source-accounts/policies/instagram",
            headers=AUTH,
            json={"mode": "always", "min_spacing_seconds": 86_401},
        )
        assert refused.status_code == 422


@pytest.mark.asyncio
async def test_the_proxy_pool_assigns_one_proxy_per_account() -> None:
    async with client(_store()) as api:
        summary = await api.post(
            "/source-proxies/import",
            headers=AUTH,
            json={
                "text": f"http://u:{PROXY_PASSWORD}@1.2.3.4:8080\nnot a proxy\nhttp://5.6.7.8:80"
            },
        )
        assert _clean(summary).json() == {"added": 2, "duplicates": 0, "invalid_lines": [2]}
        pool = _clean(await api.get("/source-proxies", headers=AUTH)).json()
        assert [(p["display"], p["account_label"]) for p in pool] == [
            ("1.2.3.4:8080", None),
            ("5.6.7.8:80", None),
        ]
        first, second = (p["id"] for p in pool)
        account = (
            await api.post(
                "/source-accounts",
                headers=AUTH,
                json={"platform": "instagram", "label": "a", "cookies": COOKIES, "proxy_id": first},
            )
        ).json()
        assert (account["proxy_id"], account["proxy_display"]) == (first, "1.2.3.4:8080")
        taken = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "b", "cookies": COOKIES, "proxy_id": first},
        )
        assert (taken.status_code, taken.json()["detail"]["code"]) == (409, "proxy_in_use")
        held = await api.delete(f"/source-proxies/{first}", headers=AUTH)
        assert (held.status_code, held.json()["detail"]["code"]) == (409, "proxy_in_use")
        moved = await api.patch(
            f"/source-accounts/{account['id']}", headers=AUTH, json={"proxy_id": second}
        )
        assert moved.json()["proxy_display"] == "5.6.7.8:80"
        cleared = await api.patch(
            f"/source-accounts/{account['id']}", headers=AUTH, json={"proxy_id": None}
        )
        assert cleared.json()["proxy_id"] is None
        assert (await api.delete(f"/source-proxies/{first}", headers=AUTH)).status_code == 204


@pytest.mark.asyncio
async def test_accounts_are_relabelled_disabled_reimported_and_deleted() -> None:
    async with client(_store()) as api:
        account = (
            await api.post(
                "/source-accounts",
                headers=AUTH,
                json={"platform": "instagram", "label": "a", "cookies": COOKIES},
            )
        ).json()
        path = f"/source-accounts/{account['id']}"
        renamed = await api.patch(path, headers=AUTH, json={"label": "renamed", "disabled": True})
        assert (renamed.json()["label"], renamed.json()["status"]) == ("renamed", "disabled")
        reimported = await api.put(f"{path}/cookies", headers=AUTH, json={"cookies": COOKIES})
        assert _clean(reimported).json()["status"] == "disabled"
        enabled = await api.patch(path, headers=AUTH, json={"disabled": False})
        assert enabled.json()["status"] == "healthy"
        wrong = await api.put(f"{path}/cookies", headers=AUTH, json={"cookies": "garbage"})
        assert (wrong.status_code, wrong.json()["detail"]["code"]) == (422, "invalid_cookie_file")
        assert (await api.delete(path, headers=AUTH)).status_code == 204
        gone = await api.patch(path, headers=AUTH, json={"label": "x"})
        assert (gone.status_code, gone.json()["detail"]["code"]) == (404, "not_found")


def _client_with_checker(store: SourceAccountStore, verdict: str) -> httpx.AsyncClient:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"), source_account_store=store)
    seen: list[tuple[str, object]] = []

    async def checker(platform: str, access: object) -> str:
        seen.append((platform, access))
        return verdict

    app.state.session_checker = checker
    app.state.seen_checks = seen
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1")


@pytest.mark.parametrize(
    ("verdict", "status"),
    [("valid", "healthy"), ("expired", "expired"), ("inconclusive", "disabled")],
)
@pytest.mark.asyncio
async def test_a_session_check_records_only_a_clear_verdict(verdict: str, status: str) -> None:
    store = _store()
    cookies = parse_cookies("instagram", COOKIES + "\n", now=datetime.now(UTC))
    account = store.add_account("instagram", "a", cookies)
    store.update_account(account.id, disabled=True)
    if verdict != "inconclusive":
        store.update_account(account.id, disabled=False)
    async with _client_with_checker(store, verdict) as api:
        checked = await api.post(f"/source-accounts/{account.id}/test", headers=AUTH)
    body = _clean(checked).json()
    assert (body["result"], body["account"]["status"]) == (verdict, status)


@pytest.mark.asyncio
async def test_a_session_check_of_an_unknown_account_is_not_found() -> None:
    async with _client_with_checker(_store(), "valid") as api:
        missing = await api.post(
            "/source-accounts/00000000-0000-0000-0000-000000000000/test", headers=AUTH
        )
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "not_found")


def test_the_api_installs_the_provider_log_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    from thoth_control_plane.api import app as app_module

    calls: list[bool] = []
    monkeypatch.setattr(app_module, "configure_provider_logging", lambda: calls.append(True))
    create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"))
    assert calls == [True]


@pytest.mark.asyncio
async def test_a_proxy_taken_between_the_check_and_the_write_is_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    async with client(store) as api:
        await api.post("/source-proxies/import", headers=AUTH, json={"text": "http://1.2.3.4:8080"})
        (proxy,) = (await api.get("/source-proxies", headers=AUTH)).json()
        body = {"platform": "instagram", "cookies": COOKIES, "proxy_id": proxy["id"]}
        await api.post("/source-accounts", headers=AUTH, json={**body, "label": "a"})
        # The check sees a free proxy; the unique constraint catches the race instead.
        monkeypatch.setattr(store, "_holder", lambda session, proxy_id: None)
        raced = await api.post("/source-accounts", headers=AUTH, json={**body, "label": "b"})
        assert (raced.status_code, raced.json()["detail"]["code"]) == (409, "proxy_in_use")


@pytest.mark.asyncio
async def test_a_label_taken_between_the_check_and_the_write_is_a_conflict() -> None:
    def write() -> None:
        raise IntegrityError(
            "INSERT", None, Exception('unique constraint "source_accounts_platform_label_key"')
        )

    with pytest.raises(HTTPException) as caught:
        await source_accounts_routes._call(write)
    assert (caught.value.status_code, caught.value.detail) == (409, {"code": "label_taken"})


@pytest.mark.asyncio
async def test_an_oversized_import_names_the_file_problem() -> None:
    async with client(_store()) as api:
        cookies = await api.post(
            "/source-accounts",
            headers=AUTH,
            json={"platform": "instagram", "label": "a", "cookies": "x" * (MAX_IMPORT_BYTES + 1)},
        )
        assert (cookies.status_code, cookies.json()["detail"]["code"]) == (
            422,
            "invalid_cookie_file",
        )
        proxies = await api.post(
            "/source-proxies/import", headers=AUTH, json={"text": "x" * (MAX_PROXY_BYTES + 1)}
        )
        assert (proxies.status_code, proxies.json()["detail"]["code"]) == (
            422,
            "invalid_proxy_file",
        )


def _profiled_client(store: SourceAccountStore, root: Path) -> httpx.AsyncClient:
    from thoth_control_plane.acquisition.accounts.profiles import AccountProfiles

    profiles = AccountProfiles(store._vault, root)  # the store's own vault, as the app builds it
    app = create_app(
        Settings(THOTH_CONTROL_PLANE_API_KEY="test-key"),
        source_account_store=store,
        account_profiles=profiles,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1")


@pytest.mark.asyncio
async def test_the_policy_carries_budget_and_engine() -> None:
    async with client(_store()) as api:
        path = "/source-accounts/policies/instagram"
        body = {"mode": "fallback", "min_spacing_seconds": 900}
        updated = await api.put(
            path, headers=AUTH, json={**body, "daily_budget": 5, "engine": "camoufox"}
        )
        assert (updated.json()["daily_budget"], updated.json()["engine"]) == (5, "camoufox")
        overview = (await api.get("/source-accounts", headers=AUTH)).json()
        instagram = next(p for p in overview["platforms"] if p["platform"] == "instagram")
        assert (instagram["daily_budget"], instagram["engine"]) == (5, "camoufox")
        tiktok = next(p for p in overview["platforms"] if p["platform"] == "tiktok")
        assert (tiktok["daily_budget"], tiktok["engine"]) == (40, "patchright")
        for refused in ({"engine": "chromium"}, {"daily_budget": -1}, {"daily_budget": 100_001}):
            answer = await api.put(path, headers=AUTH, json={**body, **refused})
            assert answer.status_code == 422


@pytest.mark.asyncio
async def test_unavailable_lists_default_budgets_and_engines() -> None:
    async with client(None) as api:
        overview = (await api.get("/source-accounts", headers=AUTH)).json()
        budgets = {p["platform"]: (p["daily_budget"], p["engine"]) for p in overview["platforms"]}
        assert budgets["instagram"] == (20, "patchright")


@pytest.mark.asyncio
async def test_an_account_takes_a_locale_and_a_valid_timezone() -> None:
    async with client(_store()) as api:
        account = (
            await api.post(
                "/source-accounts",
                headers=AUTH,
                json={"platform": "instagram", "label": "a", "cookies": COOKIES},
            )
        ).json()
        assert (account["locale"], account["timezone"]) == ("id-ID", "Asia/Jakarta")
        assert (account["fingerprint_set"], account["uses_today"]) == (False, 0)
        path = f"/source-accounts/{account['id']}"
        changed = await api.patch(
            path, headers=AUTH, json={"locale": "en-US", "timezone": "Asia/Makassar"}
        )
        assert (changed.json()["locale"], changed.json()["timezone"]) == ("en-US", "Asia/Makassar")
        for refused in ({"timezone": "Mars/Olympus"}, {"locale": "indonesian"}):
            answer = await api.patch(path, headers=AUTH, json=refused)
            assert answer.status_code == 422


@pytest.mark.asyncio
async def test_a_fingerprint_reset_and_a_delete_remove_the_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thoth_control_plane.acquisition.accounts import fingerprints

    monkeypatch.setattr(
        fingerprints, "new_fingerprint", lambda: {"navigator": {"userAgent": "Firefox/150.0"}}
    )
    store = _store()
    store.set_policy("instagram", "fallback", 0, engine="camoufox")
    root = tmp_path / "profiles"
    async with _profiled_client(store, root) as api:
        account = (
            await api.post(
                "/source-accounts",
                headers=AUTH,
                json={"platform": "instagram", "label": "a", "cookies": COOKIES},
            )
        ).json()
        assert store.lease("instagram") is not None  # makes the fingerprint
        root.mkdir()
        for engine in ("patchright", "camoufox"):
            (root / f"{account['id']}.{engine}.profile").write_bytes(b"sealed")
        path = f"/source-accounts/{account['id']}"
        listed = await api.get("/source-accounts", headers=AUTH)
        assert "userAgent" not in listed.text and "Firefox" not in listed.text

        reset = await api.patch(path, headers=AUTH, json={"reset_fingerprint": True})

        assert reset.json()["fingerprint_set"] is False
        assert list(root.glob("*.profile")) == []
        (root / f"{account['id']}.patchright.profile").write_bytes(b"sealed")
        assert (await api.delete(path, headers=AUTH)).status_code == 204
        assert list(root.glob("*.profile")) == []
        assert (root / f"{account['id']}.deleted").exists()  # an open lease cannot write back


@pytest.mark.asyncio
async def test_camoufox_outside_instagram_is_refused() -> None:
    async with client(_store()) as api:
        answer = await api.put(
            "/source-accounts/policies/tiktok",
            headers=AUTH,
            json={"mode": "fallback", "min_spacing_seconds": 60, "engine": "camoufox"},
        )
        assert (answer.status_code, answer.json()["detail"]["code"]) == (422, "engine_unsupported")


@pytest.mark.asyncio
async def test_a_policy_put_without_budget_or_engine_keeps_them() -> None:
    store = _store()
    store.set_policy("instagram", "fallback", 600, daily_budget=7, engine="camoufox")
    async with client(store) as api:
        answer = await api.put(
            "/source-accounts/policies/instagram",
            headers=AUTH,
            json={"mode": "always", "min_spacing_seconds": 600},
        )
        assert (answer.json()["daily_budget"], answer.json()["engine"]) == (7, "camoufox")
