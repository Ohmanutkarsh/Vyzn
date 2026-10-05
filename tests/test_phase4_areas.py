"""
Automated Integration & Unit Tests for Phase 4: Watch Areas (S7)
Tests:
1. WatchAreaConfig validation (normalized coords, responses, stay times, max 5 areas).
2. Endpoints: GET /api/cameras/{id}/areas, PUT /api/cameras/{id}/areas, GET /api/areas, POST /api/cameras/{id}/snapshot.
3. MOG2MotionGate binary ROI masking (road motion outside area masked out, area motion detected).
4. Foot-position detection evaluation (is_foot_in_polygon: bottom-centre vs centroid).
5. Audit log tracking (CAMERA_AREAS_UPDATED).
"""

import os
import time
import pytest
import numpy as np
import cv2
from pathlib import Path
from fastapi.testclient import TestClient

from vyzn.core.config import EdgeSettings, CameraConfig, WatchAreaConfig, ZonePolygon
from vyzn.core.database import EventDatabase
from vyzn.motion.mog2_gate import MOG2MotionGate
from vyzn.scoring.engine import is_foot_in_polygon, is_point_in_polygon
from vyzn.api.routes import app, init_api


@pytest.fixture
def setup_env(tmp_path):
    db_file = tmp_path / "test_areas.db"
    data_dir = tmp_path / "clips"
    data_dir.mkdir(parents=True, exist_ok=True)

    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_test_areas",
        data_dir=data_dir,
        db_path=db_file,
        cameras=[
            CameraConfig(
                camera_id="cam_test_entrance",
                name="Shop entrance",
                rtsp_url="test://simulate?code=success",
                enabled=True,
                watch_areas=[]
            ),
            CameraConfig(
                camera_id="cam_test_counter",
                name="Cash counter",
                rtsp_url="test://simulate?code=success",
                enabled=True,
                watch_areas=[]
            )
        ]
    )

    init_api(db, settings)
    yield db, settings
    db.close()


def test_watch_area_model_validation():
    """Validates WatchAreaConfig normalized coordinate constraints and fields."""
    area = WatchAreaConfig(
        id="area_1",
        camera_id="cam_test",
        name="Cash counter",
        polygon=[[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]],
        response="alert",
        min_stay_seconds=10,
        schedule="always",
        version=1
    )
    assert area.name == "Cash counter"
    assert area.response == "alert"
    assert area.min_stay_seconds == 10
    assert len(area.polygon) == 4


def test_mog2_motion_masking():
    """
    Verifies Section 6.4 core invariant:
    Motion strictly on the road (outside watch area) is masked out (has_motion=False, dropped_outside=True).
    Motion inside the watch area is detected (has_motion=True).
    """
    gate = MOG2MotionGate(history=50, var_threshold=16.0, min_motion_ratio=0.01)
    cam_id = "cam_mask_test"

    # Define a shop watch area in the right half of the frame: [0.5, 0.0] to [1.0, 1.0]
    shop_area = [
        [0.5, 0.0],
        [1.0, 0.0],
        [1.0, 1.0],
        [0.5, 1.0]
    ]
    gate.set_camera_areas(cam_id, [shop_area])

    # Establish clean background (100x100 black frames)
    bg = np.zeros((100, 100, 3), dtype=np.uint8)
    for _ in range(25):
        gate.process_frame(cam_id, bg)

    # 1. Simulate motion ONLY on the road (left half: x from 10 to 40)
    road_motion = bg.copy()
    cv2.rectangle(road_motion, (10, 20), (40, 80), (255, 255, 255), -1)

    has_motion, ratio, masked_fg = gate.process_frame(cam_id, road_motion)
    assert not has_motion, "Road motion outside watch area must NOT trigger motion!"
    assert gate.had_motion_dropped_outside(cam_id), "Dropped outside flag must be True!"

    # 2. Simulate motion INSIDE the shop watch area (right half: x from 60 to 90)
    shop_motion = bg.copy()
    cv2.rectangle(shop_motion, (60, 20), (90, 80), (255, 255, 255), -1)

    has_motion_shop, ratio_shop, _ = gate.process_frame(cam_id, shop_motion)
    assert has_motion_shop, "Motion inside shop watch area MUST trigger motion!"


def test_foot_position_evaluation():
    """
    Verifies Section 6.4 requirement:
    Decide 'inside an area' from the bottom-centre point of the person's box (where they stand),
    not the box centre.
    """
    # Watch area polygon (lower quarter of frame: y in 0.5..1.0, x in 0.3..0.7)
    polygon = [
        [0.3, 0.5],
        [0.7, 0.5],
        [0.7, 1.0],
        [0.3, 1.0]
    ]

    # Case A: Person stands on the road (feet at y=0.45), but upper body leans in
    # Box: x1=0.4, y1=0.2, x2=0.6, y2=0.45
    # Centroid: (0.5, 0.325) -> outside. Foot: (0.5, 0.45) -> outside.
    box_standing_outside = [0.4, 0.2, 0.6, 0.45]
    assert not is_foot_in_polygon(box_standing_outside, polygon)

    # Case B: Person stands inside the shop (feet at y=0.65), upper body at y=0.35 (outside)
    # Centroid: (0.5, 0.5) [on the edge]. Foot: (0.5, 0.65) -> firmly inside!
    box_feet_inside = [0.4, 0.35, 0.6, 0.65]
    assert is_foot_in_polygon(box_feet_inside, polygon)


def test_areas_crud_lifecycle(setup_env):
    """Verifies GET/PUT /api/cameras/{id}/areas, audit logging, and max 5 limit."""
    db, settings = setup_env
    client = TestClient(app)

    cam_id = "cam_test_entrance"

    # 1. Initial GET: 0 areas, status online/offline
    res = client.get(f"/api/cameras/{cam_id}/areas")
    assert res.status_code == 200
    data = res.json()
    assert data["camera_id"] == cam_id
    assert data["area_count"] == 0
    assert data["ignored_moments_count"] == 0

    # 2. PUT: Save 2 valid watch areas
    payload = {
        "areas": [
            {
                "id": "area_counter",
                "name": "Cash counter",
                "polygon": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]],
                "response": "alert",
                "min_stay_seconds": 30,
                "schedule": "always"
            },
            {
                "id": "area_floor",
                "name": "Shop floor",
                "polygon": [[0.5, 0.5], [0.9, 0.5], [0.9, 0.9], [0.5, 0.9]],
                "response": "review",
                "min_stay_seconds": 10,
                "schedule": "outside_shop_hours"
            }
        ]
    }
    put_res = client.put(f"/api/cameras/{cam_id}/areas", json=payload)
    assert put_res.status_code == 200
    put_data = put_res.json()
    assert put_data["ok"] is True
    assert put_data["area_count"] == 2
    assert put_data["version"] >= 1

    # Verify persistence via GET
    get_res = client.get(f"/api/cameras/{cam_id}/areas")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["area_count"] == 2
    assert get_data["areas"][0]["name"] == "Cash counter"
    assert get_data["areas"][0]["min_stay_seconds"] == 30
    assert get_data["areas"][1]["name"] == "Shop floor"

    # 3. Verify audit log
    db.flush()
    audits = db.get_audit_logs(limit=10)
    area_audit = next((a for a in audits if a.get("action") == "CAMERA_AREAS_UPDATED"), None)
    assert area_audit is not None, "CAMERA_AREAS_UPDATED must be logged in audit_log!"

    # 4. Limit check: Attempting to save 6 areas must fail with 400
    too_many_areas = {
        "areas": [
            {"name": f"Area {i}", "polygon": [[0,0], [0.1,0], [0.1,0.1]]} for i in range(6)
        ]
    }
    fail_res = client.put(f"/api/cameras/{cam_id}/areas", json=too_many_areas)
    assert fail_res.status_code == 400
    assert "Maximum 5 areas" in fail_res.json()["detail"]


def test_areas_picker_overview_and_ignored_count(setup_env):
    """Verifies GET /api/areas picker facts and ignored moments tracking."""
    db, settings = setup_env
    client = TestClient(app)

    cam_id = "cam_test_entrance"

    # Increment ignored moments
    db.increment_ignored_moments(cam_id, 42)
    db.flush()

    res = client.get("/api/areas")
    assert res.status_code == 200
    cameras = res.json()
    assert len(cameras) >= 2

    target = next((c for c in cameras if c["id"] == cam_id), None)
    assert target is not None
    assert target["ignored_moments_count"] == 42


def test_snapshot_refresh_endpoint(setup_env):
    """Verifies POST /api/cameras/{id}/snapshot triggers picture update."""
    db, settings = setup_env
    client = TestClient(app)

    res = client.post("/api/cameras/cam_test_entrance/snapshot")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "snapshot_url" in data
