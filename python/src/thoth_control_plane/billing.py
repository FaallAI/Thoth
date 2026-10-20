"""Billing's domain: plans, subscriptions and the allowance (spec 2026-10-20 billing)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

FREE_PLAN_ID = "free"
Kind = Literal["workflow", "video"]


class PlanLimitReached(Exception):
    """The workspace used this period's allowance of `kind` (spec 1.4): HTTP 402."""

    def __init__(self, kind: str, used: int, allowance: int, period_end: datetime | None) -> None:
        super().__init__("plan_limit_reached")
        self.kind, self.used, self.allowance, self.period_end = kind, used, allowance, period_end


class BillingUnavailable(RuntimeError):
    """The billing tables could not be read: a start is refused, never admitted (spec 3.3)."""


class UnknownPlan(LookupError):
    pass


class InvalidPlan(ValueError):
    pass


@dataclass(frozen=True)
class PlanView:
    plan_id: str
    name: str
    price_idr: int
    workflows_per_period: int
    videos_per_period: int
    period_days: int
    active: bool


@dataclass(frozen=True)
class SubscriptionView:
    workspace_id: str
    plan_id: str
    period_start: datetime
    period_end: datetime


@dataclass(frozen=True)
class AllowanceView:
    workspace_id: str
    unlimited: bool
    plan: PlanView | None
    period_start: datetime | None
    period_end: datetime | None
    workflows_used: int
    workflows_allowed: int | None
    videos_used: int
    videos_allowed: int | None


@dataclass(frozen=True)
class InvoiceView:
    invoice_id: str
    plan_id: str
    amount_idr: int
    status: str
    invoice_url: str | None
    created_at: datetime
    paid_at: datetime | None


def workflow_ref(actor_type: str, actor_id: str, idempotency_key: str) -> str:
    """The ledger key of one workflow start: an idempotent retry reuses it."""
    return sha256(f"{actor_type}\0{actor_id}\0{idempotency_key}".encode()).hexdigest()
