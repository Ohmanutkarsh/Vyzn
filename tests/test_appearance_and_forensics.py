"""
Unit and integration tests for AI Appearance Search, Attribute Extraction,
Forensic Evidence Pack Exporter, and Bandwidth QoS endpoints.
"""

import os
import io
import json
import zipfile
import tempfile
import numpy as np
import cv2
from pathlib import Path

from vyzn.ai.attributes import (
    classify_hsv_pixel,
    get_dominant_color_from_patch,
    extract_appearance_attributes
)
from vyzn.core.events import EventRecord
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings, CameraConfig
from vyzn.api.routes import app, init_api


def test_hsv_pixel_classification():
    """Verifies that standard HSV ranges classify into expected color buckets."""
    # Red (Hue 0 or 175)
    assert classify_hsv_pixel(5, 200, 200) == "red"
    assert classify_hsv_pixel(172, 200, 200) == "red"

    # Blue (Hue ~120)
    assert classify_hsv_pixel(120, 200, 200) == "blue"

    # Green (Hue ~60)
    assert classify_hsv_pixel(60, 200, 200) == "green"

    # Yellow (Hue ~30)
    assert classify_hsv_pixel(30, 200, 200) == "yellow"

    # Black (low brightness V)
    assert classify_hsv_pixel(0, 0, 30) == "black"

    # White (low saturation S, high brightness V)
    assert classify_hsv_pixel(0, 10, 240) == "white"


def test_appearance_attribute_extraction_on_crops():
    """Verifies that extract_appearance_attributes detects clothing color and zones."""
    # Create synthetic frame: 300x300 BGR
    frame = np.zeros((300, 300, 3), dtype=np.uint8)

    # Place a red person upper torso and blue pants in [50, 50, 250, 150]
    # Person box: y from 50 to 250, x from 50 to 150
    # Upper half: y: 50 to 150 -> BGR Red: (0, 0, 255)
    frame[50:150, 50:150] = (0, 0, 255)
    # Lower half: y: 150 to 250 -> BGR Blue: (255, 0, 0)
    frame[150:250, 50:150] = (255, 0, 0)

    norm_box = [50 / 300.0, 50 / 300.0, 150 / 300.0, 250 / 300.0]
    attrs = extract_appearance_attributes(frame, norm_box, object_type="person")

    assert attrs["dominant_color"] in ["red", "blue"]
    assert attrs["upper_color"] == "red"
    assert attrs["lower_color"] == "blue"
    assert "upper_red" in attrs["tags"]
    assert "lower_blue" in attrs["tags"]


def test_database_attribute_query_filtering():
    """Verifies that EventDatabase filters records by color, zone, and object_type."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_events.db"
        db = EventDatabase(db_path)

        ev1 = EventRecord(
            event_group_id="ev_red_vault",
            camera_id="cam_vault",
            start_time="2026-09-11T12:00:00Z",
            object_type="person",
            confidence=0.92,
            score=85,
            dominant_color="red",
            zone_name="restricted_vault",
            file_path="",
            thumb_path=""
        )
        ev2 = EventRecord(
            event_group_id="ev_blue_corridor",
            camera_id="cam_corridor",
            start_time="2026-09-11T12:05:00Z",
            object_type="person",
            confidence=0.88,
            score=45,
            dominant_color="blue",
            zone_name="main_corridor",
            file_path="",
            thumb_path=""
        )
        ev3 = EventRecord(
            event_group_id="ev_vehicle_shutter",
            camera_id="cam_shutter",
            start_time="2026-09-11T12:10:00Z",
            object_type="vehicle",
            confidence=0.95,
            score=75,
            dominant_color="white",
            zone_name="rear_shutter",
            file_path="",
            thumb_path=""
        )

        db.execute_sync("SELECT 1")  # Ensure initialized
        # Insert events synchronously via execute_sync
        for ev in [ev1, ev2, ev3]:
            db.execute_sync(
                """
                INSERT INTO events (
                    event_group_id, camera_id, start_time, object_type, confidence, score,
                    status, starred, synced, user_triage, file_path, thumb_path, dominant_color, zone_name
                ) VALUES (?, ?, ?, ?, ?, ?, 'raw', 0, 0, 'unreviewed', '', '', ?, ?)
                """,
                (ev.event_group_id, ev.camera_id, ev.start_time, ev.object_type, ev.confidence,
                 ev.score, ev.dominant_color, ev.zone_name)
            )

        # Filter by color = 'red'
        red_results = db.query_events(color="red")
        assert len(red_results) == 1
        assert red_results[0].event_group_id == "ev_red_vault"

        # Filter by zone = 'rear_shutter'
        shutter_results = db.query_events(zone="rear_shutter")
        assert len(shutter_results) == 1
        assert shutter_results[0].object_type == "vehicle"

        # Filter by object_type = 'person'
        people = db.query_events(object_type="person")
        assert len(people) == 2

        db.close()


def test_forensic_pack_generation_and_manifest():
    """Verifies that the /forensic-pack endpoint produces a tamper-evident ZIP with Section 65B legal text."""
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        db_path = td / "events.db"
        db = EventDatabase(db_path)

        # Create dummy video and thumbnail files
        video_file = td / "ev_test_01.mp4"
        video_file.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00test_video_data")

        thumb_file = td / "ev_test_01_thumb.jpg"
        thumb_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIFdummy_thumbnail_data")

        ev = EventRecord(
            event_group_id="ev_test_01",
            camera_id="cam_vault",
            start_time="2026-09-11T10:00:00Z",
            end_time="2026-09-11T10:00:08Z",
            object_type="person",
            confidence=0.95,
            score=82,
            dominant_color="red",
            zone_name="restricted_vault",
            file_path=str(video_file),
            thumb_path=str(thumb_file)
        )

        db.execute_sync(
            """
            INSERT INTO events (
                event_group_id, camera_id, start_time, end_time, object_type, confidence, score,
                status, starred, synced, user_triage, file_path, thumb_path, dominant_color, zone_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'raw', 0, 0, 'unreviewed', ?, ?, ?, ?)
            """,
            (ev.event_group_id, ev.camera_id, ev.start_time, ev.end_time, ev.object_type, ev.confidence,
             ev.score, ev.file_path, ev.thumb_path, ev.dominant_color, ev.zone_name)
        )

        settings = EdgeSettings(
            site_id="site_nagpur_hub",
            site_name="Nagpur Hub • Main Store",
            data_dir=td,
            cameras=[CameraConfig(camera_id="cam_vault", name="Vault", rtsp_url="sim://vault")]
        )

        init_api(db, settings)
        client = TestClient(app)

        resp = client.get("/api/v1/events/ev_test_01/forensic-pack")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        # Verify ZIP contents
        with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
            namelist = zf.namelist()
            assert "ev_test_01.mp4" in namelist
            assert "ev_test_01_thumb.jpg" in namelist
            assert "manifest_sha256.json" in namelist
            assert "SECTION_65B_LEGAL_CERTIFICATE.txt" in namelist

            manifest = json.loads(zf.read("manifest_sha256.json").decode("utf-8"))
            assert manifest["site_id"] == "site_nagpur_hub"
            assert manifest["dominant_color"] == "red"
            assert manifest["zone_name"] == "restricted_vault"
            assert manifest["threat_score"] == 82
            assert len(manifest["video_sha256"]) == 64  # SHA-256 length

            cert = zf.read("SECTION_65B_LEGAL_CERTIFICATE.txt").decode("utf-8")
            assert "BHARATIYA SAKSHYA ADHINIYAM, 2023" in cert
            assert "SECTION 65B OF THE INDIAN EVIDENCE ACT" in cert
            assert "Nagpur Hub" in cert

        db.close()


def test_bandwidth_settings_api():
    """Verifies that bandwidth QoS endpoints read and write configuration safely."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    get_res = client.get("/api/v1/settings/bandwidth")
    assert get_res.status_code == 200
    data = get_res.json()
    assert "max_upload_mbps" in data
    assert "retention_hours" in data

    post_res = client.post("/api/v1/settings/bandwidth", json={
        "max_upload_mbps": 4.5,
        "retention_hours": 48,
        "asymmetrical_sync": True
    })
    assert post_res.status_code == 200
    updated = post_res.json()["config"]
    assert updated["max_upload_mbps"] == 4.5
    assert updated["retention_hours"] == 48


def test_forensic_search_endpoint():
    """Verifies that the GET /api/v1/forensics/search endpoint supports multi-criteria queries."""
    from fastapi.testclient import TestClient

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        td = Path(tmpdir)
        db_path = td / "forensics_test.db"
        db = EventDatabase(db_path)
        settings = EdgeSettings(site_id="site_search_hub")
        init_api(db, settings)

        # Seed events
        events_data = [
            ("ev_search_1", "cam_vault", "2026-09-12T10:00:00Z", "person", 0.95, 90, "red", "restricted_vault", "Intruder detected in vault"),
            ("ev_search_2", "cam_corridor", "2026-09-12T11:00:00Z", "vehicle", 0.88, 40, "blue", "main_corridor", "Vehicle passing corridor"),
            ("ev_search_3", "cam_counter", "2026-09-12T12:00:00Z", "person", 0.91, 75, "black", "cash_counter", "Cash counter breach alert")
        ]

        for gid, cid, st, obj, conf, sc, col, zn, desc in events_data:
            db.execute_sync(
                """
                INSERT INTO events (
                    event_group_id, camera_id, start_time, object_type, confidence, score,
                    status, starred, synced, user_triage, file_path, thumb_path, dominant_color, zone_name
                ) VALUES (?, ?, ?, ?, ?, ?, 'raw', 0, 0, 'unreviewed', '', '', ?, ?)
                """,
                (gid, cid, st, obj, conf, sc, col, zn)
            )

        client = TestClient(app)

        # 1. Filter by object_type = 'person'
        res = client.get("/api/v1/forensics/search?object_type=person")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 2
        ids = [r["event_group_id"] for r in data["results"]]
        assert "ev_search_1" in ids
        assert "ev_search_3" in ids

        # 2. Filter by color = 'red'
        res = client.get("/api/v1/forensics/search?color=red")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert data["results"][0]["event_group_id"] == "ev_search_1"

        # 3. Filter by min_score = 80
        res = client.get("/api/v1/forensics/search?min_score=80")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert data["results"][0]["event_group_id"] == "ev_search_1"

        # 4. Free-text search q = 'counter'
        res = client.get("/api/v1/forensics/search?q=counter")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert data["results"][0]["event_group_id"] == "ev_search_3"

        # 5. Temporal range filter
        res = client.get("/api/v1/forensics/search?date_from=2026-09-12T10:30:00Z")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 2
        ids = [r["event_group_id"] for r in data["results"]]
        assert "ev_search_2" in ids
        assert "ev_search_3" in ids

        db.close()

