"""The billing store on in-memory SQLite; locking is tested on PostgreSQL apart."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from thoth_control_plane.billing import (
    InvalidPlan,
    PlanConflict,
    PlanLimitReached,
    UnknownPlan,
    UnknownWorkspace,
)
from thoth_control_plane.infrastructure import billing_models  # noqa: F401
from thoth_control_plane.infrastructure.account_models import WorkspaceRow
from thoth_control_plane.infrastructure.billing_models import PlanRow
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.infrastructure.source_account_models import Base

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock) -> BillingStore:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(WorkspaceRow(workspace_id="ws_a", name="A", created_at=NOW))
        session.add(
            PlanRow(
                plan_id="free",
                name="Free",
                price_idr=0,
                workflows_per_period=3,
                videos_per_period=1,
                period_days=30,
                active=True,
                updated_at=NOW,
            )
        )
    return BillingStore(engine, clock)


def _pro(store: BillingStore) -> None:
    store.set_plan(
        "pro", name="Pro", price_idr=99000, workflows=50, videos=20, period_days=30, active=True
    )


def test_a_new_workspace_is_on_free_from_now(store: BillingStore) -> None:
    sub = store.subscription("ws_a")
    assert (sub.plan_id, sub.period_start, sub.period_end) == (
        "free",
        NOW,
        NOW + timedelta(days=30),
    )


def test_the_free_allowance_admits_three_workflows_then_refuses(store: BillingStore) -> None:
    assert [store.consume("ws_a", "workflow", f"r{i}") for i in range(3)] == [True] * 3
    with pytest.raises(PlanLimitReached) as refused:
        store.consume("ws_a", "workflow", "r4")
    assert (refused.value.kind, refused.value.used, refused.value.allowance) == ("workflow", 3, 3)


def test_the_same_ref_is_admitted_again_without_a_second_unit(store: BillingStore) -> None:
    assert store.consume("ws_a", "video", "rj_1") is True
    assert store.consume("ws_a", "video", "rj_1") is False  # an idempotent retry
    assert store.allowance("ws_a").videos_used == 1


def test_a_released_unit_is_given_back(store: BillingStore) -> None:
    store.consume("ws_a", "video", "rj_1")
    store.release("ws_a", "video", "rj_1")
    assert store.allowance("ws_a").videos_used == 0
    assert store.consume("ws_a", "video", "rj_2") is True


def test_the_operator_workspace_is_never_counted(store: BillingStore) -> None:
    assert [store.consume("ws_bootstrap", "workflow", f"r{i}") for i in range(10)] == [False] * 10
    assert store.allowance("ws_bootstrap").unlimited is True


def test_free_rolls_forward_and_the_new_period_starts_empty(store: BillingStore, clock) -> None:
    for i in range(3):
        store.consume("ws_a", "workflow", f"r{i}")
    clock.now = NOW + timedelta(days=31)
    sub = store.subscription("ws_a")
    assert (sub.plan_id, sub.period_start) == ("free", clock.now)
    assert store.consume("ws_a", "workflow", "r9") is True


def test_an_unpaid_plan_falls_back_to_free_at_its_end(store: BillingStore, clock) -> None:
    _pro(store)
    store.grant("ws_a", "pro", 30)
    assert store.subscription("ws_a").plan_id == "pro"
    clock.now = NOW + timedelta(days=30)
    for i in range(3):
        store.consume("ws_a", "workflow", f"r{i}")
    with pytest.raises(PlanLimitReached):  # held to free, not to the expired pro allowance
        store.consume("ws_a", "workflow", "r4")
    assert store.subscription("ws_a").plan_id == "free"


def test_plans_are_edited_and_validated(store: BillingStore) -> None:
    store.set_plan(
        "free", name="Free", price_idr=0, workflows=5, videos=2, period_days=30, active=True
    )
    assert store.allowance("ws_a").workflows_allowed == 5  # applies to the current period
    with pytest.raises(InvalidPlan):
        store.set_plan(
            "free", name="Free", price_idr=0, workflows=5, videos=2, period_days=30, active=False
        )
    with pytest.raises(InvalidPlan):
        store.set_plan(
            "Bad Id", name="X", price_idr=0, workflows=1, videos=1, period_days=30, active=True
        )
    with pytest.raises(UnknownPlan):
        store.grant("ws_a", "nope", 30)
    assert [p.plan_id for p in store.plans(active_only=True)] == ["free"]


def test_a_paid_invoice_starts_the_plan_once(store, clock) -> None:
    _pro(store)
    invoice = store.open_invoice("ws_a", "pro")
    assert (invoice.status, invoice.amount_idr) == ("pending", 99000)
    assert store.settle(invoice.invoice_id, "PAID", 99000) == "applied"
    assert store.settle(invoice.invoice_id, "PAID", 99000) == "ignored"  # a replay
    sub = store.subscription("ws_a")
    assert (sub.plan_id, sub.period_end) == ("pro", NOW + timedelta(days=30))


def test_renewing_the_same_plan_extends_its_period(store, clock) -> None:
    _pro(store)
    store.settle(store.open_invoice("ws_a", "pro").invoice_id, "PAID", 99000)
    clock.now = NOW + timedelta(days=10)
    store.settle(store.open_invoice("ws_a", "pro").invoice_id, "PAID", 99000)
    assert store.subscription("ws_a").period_end == NOW + timedelta(days=60)


def test_a_wrong_amount_an_expiry_and_an_unknown_invoice_change_nothing(store) -> None:
    _pro(store)
    invoice = store.open_invoice("ws_a", "pro")
    assert store.settle(invoice.invoice_id, "PAID", 1000) == "mismatch"
    assert store.subscription("ws_a").plan_id == "free"
    assert store.settle(invoice.invoice_id, "EXPIRED", None) == "applied"
    assert store.settle(invoice.invoice_id, "PAID", 99000) == "ignored"  # no longer pending
    assert store.settle("inv_nope", "PAID", 1) == "unknown"
    assert [i.status for i in store.invoices("ws_a")] == ["expired"]


def test_an_issued_invoice_keeps_its_amount_after_a_price_change(store) -> None:
    _pro(store)
    invoice = store.open_invoice("ws_a", "pro")
    store.set_plan(
        "pro", name="Pro", price_idr=150000, workflows=50, videos=20, period_days=30, active=True
    )
    assert store.settle(invoice.invoice_id, "PAID", 99000) == "applied"


def test_the_exchange_rate_round_trips_and_must_be_positive(store) -> None:
    assert store.usd_idr_rate() is None
    assert store.set_usd_idr_rate(16250.5) == 16250.5
    assert store.usd_idr_rate() == 16250.5
    with pytest.raises(InvalidPlan):
        store.set_usd_idr_rate(0)


def test_choosing_the_current_free_plan_again_never_resets_the_allowance(store) -> None:
    for i in range(3):
        store.consume("ws_a", "workflow", f"r{i}")
    with pytest.raises(PlanConflict) as refused:
        store.choose_free_plan("ws_a", "free")
    assert refused.value.code == "already_on_plan"
    with pytest.raises(PlanLimitReached):
        store.consume("ws_a", "workflow", "r9")


def test_a_paid_plan_in_its_period_is_never_dropped_for_a_free_one(store) -> None:
    _pro(store)
    store.grant("ws_a", "pro", 30)
    with pytest.raises(PlanConflict) as refused:
        store.choose_free_plan("ws_a", "free")
    assert refused.value.code == "plan_active"
    assert store.subscription("ws_a").plan_id == "pro"


def test_switching_between_free_plans_keeps_the_period_and_its_use(store) -> None:
    store.set_plan(
        "lite", name="Lite", price_idr=0, workflows=3, videos=1, period_days=30, active=True
    )
    for i in range(3):
        store.consume("ws_a", "workflow", f"r{i}")
    store.choose_free_plan("ws_a", "lite")
    sub = store.subscription("ws_a")
    assert (sub.plan_id, sub.period_start) == ("lite", NOW)
    with pytest.raises(PlanLimitReached):
        store.consume("ws_a", "workflow", "r9")


def test_an_old_ref_from_an_earlier_period_counts_again(store, clock) -> None:
    assert store.consume("ws_a", "workflow", "r1") is True
    clock.now = NOW + timedelta(days=31)
    assert store.consume("ws_a", "workflow", "r1") is True  # a reused key is a new start
    assert store.allowance("ws_a").workflows_used == 1


def test_a_payment_for_an_invoice_marked_failed_still_starts_the_plan(store) -> None:
    _pro(store)
    invoice = store.open_invoice("ws_a", "pro")
    store.fail_invoice(invoice.invoice_id)  # Xendit timed out but had created the invoice
    assert store.settle(invoice.invoice_id, "PAID", 99000) == "applied"
    assert store.subscription("ws_a").plan_id == "pro"


def test_a_partial_plan_edit_keeps_the_period_and_the_state(store) -> None:
    store.set_plan(
        "q",
        name="Quarter",
        price_idr=250000,
        workflows=150,
        videos=60,
        period_days=90,
        active=False,
    )
    store.set_plan(
        "q",
        name="Quarter",
        price_idr=240000,
        workflows=150,
        videos=60,
        period_days=None,
        active=None,
    )
    plan = store.plan("q")
    assert (plan.price_idr, plan.period_days, plan.active) == (240000, 90, False)


def test_an_unknown_workspace_is_named_not_asserted(store) -> None:
    with pytest.raises(UnknownWorkspace):
        store.grant("ws_nope", "free", 30)
