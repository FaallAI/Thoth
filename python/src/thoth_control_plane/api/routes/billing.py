"""Plans, allowance and checkout for the caller's workspace (spec 2026-10-20 billing)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from thoth_control_plane.api.dependencies import current_principal, require_write
from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID, Principal, is_platform_admin
from thoth_control_plane.billing import UnknownPlan
from thoth_control_plane.domain.models import StrictModel
from thoth_control_plane.infrastructure.billing_store import BillingStore
from thoth_control_plane.infrastructure.xendit import PaymentProviderUnavailable

router = APIRouter(tags=["billing"])
Caller = Annotated[Principal, Depends(current_principal)]


class CheckoutRequest(StrictModel):
    plan_id: str


class CheckoutView(StrictModel):
    invoice_id: str | None
    invoice_url: str | None
    applied: bool


def _store(request: Request) -> BillingStore:
    store = request.app.state.billing_store
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_unavailable")
    return store


@router.post("/billing/checkout", response_model=CheckoutView)
async def checkout(request: Request, body: CheckoutRequest, principal: Caller) -> CheckoutView:
    """Buy or renew a plan (spec 2.1): owners and admins of the workspace only."""
    require_write(request, principal)
    if principal.role not in ("owner", "admin") and not is_platform_admin(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")
    if principal.workspace_id == BOOTSTRAP_WORKSPACE_ID:
        raise HTTPException(status.HTTP_409_CONFLICT, "operator_workspace")
    store = _store(request)
    plan = await asyncio.to_thread(store.plan, body.plan_id)
    if plan is None or not plan.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown_plan")
    if plan.price_idr == 0:
        await asyncio.to_thread(store.apply_plan, principal.workspace_id, plan.plan_id)
        return CheckoutView(invoice_id=None, invoice_url=None, applied=True)
    payments = getattr(request.app.state, "payments", None)
    if payments is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing_unavailable")
    try:
        invoice = await asyncio.to_thread(store.open_invoice, principal.workspace_id, plan.plan_id)
    except UnknownPlan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown_plan") from None
    back = f"{request.app.state.settings.THOTH_SITE_ORIGIN}/billing"
    try:
        made = await payments.create(
            external_id=invoice.invoice_id,
            amount_idr=invoice.amount_idr,
            payer_email=principal.email or "",
            description=plan.name,
            success_url=back,
            failure_url=back,
        )
    except PaymentProviderUnavailable:
        await asyncio.to_thread(store.fail_invoice, invoice.invoice_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "payment_provider_unavailable") from None
    await asyncio.to_thread(store.attach_invoice, invoice.invoice_id, made.id, made.invoice_url)
    return CheckoutView(invoice_id=invoice.invoice_id, invoice_url=made.invoice_url, applied=False)
