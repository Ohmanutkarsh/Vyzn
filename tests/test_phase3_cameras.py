"""
Automated Integration Tests for Phase 3: Cameras & Live View
Validates Section 6.5 test table error diagnostics, camera CRUD lifecycle,
deletion logging, and live stream endpoints.
"""

from pathlib import Path
import pytest
from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path: Path):
    db_file = tmp_path / "cameras_test.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_cam_test",
        data_dir=tmp_path,
        db_path=db_file,
        telegram_bot_token=""
    )
    init_api(db, settings)
    yield db, settings
    db.close()


def test_probe_connection_diagnostics():
    """Verifies all 6 diagnostic states in the Section 6.5 connection test table."""
    client = TestClient(app)

    # 1. Success
    res = client.post("/api/cameras/test", json={"rtsp_url": "test://simulate?code=success"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["code"] == "success"
    assert data["message"] == "We can see the picture."
    assert data["width"] > 0
    assert data["height"] > 0
    assert data["fps"] > 0
    assert data["preview_base64"] is not None

    # 2. 401 Wrong credentials
    res = client.post("/api/cameras/test", json={"rtsp_url": "test://simulate?code=401"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["code"] == "auth_failed"
    assert "rejected the username or password" in data["message"]

    # 3. Timeout / Unreachable
    res = client.post("/api/cameras/test", json={"rtsp_url": "test://simulate?code=timeout&ip=192.168.1.100"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["code"] == "timeout"
    assert "Couldn't reach 192.168.1.100" in data["message"]

    # 4. Port closed / Refused
    res = client.post("/api/cameras/test", json={"rtsp_url": "test://simulate?code=port_closed&port=554"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["code"] == "port_closed"
    assert "didn't answer on port 554" in data["message"]

    # 5. 404 Channel / Path not found
    res = client.post("/api/cameras/test", json={"rtsp_url": "test://simulate?code=404"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["code"] == "not_found"
    assert "not for this channel" in data["message"]

    # 6. Unsupported video codec
    res = client.post("/api/cameras/test", json={"rtsp_url": "test://simulate?code=codec"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False
    assert data["code"] == "unsupported_codec"
    assert "switch the stream to H.264" in data["message"]


def test_probe_by_ip_and_brand():
    """Verifies Appendix C brand template building during connection testing."""
    client = TestClient(app)
    res = client.post("/api/cameras/test", json={
        "ip": "192.168.1.50",
        "port": 554,
        "username": "admin",
        "password": "secret_password",
        "brand": "Hikvision",
        "channel": 1,
        "rtsp_url": "test://simulate?code=success"
    })
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_camera_crud_lifecycle_and_deletion_log():
    """Verifies adding, listing (without credentials), patching, and deleting cameras."""
    client = TestClient(app)
    test_cam_id = "cam_test_entrance_99"
    test_cam_name = "Shop Entrance Test"
    rtsp_with_creds = "rtsp://admin:super_secret@192.168.1.88:554/live"

    # 1. Create camera with Security PIN
    res = client.post("/api/cameras", json={
        "camera_id": test_cam_id,
        "name": test_cam_name,
        "rtsp_url": rtsp_with_creds,
        "target_fps": 15.0
    }, headers={"X-Security-Pin": "202600"})
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == test_cam_id
    assert data["name"] == test_cam_name
    assert "super_secret" not in data["rtsp_url_masked"]

    # 2. List cameras and ensure passwords are never leaked
    res = client.get("/api/cameras")
    assert res.status_code == 200
    cams = res.json()
    matching = next((c for c in cams if c["id"] == test_cam_id), None)
    assert matching is not None
    assert matching["name"] == test_cam_name
    assert "super_secret" not in matching["rtsp_url_masked"]
    assert "resolution" in matching
    assert "fps" in matching
    assert "source_line" in matching

    # 3. Rename camera
    res = client.patch(f"/api/cameras/{test_cam_id}", json={"name": "Cash Counter Renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "Cash Counter Renamed"

    # 4. Delete camera with Security PIN and verify deletion_log entry
    res = client.delete(f"/api/cameras/{test_cam_id}", headers={"X-Security-Pin": "202600"})
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"

    from vyzn.api.routes import get_db
    db = get_db()
    logs = db.get_deletion_logs(camera_id=test_cam_id)
    assert len(logs) > 0
    assert "camera removed" in logs[0]["reason"]
    assert logs[0]["status"] == "camera_removed"


def test_phase3_camera_discovery_and_adoption(tmp_path: Path):
    db_file = tmp_path / "cam_adopt.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(site_id="site_cam_test", data_dir=tmp_path, db_path=db_file)
    init_api(db, settings)
    test_camera_crud_lifecycle_and_deletion_log()
    db.close()


def test_phase3_camera_test_probe_and_health(tmp_path: Path):
    db_file = tmp_path / "cam_probe.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(site_id="site_cam_test", data_dir=tmp_path, db_path=db_file)
    init_api(db, settings)
    test_probe_connection_diagnostics()
    test_probe_by_ip_and_brand()
    test_shell_status_pill()
    test_snapshot_endpoint()
    db.close()


def test_shell_status_pill():
    """Verifies the 5-priority status pill logic."""
    client = TestClient(app)
    res = client.get("/api/shell/status")
    assert res.status_code == 200
    data = res.json()
    assert "pill" in data
    assert "text" in data["pill"]
    assert "style" in data["pill"]
    assert "icon" in data["pill"]


def test_snapshot_endpoint():
    """Verifies that /api/cameras/{id}/snapshot.jpg returns valid JPEG."""
    client = TestClient(app)
    res = client.get("/api/cameras/cam_nonexistent/snapshot.jpg")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert len(res.content) > 100
