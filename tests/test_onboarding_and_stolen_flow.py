"""
Tests for Interruption-Proof Site Onboarding (Flow 3), Stolen Device Action (Flow 6),
and Account Lockout Rate Limiting (Flow 1) on Telegram Alert Channel.
"""

from pathlib import Path
import tempfile
from fastapi.testclient import TestClient
from vyzn_cloud.app import cloud_app
from vyzn_cloud.security import (
    _init_security_db,
    record_failed_login,
    is_account_locked,
    reset_failed_logins,
    save_onboarding_draft,
    get_onboarding_draft,
    list_onboarding_drafts,
    delete_onboarding_draft,
    INSTALLERS
)


def test_account_lockout_after_five_failed_attempts():
    """Validates Flow 1: 5x failed attempts triggers a 15-minute temporary lockout."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_sec.db"
        _init_security_db(db_path)

        user_email = "installer_test@vyzn.ai"

        # Attempts 1 to 4 should not lock
        for i in range(1, 5):
            is_locked = record_failed_login(user_email, max_attempts=5, lockout_seconds=900, db_path=db_path)
            assert is_locked is False

        # 5th attempt locks the account
        is_locked = record_failed_login(user_email, max_attempts=5, lockout_seconds=900, db_path=db_path)
        assert is_locked is True

        locked, remaining = is_account_locked(user_email, db_path=db_path)
        assert locked is True
        assert 800 < remaining <= 900

        # Successful reset clears lockout
        reset_failed_logins(user_email, db_path=db_path)
        locked_after, _ = is_account_locked(user_email, db_path=db_path)
        assert locked_after is False


def test_interruption_proof_onboarding_and_go_live_gate():
    """
    Validates Flow 3:
    1. Steps 1 to 5 persist server-side atomically so setup survives interruptions.
    2. Step 6 blocks 'Go Live' until Telegram test alert is confirmed received.
    3. Once verified, 'Go Live' successfully provisions the site.
    """
    client = TestClient(cloud_app)
    installer_token = "installer_key_delhi_netra_01"
    headers = {"X-Installer-Key": installer_token}

    draft_id = "draft_delhi_kirana_99"

    # 1. Step 1 & 2: Installer enters details & cameras, then drops connection / closes tab
    step2_payload = {
        "site_name": "Sharma Supermarket",
        "current_step": 2,
        "data": {
            "owner_name": "Rajesh Sharma",
            "owner_telegram": "@sharma_supermarket",
            "cameras": {
                "cam_counter": {"name": "Counter Cam", "rtsp": "rtsp://192.168.1.50/live"}
            }
        },
        "test_verified": False
    }
    save_res = client.put(f"/api/v1/fleet/onboarding/drafts/{draft_id}", json=step2_payload, headers=headers)
    assert save_res.status_code == 200

    # 2. Installer re-opens app: lists active drafts and resumes at Step 2
    list_res = client.get("/api/v1/fleet/onboarding/drafts", headers=headers)
    assert list_res.status_code == 200
    drafts = list_res.json()["drafts"]
    resumed = next((d for d in drafts if d["draft_id"] == draft_id), None)
    assert resumed is not None
    assert resumed["current_step"] == 2
    assert resumed["site_name"] == "Sharma Supermarket"

    # 3. Try to trigger Go Live prematurely before Step 6 verification -> MUST FAIL 400
    premature_res = client.post(f"/api/v1/fleet/onboarding/drafts/{draft_id}/go-live", headers=headers)
    assert premature_res.status_code == 400
    assert "Telegram first" in premature_res.json()["detail"]

    # 4. Trigger Step 6 Telegram Test Alert
    test_res = client.post(f"/api/v1/fleet/onboarding/drafts/{draft_id}/test-alert", headers=headers)
    assert test_res.status_code == 200
    assert test_res.json()["test_verified"] is True
    assert "Telegram" in test_res.json()["message"]

    # 5. Now Go Live succeeds!
    golive_res = client.post(f"/api/v1/fleet/onboarding/drafts/{draft_id}/go-live", headers=headers)
    assert golive_res.status_code == 200
    live_data = golive_res.json()
    assert live_data["status"] == "online"
    assert "site_sharma_supermarket" in live_data["site_id"]
    assert "vyzn_edge_secret_" in live_data["site_key"]

    # 6. Draft is automatically purged
    get_purged = client.get(f"/api/v1/fleet/onboarding/drafts/{draft_id}", headers=headers)
    assert get_purged.status_code == 404


def test_stolen_device_flow_and_replacement_wizard():
    """
    Validates Flow 6:
    1. Reporting device stolen revokes credentials immediately.
    2. Automatically creates an onboarding draft pre-filled with the stolen site's zones & schedule.
    """
    client = TestClient(cloud_app)
    admin_token = "installer_key_master_admin_99"
    headers = {"X-Installer-Key": admin_token}

    stolen_res = client.post("/api/v1/fleet/sites/site_local_default/stolen", headers=headers)
    assert stolen_res.status_code == 200
    data = stolen_res.json()
    assert data["status"] == "stolen_revoked"
    assert data["credentials_status"] == "REVOKED"
    assert "replacement_draft_id" in data

    repl_draft_id = data["replacement_draft_id"]

    # Fetch pre-filled replacement draft
    draft_res = client.get(f"/api/v1/fleet/onboarding/drafts/{repl_draft_id}", headers=headers)
    assert draft_res.status_code == 200
    draft_data = draft_res.json()
    assert draft_data["current_step"] == 2
    assert draft_data["data"]["stolen_site_id"] == "site_local_default"
    assert "hours" in draft_data["data"]
