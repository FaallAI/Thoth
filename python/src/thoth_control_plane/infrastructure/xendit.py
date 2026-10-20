"""Xendit invoices over its REST API (spec 2026-10-20 billing, 2.1).

The secret key is the Basic-auth user name with an empty password; it never appears in an error
or a log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)
BASE_URL = "https://api.xendit.co"
INVOICE_SECONDS = 86400


class PaymentProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderInvoice:
    id: str
    invoice_url: str


class XenditInvoices:
    def __init__(
        self, secret_key: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._key = secret_key
        self._transport = transport

    def __repr__(self) -> str:
        return "XenditInvoices()"

    async def create(
        self,
        *,
        external_id: str,
        amount_idr: int,
        payer_email: str,
        description: str,
        success_url: str,
        failure_url: str,
    ) -> ProviderInvoice:
        body = {
            "external_id": external_id,
            "amount": amount_idr,
            "description": description,
            "invoice_duration": INVOICE_SECONDS,
            "currency": "IDR",
            "success_redirect_url": success_url,
            "failure_redirect_url": failure_url,
        }
        if payer_email:
            body["payer_email"] = payer_email
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, transport=self._transport, timeout=30, auth=(self._key, "")
            ) as http:
                response = await http.post("/v2/invoices", json=body)
        except httpx.HTTPError:
            logger.warning("xendit unreachable")
            raise PaymentProviderUnavailable("payment_provider_unavailable") from None
        if response.status_code >= 300:
            logger.warning("xendit refused an invoice status=%s", response.status_code)
            raise PaymentProviderUnavailable("payment_provider_unavailable")
        try:
            payload = response.json()
            return ProviderInvoice(str(payload["id"]), str(payload["invoice_url"]))
        except (ValueError, KeyError, TypeError):
            raise PaymentProviderUnavailable("payment_provider_unavailable") from None
