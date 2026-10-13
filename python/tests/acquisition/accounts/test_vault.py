"""The source-account vault: sealing, opening, keys, and fingerprints; no network."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from thoth_control_plane.acquisition.accounts.vault import Vault, VaultError

KEY = Fernet.generate_key().decode()
SECRET = "sessionid=secret-cookie-value"


def test_a_sealed_value_opens_and_never_holds_the_plaintext() -> None:
    vault = Vault(KEY)
    token = vault.seal(SECRET)
    assert SECRET.encode() not in token
    assert vault.open(token) == SECRET


def test_another_key_or_a_damaged_token_is_a_vault_error() -> None:
    token = Vault(KEY).seal(SECRET)
    with pytest.raises(VaultError) as caught:
        Vault(Fernet.generate_key().decode()).open(token)
    assert str(caught.value) == ""
    with pytest.raises(VaultError):
        Vault(KEY).open(token[:-4] + b"AAAA")
    with pytest.raises(VaultError):
        Vault(KEY).open(b"not a token")


@pytest.mark.parametrize("key", [None, "", "not-a-fernet-key", "a" * 44])
def test_an_absent_or_malformed_key_gives_no_vault(key: str | None) -> None:
    assert Vault.from_key(key) is None


def test_fingerprints_are_stable_keyed_and_opaque() -> None:
    vault = Vault(KEY)
    assert vault.fingerprint(SECRET) == Vault(KEY).fingerprint(SECRET)
    assert vault.fingerprint(SECRET) != vault.fingerprint(SECRET + "x")
    assert vault.fingerprint(SECRET) != Vault(Fernet.generate_key().decode()).fingerprint(SECRET)
    assert "secret" not in vault.fingerprint(SECRET)


def test_bytes_seal_and_open_for_profile_archives() -> None:
    vault = Vault(KEY)
    token = vault.seal_bytes(b"\x00tar archive")

    assert b"tar archive" not in token and vault.open_bytes(token) == b"\x00tar archive"
    with pytest.raises(VaultError):
        Vault(Fernet.generate_key().decode()).open_bytes(token)
