"""A Camoufox account's Firefox fingerprint (spec 2026-10-13, section 3.4, amended 2026-10-14)."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from thoth_control_plane.acquisition.accounts.fingerprints import new_fingerprint
from thoth_control_plane.attribution.adapters.frames import ToolMissing


def _camoufox(generated: object) -> dict[str, ModuleType]:
    package, module = ModuleType("camoufox"), ModuleType("camoufox.fingerprints")
    module.generate_fingerprint = lambda: generated  # type: ignore[attr-defined]
    return {"camoufox": package, "camoufox.fingerprints": module}


def test_the_fingerprint_is_camoufoxs_own_and_json_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    generated = {"navigator": {"userAgent": "Firefox/150.0", "languages": ("id-ID",)}}
    for name, module in _camoufox(generated).items():
        monkeypatch.setitem(sys.modules, name, module)

    assert new_fingerprint() == {
        "navigator": {"userAgent": "Firefox/150.0", "languages": ["id-ID"]}
    }


def test_a_fingerprint_that_is_not_json_fails_at_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, module in _camoufox({"screen": object()}).items():
        monkeypatch.setitem(sys.modules, name, module)

    with pytest.raises(TypeError):
        new_fingerprint()


def test_without_camoufox_it_is_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "camoufox", None)
    monkeypatch.setitem(sys.modules, "camoufox.fingerprints", None)

    with pytest.raises(ToolMissing) as raised:
        new_fingerprint()
    assert raised.value.code == "camoufox_missing"
