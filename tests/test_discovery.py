"""
Unit and integration tests for Network Camera & ONVIF Auto-Discovery.
Verifies discovery service and API endpoints for 1-click camera adoption.
"""

from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import get_default_settings
from vyzn.capture.discovery import CameraDiscoveryService, DiscoveredCamera


def test_discovery_service_model_and_probing():
    discovery = CameraDiscoveryService(timeout_sec=0.1)

    # 1. Test probe against nonexistent host yields None gracefully
    res = discovery.probe_rtsp_host("192.0.2.1", port=554, timeout=0.05)
    assert res is None

    # 2. Test DiscoveredCamera serialization
    cam = DiscoveredCamera(
        ip="192.168.1.100",
        port=554,
        vendor="CP PLUS / Dahua",
        rtsp_url="rtsp://192.168.1.100:554/cam/realmonitor?channel=1&subtype=0",
        name="CP PLUS Camera 1"
    )
    d = cam.to_dict()
    assert d["ip"] == "192.168.1.100"
    assert d["vendor"] == "CP PLUS / Dahua"
    assert "rtsp://" in d["rtsp_url"]


def test_camera_discovery_and_adoption_endpoints(tmp_path):
    db = EventDatabase(tmp_path / "test_disc.db")
    settings = get_default_settings(tmp_path)
    init_api(db, settings)
    client = TestClient(app)

    # 1. Test GET /api/v1/cameras/discover
    res = client.get("/api/v1/cameras/discover?timeout=0.5")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "cameras" in data

    # 2. Test POST /api/v1/cameras/adopt
    initial_count = len(settings.cameras)
    adopt_payload = {
        "camera_id": "cam_adopted_01",
        "name": "Entrance CP-PLUS",
        "rtsp_url": "rtsp://192.168.1.150:554/cam/realmonitor?channel=1&subtype=0",
        "username": "admin",
        "password": "Password@123",
        "target_fps": 4.0
    }
    adopt_res = client.post("/api/v1/cameras/adopt", json=adopt_payload)
    assert adopt_res.status_code == 200
    adopt_data = adopt_res.json()
    assert adopt_data["status"] == "adopted"
    assert adopt_data["camera_id"] == "cam_adopted_01"
    assert len(settings.cameras) == initial_count + 1

    # Verify credentials injected into RTSP URL
    saved_cam = next(c for c in settings.cameras if c.camera_id == "cam_adopted_01")
    assert "admin:Password@123" in saved_cam.rtsp_url

    db.close()
