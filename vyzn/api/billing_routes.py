"""
FastAPI Billing & Quota Endpoints for VYZN Netra.
Handles quota inquiries, order creation with manual UPI payment, UTR submissions,
and administrative approvals with audit logging.
"""

from __future__ import annotations
import os
import re
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from vyzn.billing.service import (
    BillingService,
    is_admin_user,
    get_camera_price_paise,
    get_max_cameras_per_order,
    get_order_expiry_minutes,
    is_billing_enforcement_enabled,
    send_billing_telegram_alert
)

router = APIRouter(tags=["billing"])


class CreateOrderRequest(BaseModel):
    quantity: int = Field(..., ge=1, description="Number of camera quota slots to purchase")
    # Client amount is explicitly forbidden/ignored to guarantee server-side calculation
    client_amount: Optional[int] = None


class SubmitUtrRequest(BaseModel):
    utr: str = Field(..., description="12-digit UPI transaction reference number")


class RejectOrderRequest(BaseModel):
    reason: Optional[str] = Field("Payment verification declined by administrator", description="Reason for rejection")


def get_billing_service(request: Request) -> BillingService:
    """Dependency injection helper for BillingService using the active database instance."""
    from vyzn.api.routes import get_db
    db = get_db()
    return BillingService(db=db)


def resolve_tenant_and_user(request: Request) -> tuple[str, Optional[Dict[str, Any]]]:
    """Resolves authenticated user and tenant identifier from request context."""
    from vyzn.api.routes import get_optional_user
    user = get_optional_user(request)
    if user:
        tenant_id = str(user.get("tenant_id") or user.get("id") or user.get("user_id") or user.get("email") or "tenant_local")
        return tenant_id, user
    return "tenant_local", None


def get_current_tenant_camera_count(tenant_id: str, user: Optional[Dict[str, Any]]) -> int:
    """Computes used quota (count of current cameras) for the tenant."""
    from vyzn.api.routes import get_settings
    settings = get_settings()
    cams = settings.cameras
    if not user or user.get("role") in ("admin", "fleet_admin"):
        return len(cams)
    user_email = user.get("email")
    if user_email:
        user_cams = [c for c in cams if getattr(c, "owner_email", None) == user_email]
        if user_cams or any(getattr(c, "owner_email", None) for c in cams):
            return len(user_cams)
    return len(cams)


# ==============================================================================
# Customer Facing Endpoints
# ==============================================================================

@router.get("/billing/quota")
def get_quota_endpoint(
    request: Request,
    billing: BillingService = Depends(get_billing_service)
):
    """
    Returns current quota facts:
    - purchased: total quota slots purchased and verified
    - used: current count of cameras
    - available: max(purchased - used, 0)
    - price_per_camera_paise: price in paise from server config
    - max_per_order: maximum cameras allowed in a single order
    """
    tenant_id, user = resolve_tenant_and_user(request)
    used_count = get_current_tenant_camera_count(tenant_id, user)
    return billing.get_tenant_quota(tenant_id=tenant_id, used_count=used_count)


@router.post("/billing/quota-orders", status_code=status.HTTP_201_CREATED)
def create_order_endpoint(
    req: CreateOrderRequest,
    request: Request,
    billing: BillingService = Depends(get_billing_service)
):
    """
    Creates a new quota top-up order.
    The server calculates amount = quantity x CAMERA_PRICE_PAISE and never trusts
    an amount from the client.
    Rejects with 409 if tenant already has an open order in awaiting_payment or submitted.
    """
    tenant_id, user = resolve_tenant_and_user(request)
    user_id = str(user.get("id") or user.get("user_id") or "") if user else None
    return billing.create_order(tenant_id=tenant_id, user_id=user_id, quantity=req.quantity)


@router.get("/billing/quota-orders")
def list_orders_endpoint(
    request: Request,
    billing: BillingService = Depends(get_billing_service)
):
    """Lists orders belonging exclusively to the caller's tenant."""
    tenant_id, _ = resolve_tenant_and_user(request)
    return billing.list_orders(tenant_id=tenant_id)


@router.get("/billing/quota-orders/{order_id}")
def get_order_endpoint(
    order_id: str,
    request: Request,
    billing: BillingService = Depends(get_billing_service)
):
    """Retrieves a single order by ID for the caller's tenant."""
    tenant_id, _ = resolve_tenant_and_user(request)
    return billing.get_order(order_id=order_id, tenant_id=tenant_id)


@router.post("/billing/quota-orders/{order_id}/submit-utr")
def submit_utr_endpoint(
    order_id: str,
    req: SubmitUtrRequest,
    request: Request,
    billing: BillingService = Depends(get_billing_service)
):
    """
    Submits a 12-digit UPI reference (UTR) for manual verification.
    Validates UTR format (12 numeric digits), ensures UTR is unique across all orders,
    moves order to 'submitted' state, writes audit log, and notifies admin via Telegram.
    Rate limited to prevent brute-force attacks.
    """
    tenant_id, user = resolve_tenant_and_user(request)
    user_id = str(user.get("id") or user.get("user_id") or "") if user else None

    from vyzn.api.routes import get_settings
    settings = get_settings()

    return billing.submit_utr(
        order_id=order_id,
        tenant_id=tenant_id,
        user_id=user_id,
        utr=req.utr,
        settings=settings
    )


# ==============================================================================
# Admin Verification Endpoints
# ==============================================================================

def require_admin_user(request: Request) -> Dict[str, Any]:
    """Ensures the caller has administrative rights for billing operations."""
    from vyzn.api.routes import get_optional_user
    user = get_optional_user(request)
    if not is_admin_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for billing verification."
        )
    return user or {"role": "admin", "id": "admin_system"}


@router.get("/admin/billing/pending")
def list_pending_orders_endpoint(
    request: Request,
    admin: Dict[str, Any] = Depends(require_admin_user),
    billing: BillingService = Depends(get_billing_service)
):
    """Lists all pending orders awaiting manual approval (status = 'submitted')."""
    return billing.list_pending_orders()


@router.post("/admin/billing/orders/{order_id}/approve")
def approve_order_endpoint(
    order_id: str,
    request: Request,
    admin: Dict[str, Any] = Depends(require_admin_user),
    billing: BillingService = Depends(get_billing_service)
):
    """
    Approves a submitted quota order in ONE atomic transaction.
    Sets status = 'paid', increases purchased quota, and writes audit record.
    Approving twice is idempotent and credits quota only once.
    """
    admin_actor = str(admin.get("email") or admin.get("id") or "admin")
    return billing.approve_order(order_id=order_id, admin_user=admin_actor)


@router.post("/admin/billing/orders/{order_id}/reject")
def reject_order_endpoint(
    order_id: str,
    req: RejectOrderRequest,
    request: Request,
    admin: Dict[str, Any] = Depends(require_admin_user),
    billing: BillingService = Depends(get_billing_service)
):
    """
    Rejects a pending order with a reason. Changes NO quota.
    """
    admin_actor = str(admin.get("email") or admin.get("id") or "admin")
    return billing.reject_order(order_id=order_id, admin_user=admin_actor, reason=req.reason or "")
