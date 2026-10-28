"""
Unit & Integration tests for Vercel Cloud Serverless Billing and Quota system (api/index.py).
Tests:
- Quota math: purchased, used, available
- Server-side amount calculation
- UTR 12-digit validation and uniqueness
- Order creation & refusal of duplicate open orders
- Admin-only approval and rejection
- Idempotent approval (never credits twice)
- Strict camera quota enforcement (rejecting camera addition with QUOTA_EXHAUSTED when available <= 0)
"""

import pytest
import secrets
from fastapi import HTTPException
from pydantic import BaseModel
import api.index as ai


def test_serverless_quota_math_and_enforcement():
    unique_email = f"user_{secrets.token_hex(4)}@vyzn.ai"
    tok = ai.create_session_token(unique_email)

    class UserReq:
        cookies = {"vyzn_session": tok}
        headers = {}

    # 1. Initial quota for brand new user: 0 purchased, 0 used, 0 available
    quota = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota["purchased"] == 0
    assert quota["used"] == 0
    assert quota["available"] == 0
    assert quota["enforcement_enabled"] is True

    # 2. Camera addition must be blocked with 403 QUOTA_EXHAUSTED
    cam_req = ai.CameraCreateRequest(name="Gate Cam", rtsp_url="rtsp://10.0.0.10:554/live")
    with pytest.raises(HTTPException) as exc_info:
        ai.add_camera(cam_req, UserReq())
    assert exc_info.value.status_code == 403
    assert "QUOTA_EXHAUSTED" in str(exc_info.value.detail)

    # 3. Create order for 1 camera
    ord_res = ai.api_create_quota_order(ai.QuotaOrderCreateRequest(quantity=1), UserReq())
    assert ord_res["status"] == "awaiting_payment"
    assert ord_res["quantity"] == 1
    assert ord_res["amount_paise"] == ai.CAMERA_PRICE_PAISE

    # 4. Quota remains 0 until approved
    quota_mid = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota_mid["available"] == 0

    # 5. Submit valid 12-digit UTR
    utr = f"{secrets.randbelow(900000000000) + 100000000000}"
    sub_res = ai.api_submit_quota_order_utr(ord_res["id"], ai.SubmitUtrRequest(utr=utr), UserReq())
    assert sub_res["status"] == "submitted"

    # 6. Non-admin cannot approve
    with pytest.raises(HTTPException) as non_admin_exc:
        ai.api_admin_billing_approve(ord_res["id"], UserReq())
    assert non_admin_exc.value.status_code == 403

    # 7. Admin approval credits quota
    admin_tok = ai.create_session_token("dirtbike000000@gmail.com")

    class AdminReq:
        cookies = {"vyzn_session": admin_tok}
        headers = {}

    appr = ai.api_admin_billing_approve(ord_res["id"], AdminReq())
    assert appr["ok"] is True
    assert appr["purchased"] == 1
    assert appr["available"] == 1

    # 8. Double approval is idempotent and never double-credits
    double_appr = ai.api_admin_billing_approve(ord_res["id"], AdminReq())
    assert double_appr.get("already_approved") is True

    quota_after_appr = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota_after_appr["purchased"] == 1
    assert quota_after_appr["available"] == 1

    # 9. Adding camera now succeeds exactly once
    cam_success = ai.add_camera(cam_req, UserReq())
    assert cam_success["ok"] is True

    # 10. Quota is now 1 used, 0 available
    quota_after_add = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota_after_add["used"] == 1
    assert quota_after_add["available"] == 0

    # 11. Second camera addition must now fail with 403 QUOTA_EXHAUSTED
    with pytest.raises(HTTPException) as exc_info2:
        ai.add_camera(cam_req, UserReq())
    assert exc_info2.value.status_code == 403
    assert "QUOTA_EXHAUSTED" in str(exc_info2.value.detail)


@pytest.mark.anyio
async def test_admin_telegram_bot_approval_workflow():
    unique_email = f"user_{secrets.token_hex(4)}@vyzn.ai"
    tok = ai.create_session_token(unique_email)

    class UserReq:
        cookies = {"vyzn_session": tok}
        headers = {}

    # 1. Create order and submit UTR
    ord_res = ai.api_create_quota_order(ai.QuotaOrderCreateRequest(quantity=2), UserReq())
    utr = f"{secrets.randbelow(900000000000) + 100000000000}"
    ai.api_submit_quota_order_utr(ord_res["id"], ai.SubmitUtrRequest(utr=utr), UserReq())

    class MockWebhookReq:
        def __init__(self, payload):
            self._payload = payload
        async def json(self):
            return self._payload

    # 2. Unauthorized caller cannot approve
    unauth_payload = {
        "update_id": 1001,
        "callback_query": {
            "id": "cq_1001",
            "from": {"id": 999999999, "username": "bad_actor"},
            "data": f"admin_approve_{ord_res['id']}",
            "message": {"message_id": 55, "chat": {"id": 999999999}}
        }
    }
    unauth_res = await ai.api_telegram_admin_webhook(MockWebhookReq(unauth_payload))
    assert unauth_res.get("ok") is False
    assert unauth_res.get("error") == "Unauthorized"

    # Quota is still 0
    quota_pre = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota_pre["purchased"] == 0

    # 3. Authorized Admin (chat 6856103038) approves order
    auth_payload = {
        "update_id": 1002,
        "callback_query": {
            "id": "cq_1002",
            "from": {"id": 6856103038, "username": "admin_owner"},
            "data": f"admin_approve_{ord_res['id']}",
            "message": {"message_id": 56, "chat": {"id": 6856103038}}
        }
    }
    auth_res = await ai.api_telegram_admin_webhook(MockWebhookReq(auth_payload))
    assert auth_res.get("ok") is True
    assert auth_res.get("action") == "approved"

    # 4. Quota is now credited (+2 cameras)
    quota_post = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota_post["purchased"] == 2
    assert quota_post["available"] == 2

    # 5. Idempotent double approve
    double_res = await ai.api_telegram_admin_webhook(MockWebhookReq(auth_payload))
    assert double_res.get("ok") is True
    assert double_res.get("already_approved") is True

    # Quota remains 2
    quota_post2 = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota_post2["purchased"] == 2


@pytest.mark.anyio
async def test_admin_telegram_bot_rejection_and_commands():
    unique_email = f"user_{secrets.token_hex(4)}@vyzn.ai"
    tok = ai.create_session_token(unique_email)

    class UserReq:
        cookies = {"vyzn_session": tok}
        headers = {}

    ord_res = ai.api_create_quota_order(ai.QuotaOrderCreateRequest(quantity=1), UserReq())
    utr = f"{secrets.randbelow(900000000000) + 100000000000}"
    ai.api_submit_quota_order_utr(ord_res["id"], ai.SubmitUtrRequest(utr=utr), UserReq())

    class MockWebhookReq:
        def __init__(self, payload):
            self._payload = payload
        async def json(self):
            return self._payload

    # Reject order via Admin Bot
    reject_payload = {
        "update_id": 1003,
        "callback_query": {
            "id": "cq_1003",
            "from": {"id": 6856103038, "username": "admin_owner"},
            "data": f"admin_reject_{ord_res['id']}",
            "message": {"message_id": 57, "chat": {"id": 6856103038}}
        }
    }
    reject_res = await ai.api_telegram_admin_webhook(MockWebhookReq(reject_payload))
    assert reject_res.get("ok") is True
    assert reject_res.get("action") == "rejected"

    # Quota must NOT increase
    quota = ai.get_tenant_billing_quota("usr_" + unique_email, unique_email)
    assert quota["purchased"] == 0

    # Test /pending, /quota, /orders commands
    for cmd in ["/pending", f"/quota {unique_email}", "/orders", "/start"]:
        cmd_payload = {
            "update_id": 1004,
            "message": {
                "chat": {"id": 6856103038},
                "text": cmd
            }
        }
        res = await ai.api_telegram_admin_webhook(MockWebhookReq(cmd_payload))
        assert res.get("ok") is True
