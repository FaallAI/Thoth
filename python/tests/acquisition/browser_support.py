"""Chromium for the browser-backed card tests: skipped locally without it, required in CI.

CI sets THOTH_REQUIRE_BROWSER_TESTS=1 and installs Chromium, so a missing browser fails the run
instead of letting a broken selector pass unseen (spec 5c-2), like the PostgreSQL and MinIO
suites.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

REQUIRED = os.environ.get("THOTH_REQUIRE_BROWSER_TESTS") == "1"

try:
    from playwright import async_api
except ImportError:
    if REQUIRED:
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)


async def launch(playwright: Any) -> Any:
    try:
        return await playwright.chromium.launch()
    except Exception:
        if REQUIRED:
            raise
        pytest.skip("no Chromium build installed")


__all__ = ["REQUIRED", "async_api", "launch"]
