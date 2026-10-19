"""Send sign-in codes over SMTP (standard library), off the event loop."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from types import ModuleType
from typing import Any, Protocol

from thoth_control_plane.config import Settings

IMPLICIT_TLS_PORT = 465


class MailNotSent(Exception):
    """The relay refused or could not be reached. The server's text is never kept."""


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        *,
        smtp: ModuleType | Any = smtplib,
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._sender = sender
        self._smtp = smtp

    def __repr__(self) -> str:
        return "SmtpMailer()"

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send, to, subject, body)

    def _send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        try:
            if self._port == IMPLICIT_TLS_PORT:
                client = self._smtp.SMTP_SSL(self._host, self._port, timeout=15, context=context)
            else:
                client = self._smtp.SMTP(self._host, self._port, timeout=15)
            with client:
                if self._port != IMPLICIT_TLS_PORT:
                    client.starttls(context=context)
                if self._username:
                    client.login(self._username, self._password or "")
                client.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise MailNotSent() from None


def mailer_from(settings: Settings) -> Mailer | None:
    if not settings.email_codes_enabled:
        return None
    password = settings.THOTH_SMTP_PASSWORD
    return SmtpMailer(
        settings.THOTH_SMTP_HOST or "",
        settings.THOTH_SMTP_PORT,
        settings.THOTH_SMTP_USERNAME,
        password.get_secret_value() if password is not None else None,
        settings.THOTH_SMTP_FROM or "",
    )
