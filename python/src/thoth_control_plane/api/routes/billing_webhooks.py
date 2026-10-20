"""Xendit's invoice callback (spec 2026-10-20 billing, 2.2): public, token-verified, idempotent."""

from __future__ import annotations

import asyncio
import logging
from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

router = APIRouter(tags=["billing"], include_in_schema=False)
logger = logging.getLogger(__name__)


@router.post("/billing/webhooks/xendit")
async def xendit_webhook(
    request: Request,
    token: Annotated[str | None, Header(alias="x-callback-token")] = None,
) -> dict[str, str]:
    settings = request.app.state.settings
    store = request.app.state.billing_store
    expected = settings.THOTH_XENDIT_CALLBACK_TOKEN
    if expected is None or store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_unavailable")
    if token is None or not compare_digest(token.encode(), expected.get_secret_value().encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_token")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_body") from None
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_body")
    paid = body.get("paid_amount")
    outcome = await asyncio.to_thread(
        store.settle,
        str(body.get("external_id") or ""),
        str(body.get("status") or ""),
        int(paid) if isinstance(paid, int | float) else None,
    )
    if outcome in ("unknown", "mismatch"):
        logger.warning("xendit callback not applied outcome=%s", outcome)
    return {"status": outcome}
