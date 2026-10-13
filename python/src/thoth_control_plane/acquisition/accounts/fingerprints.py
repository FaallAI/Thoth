"""A Camoufox account's fingerprint (spec 2026-10-13, section 3.4, amended 2026-10-14).

Camoufox is Firefox, and camoufox 0.5.8 refuses any other browser's fingerprint, so the
fingerprint comes from its own generator (fpgen). The same fingerprint on every launch keeps
Camoufox's identity salt, and with it fonts, voices, and noise seeds, stable for the account.
Patchright gets none: its real Chromium presents itself.
"""

from __future__ import annotations

import json
from typing import Any


def new_fingerprint() -> dict[str, Any]:
    """A Firefox fingerprint as plain JSON values; it must survive the vault round trip."""
    try:
        from camoufox.fingerprints import generate_fingerprint
    except ImportError:
        from thoth_control_plane.attribution.adapters.frames import ToolMissing

        raise ToolMissing("camoufox_missing") from None
    return json.loads(json.dumps(generate_fingerprint()))
