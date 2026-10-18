"""
Verification tests for the user-requested fixes:
1. Gmail OTP verification gate on account signup
2. Single clip delete by ID / event_group_id
3. Purge all clips PIN requirement
4. Camera stream visual status (no fake placeholder)
5. Camera probe truthfulness (no fake online preview)
"""

import pytest
from fastapi.testclient import TestClient
from api.index import app, EMAIL_AUTH_CODES, USERS_STORE, CLIPS_BY_USER, send_gmail_otp

@pytest.fixture
def client():
    return TestClient(app)

def test_gmail_otp_required_for_signup(client):
    email = "test_signup_user@example.com"
    USERS_STORE.pop(email, None)
    EMAIL_AUTH_CODES.pop(email, None)

    # 1. Signup without OTP fails
    resp = client.post("/api/auth/signup", json={
        "email": email,
        "password": "securepassword123",
        "full_name": "Test User",
        "business_name": "Test Society",
        "business_type": "society"
    })
    assert resp.status_code == 400
    assert "Gmail OTP verification is required" in resp.json()["detail"]

    # 2. Dispatch OTP
    start_resp = client.post("/api/auth/email/start", json={"email": email})
    assert start_resp.status_code == 200
    assert start_resp.json()["ok"] is True
    assert email in EMAIL_AUTH_CODES
    code = EMAIL_AUTH_CODES[email]["code"]

    # 3. Signup with wrong OTP fails
    wrong_resp = client.post("/api/auth/signup", json={
        "email": email,
        "password": "securepassword123",
        "otp_code": "000000"
    })
    assert wrong_resp.status_code == 400
    assert "Incorrect verification code" in wrong_resp.json()["detail"]

    # 4. Signup with valid OTP succeeds
    success_resp = client.post("/api/auth/signup", json={
        "email": email,
        "password": "securepassword123",
        "otp_code": code
    })
    assert success_resp.status_code == 200
    assert success_resp.json()["ok"] is True
    assert success_resp.json()["redirect"] == "/overview"
    assert email in USERS_STORE

def test_single_clip_delete(client):
    email = "dirtbike000000@gmail.com"
    test_clip_id = "ev_cam_test_123456"
    CLIPS_BY_USER[email] = [
        {"id": test_clip_id, "event_group_id": test_clip_id, "clip_number": 99},
        {"id": "ev_cam_keep_789", "event_group_id": "ev_cam_keep_789", "clip_number": 100}
    ]

    resp = client.delete(f"/api/clips/{test_clip_id}", headers={"X-Security-Pin": "202600"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["remaining"] == 1
    assert all(c["id"] != test_clip_id for c in CLIPS_BY_USER[email])

def test_purge_all_clips_requires_pin(client):
    # Missing or wrong PIN fails
    resp = client.post("/api/clips/purge-all", headers={"X-Security-Pin": "wrong_pin"})
    assert resp.status_code == 403
    assert "Security verification failed" in resp.json()["detail"]

    # Correct PIN succeeds
    resp_ok = client.post("/api/clips/purge-all", headers={"X-Security-Pin": "202600"})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["ok"] is True

def test_camera_test_does_not_return_fake_placeholder(client):
    # Probing an unreachable LAN IP must NOT return fake online with placeholder
    resp = client.post("/api/cameras/test", json={"rtsp_url": "http://192.168.31.216:8080/video"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["status"] in ("unreachable", "offline", "error", "connect_timeout", "timeout")
    assert "preview_base64" not in data or data.get("preview_base64") is None

def test_wall_stream_visual_no_fake_placeholder(client):
    resp = client.get("/api/wall/stream?camera_id=cam_phone_cam_1792084106")
    assert resp.status_code == 200
    content = resp.text
    assert "Camera Feed Active" not in content
