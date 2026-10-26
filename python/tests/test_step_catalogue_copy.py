"""Every run-progress step code has dashboard copy (restyle spec R1, run-progress spec §5)."""

from __future__ import annotations

import re
from pathlib import Path

from thoth_control_plane.attribution.models import Verdict
from thoth_control_plane.progress import CATALOGUE

I18N = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "lib" / "i18n.ts"


def test_every_catalogue_code_has_a_dashboard_sentence() -> None:
    # The dashboard test checks Indonesian against English; this checks English against the backend.
    source = I18N.read_text(encoding="utf-8")
    keys = set(re.findall(r'^\s*"(step\.[a-z_.]+)":', source, re.MULTILINE))
    wanted = {f"step.{code}" for code in CATALOGUE if code != "attribution.verdict"}
    wanted |= {f"step.attribution.verdict.{verdict}" for verdict in Verdict.__args__}
    assert wanted <= keys, sorted(wanted - keys)
