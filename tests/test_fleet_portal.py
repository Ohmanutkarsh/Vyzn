"""
Integration tests for VYZN Cloud Multi-Tenant Fleet Observability Portal:
Verifies installer authentication, tenant scoping, HMAC-signed remote config push,
edge node site-key verification, and portal HTML rendering.
"""

from starlette.testclient import TestClient
from vyzn_cloud.app import cloud_app
from vyzn_cloud.security import generate_config_hmac, verify_config_hmac


def test_fleet_portal_authentication_enforcement():
    client = TestClient(cloud_app)

    # 1. Unauthenticated request MUST be rejected with 401
    res = client.get("/api/v1/fleet/sites")
    assert res.status_code == 401
    assert "Unauthorized" in res.json()["detail"]

    # 2. Invalid installer credentials MUST be rejected with 401
    res = client.get("/api/v1/fleet/sites", headers={"X-Installer-Key": "malicious_attacker_key"})
    assert res.status_code == 401

    # 3. Valid installer key succeeds with 200
    res = client.get("/api/v1/fleet/sites", headers={"X-Installer-Key": "installer_key_delhi_netra_01"})
    assert res.status_code == 200
    sites = res.json()
    assert len(sites) >= 1


def test_fleet_tenant_scoping_and_remote_config_dispatch():
    client = TestClient(cloud_app)
    delhi_headers = {"X-Installer-Key": "installer_key_delhi_netra_01"}

    # 1. Attempting to modify an out-of-scope site MUST return 403 Forbidden
    unauthorized_payload = {
        "alert_score_threshold": 75,
        "business_hours_start": "09:00",
        "business_hours_end": "21:00",
        "cameras": {}
    }
    res = client.post(
        "/api/v1/fleet/sites/site_unauthorized_mumbai/config",
        json=unauthorized_payload,
        headers=delhi_headers
    )
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]

    # 2. Modifying an authorized site succeeds and produces HMAC signature
    valid_payload = {
        "alert_score_threshold": 75,
        "business_hours_start": "09:00",
        "business_hours_end": "22:00",
        "cameras": {
            "cam_front": {
                "restricted_zones": [
                    {"name": "vault", "points": [[0.5, 0.5], [0.9, 0.5], [0.9, 0.9], [0.5, 0.9]]}
                ]
            }
        }
    }
    res = client.post(
        "/api/v1/fleet/sites/site_local_default/config",
        json=valid_payload,
        headers=delhi_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "deployed"
    assert data["config_version"] >= 2
    assert "signature" in data
    assert "config_hash" in data

    # 3. Verify Edge Box can pull this signed configuration using its X-Site-Key
    edge_res = client.get(
        "/api/v1/edge/sites/site_local_default/config",
        headers={"X-Site-Key": "vyzn_edge_secret_local_default_2026"}
    )
    assert edge_res.status_code == 200
    pulled = edge_res.json()
    assert pulled["config_version"] == data["config_version"]
    assert pulled["config_hash"] == data["config_hash"]
    # Cryptographically verify the signature
    assert verify_config_hmac("site_local_default", pulled["config"], pulled["signature"]) is True

    # 4. Edge box with invalid site key is rejected with 401
    bad_edge = client.get(
        "/api/v1/edge/sites/site_local_default/config",
        headers={"X-Site-Key": "wrong_secret_key"}
    )
    assert bad_edge.status_code == 401


def test_stolen_device_site_key_revocation():
    """
    CRITICAL PHYSICAL SECURITY TEST:
    Burglary scenario: If an edge box is physically stolen, installer revokes its key.
    The stolen box attempting subsequent communication with the cloud is immediately rejected.
    """
    client = TestClient(cloud_app)
    installer_headers = {"X-Installer-Key": "installer_key_delhi_netra_01"}
    stolen_site_id = "site_verma_retail"
    stolen_key = "vyzn_edge_secret_verma_retail_1184"

    # 1. Before theft, edge device authenticates successfully
    pre_theft_res = client.get(
        f"/api/v1/edge/sites/{stolen_site_id}/config",
        headers={"X-Site-Key": stolen_key}
    )
    # Site may not have managed config yet or returns 200/404, but auth passes (not 401)
    assert pre_theft_res.status_code != 401

    # 2. Installer reports device stolen and revokes key from fleet portal
    revoke_res = client.post(
        f"/api/v1/fleet/sites/{stolen_site_id}/revoke-key",
        headers=installer_headers
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"

    # 3. Thief with stolen box attempts to pull config or send heartbeat using stolen key
    post_theft_res = client.get(
        f"/api/v1/edge/sites/{stolen_site_id}/config",
        headers={"X-Site-Key": stolen_key}
    )
    # MUST BE REJECTED WITH 401 and generic "Unauthorized" with zero state leakage
    assert post_theft_res.status_code == 401
    assert post_theft_res.json()["detail"] == "Unauthorized"


def test_installer_key_revocation():
    """Verifies that an individual installer credential can be immediately invalidated."""
    from vyzn_cloud.security import revoke_installer_key
    client = TestClient(cloud_app)
    token = "installer_key_master_admin_99"

    # 1. Valid before revocation
    res = client.get("/api/v1/fleet/sites", headers={"X-Installer-Key": token})
    assert res.status_code == 200

    # 2. Revoke key
    assert revoke_installer_key(token) is True

    # 3. Subsequent call MUST fail with 401 and generic "Unauthorized"
    res_revoked = client.get("/api/v1/fleet/sites", headers={"X-Installer-Key": token})
    assert res_revoked.status_code == 401
    assert res_revoked.json()["detail"] == "Unauthorized"


def test_durable_revocation_across_service_restart():
    """
    PERSISTENCE INVARIANT:
    Ensures that revoked credentials persist in SQLite across simulated service restarts.
    Wiping in-memory sets and re-initializing the database MUST reload blacklists.
    """
    from vyzn_cloud.security import (
        REVOKED_SITE_KEYS,
        REVOKED_INSTALLER_KEYS,
        SITE_SECRETS,
        _init_security_db
    )
    client = TestClient(cloud_app)
    stolen_key = "vyzn_edge_secret_verma_retail_1184"

    # Verify stolen key is in memory
    assert stolen_key in REVOKED_SITE_KEYS

    # Simulate catastrophic service restart: wipe in-memory sets completely
    REVOKED_SITE_KEYS.clear()
    REVOKED_INSTALLER_KEYS.clear()
    SITE_SECRETS.clear()

    # Re-initialize DB schema and cache from persistent storage
    _init_security_db()

    # Stolen key MUST be restored to in-memory blacklist
    assert stolen_key in REVOKED_SITE_KEYS

    # Stolen box connection attempt must still be rejected
    res = client.get(
        "/api/v1/edge/sites/site_verma_retail/config",
        headers={"X-Site-Key": stolen_key}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized"


def test_site_key_reissuance_and_staged_config_resigning():
    """
    KEY ROTATION & REISSUANCE INVARIANT:
    Verifies that when a replacement box is installed for a site (e.g. site_verma_retail after theft),
    the installer can reissue a fresh key. Staged config is automatically re-signed with the new key.
    """
    client = TestClient(cloud_app)
    installer_headers = {"X-Installer-Key": "installer_key_delhi_netra_01"}
    site_id = "site_verma_retail"

    # 1. Stage a configuration for site_verma_retail
    stage_res = client.post(
        f"/api/v1/fleet/sites/{site_id}/config",
        json={
            "alert_score_threshold": 70,
            "business_hours_start": "09:00",
            "business_hours_end": "21:00",
            "cameras": {}
        },
        headers=installer_headers
    )
    assert stage_res.status_code == 200

    # 2. Reissue key for replacement box
    reissue_res = client.post(
        f"/api/v1/fleet/sites/{site_id}/reissue-key",
        headers=installer_headers
    )
    assert reissue_res.status_code == 200
    data = reissue_res.json()
    assert data["status"] == "reissued"
    assert data["site_id"] == site_id
    assert data["staged_config_resigned"] is True
    new_key = data["new_site_key"]
    assert new_key.startswith(f"vyzn_edge_secret_{site_id}_")

    # 3. Old stolen key must now be rejected
    old_key = "vyzn_edge_secret_verma_retail_1184"
    old_res = client.get(
        f"/api/v1/edge/sites/{site_id}/config",
        headers={"X-Site-Key": old_key}
    )
    assert old_res.status_code == 401
    assert old_res.json()["detail"] == "Unauthorized"

    # 4. New replacement box successfully authenticates and pulls staged config
    new_res = client.get(
        f"/api/v1/edge/sites/{site_id}/config",
        headers={"X-Site-Key": new_key}
    )
    assert new_res.status_code == 200
    pulled = new_res.json()
    assert "signature" in pulled

    # 5. The pulled config signature cryptographically verifies with the new key
    assert verify_config_hmac(site_id, pulled["config"], pulled["signature"]) is True


def test_fleet_portal_html_rendering():
    client = TestClient(cloud_app)
    res = client.get("/fleet")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    content = res.text
    assert "VYZN NETRA" in content
    assert "Multi-Tenant Fleet Observability" in content
    assert "Remote OTA Config Dispatcher" in content
    assert "draftResumeBanner" in content
    assert "onboardingModal" in content
    assert "Report Stolen" in content
    assert "triggerWizardTestAlert" in content
    assert "submitGoLive" in content