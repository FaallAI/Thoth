"""Rotation and health rules for source accounts; pure, so every rule is testable alone."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

Mode = Literal["anonymous", "fallback", "always"]
Status = Literal["healthy", "cooldown", "expired", "disabled"]
Outcome = Literal["success", "blocked", "challenge", "rate_limited", "login_wall", "undecryptable"]
MODES: tuple[Mode, ...] = ("anonymous", "fallback", "always")
DEFAULT_MODE: Mode = "fallback"
DEFAULT_SPACING_SECONDS = 60
# Spec 2026-10-13 (account safety): leases per account per UTC day, and Instagram's spacing.
DEFAULT_DAILY_BUDGETS = {"instagram": 20, "tiktok": 40, "x": 30, "youtube": 60, "threads": 30}
DEFAULT_SPACING_SECONDS_BY_PLATFORM = {"instagram": 600}
ENGINES = ("patchright", "camoufox")
# Only Instagram's signed-in reels discovery runs Camoufox (spec 3.4); every other session is
# Scrapling and Patchright, where a Firefox profile and fingerprint would not belong.
CAMOUFOX_PLATFORMS = frozenset({"instagram"})
MAX_SPACING_SECONDS = 86_400
# Longer than the 5-minute acquisition activity, so only a dead holder's lease ever expires.
LEASE = timedelta(minutes=10)
COOLDOWN_STEPS = (
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
)
COOLING_OUTCOMES = ("blocked", "challenge", "rate_limited")


@dataclass(frozen=True)
class Health:
    status: Status
    cooldown_level: int = 0
    cooldown_until: datetime | None = None
    success_count: int = 0
    failure_count: int = 0


def after(health: Health, outcome: Outcome, now: datetime) -> Health:
    """The account's health once an acquisition reports `outcome`.

    A `disabled` account keeps its status: only the dashboard enables it again.
    """
    if outcome == "success":
        new = replace(
            health,
            status="healthy",
            cooldown_level=0,
            cooldown_until=None,
            success_count=health.success_count + 1,
        )
    elif outcome in COOLING_OUTCOMES:
        level = min(health.cooldown_level + 1, len(COOLDOWN_STEPS))
        new = replace(
            health,
            status="cooldown",
            cooldown_level=level,
            cooldown_until=now + COOLDOWN_STEPS[level - 1],
            failure_count=health.failure_count + 1,
        )
    elif outcome == "login_wall":
        new = replace(health, status="expired", failure_count=health.failure_count + 1)
    else:
        new = replace(health, status="expired")
    return replace(new, status="disabled") if health.status == "disabled" else new
