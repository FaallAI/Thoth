"""Turn a provider's answer into a verified identity, or refuse it with a fixed code."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from thoth_control_plane.auth.models import SignInRefused, VerifiedIdentity


def _domain(email: str) -> str:
    return email.rpartition("@")[2] if "@" in email else ""


def google_identity(userinfo: Mapping[str, object], domain: str) -> VerifiedIdentity:
    if userinfo.get("email_verified") is not True:
        raise SignInRefused("unverified_email")
    email = str(userinfo.get("email") or "").strip().lower()
    wanted = domain.strip().lower()
    if not email or _domain(email) != wanted:
        raise SignInRefused("not_allowed")
    hosted = userinfo.get("hd")
    if hosted is not None and str(hosted).strip().lower() != wanted:
        raise SignInRefused("not_allowed")
    subject = str(userinfo.get("sub") or "")
    if not subject:
        raise SignInRefused("provider_error")
    return VerifiedIdentity("google", subject, email, str(userinfo.get("name") or email)[:200])


def github_identity(
    user: Mapping[str, object],
    emails: Sequence[Mapping[str, object]],
    membership: Mapping[str, object] | None,
    org: str,
) -> VerifiedIdentity:
    subject = str(user.get("id") or "")
    if not subject:
        raise SignInRefused("provider_error")
    primary = next((e for e in emails if isinstance(e, Mapping) and e.get("primary")), None)
    email = str((primary or {}).get("email") or "").strip().lower()
    if primary is None or primary.get("verified") is not True or "@" not in email:
        raise SignInRefused("unverified_email")
    organization = (membership or {}).get("organization") or {}
    login = str(organization.get("login") or "") if isinstance(organization, Mapping) else ""
    if (
        membership is None
        or membership.get("state") != "active"
        or login.lower() != org.strip().lower()
    ):
        raise SignInRefused("not_allowed")
    name = str(user.get("name") or user.get("login") or email)[:200]
    return VerifiedIdentity("github", subject, email, name)
