"""
Tests for FastAPI REST endpoints and Web Dashboard serving.
"""

from pathlib import Path
from starlette.testclient import TestClient
from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings
from vyzn.core.events import EventRecord


def test_api_endpoints_and_dashboard_serving(tmp_path: Path):
    db_file = tmp_path / "api_test.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_api_test",
        data_dir=tmp_path,
        db_path=db_file
    )

    # Insert a sample event
    sample_event = EventRecord(
        event_group_id="ev_api_01",
        camera_id="cam_corridor",
        start_time="2026-09-09T14:00:00Z",
        object_type="person",
        confidence=0.92,
        score=85,
        status="raw",
        file_path=str(tmp_path / "clip.mp4"),
        thumb_path=str(tmp_path / "thumb.jpg")
    )
    db.insert_event(sample_event)

    init_api(db, settings)
    client = TestClient(app)

    # 1. Test Status
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["site_id"] == "site_api_test"

    # 2. Test Events Retrieval
    res = client.get("/api/events")
    assert res.status_code == 200
    events = res.json()
    assert len(events) >= 1
    assert events[0]["event_group_id"] == "ev_api_01"
    assert events[0]["score"] == 85

    # 3. Test Storage Statistics
    res = client.get("/api/storage")
    assert res.status_code == 200
    storage = res.json()
    assert "disk_free_pct" in storage
    assert storage["raw_events_count"] >= 1

    # 4. Test Star Action
    res = client.post("/api/events/ev_api_01/star")
    assert res.status_code == 200
    assert res.json()["starred"] == 1

    # 5. Test Dashboard Serving
    res = client.get("/")
    assert res.status_code == 200
    assert "VYZN Surveillance Console" in res.text

    db.close()
