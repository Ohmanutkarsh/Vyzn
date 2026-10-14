"""
Tests for:
1. Purging all clips via EventDatabase.purge_all_clips and POST /api/clips/purge-all
2. Subfolder separation in storage: clips/ and full_footage/
3. Continuous whole footage writing via ClipWriter.write_continuous_footage_chunk
4. Folder browser endpoint POST /api/settings/browse-folder
"""

import os
import shutil
import tempfile
import numpy as np
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord
from vyzn.recording.clip_writer import ClipWriter
from vyzn.api.routes import app


@pytest.fixture
def temp_storage_env():
    tmp_dir = tempfile.mkdtemp(prefix="vyzn_storage_test_")
    db_path = Path(tmp_dir) / "index.db"
    db = EventDatabase(db_path)
    yield Path(tmp_dir), db
    db.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_purge_all_clips_and_disk_files(temp_storage_env):
    tmp_path, db = temp_storage_env
    writer = ClipWriter(data_root=tmp_path)

    # Create dummy frames and write a clip
    frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(8)]
    res = writer.write_clip_from_frames(
        camera_id="cam_test_purge",
        event_group_id="ev_purge_01",
        frames=frames,
        fps=4.0
    )
    assert Path(res.clip_path).exists()
    assert "clips" in res.clip_path

    # Insert into database
    ev = EventRecord(
        event_group_id="ev_purge_01",
        camera_id="cam_test_purge",
        start_time="2026-10-14T10:00:00Z",
        end_time="2026-10-14T10:00:02Z",
        score=75,
        object_type="person",
        file_path=res.clip_path,
        thumb_path=res.thumb_path,
        clip_number=1
    )
    db.insert_event(ev)
    db.flush()

    assert db.query_clips()["total"] == 1

    # Execute purge_all_clips
    count = db.purge_all_clips()
    assert count == 1
    assert db.query_clips()["total"] == 0
    assert not Path(res.clip_path).exists()


def test_storage_subfolders_separation(temp_storage_env):
    tmp_path, db = temp_storage_env
    writer = ClipWriter(data_root=tmp_path)

    # 1. Incident clip goes to clips/
    frames = [np.zeros((64, 64, 3), dtype=np.uint8) for _ in range(6)]
    clip_res = writer.write_clip_from_frames(
        camera_id="cam_cam1",
        event_group_id="ev_incident_123",
        frames=frames,
        fps=4.0
    )
    assert "clips" in clip_res.clip_path
    assert Path(clip_res.clip_path).exists()

    # 2. Continuous whole footage goes to full_footage/
    footage_path = writer.write_continuous_footage_chunk(
        camera_id="cam_cam1",
        frames=frames,
        fps=4.0,
        start_time_str="20261014_120000"
    )
    assert footage_path is not None
    assert "full_footage" in footage_path
    assert Path(footage_path).exists()

    # Verify both distinct subfolders exist inside user storage directory
    assert (tmp_path / "clips").is_dir()
    assert (tmp_path / "full_footage").is_dir()


def test_purge_all_endpoint_api(temp_storage_env):
    tmp_path, db = temp_storage_env
    from vyzn.api.routes import init_api
    from vyzn.core.config import EdgeSettings
    settings = EdgeSettings(site_id="test_site", data_dir=tmp_path, db_path=tmp_path / "index.db")
    init_api(db, settings)

    client = TestClient(app)
    # Purge with valid PIN
    resp = client.post("/api/clips/purge-all", headers={"X-Security-Pin": "202600"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "purged_count" in data


def test_browse_folder_endpoint(monkeypatch):
    import subprocess
    # Mock subprocess.run so GUI dialog doesn't block headless tests
    class MockProcess:
        stdout = "C:\\VyznStorage\\CustomFootage\n"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: MockProcess())

    client = TestClient(app)
    resp = client.post("/api/settings/browse-folder")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["selected_path"] == "C:\\VyznStorage\\CustomFootage"
