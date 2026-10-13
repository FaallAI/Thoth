"""The source-account vault: Fernet encryption of cookie sets and proxy URLs.

The key is `THOTH_ACCOUNT_VAULT_KEY`, a Fernet key. Plaintext exists only in memory while a
session is built. A token this vault cannot open raises `VaultError`, which carries neither
the token nor the key.
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

_FINGERPRINT_CONTEXT = b"thoth-source-accounts/fingerprint/v1"


class VaultError(Exception):
    """A token this vault cannot open: another key, or a damaged value."""


class Vault:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)
        self._mac_key = hashlib.sha256(_FINGERPRINT_CONTEXT + key.encode("utf-8")).digest()

    @classmethod
    def from_key(cls, key: str | None) -> Vault | None:
        """A vault for a usable key; None when the key is absent or not a Fernet key."""
        if not key:
            return None
        try:
            return cls(key)
        except ValueError:
            return None

    def seal(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def open(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(bytes(token)).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, TypeError, ValueError):
            raise VaultError() from None

    def seal_bytes(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def open_bytes(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(bytes(token))
        except (InvalidToken, TypeError, ValueError):
            raise VaultError() from None

    def fingerprint(self, text: str) -> str:
        """A keyed digest that detects duplicates without keeping `text` in clear."""
        return hmac.new(self._mac_key, text.encode("utf-8"), hashlib.sha256).hexdigest()
