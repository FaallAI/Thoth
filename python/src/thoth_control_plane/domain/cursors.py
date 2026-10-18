"""Opaque keyset cursors: `base64(<iso time>|<id>)`, newest-first paging."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime


class InvalidCursor(ValueError):
    """A cursor the server did not mint: a client error, answered 422."""


def encode_cursor(moment: datetime, key: str) -> str:
    return base64.urlsafe_b64encode(f"{moment.isoformat()}|{key}".encode()).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        moment, key = raw.split("|", 1)
        return datetime.fromisoformat(moment), key
    except (UnicodeError, binascii.Error, ValueError):
        raise InvalidCursor("invalid_cursor") from None
