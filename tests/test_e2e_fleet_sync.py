"""
End-to-End Integration Test:
Verifies the complete closed loop between Edge Node and Cloud Fleet Manager:
1. Heartbeat telemetry ingestion & watchdog status tracking.
2. Multi-tenant installer authentication and remote signed OTA configuration dispatch.
3. Edge OTA pull, cryptographic HMAC verification, semantic validation, and wholesale atomic swap.
4. Fleet synchronization convergence verification.
5. Inviolable threat floor alerting on real intruders after hours.
"""

from pathlib import Path
from datetime import datetime, timezone
from starlette.testclient import TestClient

from vyzn_cloud.app import cloud_app, watchdog
from vyzn_cloud.security import (
    generate_config_hmac,
    verify_config_hmac,
    compute_config_hash,
    SITE_SECRETS
)
from vyzn.core.config import EdgeSettings, CameraConfig, ZonePolygon, BusinessHours
from vyzn.core.database import EventDatabase
from vyzn.core.events import DetectionCandidate
from vyzn.pipeline import EdgePipeline
from vyzn.telemetry.ota_sync import OTASyncWorker


def test_end_to_end_fleet_observability_and_ota_closed_loop(tmp_path):
    client = TestClient(cloud_app)

    # 1. Initialize Edge Settings and Database in tmp_path
    cam = CameraConfig(
        camera_id="cam_front_counter",
        name="Front Counter",
        rtsp_url="sim://counter",
        is_night_ir=False,
        business_hours=BusinessHours(enabled=False),
        restricted_zones=[
            ZonePolygon(name="initial_zone", points=[[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3]])
        ]
    )
    settings = EdgeSettings(
        site_id="site_local_default",
        site_name="Local Edge Demonstration",
        data_dir=tmp_path / "clips",
        db_path=tmp_path / "index.db",
        alert_score_threshold=70,
        cloud_webhook_url="http://mock-cloud",
        cloud_auth_token="vyzn_edge_secret_local_default_2026",
        cameras=[cam]
    )
    db = EventDatabase(settings.db_path)
    pipeline = EdgePipeline(settings=settings, use_synthetic=True)

    # 2. Step A: Edge Heartbeat Transmission to Cloud
    initial_hash = pipeline.get_telemetry_status().get("config_hash", "init_hash")
    heartbeat_payload = {
        "site_id": "site_local_default",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "uptime_sec": 120.0,
            "cpu_usage_pct": 18.5,
            "cpu_temp_c": 46.0,
            "ram_used_mb": 450.0,
            "disk_free_pct": 72.0
        },
        "pipeline": pipeline.get_telemetry_status(),
        "config_hash": initial_hash
    }
    hb_res = client.post("/api/v1/telemetry/heartbeat", json=heartbeat_payload)
    assert hb_res.status_code == 200
    assert hb_res.json()["status"] == "acknowledged"

    # 3. Step B: Installer Inspects Fleet on Port 9000
    installer_headers = {"X-Installer-Key": "installer_key_delhi_netra_01"}
    sites_res = client.get("/api/v1/fleet/sites", headers=installer_headers)
    assert sites_res.status_code == 200
    fleet_sites = sites_res.json()
    local_site = next((s for s in fleet_sites if s["site_id"] == "site_local_default"), None)
    assert local_site is not None
    assert local_site["status"] == "ONLINE"

    # 4. Step C: Installer Deploys New Signed Restricted Zone via Cloud API
    new_vault_zone = [[0.6, 0.6], [0.95, 0.6], [0.95, 0.95], [0.6, 0.95]]
    ota_payload = {
        "alert_score_threshold": 75,
        "business_hours_start": "09:00",
        "business_hours_end": "22:00",
        "cameras": {
            "cam_front_counter": {
                "restricted_zones": [
                    {"name": "high_security_safe_vault", "points": new_vault_zone}
                ]
            }
        }
    }
    deploy_res = client.post(
        "/api/v1/fleet/sites/site_local_default/config",
        json=ota_payload,
        headers=installer_headers
    )
    assert deploy_res.status_code == 200
    deploy_data = deploy_res.json()
    assert deploy_data["status"] == "deployed"
    cloud_new_hash = deploy_data["config_hash"]

    # 5. Step D: Cloud detects hash difference on next heartbeat
    check_hb = client.post(
        "/api/v1/telemetry/heartbeat",
        json={**heartbeat_payload, "config_hash": initial_hash}
    )
    assert check_hb.json()["new_config_available"] is True

    # 6. Step E: Edge Node Pulls, Cryptographically Verifies, and Atomically Applies Config
    edge_pull = client.get(
        "/api/v1/edge/sites/site_local_default/config",
        headers={"X-Site-Key": settings.cloud_auth_token}
    )
    assert edge_pull.status_code == 200
    ota_package = edge_pull.json()

    # Pass package into Edge OTA Sync Worker
    sync_worker = pipeline.ota_sync
    applied = sync_worker.apply_ota_payload(ota_package)
    assert applied is True

    # Verify atomic update on pipeline
    assert pipeline.settings.alert_score_threshold == 75
    assert pipeline.scoring_engine.alert_threshold == 75
    updated_cam = pipeline.settings.cameras[0]
    assert updated_cam.restricted_zones[0].name == "high_security_safe_vault"
    assert sync_worker.current_config_hash == cloud_new_hash

    # 7. Step F: Edge Heartbeat with New Hash Converges Fleet State
    converge_hb = client.post(
        "/api/v1/telemetry/heartbeat",
        json={**heartbeat_payload, "config_hash": cloud_new_hash}
    )
    assert converge_hb.json()["new_config_available"] is False

    # 8. Step G: Verified Intruder After-Hours Alerts Inviolably under New Threshold (75)
    burglar = DetectionCandidate(
        camera_id="cam_front_counter",
        object_type="person",
        confidence=0.45,
        motion_ratio=0.01,
        track_duration_sec=0.5,
        bounding_box=[0.7, 0.7, 0.8, 0.85],
        is_after_hours=True,
        is_in_restricted_zone=True,
        is_night_ir=False,
        timestamp=datetime.now(timezone.utc)
    )
    score, should_alert, breakdown = pipeline.scoring_engine.evaluate(burglar, camera_bias=-25)
    assert breakdown["is_valid_detection"] is True
    assert score >= 75, f"Expected threat floor >= 75, got {score}"
    assert should_alert is True, "Intruder must alert even after OTA threshold update"

    db.close()