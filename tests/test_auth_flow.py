"""
Phase 2 Authentication, Session Management, and Telegram Link Flow Verification.
Tests screens S1 -> S2 -> S3 -> S4 state machine per v1.1 specification.
"""

from pathlib import Path
from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings


def test_phase2_auth_and_telegram_flow(tmp_path: Path):
    db_file = tmp_path / "auth_test.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_auth_test",
        data_dir=tmp_path,
        db_path=db_file,
        telegram_bot_token=""
    )
    init_api(db, settings)
    client = TestClient(app)

    # 1. S1 Email validation
    res = client.post("/api/auth/email/start", json={"email": "not-an-email"})
    assert res.status_code == 400
    assert "Enter a valid email address" in res.json()["detail"]

    # Valid email start
    test_email = "owner@kirana.in"
    res = client.post("/api/auth/email/start", json={"email": test_email})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    dev_code = res.json()["dev_code"]
    assert len(dev_code) == 6

    # 2. S2 Wrong code attempt
    res = client.post("/api/auth/email/verify", json={"email": test_email, "code": "000000"})
    assert res.status_code == 400
    assert "That code isn't right" in res.json()["detail"]

    # S2 Verify with correct code
    res = client.post("/api/auth/email/verify", json={"email": test_email, "code": dev_code})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["next_step"] in ("/setup/phone", "/overview")
    assert "vyzn_session" in res.cookies

    # 3. GET /api/me (authenticated)
    res = client.get("/api/me")
    assert res.status_code == 200
    user_data = res.json()
    assert user_data["email"] == test_email
    assert user_data["phone_e164"] is None
    assert user_data["telegram_status"] == "not_linked"

    # 4. S3 Phone validation
    res = client.post("/api/me/phone", json={"phoneE164": "12345"})
    assert res.status_code == 400
    assert "Enter a 10-digit mobile number starting with 6, 7, 8 or 9" in res.json()["detail"]

    # S3 Valid Indian phone (+91 9876543210)
    res = client.post("/api/me/phone", json={"phoneE164": "9876543210"})
    assert res.status_code == 200
    assert res.json()["phone_e164"] == "+919876543210"

    # Verify updated profile
    res = client.get("/api/me")
    assert res.json()["phone_e164"] == "+919876543210"

    # 5. S4 Telegram link generation
    res = client.post("/api/telegram/link")
    assert res.status_code == 200
    link_data = res.json()
    assert "deepLink" in link_data
    assert "start=" in link_data["deepLink"]
    token = link_data["token"]

    # 6. S4 Polling: Initial state is waiting
    res = client.get("/api/telegram/status")
    assert res.status_code == 200
    assert res.json()["status"] == "waiting"

    # 7. S4 Telegram Mismatch Case
    res = client.post("/api/telegram/simulate-link", json={
        "token": token,
        "phone": "+919123456789"  # Different phone number
    })
    assert res.status_code == 200
    assert res.json()["status"] == "mismatch"

    res = client.get("/api/telegram/status")
    assert res.json()["status"] == "mismatch"

    # 8. S4 Telegram Match Case
    res = client.post("/api/telegram/simulate-link", json={
        "token": token,
        "phone": "+919876543210",
        "chat_id": "123456789",
        "username": "kirana_owner"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "connected"

    # 9. Verify S4 Polling now reports connected
    res = client.get("/api/telegram/status")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["status"] == "connected"
    assert status_data["telegram_chat_id"] == "123456789"
    assert status_data["telegram_username"] == "kirana_owner"

    # 10. S4 Test alert ping
    res = client.post("/api/telegram/test")
    assert res.status_code == 200
    test_res = res.json()
    assert test_res["ok"] is True
    assert "latencyMs" in test_res
    assert "deliveredAtMs" in test_res

    # 11. Returning user verification bypasses setup to /overview
    res = client.post("/api/auth/email/start", json={"email": test_email})
    new_code = res.json()["dev_code"]
    res = client.post("/api/auth/email/verify", json={"email": test_email, "code": new_code})
    assert res.json()["next_step"] == "/overview"

    # 12. Sign out
    res = client.post("/api/auth/signout")
    assert res.status_code == 200
    client.cookies.clear()
    res = client.get("/api/me")
    assert res.status_code == 401

    # 13. Test Auth Page HTML routes
    for path in ["/login", "/login/code", "/setup/phone", "/setup/telegram"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "VYZN" in res.text
        assert "auth.js" in res.text
        assert "72 hours" in res.text

    db.close()
