"""
Comprehensive automated test suite for VYZN Netra Camera Quota & Manual UPI Billing System.
Verifies:
1. Amount is always server-calculated (never trusts client amount).
2. Quota math: available = max(purchased - used, 0).
3. Concurrency test: with 1 slot left, 2 simultaneous adds result in exactly 1 success and 1 QUOTA_EXHAUSTED.
4. Double-approve credits quota only once (idempotent).
5. UTR uniqueness (duplicate UTR is rejected).
6. Expired orders cannot be submitted.
7. Submitted orders never auto-expire.
8. Second open order is refused while awaiting_payment or submitted.
9. Non-admins cannot approve or reject orders.
10. Quota changes ONLY via approve action.
"""

import os
import time
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings, CameraConfig
from vyzn.billing.service import (
    BillingService,
    get_camera_price_paise,
    get_max_cameras_per_order
)
from vyzn.billing.provider import ManualUpiProvider

client = TestClient(app)


@pytest.fixture
def test_env():
    """Sets up an isolated database and test settings for each test."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_billing.db"
        db = EventDatabase(db_path=db_path)
        settings = EdgeSettings(data_dir=Path(tmp_dir), db_path=db_path)
        settings.cameras = []
        init_api(db=db, settings=settings)

        # Set standard test environment
        os.environ["UPI_VPA"] = "vyzntest@upi"
        os.environ["UPI_PAYEE_NAME"] = "VYZN Test"
        os.environ["CAMERA_PRICE_PAISE"] = "50000"
        os.environ["MAX_CAMERAS_PER_ORDER"] = "10"
        os.environ["ORDER_EXPIRY_MINUTES"] = "30"
        os.environ["ADMIN_USER_IDS"] = "admin_user_01,admin@vyzn.ai"
        os.environ["BILLING_ENFORCEMENT"] = "false"

        try:
            yield {
                "tmp_dir": tmp_dir,
                "db": db,
                "settings": settings,
                "billing": BillingService(db=db)
            }
        finally:
            db.close()


def test_amount_always_server_calculated(test_env):
    """
    Test 1: Server calculates amount = quantity x CAMERA_PRICE_PAISE.
    Any client-provided amount is ignored or overwritten.
    """
    billing = test_env["billing"]
    tenant_id = "tenant_test_calc"

    # 3 cameras at 50,000 paise each = 150,000 paise (₹1,500)
    order = billing.create_order(tenant_id=tenant_id, user_id="user_1", quantity=3)
    assert order["quantity"] == 3
    assert order["unit_price_paise"] == 50000
    assert order["amount_paise"] == 150000
    assert order["status"] == "awaiting_payment"
    assert order["order_code"].startswith("VYZ-")
    assert "upi_link" in order
    assert "pa=vyzntest%40upi" in order["upi_link"] or "pa=vyzntest@upi" in order["upi_link"]
    assert "am=1500.00" in order["upi_link"]
    assert "cu=INR" in order["upi_link"]
    assert order["qr"].startswith("data:image/png;base64,")

    # API POST /billing/quota-orders also enforces server-side calculation
    # Even if client tries to send an amount or override price, server enforces:
    resp = client.post("/billing/quota-orders", json={"quantity": 2, "client_amount": 100})
    assert resp.status_code == 201
    data = resp.json()
    assert data["amount_paise"] == 100000
    assert data["unit_price_paise"] == 50000

    # Second open order for the same tenant is refused with 409
    resp2 = client.post("/billing/quota-orders", json={"quantity": 1})
    assert resp2.status_code == 409


def test_quota_math(test_env):
    """
    Test 2: Quota calculation:
    used = current camera count
    available = max(purchased - used, 0)
    """
    billing = test_env["billing"]
    tenant_id = "tenant_math"

    # Initial state: used = 0 -> backfills purchased = 0, available = 0
    q = billing.get_tenant_quota(tenant_id, used_count=0)
    assert q["purchased"] == 0
    assert q["used"] == 0
    assert q["available"] == 0

    # If tenant has 3 cameras already configured, backfill sets purchased = 3
    tenant_backfill = "tenant_existing_shop"
    q_bf = billing.get_tenant_quota(tenant_backfill, used_count=3)
    assert q_bf["purchased"] == 3
    assert q_bf["used"] == 3
    assert q_bf["available"] == 0

    # Manually add purchased quota = 5
    from vyzn.billing.service import sqlite3_connect_write
    conn = sqlite3_connect_write(test_env["db"].db_path)
    conn.execute("UPDATE camera_quota SET purchased = 5 WHERE tenant_id = ?", (tenant_backfill,))
    conn.commit()
    conn.close()

    # Now used = 3, purchased = 5 -> available = 2
    q_updated = billing.get_tenant_quota(tenant_backfill, used_count=3)
    assert q_updated["purchased"] == 5
    assert q_updated["used"] == 3
    assert q_updated["available"] == 2

    # If used > purchased (e.g. edge node had 6 cameras): available = max(5 - 6, 0) = 0
    q_over = billing.get_tenant_quota(tenant_backfill, used_count=6)
    assert q_over["available"] == 0


def test_second_open_order_refused(test_env):
    """
    Test 3: A tenant can have at most ONE order in awaiting_payment or submitted.
    Creating a second open order raises 409 Conflict.
    """
    billing = test_env["billing"]
    tenant_id = "tenant_single_order"

    # First order
    order1 = billing.create_order(tenant_id=tenant_id, user_id="u1", quantity=2)
    assert order1["status"] == "awaiting_payment"

    # Attempt to create second order while first is awaiting_payment -> 409
    with pytest.raises(Exception) as exc_info:
        billing.create_order(tenant_id=tenant_id, user_id="u1", quantity=1)
    assert "already exists" in str(exc_info.value).lower() or getattr(exc_info.value, "status_code", None) == 409

    # Submit UTR for order1 -> status becomes submitted
    billing.submit_utr(order_id=order1["id"], tenant_id=tenant_id, user_id="u1", utr="123456789012")

    # Attempt to create second order while first is submitted -> 409
    with pytest.raises(Exception) as exc_info:
        billing.create_order(tenant_id=tenant_id, user_id="u1", quantity=1)
    assert getattr(exc_info.value, "status_code", None) == 409


def test_utr_uniqueness_and_validation(test_env):
    """
    Test 4: UTR must be exactly 12 numeric digits.
    Duplicate UTRs across orders are rejected with 409.
    """
    billing = test_env["billing"]

    # Order 1
    ord1 = billing.create_order(tenant_id="t1", user_id="u1", quantity=1)

    # Invalid UTR format (letters, short, long)
    for bad_utr in ["123", "abcdefghijkl", "12345678901", "1234567890123", ""]:
        with pytest.raises(Exception) as exc:
            billing.submit_utr(order_id=ord1["id"], tenant_id="t1", user_id="u1", utr=bad_utr)
        assert getattr(exc.value, "status_code", None) == 400

    # Valid UTR
    res = billing.submit_utr(order_id=ord1["id"], tenant_id="t1", user_id="u1", utr="987654321098")
    assert res["status"] == "submitted"
    assert res["utr"] == "987654321098"

    # Order 2 from a different tenant
    ord2 = billing.create_order(tenant_id="t2", user_id="u2", quantity=2)

    # Attempting to submit the same UTR -> 409 Conflict
    with pytest.raises(Exception) as exc:
        billing.submit_utr(order_id=ord2["id"], tenant_id="t2", user_id="u2", utr="987654321098")
    assert getattr(exc.value, "status_code", None) == 409
    assert "already been submitted" in str(exc.value.detail).lower()


def test_order_expiry_and_submitted_protection(test_env):
    """
    Test 5:
    - Expired awaiting_payment orders cannot accept UTR submission.
    - Submitted orders are NEVER auto-expired.
    """
    billing = test_env["billing"]
    tenant_id = "tenant_expiry"

    # Create order with past expiration
    ord_exp = billing.create_order(tenant_id=tenant_id, user_id="u1", quantity=1)

    # Manually backdate expires_at to 1 hour ago
    from vyzn.billing.service import sqlite3_connect_write
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn = sqlite3_connect_write(test_env["db"].db_path)
    conn.execute("UPDATE quota_orders SET expires_at = ? WHERE id = ?", (past_iso, ord_exp["id"]))
    conn.commit()
    conn.close()

    # Attempting to submit UTR -> 400 Expired
    with pytest.raises(Exception) as exc:
        billing.submit_utr(order_id=ord_exp["id"], tenant_id=tenant_id, user_id="u1", utr="111122223333")
    assert getattr(exc.value, "status_code", None) == 400
    assert "expired" in str(exc.value.detail).lower()

    # Verify status is marked expired in database
    ord_record = billing.get_order(ord_exp["id"])
    assert ord_record["status"] == "expired"

    # Now test that submitted orders NEVER auto-expire
    ord_sub = billing.create_order(tenant_id="tenant_sub", user_id="u2", quantity=2)
    billing.submit_utr(order_id=ord_sub["id"], tenant_id="tenant_sub", user_id="u2", utr="222233334444")

    # Backdate submitted order's expires_at
    conn = sqlite3_connect_write(test_env["db"].db_path)
    conn.execute("UPDATE quota_orders SET expires_at = ? WHERE id = ?", (past_iso, ord_sub["id"]))
    conn.commit()
    conn.close()

    # Run expire_stale_orders()
    expired_count = billing.expire_stale_orders()
    # Must NOT touch the submitted order
    ord_sub_check = billing.get_order(ord_sub["id"])
    assert ord_sub_check["status"] == "submitted"


def test_double_approve_credits_once(test_env):
    """
    Test 6: Approving an order credits quota atomically.
    Approving twice fails on the second attempt and credits quota only ONCE.
    """
    billing = test_env["billing"]
    tenant_id = "tenant_idempotency"

    # Setup quota: purchased = 2
    billing.get_tenant_quota(tenant_id, used_count=2)

    # Create and submit order for 3 cameras
    ord1 = billing.create_order(tenant_id=tenant_id, user_id="u1", quantity=3)
    billing.submit_utr(order_id=ord1["id"], tenant_id=tenant_id, user_id="u1", utr="555566667777")

    # First approval -> success
    appr1 = billing.approve_order(order_id=ord1["id"], admin_user="admin@vyzn.ai")
    assert appr1["status"] == "paid"
    assert appr1["quantity_added"] == 3
    assert appr1["new_purchased_quota"] == 5

    # Check database quota
    q1 = billing.get_tenant_quota(tenant_id, used_count=2)
    assert q1["purchased"] == 5

    # Second approval attempt on the same order -> must fail and never add quota again
    with pytest.raises(Exception) as exc:
        billing.approve_order(order_id=ord1["id"], admin_user="admin@vyzn.ai")
    assert getattr(exc.value, "status_code", None) in (400, 409)

    # Verify quota is STILL 5, not 8!
    q2 = billing.get_tenant_quota(tenant_id, used_count=2)
    assert q2["purchased"] == 5


def test_reject_changes_no_quota(test_env):
    """
    Test 7: Rejecting an order changes status to rejected and leaves quota untouched.
    """
    billing = test_env["billing"]
    tenant_id = "tenant_reject"

    billing.get_tenant_quota(tenant_id, used_count=1)

    ord1 = billing.create_order(tenant_id=tenant_id, user_id="u1", quantity=4)
    billing.submit_utr(order_id=ord1["id"], tenant_id=tenant_id, user_id="u1", utr="777788889999")

    rej = billing.reject_order(order_id=ord1["id"], admin_user="admin@vyzn.ai", reason="Fake transaction ID")
    assert rej["status"] == "rejected"
    assert rej["reject_reason"] == "Fake transaction ID"

    # Quota remains 1
    q = billing.get_tenant_quota(tenant_id, used_count=1)
    assert q["purchased"] == 1
    assert q["available"] == 0


def test_non_admins_cannot_approve(test_env):
    """
    Test 8: Non-admin users cannot access admin approval/rejection endpoints.
    """
    db = test_env["db"]
    user_shop = db.get_or_create_user("shopkeeper@kirana.in")
    sess_shop = db.create_session(user_shop["id"])

    # Create an order
    billing = test_env["billing"]
    ord1 = billing.create_order(tenant_id="tenant_delhi_001", user_id=user_shop["id"], quantity=2)
    billing.submit_utr(order_id=ord1["id"], tenant_id="tenant_delhi_001", user_id=user_shop["id"], utr="121212121212")

    # Non-admin attempts to view pending orders -> 403
    resp = client.get("/admin/billing/pending", cookies={"vyzn_session": sess_shop})
    assert resp.status_code == 403

    # Non-admin attempts to approve -> 403
    resp = client.post(f"/admin/billing/orders/{ord1['id']}/approve", cookies={"vyzn_session": sess_shop})
    assert resp.status_code == 403

    # Admin user attempts to approve -> 200
    user_admin = db.get_or_create_user("admin@vyzn.ai")
    conn = db._get_read_conn()
    conn.execute("UPDATE users SET telegram_username = 'admin' WHERE id = ?", (user_admin["id"],))
    conn.close()
    sess_admin = db.create_session(user_admin["id"])

    # Provide admin credentials
    resp = client.post(f"/admin/billing/orders/{ord1['id']}/approve", cookies={"vyzn_session": sess_admin})
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


def test_concurrency_one_slot_two_simultaneous_adds(test_env):
    """
    Test 9 (CRUCIAL CONCURRENCY CASE):
    With exactly 1 available quota slot, two simultaneous camera add requests
    must result in EXACTLY ONE success and ONE failure with QUOTA_EXHAUSTED.
    """
    os.environ["BILLING_ENFORCEMENT"] = "true"
    db = test_env["db"]
    settings = test_env["settings"]

    # User setup
    user = db.get_or_create_user("concurrency@vyzn.ai")
    sess = db.create_session(user["id"])
    tenant_id = user["id"]

    # Set quota: purchased = 1, used = 0 -> available = 1
    from vyzn.billing.service import sqlite3_connect_write
    conn = sqlite3_connect_write(db.db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO camera_quota (tenant_id, purchased, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (tenant_id, 1, now_iso, now_iso)
    )
    conn.commit()
    conn.close()

    results = []
    errors = []

    def try_add_camera(cam_idx: int):
        c = TestClient(app)
        res = c.post(
            "/api/cameras",
            headers={"X-Security-Pin": "202600"},
            cookies={"vyzn_session": sess},
            json={
                "name": f"Concurrency Cam {cam_idx}",
                "rtsp_url": f"rtsp://192.168.1.{100 + cam_idx}/stream"
            }
        )
        if res.status_code == 200:
            results.append(res.json())
        else:
            errors.append(res)

    # Launch 2 simultaneous adds
    t1 = threading.Thread(target=try_add_camera, args=(1,))
    t2 = threading.Thread(target=try_add_camera, args=(2,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # EXACTLY 1 must succeed and 1 must fail with 403 QUOTA_EXHAUSTED
    assert len(results) == 1, f"Expected 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected 1 failure, got {len(errors)}"

    err = errors[0]
    assert err.status_code == 403
    assert err.json().get("detail") == "QUOTA_EXHAUSTED"

    # Verify final camera count is exactly 1
    assert len(settings.cameras) == 1
    os.environ["BILLING_ENFORCEMENT"] = "false"
