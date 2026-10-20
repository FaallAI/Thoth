"""Every activity runs inside its workflow's meter scope (spec 2026-10-20, 2.2)."""

from types import SimpleNamespace

import pytest

from thoth_control_plane import metering
from thoth_control_plane.activities import meter_scope
from thoth_control_plane.metering import MeterScope


class Next:
    def __init__(self) -> None:
        self.seen: MeterScope | None = None

    async def execute_activity(self, input):
        self.seen = metering.current_scope()
        return "done"


def _memo(values):
    async def memo():
        return values

    return memo


class Client:
    def __init__(self, memo=None, fail=False) -> None:
        self.memo, self.fail = memo or {}, fail

    def get_workflow_handle(self, workflow_id):
        client = self

        class Handle:
            async def describe(self):
                if client.fail:
                    raise RuntimeError("temporal down")
                return SimpleNamespace(memo=_memo(client.memo))

        return Handle()


@pytest.fixture
def info(monkeypatch):
    monkeypatch.setattr(meter_scope.activity, "info", lambda: SimpleNamespace(workflow_id="wf_1"))


async def test_the_memo_names_the_workspace_before_any_run_row_exists(info) -> None:
    following = Next()
    interceptor = meter_scope.MeterScopeInterceptor(Client({"workspace_id": "ws_a"}))
    assert await interceptor.intercept_activity(following).execute_activity(object()) == "done"
    assert following.seen == MeterScope("ws_a", workflow_id="wf_1")
    assert metering.current_scope() is None  # the scope ends with the activity


async def test_without_temporal_the_scope_falls_back_to_the_bootstrap(info) -> None:
    following = Next()
    interceptor = meter_scope.MeterScopeInterceptor(Client(fail=True))
    await interceptor.intercept_activity(following).execute_activity(object())
    assert following.seen == MeterScope("ws_bootstrap", workflow_id="wf_1")
