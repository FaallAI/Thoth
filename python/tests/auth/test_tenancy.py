"""The data actor of a workspace, and back (spec 1.1)."""

from thoth_control_plane.auth.models import (
    BOOTSTRAP_WORKSPACE_ID,
    LEGACY_ACTOR_ID,
    actor_workspace_id,
    data_actor_id,
)


def test_the_bootstrap_workspace_keeps_the_legacy_owner_actor() -> None:
    assert data_actor_id(BOOTSTRAP_WORKSPACE_ID) == LEGACY_ACTOR_ID == "owner"
    assert actor_workspace_id("owner") == BOOTSTRAP_WORKSPACE_ID


def test_any_other_workspace_is_its_own_actor_and_back() -> None:
    assert data_actor_id("ws_abc") == "ws_abc"
    assert actor_workspace_id("ws_abc") == "ws_abc"
