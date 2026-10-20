"""Who a provider may sign in (spec section 2, step 3). Pure functions, no network."""

import pytest

from thoth_control_plane.auth.models import SignInRefused
from thoth_control_plane.auth.rules import github_identity, google_identity


def refused(call) -> str:
    with pytest.raises(SignInRefused) as caught:
        call()
    return caught.value.code


def userinfo(**extra):
    return {
        "sub": "g-1",
        "email": "alice@acme.test",
        "email_verified": True,
        "name": "Alice",
    } | extra


def test_google_accepts_a_verified_address_in_the_exact_domain_lowercased() -> None:
    identity = google_identity(userinfo(email="ALICE@Acme.Test", hd="acme.test"), "acme.test")
    assert (identity.provider, identity.subject, identity.email) == (
        "google",
        "g-1",
        "alice@acme.test",
    )


@pytest.mark.parametrize(
    "email", ["alice@sub.acme.test", "alice@acme.test.evil.test", "alice@evil.test", "acme.test"]
)
def test_google_refuses_any_other_domain(email) -> None:
    assert refused(lambda: google_identity(userinfo(email=email), "acme.test")) == "not_allowed"


@pytest.mark.parametrize("verified", [False, None, "true"])
def test_google_requires_a_provider_verified_email(verified) -> None:
    claims = userinfo(email_verified=verified)
    assert refused(lambda: google_identity(claims, "acme.test")) == "unverified_email"


def test_google_refuses_a_workspace_claim_for_another_domain() -> None:
    claims = userinfo(hd="other.test")
    assert refused(lambda: google_identity(claims, "acme.test")) == "not_allowed"


GITHUB_USER = {"id": 42, "login": "alice", "name": "Alice"}
VERIFIED = [{"email": "Alice@Acme.test", "primary": True, "verified": True}]


def membership(state="active", org="Acme"):
    return {"state": state, "organization": {"login": org}}


def test_github_accepts_an_active_member_with_a_verified_primary_email() -> None:
    identity = github_identity(GITHUB_USER, VERIFIED, membership(), "acme")
    assert (identity.provider, identity.subject, identity.email, identity.display_name) == (
        "github",
        "42",
        "alice@acme.test",
        "Alice",
    )


@pytest.mark.parametrize("member", [None, membership(state="pending"), membership(org="Other")])
def test_github_refuses_anyone_not_an_active_member_of_the_org(member) -> None:
    assert refused(lambda: github_identity(GITHUB_USER, VERIFIED, member, "acme")) == "not_allowed"


@pytest.mark.parametrize(
    "emails",
    [
        [],
        [{"email": "a@acme.test", "primary": True, "verified": False}],
        [{"email": "a@acme.test", "primary": False, "verified": True}],
    ],
)
def test_github_requires_a_verified_primary_email(emails) -> None:
    call = lambda: github_identity(GITHUB_USER, emails, membership(), "acme")  # noqa: E731
    assert refused(call) == "unverified_email"


def test_public_sign_up_admits_a_verified_google_address_from_any_domain() -> None:
    outsider = userinfo(email="Someone@Gmail.com")
    assert refused(lambda: google_identity(outsider, "acme.test")) == "not_allowed"
    assert google_identity(outsider, "acme.test", public=True).email == "someone@gmail.com"
    unverified = userinfo(email="x@gmail.com", email_verified=False)
    assert refused(lambda: google_identity(unverified, "acme.test", public=True)) == (
        "unverified_email"
    )


def test_public_sign_up_admits_a_github_user_outside_the_org_with_a_verified_email() -> None:
    user = {"id": 7, "login": "out"}
    emails = [{"email": "out@x.test", "primary": True, "verified": True}]
    assert refused(lambda: github_identity(user, emails, None, "FaallAI")) == "not_allowed"
    assert github_identity(user, emails, None, "FaallAI", public=True).email == "out@x.test"
    unverified = [{**emails[0], "verified": False}]
    assert refused(lambda: github_identity(user, unverified, None, "FaallAI", public=True)) == (
        "unverified_email"
    )
