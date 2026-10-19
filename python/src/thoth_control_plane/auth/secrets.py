"""Random tokens, their hashes, and email codes. Only hashes and HMACs are ever stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets

#: Lets secret scanners recognise a leaked developer token.
TOKEN_PREFIX = "thoth_pat_"


def random_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def token_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hmac(secret: str, challenge_id: str, code: str) -> str:
    message = f"{challenge_id}:{code}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def same(a: str, b: str) -> bool:
    """Constant-time comparison that also accepts non-ASCII text."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
