"""Health rules for one reported outcome; pure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from thoth_control_plane.acquisition.accounts.policy import COOLDOWN_STEPS, Health, after

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_success_heals_and_counts() -> None:
    cooling = Health("cooldown", cooldown_level=3, cooldown_until=NOW, failure_count=2)
    assert after(cooling, "success", NOW) == Health(
        "healthy", cooldown_level=0, cooldown_until=None, success_count=1, failure_count=2
    )


@pytest.mark.parametrize("outcome", ["blocked", "challenge", "rate_limited"])
def test_blocks_climb_the_cooldown_ladder_and_stop_at_a_day(outcome: str) -> None:
    health = Health("healthy")
    seen = []
    for _ in range(6):
        health = after(health, outcome, NOW)  # type: ignore[arg-type]
        seen.append(health.cooldown_until - NOW)
    assert seen == [*COOLDOWN_STEPS, COOLDOWN_STEPS[-1], COOLDOWN_STEPS[-1]]
    assert (health.status, health.cooldown_level, health.failure_count) == ("cooldown", 4, 6)
    assert (
        timedelta(minutes=15),
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=24),
    ) == COOLDOWN_STEPS


def test_a_login_wall_expires_the_account() -> None:
    assert after(Health("healthy"), "login_wall", NOW) == Health("expired", failure_count=1)


def test_an_undecryptable_account_expires_without_counting_a_failure() -> None:
    assert after(Health("healthy"), "undecryptable", NOW) == Health("expired")


def test_a_disabled_account_stays_disabled_whatever_happens() -> None:
    for outcome in ("success", "blocked", "login_wall"):
        assert after(Health("disabled"), outcome, NOW).status == "disabled"  # type: ignore[arg-type]
