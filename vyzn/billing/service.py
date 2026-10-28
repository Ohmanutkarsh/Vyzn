"""
Billing and Camera Quota service for VYZN Netra.
Handles orders, quota calculations, manual UPI verification, audit logging, and Telegram alerts.
"""

from __future__ import annotations
import os
import re
import time
import secrets
import threading
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, status

from vyzn.billing.provider import PaymentProvider, ManualUpiProvider

logger = logging.getLogger("vyzn.billing")

# Thread-safe locks per tenant to guarantee atomic operations and prevent race conditions
_TENANT_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()

# Rate limiting for UTR submissions: tenant_id/ip -> list of timestamps
_UTR_RATE_LIMITS: Dict[str, List[float]] = {}
_RATE_LIMIT_LOCK = threading.Lock()
MAX_UTR_SUBMITS_PER_MINUTE = 5


def get_tenant_lock(tenant_id: str) -> threading.Lock:
    """Returns or creates a thread-safe Lock for a specific tenant."""
    with _LOCKS_LOCK:
        if tenant_id not in _TENANT_LOCKS:
            _TENANT_LOCKS[tenant_id] = threading.Lock()
        return _TENANT_LOCKS[tenant_id]


def get_camera_price_paise() -> int:
    """Reads configured camera price per unit in paise (e.g. 249900 paise = ₹2,499.00)."""
    raw = os.environ.get("CAMERA_PRICE_PAISE", "249900").strip()
    try:
        val = int(raw)
        return max(val, 1)
    except ValueError:
        return 249900


def get_max_cameras_per_order() -> int:
    """Reads maximum cameras allowed per single order."""
    raw = os.environ.get("MAX_CAMERAS_PER_ORDER", "20").strip()
    try:
        val = int(raw)
        return max(val, 1)
    except ValueError:
        return 20


def get_order_expiry_minutes() -> int:
    """Reads order expiration window in minutes."""
    raw = os.environ.get("ORDER_EXPIRY_MINUTES", "30").strip()
    try:
        val = int(raw)
        return max(val, 1)
    except ValueError:
        return 30


def is_billing_enforcement_enabled() -> bool:
    """Checks whether camera quota enforcement is active."""
    return os.environ.get("BILLING_ENFORCEMENT", "true").lower() in ("true", "1", "yes")



def get_admin_user_ids() -> List[str]:
    """Reads configured list of admin user IDs or emails from environment."""
    raw = os.environ.get("ADMIN_USER_IDS", "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    """Checks if the user has administrative privileges for billing actions."""
    if not user:
        return False
    role = user.get("role", "")
    if role in ("admin", "fleet_admin"):
        return True
    user_id = str(user.get("id") or user.get("user_id") or "").strip().lower()
    email = str(user.get("email") or "").strip().lower()
    default_admins = {"dirtbike000000@gmail.com", "tapise.utkarsh@gmail.com", "usr_primary_cloud"}
    if user_id in default_admins or email in default_admins:
        return True
    admin_ids = [x.lower() for x in get_admin_user_ids()]
    if not admin_ids:
        return False
    return user_id in admin_ids or email in admin_ids



def check_utr_rate_limit(key: str) -> None:
    """Enforces rate limiting on UTR submissions."""
    now = time.time()
    with _RATE_LIMIT_LOCK:
        timestamps = _UTR_RATE_LIMITS.get(key, [])
        # Keep only timestamps within the last 60 seconds
        timestamps = [t for t in timestamps if now - t < 60.0]
        if len(timestamps) >= MAX_UTR_SUBMITS_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many UTR submission attempts. Please wait a minute and try again."
            )
        timestamps.append(now)
        _UTR_RATE_LIMITS[key] = timestamps


def send_billing_telegram_alert(order: Dict[str, Any], settings: Any = None) -> bool:
    """
    Sends an instant Telegram notification to the store/admin owner when a UTR is submitted.
    Uses existing Telegram alert integration safely without raising unhandled exceptions.
    """
    try:
        import requests
        import json

        bot_token = os.environ.get("ADMIN_TELEGRAM_BOT_TOKEN") or os.environ.get("VYZN_ADMIN_TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("ADMIN_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "6856103038"

        # Dynamic cloud fallback
        if not bot_token:
            try:
                from vyzn.core.supabase_sync import get_supabase_url, get_supabase_headers, is_supabase_configured
                if is_supabase_configured():
                    r = requests.get(f"{get_supabase_url()}/storage/v1/object/vyzn-cloud-state/billing_state.json", headers=get_supabase_headers(), timeout=2.5)
                    if r.status_code == 200:
                        s = r.json()
                        bot_token = s.get("admin_telegram_bot_token")
                        if s.get("admin_telegram_chat_id"):
                            chat_id = str(s["admin_telegram_chat_id"])
            except Exception:
                pass

        if not bot_token or not chat_id:
            logger.info("Payment Telegram alert skipped: dedicated admin bot (ADMIN_TELEGRAM_BOT_TOKEN) not configured.")
            return False

        api_url = f"https://api.telegram.org/bot{bot_token}"
        amount_rupees = order["amount_paise"] / 100.0
        order_id = str(order.get("id"))
        order_code = order.get("order_code")
        tenant = order.get("tenant_id") or order.get("user_email") or "Unknown"
        qty = order.get("quantity", 1)
        utr = order.get("utr", "N/A")
        sub_time = order.get("submitted_at") or datetime.now(timezone.utc).isoformat()

        text = (
            "💳 *New VYZN Camera Quota Payment Submitted*\n\n"
            f"• *Order Code*: `{order_code}`\n"
            f"• *Tenant / Account*: `{tenant}`\n"
            f"• *Cameras Requested*: *+{qty}* camera(s)\n"
            f"• *Amount*: *₹{amount_rupees:,.2f}*\n"
            f"• *12-Digit UTR*: `{utr}`\n"
            f"• *Submitted At*: {sub_time}\n\n"
            "⚠️ *Manual Verification Required:*\n"
            f"_Match amount (₹{amount_rupees:,.2f}), UTR (`{utr}`), and order code in your UPI app before approving._"
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": f"✅ Approve (+{qty} cams)", "callback_data": f"admin_approve_{order_id}"},
                    {"text": "❌ Reject", "callback_data": f"admin_reject_{order_id}"}
                ],
                [
                    {"text": "📊 Open Admin Console", "url": "https://vyzn-security.vercel.app/admin/billing"}
                ]
            ]
        }

        resp = requests.post(
            f"{api_url}/sendMessage",
            json={
                "chat_id": str(chat_id),
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": inline_keyboard
            },
            timeout=8.0
        )
        return (resp.status_code == 200 and resp.json().get("ok"))
    except Exception as e:
        logger.warning(f"Failed to dispatch Telegram billing notification: {e}")
        return False


class BillingService:
    """Core billing and quota operations engine."""

    def __init__(self, db: Any, payment_provider: Optional[PaymentProvider] = None):
        self.db = db
        self.provider = payment_provider or ManualUpiProvider()

    def get_tenant_quota(self, tenant_id: str, used_count: int) -> Dict[str, Any]:
        """
        Retrieves quota for a tenant:
        used = current camera count
        available = max(purchased - used, 0)
        Backfills initial purchased = used if no record exists yet.
        """
        conn = self.db._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT purchased FROM camera_quota WHERE tenant_id = ?", (tenant_id,))
            row = cursor.fetchone()
            if row is not None:
                purchased = int(row[0])
            else:
                # Backfill: initialize purchased = used_count so existing cameras are never blocked
                now_iso = datetime.now(timezone.utc).isoformat()
                purchased = used_count
                self.db.writer.queue.put((
                    "INSERT OR IGNORE INTO camera_quota (tenant_id, purchased, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (tenant_id, purchased, now_iso, now_iso),
                    None
                ))

            available = max(purchased - used_count, 0)
            return {
                "tenant_id": tenant_id,
                "purchased": purchased,
                "used": used_count,
                "available": available,
                "price_per_camera_paise": get_camera_price_paise(),
                "max_per_order": get_max_cameras_per_order(),
                "enforcement_enabled": is_billing_enforcement_enabled()
            }
        finally:
            conn.close()

    def create_order(
        self,
        tenant_id: str,
        user_id: Optional[str],
        quantity: int
    ) -> Dict[str, Any]:
        """
        Creates a new quota top-up order.
        Validates quantity and ensures tenant has at most ONE order in awaiting_payment or submitted.
        Calculates amount strictly on the server: quantity x CAMERA_PRICE_PAISE.
        """
        max_qty = get_max_cameras_per_order()
        if quantity < 1 or quantity > max_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid camera quantity. Must be between 1 and {max_qty}."
            )

        with get_tenant_lock(tenant_id):
            # Expire any stale orders first
            self.expire_stale_orders()

            conn = self.db._get_read_conn()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, order_code, status FROM quota_orders WHERE tenant_id = ? AND status IN ('awaiting_payment', 'submitted')",
                    (tenant_id,)
                )
                open_order = cursor.fetchone()
                if open_order:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"An open order ({open_order[1]}) with status '{open_order[2]}' already exists. Please complete or cancel it."
                    )
            finally:
                conn.close()

            # Server-calculated amount
            unit_price_paise = get_camera_price_paise()
            amount_paise = quantity * unit_price_paise

            # Generate unique human-readable order code like VYZ-4821
            order_code = f"VYZ-{secrets.randbelow(9000) + 1000}"
            order_id = f"ord_{secrets.token_hex(8)}"
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            expires_at = (now + timedelta(minutes=get_order_expiry_minutes())).isoformat()

            order_record = {
                "id": order_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "quantity": quantity,
                "unit_price_paise": unit_price_paise,
                "amount_paise": amount_paise,
                "order_code": order_code,
                "status": "awaiting_payment",
                "utr": None,
                "submitted_at": None,
                "verified_by": None,
                "verified_at": None,
                "reject_reason": None,
                "expires_at": expires_at,
                "created_at": now_iso
            }

            # Persist order synchronously via direct connection to respect partial unique index
            conn = sqlite3_connect_write(self.db.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO quota_orders (
                        id, tenant_id, user_id, quantity, unit_price_paise, amount_paise,
                        order_code, status, utr, submitted_at, verified_by, verified_at,
                        reject_reason, expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id, tenant_id, user_id, quantity, unit_price_paise, amount_paise,
                        order_code, "awaiting_payment", None, None, None, None,
                        None, expires_at, now_iso
                    )
                )
                # Audit row
                conn.execute(
                    "INSERT INTO payment_audit (order_id, actor, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    (order_id, user_id or tenant_id, "ORDER_CREATED", f"Created order {order_code} for {quantity} cameras (₹{amount_paise/100:.2f})", now_iso)
                )
                conn.commit()
            finally:
                conn.close()

            # Build payment instructions via PaymentProvider
            payment = self.provider.build_payment(order_record)
            order_record["upi_link"] = payment["upi_link"]
            order_record["qr"] = payment["qr"]

            return order_record

    def submit_utr(
        self,
        order_id: str,
        tenant_id: str,
        user_id: Optional[str],
        utr: str,
        settings: Any = None
    ) -> Dict[str, Any]:
        """
        Validates 12-digit UTR, prevents reuse, sets status to 'submitted', logs audit,
        and dispatches Telegram notification to the admin.
        """
        utr_clean = str(utr).strip()
        if not re.match(r"^\d{12}$", utr_clean):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid UTR: proof of payment must be a valid 12-digit UPI reference number."
            )

        check_utr_rate_limit(f"{tenant_id}:{user_id or ''}")

        with get_tenant_lock(tenant_id):
            conn = sqlite3_connect_write(self.db.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, tenant_id, status, expires_at, order_code, quantity, amount_paise FROM quota_orders WHERE id = ?",
                    (order_id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

                o_id, o_tenant, o_status, o_expires_at, o_code, o_qty, o_amount = row
                if o_tenant != tenant_id:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this order.")

                if o_status != "awaiting_payment":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Order cannot accept UTR. Current status: '{o_status}'."
                    )

                # Check expiration
                try:
                    exp_dt = datetime.fromisoformat(o_expires_at)
                    if datetime.now(timezone.utc) > exp_dt:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        conn.execute("UPDATE quota_orders SET status = 'expired' WHERE id = ?", (order_id,))
                        conn.execute(
                            "INSERT INTO payment_audit (order_id, actor, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                            (order_id, user_id or tenant_id, "ORDER_EXPIRED", "Order expired prior to UTR submission", now_iso)
                        )
                        conn.commit()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Order has expired. Please create a new order."
                        )
                except ValueError:
                    pass

                # Check UTR uniqueness across all orders
                cursor.execute("SELECT id, order_code FROM quota_orders WHERE utr = ? AND id != ?", (utr_clean, order_id))
                existing = cursor.fetchone()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="This UTR has already been submitted for another order. Please check your transaction reference."
                    )

                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE quota_orders SET status = 'submitted', utr = ?, submitted_at = ? WHERE id = ?",
                    (utr_clean, now_iso, order_id)
                )
                conn.execute(
                    "INSERT INTO payment_audit (order_id, actor, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    (order_id, user_id or tenant_id, "UTR_SUBMITTED", f"Submitted 12-digit UTR: {utr_clean}", now_iso)
                )
                conn.commit()

                updated_order = {
                    "id": order_id,
                    "order_code": o_code,
                    "tenant_id": tenant_id,
                    "quantity": o_qty,
                    "amount_paise": o_amount,
                    "status": "submitted",
                    "utr": utr_clean,
                    "submitted_at": now_iso
                }
            finally:
                conn.close()

            # Dispatch notification
            send_billing_telegram_alert(updated_order, settings=settings)
            return updated_order

    def approve_order(self, order_id: str, admin_user: str) -> Dict[str, Any]:
        """
        Approves a submitted order in ONE atomic transaction:
        - Locks order row
        - Requires status == 'submitted'
        - Sets status to 'paid'
        - Upserts camera_quota by adding quantity to purchased
        - Writes audit row
        Approving twice credits only once.
        """
        conn = sqlite3_connect_write(self.db.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tenant_id, quantity, status, order_code, amount_paise FROM quota_orders WHERE id = ?",
                (order_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

            o_id, tenant_id, quantity, o_status, o_code, o_amount = row

            if o_status != "submitted":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Order must be in 'submitted' status to approve. Current status: '{o_status}'."
                )

            with get_tenant_lock(tenant_id):
                now_iso = datetime.now(timezone.utc).isoformat()
                # 1. Update order status to paid
                conn.execute(
                    "UPDATE quota_orders SET status = 'paid', verified_by = ?, verified_at = ? WHERE id = ? AND status = 'submitted'",
                    (admin_user, now_iso, order_id)
                )
                if cursor.rowcount == 0:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Order state changed concurrently. Approval aborted."
                    )

                # 2. Credit camera quota
                cursor.execute("SELECT purchased FROM camera_quota WHERE tenant_id = ?", (tenant_id,))
                q_row = cursor.fetchone()
                if q_row is not None:
                    new_purchased = int(q_row[0]) + quantity
                    conn.execute(
                        "UPDATE camera_quota SET purchased = ?, updated_at = ? WHERE tenant_id = ?",
                        (new_purchased, now_iso, tenant_id)
                    )
                else:
                    new_purchased = quantity
                    conn.execute(
                        "INSERT INTO camera_quota (tenant_id, purchased, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (tenant_id, new_purchased, now_iso, now_iso)
                    )

                # 3. Payment audit entry
                conn.execute(
                    "INSERT INTO payment_audit (order_id, actor, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    (order_id, admin_user, "ORDER_APPROVED", f"Approved {o_code}. Added {quantity} cameras to quota. Total purchased: {new_purchased}.", now_iso)
                )

                conn.commit()

                return {
                    "status": "paid",
                    "order_id": order_id,
                    "order_code": o_code,
                    "tenant_id": tenant_id,
                    "quantity_added": quantity,
                    "new_purchased_quota": new_purchased,
                    "verified_by": admin_user,
                    "verified_at": now_iso
                }
        finally:
            conn.close()

    def reject_order(self, order_id: str, admin_user: str, reason: str = "") -> Dict[str, Any]:
        """
        Rejects an order in awaiting_payment or submitted status.
        Does NOT alter quota. Writes audit row.
        """
        conn = sqlite3_connect_write(self.db.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tenant_id, status, order_code FROM quota_orders WHERE id = ?",
                (order_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

            o_id, tenant_id, o_status, o_code = row
            if o_status not in ("awaiting_payment", "submitted"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot reject order with status '{o_status}'."
                )

            with get_tenant_lock(tenant_id):
                now_iso = datetime.now(timezone.utc).isoformat()
                reason_clean = (reason or "Payment verification declined by administrator").strip()

                conn.execute(
                    "UPDATE quota_orders SET status = 'rejected', reject_reason = ?, verified_by = ?, verified_at = ? WHERE id = ?",
                    (reason_clean, admin_user, now_iso, order_id)
                )
                conn.execute(
                    "INSERT INTO payment_audit (order_id, actor, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    (order_id, admin_user, "ORDER_REJECTED", f"Rejected order {o_code}. Reason: {reason_clean}", now_iso)
                )
                conn.commit()

                return {
                    "status": "rejected",
                    "order_id": order_id,
                    "order_code": o_code,
                    "tenant_id": tenant_id,
                    "reject_reason": reason_clean,
                    "verified_by": admin_user,
                    "verified_at": now_iso
                }
        finally:
            conn.close()

    def expire_stale_orders(self) -> int:
        """
        Marks awaiting_payment orders whose expires_at is past now as 'expired'.
        NEVER auto-expires a 'submitted' order.
        """
        conn = sqlite3_connect_write(self.db.db_path)
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tenant_id, order_code FROM quota_orders WHERE status = 'awaiting_payment' AND expires_at < ?",
                (now_iso,)
            )
            stale = cursor.fetchall()
            count = 0
            for o_id, tenant_id, o_code in stale:
                conn.execute("UPDATE quota_orders SET status = 'expired' WHERE id = ?", (o_id,))
                conn.execute(
                    "INSERT INTO payment_audit (order_id, actor, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    (o_id, "system", "ORDER_EXPIRED", f"Auto-expired awaiting_payment order {o_code} past expiry window", now_iso)
                )
                count += 1
            if count > 0:
                conn.commit()
            return count
        finally:
            conn.close()

    def list_orders(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Lists all orders belonging to tenant, ordered by creation date desc."""
        self.expire_stale_orders()
        conn = self.db._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tenant_id, user_id, quantity, unit_price_paise, amount_paise,
                       order_code, status, utr, submitted_at, verified_by, verified_at,
                       reject_reason, expires_at, created_at
                FROM quota_orders
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                """,
                (tenant_id,)
            )
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_order(self, order_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetches a single order by ID, optionally validating tenant ownership."""
        self.expire_stale_orders()
        conn = self.db._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tenant_id, user_id, quantity, unit_price_paise, amount_paise,
                       order_code, status, utr, submitted_at, verified_by, verified_at,
                       reject_reason, expires_at, created_at
                FROM quota_orders
                WHERE id = ?
                """,
                (order_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
            cols = [d[0] for d in cursor.description]
            order = dict(zip(cols, row))
            if tenant_id and order["tenant_id"] != tenant_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

            # Attach UPI link and QR code if order is in awaiting_payment
            if order["status"] == "awaiting_payment":
                payment = self.provider.build_payment(order)
                order["upi_link"] = payment["upi_link"]
                order["qr"] = payment["qr"]

            return order
        finally:
            conn.close()

    def list_pending_orders(self) -> List[Dict[str, Any]]:
        """Lists pending orders requiring admin verification (status = 'submitted')."""
        conn = self.db._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tenant_id, user_id, quantity, unit_price_paise, amount_paise,
                       order_code, status, utr, submitted_at, verified_by, verified_at,
                       reject_reason, expires_at, created_at
                FROM quota_orders
                WHERE status = 'submitted'
                ORDER BY submitted_at ASC
                """
            )
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()


def sqlite3_connect_write(db_path: Any):
    """Opens a synchronous write connection with busy timeout to SQLite."""
    import sqlite3
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    return conn
