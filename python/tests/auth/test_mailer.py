"""Email codes over SMTP; the library is faked so no socket opens (spec section 5)."""

import smtplib
import types
from typing import ClassVar

import pytest

from thoth_control_plane.auth.mailer import MailNotSent, SmtpMailer, mailer_from
from thoth_control_plane.config import Settings


class FakeSmtp:
    sent: ClassVar[list] = []
    calls: ClassVar[list] = []
    fail = False

    def __init__(self, host, port, timeout, **_):
        FakeSmtp.calls.append(("connect", type(self).__name__, host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSmtp.calls.append(("starttls",))

    def login(self, user, password):
        FakeSmtp.calls.append(("login", user))

    def send_message(self, message):
        if FakeSmtp.fail:
            raise smtplib.SMTPException("relay refused")
        FakeSmtp.sent.append(message)


class FakeSmtpSsl(FakeSmtp):
    pass


@pytest.fixture(autouse=True)
def reset():
    FakeSmtp.sent, FakeSmtp.calls, FakeSmtp.fail = [], [], False


FAKE = types.SimpleNamespace(
    SMTP=FakeSmtp, SMTP_SSL=FakeSmtpSsl, SMTPException=smtplib.SMTPException
)


async def test_a_code_is_sent_over_starttls_with_login() -> None:
    mailer = SmtpMailer("smtp.test", 587, "user", "pw", "Thoth <no-reply@acme.test>", smtp=FAKE)
    await mailer.send("alice@acme.test", "Your code", "123456")
    (message,) = FakeSmtp.sent
    assert (message["To"], message["From"], message["Subject"]) == (
        "alice@acme.test",
        "Thoth <no-reply@acme.test>",
        "Your code",
    )
    assert [call[0] for call in FakeSmtp.calls] == ["connect", "starttls", "login"]


async def test_port_465_uses_implicit_tls() -> None:
    await SmtpMailer("smtp.test", 465, None, None, "a@acme.test", smtp=FAKE).send(
        "b@acme.test", "s", "b"
    )
    assert FakeSmtp.calls[0][1] == "FakeSmtpSsl"
    assert ("starttls",) not in FakeSmtp.calls


async def test_a_relay_failure_is_mail_not_sent_without_the_server_text() -> None:
    FakeSmtp.fail = True
    with pytest.raises(MailNotSent) as caught:
        await SmtpMailer("smtp.test", 587, None, None, "a@acme.test", smtp=FAKE).send(
            "b@acme.test", "s", "b"
        )
    assert "relay refused" not in str(caught.value)


def test_no_mailer_without_host_and_sender() -> None:
    assert mailer_from(Settings(THOTH_CONTROL_PLANE_API_KEY="k")) is None
    configured = Settings(
        THOTH_CONTROL_PLANE_API_KEY="k", THOTH_SMTP_HOST="smtp.test", THOTH_SMTP_FROM="a@acme.test"
    )
    assert isinstance(mailer_from(configured), SmtpMailer)
