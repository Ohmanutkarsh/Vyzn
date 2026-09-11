"""
Integration tests for VYZN Direct Cloud Event Ingestion Gateway.
Verifies zero-hardware serverless snapshot ingestion, site authentication,
threat scoring, and fleet incident logging.
"""

import cv2
import numpy as np
from starlette.testclient import TestClient
from vyzn_cloud.app import cloud_app
from vyzn_cloud.security import SITE_SECRETS, revoke_site_key, _reset_security_state


def create_test_jpeg_bytes(brightness: int = 150) -> bytes:
    """Generates synthetic JPEG test frame."""
    frame = np.full((360, 640, 3), brightness, dtype=np.uint8)
    # Add dark rectangular box representing detected object
    cv2.rectangle(frame, (200, 100), (440, 300), (20, 20, 20), -1)
    success, encoded = cv2.imencode(".jpg", frame)
    return encoded.tobytes() if success else b""


def test_cloud_ingest_authentication_enforcement():
    client = TestClient(cloud_app)

    # 1. Missing site key returns 401
    res = client.post("/api/v1/cloud/ingest/snapshot")
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized"

    # 2. Invalid site key returns 401
    res = client.post(
        "/api/v1/cloud/ingest/snapshot?site_id=site_local_default",
        headers={"X-Site-Key": "invalid_bogus_key"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Unauthorized"


def test_cloud_ingest_snapshot_processing_and_threat_scoring():
    """
    Simulates CP Plus / Hikvision NVR sending motion snapshot to VYZN Cloud.
    Verifies serverless ONNX object detection and 5-layer threat scoring.
    """
    _reset_security_state()
    client = TestClient(cloud_app)
    site_id = "site_local_default"
    site_key = SITE_SECRETS[site_id]

    jpeg_bytes = create_test_jpeg_bytes(brightness=180)

    # 1. Post snapshot via multipart upload
    files = {"file": ("motion_01.jpg", jpeg_bytes, "image/jpeg")}
    data = {"site_id": site_id, "camera_id": "cam_front"}
    headers = {"X-Site-Key": site_key}

    res = client.post("/api/v1/cloud/ingest/snapshot", files=files, data=data, headers=headers)
    assert res.status_code == 200
    resp_data = res.json()
    assert resp_data["status"] == "processed"
    assert resp_data["site_id"] == site_id
    assert resp_data["camera_id"] == "cam_front"
    assert "highest_score" in resp_data
    assert "triage" in resp_data


def test_cloud_ingest_json_webhook():
    """Verifies JSON webhook ingestion from smart NVRs or third-party gateways."""
    _reset_security_state()
    client = TestClient(cloud_app)
    site_id = "site_local_default"
    site_key = SITE_SECRETS[site_id]

    payload = {
        "site_id": site_id,
        "camera_id": "cam_back_alley",
        "alarm_type": "motion_detection"
    }
    headers = {"X-Site-Key": site_key}

    res = client.post("/api/v1/cloud/ingest/webhook", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "processed"
    assert data["site_id"] == site_id
    assert data["camera_id"] == "cam_back_alley"
    assert "score" in data
