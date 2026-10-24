"""Shared fixtures for the acquisition tests."""

from __future__ import annotations

import pytest

from thoth_control_plane.acquisition import card_browser


@pytest.fixture(autouse=True)
def _fast_card_page_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The card pages pace `PAGE_SPACING_SECONDS` apart in production; tests never wait."""
    monkeypatch.setattr(card_browser, "PAGE_SPACING_SECONDS", 0.0)
