"""Checkout and the Xendit webhook through the API (spec 2026-10-20 billing, 2)."""

from datetime import UTC, datetime

import httpx
import pytest

from tests.api.test_auth_principal import SERVICE, bearer_for
from tests.sqlite_support import sqlite_engine
from thoth_control_plane.api import create_app
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID
from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure import account_models, billing_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.account_store import AccountStore
from thoth_control_plane.infrastructure.billing_models import PlanRow
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.infrastructure.source_account_models import Base
from thoth_control_plane.infrastructure.xendit import PaymentProviderUnavailable, ProviderInvoice

TOKEN = "cb-token"


class Payments:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.calls = fail, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise PaymentProviderUnavailable("payment_provider_unavailable")
        return ProviderInvoice("xnd_1", "https://checkout.x/1")


@pytest.fixture
def world(gateway):
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            WorkspaceRow.__table__.insert().values(
                workspace_id=BOOTSTRAP_WORKSPACE_ID, name="Thoth", created_at=now
            )
        )
        connection.execute(
            PlanRow.__table__.insert().values(
                plan_id="free",
                name="Free",
                price_idr=0,
                workflows_per_period=3,
                videos_per_period=1,
                period_days=30,
                active=True,
                updated_at=now,
            )
        )
    accounts, billing = AccountStore(engine), BillingStore(engine)
    billing.set_plan(
        "pro", name="Pro", price_idr=99000, workflows=50, videos=20, period_days=30, active=True
    )
    payments = Payments()
    settings = Settings(
        THOTH_CONTROL_PLANE_API_KEY="test-key",
        THOTH_XENDIT_CALLBACK_TOKEN=TOKEN,
        THOTH_XENDIT_SECRET_KEY="xnd_secret",
    )
    app = create_app(settings, gateway, account_store=accounts, billing_store=billing)
    app.state.payments = payments
    accounts.ensure_user("alice@acme.test", "Alice")
    bob = bearer_for(accounts, "bob@acme.test")  # owner of his own workspace
    bob_ws = accounts.ensure_user("bob@acme.test", "Bob").workspace_id
    return app, billing, payments, bob, bob_ws


async def _call(app, method, path, headers=None, body=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers or {}, json=body)


async def test_checkout_opens_an_invoice_and_the_paid_webhook_starts_the_plan(world) -> None:
    app, billing, payments, bob, bob_ws = world
    made = await _call(app, "POST", "/api/v1/billing/checkout", bob, {"plan_id": "pro"})
    assert made.status_code == 200 and made.json()["invoice_url"] == "https://checkout.x/1"
    invoice_id = made.json()["invoice_id"]
    assert payments.calls[0]["external_id"] == invoice_id
    assert payments.calls[0]["amount_idr"] == 99000
    paid = {"external_id": invoice_id, "status": "PAID", "paid_amount": 99000}
    wrong = await _call(app, "POST", "/billing/webhooks/xendit", {"x-callback-token": "no"}, paid)
    assert wrong.status_code == 401 and billing.subscription(bob_ws).plan_id == "free"
    ok = await _call(app, "POST", "/billing/webhooks/xendit", {"x-callback-token": TOKEN}, paid)
    assert ok.status_code == 200 and billing.subscription(bob_ws).plan_id == "pro"


async def test_checkout_refusals(world) -> None:
    app, _billing, payments, bob, _ = world
    unknown = await _call(app, "POST", "/api/v1/billing/checkout", bob, {"plan_id": "nope"})
    operator = await _call(app, "POST", "/api/v1/billing/checkout", SERVICE, {"plan_id": "pro"})
    payments.fail = True
    down = await _call(app, "POST", "/api/v1/billing/checkout", bob, {"plan_id": "pro"})
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown_plan"})
    assert (operator.status_code, operator.json()) == (409, {"detail": "operator_workspace"})
    assert (down.status_code, down.json()) == (502, {"detail": "payment_provider_unavailable"})


async def test_a_free_plan_needs_no_invoice(world) -> None:
    app, billing, payments, bob, bob_ws = world
    billing.set_plan(
        "lite", name="Lite", price_idr=0, workflows=3, videos=1, period_days=30, active=True
    )
    made = await _call(app, "POST", "/api/v1/billing/checkout", bob, {"plan_id": "lite"})
    assert made.json() == {"invoice_id": None, "invoice_url": None, "applied": True}
    assert payments.calls == [] and billing.subscription(bob_ws).plan_id == "lite"


async def test_a_free_checkout_never_resets_an_allowance_or_drops_a_paid_period(world) -> None:
    app, billing, _payments, bob, bob_ws = world
    again = await _call(app, "POST", "/api/v1/billing/checkout", bob, {"plan_id": "free"})
    billing.grant(bob_ws, "pro", 30)
    drop = await _call(app, "POST", "/api/v1/billing/checkout", bob, {"plan_id": "free"})
    assert (again.status_code, again.json()) == (409, {"detail": "already_on_plan"})
    assert (drop.status_code, drop.json()) == (409, {"detail": "plan_active"})
    assert billing.subscription(bob_ws).plan_id == "pro"


async def test_without_xendit_checkout_and_the_webhook_are_unavailable(gateway) -> None:
    app = create_app(Settings(THOTH_CONTROL_PLANE_API_KEY="k"), gateway)
    hook = await _call(app, "POST", "/billing/webhooks/xendit", {"x-callback-token": "x"}, {})
    assert (hook.status_code, hook.json()) == (503, {"detail": "billing_unavailable"})
