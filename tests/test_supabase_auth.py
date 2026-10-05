"""
Tests for Supabase Auth gateway, Email/Password sign-in, JWT verification,
and camera configuration listing in VYZN Netra.
"""

import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.config import EdgeSettings, CameraConfig
from vyzn.core.database import EventDatabase
from vyzn.supabase_client import (
    sign_in_with_email,
    sign_up_with_email,
    generate_dev_token,
    LOCAL_DEV_USERS
)


def get_test_client(tmp_path: Path):
    db_path = tmp_path / "auth_test.db"
    db = EventDatabase(db_path)
    settings = EdgeSettings(
        site_id="site_auth_test",
        site_name="SafeNet Demo Mart",
        data_dir=tmp_path,
        cameras=[
            CameraConfig(camera_id="cam_main", name="Main Entrance", rtsp_url="rtsp://admin:secret@192.168.1.10:554/ch01"),
            CameraConfig(camera_id="cam_vault", name="Locker Room", rtsp_url="rtsp://192.168.1.20:554/live")
        ]
    )
    init_api(db, settings, None)
    return TestClient(app), db


def test_supabase_auth_login_valid(tmp_path: Path):
    """Verifies that known user can authenticate and receive a valid JWT access token."""
    client, db = get_test_client(tmp_path)
    try:
        resp = client.post("/api/v1/auth/login", json={
            "email": "shopkeeper@kirana.in",
            "password": "kirana123"
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "success"
        assert "access_token" in data
        assert data["user"]["email"] == "shopkeeper@kirana.in"
        assert data["user"]["role"] == "shopkeeper"
    finally:
        db.close()


def test_supabase_auth_login_invalid(tmp_path: Path):
    """Verifies that invalid credentials result in 401 Unauthorized."""
    client, db = get_test_client(tmp_path)
    try:
        resp = client.post("/api/v1/auth/login", json={
            "email": "shopkeeper@kirana.in",
            "password": "wrong_password"
        })
        assert resp.status_code == 401
    finally:
        db.close()


def test_supabase_auth_register_and_profile(tmp_path: Path):
    """Verifies registering a new user and verifying the JWT token via /api/v1/auth/me."""
    client, db = get_test_client(tmp_path)
    try:
        email = "new_owner@supermart.in"
        reg_resp = client.post("/api/v1/auth/register", json={
            "email": email,
            "password": "supermartpassword99",
            "full_name": "Rajesh Supermart Owner",
            "role": "shopkeeper"
        })
        assert reg_resp.status_code == 200, reg_resp.text
        reg_data = reg_resp.json()
        token = reg_data["access_token"]
        assert token is not None

        # Call /api/v1/auth/me with Bearer token
        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 200, me_resp.text
        me_data = me_resp.json()
        assert me_data["status"] == "authenticated"
        assert me_data["user"]["email"] == email
        assert me_data["user"]["role"] == "shopkeeper"
    finally:
        db.close()


def test_supabase_auth_protected_me_rejects_unauthorized(tmp_path: Path):
    """Verifies that /api/v1/auth/me rejects requests without token or with forged token."""
    client, db = get_test_client(tmp_path)
    try:
        # 1. No token
        resp_no_token = client.get("/api/v1/auth/me")
        assert resp_no_token.status_code == 401

        # 2. Forged token
        resp_bad_token = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.jwt.token"})
        assert resp_bad_token.status_code == 401
    finally:
        db.close()


def test_camera_list_masks_credentials(tmp_path: Path):
    """Verifies GET /api/cameras returns configured cameras with sensitive RTSP credentials masked."""
    client, db = get_test_client(tmp_path)
    try:
        resp = client.get("/api/cameras")
        assert resp.status_code == 200, resp.text
        cams = resp.json()
        assert len(cams) == 2
        cam1 = next(c for c in cams if c["camera_id"] == "cam_main")
        assert cam1["name"] == "Main Entrance"
        # Verify password is not exposed in masked URL
        assert "secret" not in cam1["rtsp_url_masked"]
        assert "192.168.1.10:554/ch01" in cam1["rtsp_url_masked"]
    finally:
        db.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        test_supabase_auth_login_valid(p)
        test_supabase_auth_login_invalid(p)
        test_supabase_auth_register_and_profile(p)
        test_supabase_auth_protected_me_rejects_unauthorized(p)
        test_camera_list_masks_credentials(p)
        print("ALL_SUPABASE_AUTH_TESTS_PASSED")
