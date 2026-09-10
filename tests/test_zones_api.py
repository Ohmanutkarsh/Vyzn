"""
Tests for camera snapshots and dynamic polygon zone API endpoints.
"""

from pathlib import Path
from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings, CameraConfig


def test_zones_and_snapshot_api(tmp_path: Path):
    db_file = tmp_path / "zone_test.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_zone_test",
        data_dir=tmp_path,
        db_path=db_file
    )
    settings.cameras = [
        CameraConfig(
            camera_id="cam_cash_counter",
            name="Cash Counter",
            rtsp_url="sim://cash",
            target_fps=4.0
        )
    ]

    init_api(db, settings)
    client = TestClient(app)

    # 1. Test Camera Snapshot
    snap_res = client.get("/api/cameras/cam_cash_counter/snapshot.jpg")
    assert snap_res.status_code == 200
    assert snap_res.headers["content-type"] == "image/jpeg"
    assert len(snap_res.content) > 100

    # 2. Test Create Restricted Polygon Zone
    zone_payload = {
        "name": "cash_drawer_box_test",
        "points": [[0.60, 0.40], [0.85, 0.40], [0.85, 0.70], [0.60, 0.70]],
        "weight": 25,
        "schedule_mode": "restricted_all_times",
        "description": "Test cash counter zone"
    }
    create_res = client.post("/api/cameras/cam_cash_counter/zones", json=zone_payload)
    assert create_res.status_code == 200
    res_data = create_res.json()
    assert res_data["status"] == "success"
    assert res_data["zone_name"] == "cash_drawer_box_test"
    assert res_data["vertex_count"] == 4

    # 3. Test Get Active Zones
    get_res = client.get("/api/cameras/cam_cash_counter/zones")
    assert get_res.status_code == 200
    zones = get_res.json()
    assert len(zones) >= 1
    assert any(z["name"] == "cash_drawer_box_test" for z in zones)

    db.close()
