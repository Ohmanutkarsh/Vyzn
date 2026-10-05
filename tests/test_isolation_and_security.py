"""
Unit and integration tests for multi-tenant isolation, 6-digit security gates,
clip deletion, watch areas, and settings management.
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from vyzn.api.routes import app
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings, CameraConfig, WatchAreaConfig

client = TestClient(app)

def test_multi_tenant_isolation_and_security_gate():
    # 1. Setup isolated database and test users
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_events.db")
        db = EventDatabase(db_path=db_path)

        user_a = db.get_or_create_user("alice@shop.com")
        user_b = db.get_or_create_user("bob@retail.com")

        sess_a = db.create_session(user_a["id"])
        sess_b = db.create_session(user_b["id"])

        # Initialize global API state for testing
        from vyzn.api import routes
        from pathlib import Path
        test_settings = EdgeSettings(data_dir=Path(tmp_dir), db_path=Path(db_path))
        routes.init_api(db=db, settings=test_settings)

        try:
            # 2. Test Security Gate for Add Camera
            # Without PIN -> 403
            resp = client.post("/api/cameras", json={
                "name": "Alice Front Cam",
                "rtsp_url": "0",
                "target_fps": 4.0
            }, cookies={"vyzn_session": sess_a})
            assert resp.status_code == 403, f"Expected 403 without PIN, got {resp.status_code}"

            # With wrong PIN -> 403
            resp = client.post("/api/cameras", json={
                "name": "Alice Front Cam",
                "rtsp_url": "0",
                "target_fps": 4.0
            }, headers={"X-Security-Pin": "999999"}, cookies={"vyzn_session": sess_a})
            assert resp.status_code == 403

            # With valid PIN -> 200 OK
            resp = client.post("/api/cameras", json={
                "name": "Alice Front Cam",
                "rtsp_url": "0",
                "target_fps": 4.0
            }, headers={"X-Security-Pin": "202600"}, cookies={"vyzn_session": sess_a})
            assert resp.status_code == 200, f"Expected 200 with PIN, got {resp.text}"
            cam_a_id = resp.json()["id"]

            # User B adds Camera B
            resp = client.post("/api/cameras", json={
                "name": "Bob Store Cam",
                "rtsp_url": "1",
                "target_fps": 4.0
            }, headers={"X-Security-Pin": "202600"}, cookies={"vyzn_session": sess_b})
            assert resp.status_code == 200
            cam_b_id = resp.json()["id"]

            # 3. Test Isolation on GET /api/cameras
            # Alice queries cameras -> MUST ONLY see Alice Front Cam
            resp_a = client.get("/api/cameras", cookies={"vyzn_session": sess_a})
            assert resp_a.status_code == 200
            cams_a = [c["id"] for c in resp_a.json()]
            assert cam_a_id in cams_a
            assert cam_b_id not in cams_a, "Alice must not see Bob's camera!"

            # Bob queries cameras -> MUST ONLY see Bob Store Cam
            resp_b = client.get("/api/cameras", cookies={"vyzn_session": sess_b})
            assert resp_b.status_code == 200
            cams_b = [c["id"] for c in resp_b.json()]
            assert cam_b_id in cams_b
            assert cam_a_id not in cams_b, "Bob must not see Alice's camera!"

            # 4. Test Watch Areas retrieval
            resp = client.get(f"/api/cameras/{cam_a_id}/areas")
            assert resp.status_code == 200
            areas_data = resp.json()
            assert "areas" in areas_data

            # 5. Test Settings Profile & Phone Update
            resp = client.get("/api/settings/profile", cookies={"vyzn_session": sess_a})
            assert resp.status_code == 200
            prof = resp.json()
            assert prof["email"] == "alice@shop.com"

            # Update phone
            resp = client.post("/api/settings/phone", json={"phone": "9876543210"}, cookies={"vyzn_session": sess_a})
            assert resp.status_code == 200
            assert resp.json()["phone_e164"] == "+919876543210"

            # Update security PIN
            resp = client.post("/api/settings/security-pin", json={
                "current_pin": "202600",
                "new_pin": "654321"
            }, cookies={"vyzn_session": sess_a})
            assert resp.status_code == 200

            # Delete Camera A without PIN -> 403
            resp = client.delete(f"/api/cameras/{cam_a_id}", cookies={"vyzn_session": sess_a})
            assert resp.status_code == 403

            # Delete Camera A with updated PIN -> 200
            resp = client.delete(f"/api/cameras/{cam_a_id}", headers={"X-Security-Pin": "654321"}, cookies={"vyzn_session": sess_a})
            assert resp.status_code == 200

            # 6. Test Clip Insertion & Deletion with Security PIN Gate
            clip_event_id = "ev_test_sec_01"
            dummy_file = os.path.join(tmp_dir, "test_clip.mp4")
            with open(dummy_file, "w") as f:
                f.write("dummy video data")

            from vyzn.core.events import EventRecord
            ev = EventRecord(
                event_group_id=clip_event_id,
                camera_id=cam_b_id,
                start_time="2026-10-05T12:00:00Z",
                end_time="2026-10-05T12:00:15Z",
                score=85,
                object_type="person",
                tier="alert",
                clip_number=101,
                file_path=dummy_file,
                owner_email="bob@retail.com"
            )
            db.insert_event(ev)
            db.flush()

            # Alice queries flags -> cannot see Bob's clip
            resp = client.get("/api/clips/flags", cookies={"vyzn_session": sess_a})
            assert resp.status_code == 200
            assert len(resp.json()["flags"]) == 0

            # Bob queries flags -> can see Bob's clip
            resp = client.get("/api/clips/flags", cookies={"vyzn_session": sess_b})
            assert resp.status_code == 200
            assert len(resp.json()["flags"]) == 1

            # Delete clip without PIN -> 403
            resp = client.delete(f"/api/clips/{clip_event_id}", cookies={"vyzn_session": sess_b})
            assert resp.status_code == 403

            # Delete clip with valid PIN -> 200
            resp = client.delete(f"/api/clips/{clip_event_id}", headers={"X-Security-Pin": "202600"}, cookies={"vyzn_session": sess_b})
            assert resp.status_code == 200
            assert not os.path.exists(dummy_file), "Physical file should be deleted from disk!"

            # Clip should now be gone from DB
            assert db.get_clip_by_id(clip_event_id) is None

        finally:
            db.close()

if __name__ == "__main__":
    test_multi_tenant_isolation_and_security_gate()
    print("ALL TESTS PASSED SUCCESSFULLY!")
