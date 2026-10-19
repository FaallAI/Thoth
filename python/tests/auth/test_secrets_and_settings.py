"""Secret helpers and the sign-in settings (spec 2026-10-19, sections 3 and 5)."""

from thoth_control_plane.auth.models import SCOPE_SETS, Principal
from thoth_control_plane.auth.secrets import (
    TOKEN_PREFIX,
    code_hmac,
    new_code,
    random_token,
    same,
    token_hash,
)
from thoth_control_plane.config import Settings


def test_tokens_are_random_prefixed_and_only_their_hash_is_stable() -> None:
    first, second = random_token(TOKEN_PREFIX), random_token(TOKEN_PREFIX)
    assert first.startswith("thoth_pat_") and first != second
    assert len(first) > len(TOKEN_PREFIX) + 40
    assert token_hash(first) == token_hash(first) != token_hash(second)
    assert len(token_hash(first)) == 64


def test_codes_are_six_digits_and_their_hmac_binds_the_challenge() -> None:
    code = new_code()
    assert len(code) == 6 and code.isdigit()
    assert code_hmac("s", "chl_1", "123456") != code_hmac("s", "chl_2", "123456")
    assert code_hmac("s", "chl_1", "123456") != code_hmac("t", "chl_1", "123456")
    assert same("abc", "abc") and not same("abc", "abd")
    assert not same("é", "e")  # non-ASCII input compares as bytes instead of raising


def test_scope_levels_imply_the_lower_ones() -> None:
    assert SCOPE_SETS["read"] == {"read"}
    assert SCOPE_SETS["write"] == {"read", "write"}
    assert SCOPE_SETS["admin"] == {"read", "write", "admin"}
    principal = Principal(None, "ws_bootstrap", SCOPE_SETS["admin"], "service")
    assert principal.email is None


def test_blank_auth_settings_are_unset_and_sign_in_needs_every_part() -> None:
    blank = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_AUTH_GOOGLE_CLIENT_ID="",
        THOTH_AUTH_GOOGLE_CLIENT_SECRET="",
        THOTH_SMTP_HOST="  ",
    )
    assert blank.THOTH_AUTH_GOOGLE_CLIENT_ID is None
    assert blank.THOTH_AUTH_GOOGLE_CLIENT_SECRET is None
    assert blank.THOTH_SMTP_HOST is None
    assert not blank.google_sign_in_enabled and not blank.cookie_secure
    ready = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k",
        THOTH_EDITOR_DATABASE_URL="postgresql://u:p@db/x",
        THOTH_SITE_ORIGIN="https://thoth.example",
        THOTH_AUTH_SECRET="s" * 32,
        THOTH_SMTP_HOST="smtp.example",
        THOTH_SMTP_FROM="Thoth <no-reply@thoth.example>",
        THOTH_AUTH_GOOGLE_CLIENT_ID="gid",
        THOTH_AUTH_GOOGLE_CLIENT_SECRET="gsecret",
        THOTH_AUTH_GOOGLE_DOMAIN="acme.test",
    )
    assert ready.sign_in_ready and ready.google_sign_in_enabled and ready.cookie_secure
    assert not ready.github_sign_in_enabled
