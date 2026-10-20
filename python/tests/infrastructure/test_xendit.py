"""The Xendit invoice adapter over a fake transport; no request leaves the machine."""

import base64
import json

import httpx
import pytest

from thoth_control_plane.infrastructure.xendit import PaymentProviderUnavailable, XenditInvoices


async def test_an_invoice_request_carries_what_xendit_needs() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "xnd_1", "invoice_url": "https://checkout.x/1"})

    invoices = XenditInvoices("xnd_secret", transport=httpx.MockTransport(handler))
    made = await invoices.create(
        external_id="inv_1",
        amount_idr=99000,
        payer_email="a@b.test",
        description="Pro",
        success_url="http://site/billing",
        failure_url="http://site/billing",
    )
    assert (made.id, made.invoice_url) == ("xnd_1", "https://checkout.x/1")
    assert seen["url"] == "https://api.xendit.co/v2/invoices"
    assert seen["auth"] == "Basic " + base64.b64encode(b"xnd_secret:").decode()
    assert seen["body"] == {
        "external_id": "inv_1",
        "amount": 99000,
        "payer_email": "a@b.test",
        "description": "Pro",
        "invoice_duration": 86400,
        "currency": "IDR",
        "success_redirect_url": "http://site/billing",
        "failure_redirect_url": "http://site/billing",
    }


@pytest.mark.parametrize("status", [400, 401, 500])
async def test_a_refusal_never_carries_the_secret(status) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json={"message": "no"}))
    with pytest.raises(PaymentProviderUnavailable) as failed:
        await XenditInvoices("xnd_secret", transport=transport).create(
            external_id="i",
            amount_idr=1,
            payer_email="a@b.test",
            description="d",
            success_url="u",
            failure_url="u",
        )
    assert "xnd_secret" not in repr(failed.value)
