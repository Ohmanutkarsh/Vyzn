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


def test_fleet_portal_html_rendering():
    client = TestClient(cloud_app)
    res = client.get("/fleet")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    content = res.text
    assert "VYZN NETRA" in content
    assert "Multi-Tenant Fleet Observability" in content
    assert "Remote OTA Config Dispatcher" in content