import pytest
from pathlib import Path
from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase, hash_password, verify_password
from vyzn.core.config import EdgeSettings


def test_password_hashing():
    pwd = "supersecretpassword123"
    h = hash_password(pwd)
    assert ":" in h
    assert verify_password(pwd, h) is True
    assert verify_password("wrongpassword", h) is False
    assert verify_password("", h) is False


def test_database_user_credentials(tmp_path: Path):
    db_file = tmp_path / "test_auth.db"
    db = EventDatabase(db_file)

    user = db.create_user_with_credentials(
        email="merchant@shop.in",
        password="securepass2026",
        full_name="Rajesh Sharma",
        business_name="Sharma Supermarket",
        business_type="supermarket",
        phone_e164="+919876543210"
    )
    assert user["email"] == "merchant@shop.in"
    assert user["full_name"] == "Rajesh Sharma"
    assert user["business_name"] == "Sharma Supermarket"

    # Verify correct credentials
    verified = db.verify_user_credentials("merchant@shop.in", "securepass2026")
    assert verified is not None
    assert verified["id"] == user["id"]

    # Verify wrong password
    bad = db.verify_user_credentials("merchant@shop.in", "wrongpass")
    assert bad is None

    # Verify non-existent user
    non_existent = db.verify_user_credentials("nobody@shop.in", "securepass2026")
    assert non_existent is None


def test_api_signup_and_login_flow(tmp_path: Path):
    db_file = tmp_path / "api_auth_test.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_pwd_auth",
        data_dir=tmp_path,
        db_path=db_file
    )
    init_api(db, settings)
    client = TestClient(app)

    # 1. Sign up a new user
    signup_payload = {
        "email": "testowner_2026@vyzn.ai",
        "password": "mypassword123",
        "full_name": "Test Owner",
        "business_name": "Apex Electronics",
        "business_type": "electronics",
        "phone_e164": "+919811223344"
    }
    res_signup = client.post("/api/auth/signup", json=signup_payload)
    assert res_signup.status_code == 200, res_signup.text
    signup_data = res_signup.json()
    assert signup_data["ok"] is True
    assert signup_data["user"]["email"] == "testowner_2026@vyzn.ai"
    assert "vyzn_session" in res_signup.cookies

    # 2. Try duplicate signup (should fail)
    res_dup = client.post("/api/auth/signup", json=signup_payload)
    assert res_dup.status_code == 400

    # 3. Log in with correct password
    login_payload = {
        "email": "testowner_2026@vyzn.ai",
        "password": "mypassword123",
        "remember": True
    }
    res_login = client.post("/api/auth/login", json=login_payload)
    assert res_login.status_code == 200, res_login.text
    login_data = res_login.json()
    assert login_data["ok"] is True
    assert login_data["redirect"] == "/overview"
    assert "vyzn_session" in res_login.cookies

    # 4. Log in with wrong password
    bad_login = {
        "email": "testowner_2026@vyzn.ai",
        "password": "wrongpassword"
    }
    res_bad = client.post("/api/auth/login", json=bad_login)
    assert res_bad.status_code == 401
