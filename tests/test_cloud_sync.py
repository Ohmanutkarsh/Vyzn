"""
Tests for Cloudflare R2 / S3 Object Storage Synchronization Worker.
"""

import time
from pathlib import Path
from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord
from vyzn.storage.cloud_sync import CloudSyncWorker


def test_cloud_sync_worker_marks_synced(tmp_path: Path):
    db_file = tmp_path / "sync_test.db"
    db = EventDatabase(db_file)

    # Create dummy video and thumbnail files
    clip_file = tmp_path / "test_clip.mp4"
    clip_file.write_bytes(b"dummy_mp4_bytes")
    thumb_file = tmp_path / "test_thumb.jpg"
    thumb_file.write_bytes(b"dummy_jpg_bytes")

    # Insert un-synced high-confidence event (score: 85 >= 70)
    event = EventRecord(
        event_group_id="ev_sync_001",
        camera_id="cam_corridor",
        start_time="2026-09-10T10:00:00Z",
        object_type="person",
        confidence=0.89,
        score=85,
        status="raw",
        synced=0,
        file_path=str(clip_file),
        thumb_path=str(thumb_file)
    )
    db.insert_event(event)
    time.sleep(0.3)

    # Verify event initially has synced = 0
    ev_before = db.get_event("ev_sync_001")
    assert ev_before is not None
    assert ev_before.synced == 0

    # Run one sync sweep
    worker = CloudSyncWorker(db=db, min_score=70)
    worker.sync_pending_events()
    time.sleep(0.3)

    # Verify event is updated to synced = 1
    ev_after = db.get_event("ev_sync_001")
    assert ev_after is not None
    assert ev_after.synced == 1

    db.close()
