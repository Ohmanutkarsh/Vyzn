import os
import sys
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings, CameraConfig
from vyzn.core.events import EventRecord


def test_triage_and_metrics_endpoints():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = EventDatabase(db_path)
        settings = EdgeSettings(
            site_id="test_site",
            site_name="Test Kirana",
            cameras=[CameraConfig(camera_id="cam_test", name="Test Cam", rtsp_url="mock")]
        )
        init_api(db=db, settings=settings)
        client = TestClient(app)

        # 1. Insert an event
        ev = EventRecord(
            event_group_id="ev_triage_101",
            camera_id="cam_test",
            start_time="2026-09-11T12:00:00Z",
            object_type="person",
            confidence=0.9,
            score=85
        )
        db.insert_event(ev)
        import time
        time.sleep(0.3)

        # 2. Test Triage endpoint
        t_res = client.post("/api/events/ev_triage_101/triage", json={"triage": "false_positive"})
        assert t_res.status_code == 200
        assert t_res.json()["triage"] == "false_positive"

        # 3. Test System Metrics endpoint
        m_res = client.get("/api/system/metrics")
        assert m_res.status_code == 200
        m_data = m_res.json()
        assert "cpu_percent" in m_data
        assert "ram_used_mb" in m_data
        assert "triage_stats" in m_data
        assert m_data["triage_stats"]["false_positive"] == 1

        # 4. Test DPDP Notice endpoint
        n_res = client.get("/api/dpdp/notice")
        assert n_res.status_code == 200
        assert "DPDP ACT 2023 COMPLIANT" in n_res.text

        # 5. Test Dual Zone Creation (Privacy Mask)
        pz_res = client.post(
            "/api/cameras/cam_test/zones",
            json={
                "name": "privacy_front_street",
                "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]],
                "zone_type": "privacy_mask"
            }
        )
        assert pz_res.status_code == 200
        assert pz_res.json()["zone_type"] == "privacy_mask"

        # Verify retrieved zones separates restricted vs privacy
        gz_res = client.get("/api/cameras/cam_test/zones")
        assert gz_res.status_code == 200
        gz_data = gz_res.json()
        assert any(z.get("zone_type") == "privacy_mask" and z["name"] == "privacy_front_street" for z in gz_data)

        db.close()



if __name__ == "__main__":
    test_triage_and_metrics_endpoints()
    print("Triage and Metrics API tests passed!")
