"""
Unit and Integration tests for:
1. First page login with Gmail/Email OTP
2. Mobile phone OTP start, verify, and skip flows
3. Supabase Cloud Sync service (user storage and login audit history)
4. Supabase status diagnostics endpoint
"""

import os
import pytest
from pathlib import Path
from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings
from vyzn.core.supabase_sync import (
    is_supabase_configured,
    sync_user_to_supabase,
    record_login_event_to_supabase,
    test_supabase_connection as check_supabase_connection
)


def get_test_client(tmp_path: Path):
    db_file = tmp_path / "auth_supabase_test.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_phone_supabase_test",
        data_dir=tmp_path,
        db_path=db_file,
        telegram_bot_token=""
    )
    init_api(db, settings)
    return TestClient(app), db


def test_first_page_serves_login_for_unauthenticated_visitor(tmp_path: Path):
    """Verifies that visiting the root '/' page serves the login view for unauthenticated visitors."""
    client, db = get_test_client(tmp_path)
    try:
        res = client.get("/")
        assert res.status_code == 200
        # Should contain VYZN and the login card elements
        assert "VYZN" in res.text
        assert "auth-card" in res.text or "Sign in" in res.text or "auth.js" in res.text
    finally:
        db.close()


def test_gmail_otp_login_and_supabase_sync_hook(tmp_path: Path):
    """Verifies email OTP authentication for Gmail user and triggers Supabase storage."""
    client, db = get_test_client(tmp_path)
    try:
        gmail_user = "retailer.owner@gmail.com"

        # 1. Start Email OTP
        start_res = client.post("/api/auth/email/start", json={"email": gmail_user})
        assert start_res.status_code == 200
        assert start_res.json()["ok"] is True
        dev_code = start_res.json()["dev_code"]
        assert len(dev_code) == 6

        # 2. Verify with code
        verify_res = client.post("/api/auth/email/verify", json={"email": gmail_user, "code": dev_code})
        assert verify_res.status_code == 200
        data = verify_res.json()
        assert data["ok"] is True
        assert data["next_step"] in ("/setup/phone", "/overview")
        assert data["user"]["email"] == gmail_user
        assert "vyzn_session" in verify_res.cookies

        # 3. Authenticated session now sees overview on root '/'
        root_res = client.get("/")
        assert root_res.status_code == 200
        assert "overview" in root_res.text or "VYZN" in root_res.text
    finally:
        db.close()


def test_phone_otp_start_and_validation(tmp_path: Path):
    """Tests mobile number validation and OTP dispatch."""
    client, db = get_test_client(tmp_path)
    try:
        # Sign in first
        email = "kirana.owner@gmail.com"
        s_res = client.post("/api/auth/email/start", json={"email": email})
        client.post("/api/auth/email/verify", json={"email": email, "code": s_res.json()["dev_code"]})

        # 1. Invalid phone number (too short)
        res = client.post("/api/auth/phone/start", json={"phoneE164": "98765"})
        assert res.status_code == 400
        assert "10-digit mobile number" in res.json()["detail"]

        # 2. Invalid start digit (not 6,7,8,9)
        res = client.post("/api/auth/phone/start", json={"phoneE164": "1234567890"})
        assert res.status_code == 400
        assert "starting with 6, 7, 8 or 9" in res.json()["detail"]

        # 3. Valid Indian phone number
        res = client.post("/api/auth/phone/start", json={"phoneE164": "9876543210"})
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["phone_e164"] == "+919876543210"
        assert len(body["dev_code"]) == 6
    finally:
        db.close()


def test_phone_otp_verify_flow_and_profile_update(tmp_path: Path):
    """Tests submitting correct and incorrect phone OTP codes."""
    client, db = get_test_client(tmp_path)
    try:
        email = "delhi.store@gmail.com"
        s_res = client.post("/api/auth/email/start", json={"email": email})
        client.post("/api/auth/email/verify", json={"email": email, "code": s_res.json()["dev_code"]})

        phone = "9811223344"
        phone_e164 = "+919811223344"
        start_res = client.post("/api/auth/phone/start", json={"phoneE164": phone})
        dev_code = start_res.json()["dev_code"]

        # 1. Wrong OTP code
        wrong_res = client.post("/api/auth/phone/verify", json={"phoneE164": phone, "code": "000000"})
        assert wrong_res.status_code == 400
        assert "That code isn't right" in wrong_res.json()["detail"]

        # 2. Correct OTP code
        ok_res = client.post("/api/auth/phone/verify", json={"phoneE164": phone, "code": dev_code})
        assert ok_res.status_code == 200
        data = ok_res.json()
        assert data["ok"] is True
        assert data["phone_verified"] is True
        assert data["phone_e164"] == phone_e164
        assert data["next_step"] == "/overview"

        # 3. Verify /api/me reflects phone_verified=True
        me_res = client.get("/api/me")
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["phone_e164"] == phone_e164
        assert me_data["phone_verified"] is True
    finally:
        db.close()


def test_phone_otp_skip_option(tmp_path: Path):
    """Tests the skip phone verification endpoint for flexible onboarding."""
    client, db = get_test_client(tmp_path)
    try:
        email = "quick.user@gmail.com"
        s_res = client.post("/api/auth/email/start", json={"email": email})
        client.post("/api/auth/email/verify", json={"email": email, "code": s_res.json()["dev_code"]})

        res = client.post("/api/auth/phone/skip")
        assert res.status_code == 200
        assert res.json()["ok"] is True
        assert res.json()["next_step"] == "/overview"
    finally:
        db.close()


def test_supabase_status_endpoint(tmp_path: Path):
    """Tests the /api/auth/supabase/status diagnostic endpoint."""
    client, db = get_test_client(tmp_path)
    try:
        res = client.get("/api/auth/supabase/status")
        assert res.status_code == 200
        data = res.json()
        assert "configured" in data
        assert "connected" in data
        assert "message" in data
    finally:
        db.close()


def test_supabase_sync_service_graceful_fallback(monkeypatch):
    """Verifies that Supabase sync service degrades gracefully when credentials are not configured."""
    # Ensure environment variables are clear
    monkeypatch.delenv("VYZN_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("VYZN_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    assert is_supabase_configured() is False

    user_payload = {
        "id": "usr_test_fallback",
        "email": "offline.test@gmail.com",
        "phone_e164": "+919876543210",
        "phone_verified": True
    }
    sync_result = sync_user_to_supabase(user_payload)
    assert sync_result["synced"] is False
    assert sync_result["reason"] == "supabase_not_configured"

    # Test login history fallback
    logged = record_login_event_to_supabase(
        user_id="usr_test_fallback",
        email="offline.test@gmail.com"
    )
    assert logged is False

    # Test connection check fallback
    health = check_supabase_connection()
    assert health["configured"] is False
    assert health["connected"] is False
