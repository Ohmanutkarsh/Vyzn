"""
Tests for SQLite WAL database and multi-threaded concurrency safety.
"""

import time
import threading
from pathlib import Path
from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord


def test_database_crud_operations(tmp_path: Path):
    db_file = tmp_path / "test_index.db"
    db = EventDatabase(db_file)

    event = EventRecord(
        event_group_id="ev_test_001",
        camera_id="cam_01",
        start_time="2026-09-09T12:00:00Z",
        end_time="2026-09-09T12:00:10Z",
        object_type="person",
        confidence=0.88,
        score=82,
        status="raw",
        file_path="/tmp/clip.mp4",
        thumb_path="/tmp/thumb.jpg"
    )

    db.insert_event(event)
    time.sleep(0.3)  # Allow worker to drain queue

    # Query event
    retrieved = db.get_event("ev_test_001")
    assert retrieved is not None
    assert retrieved.event_group_id == "ev_test_001"
    assert retrieved.score == 82
    assert retrieved.object_type == "person"

    # Update status
    db.update_event_status("ev_test_001", "compressed")
    time.sleep(0.3)

    updated = db.get_event("ev_test_001")
    assert updated is not None
    assert updated.status == "compressed"

    db.close()


def test_concurrent_multi_thread_writes(tmp_path: Path):
    """Stress test: 5 concurrent capture threads enqueueing 30 records each to verify serialized FIFO queue write absorption without database lock errors."""
    db_file = tmp_path / "concurrent_index.db"

    db = EventDatabase(db_file)

    num_threads = 5
    records_per_thread = 30
    errors = []

    def worker_func(thread_idx: int):
        try:
            for r_idx in range(records_per_thread):
                ev = EventRecord(
                    event_group_id=f"ev_t{thread_idx}_r{r_idx}",
                    camera_id=f"cam_{thread_idx}",
                    start_time="2026-09-09T12:00:00Z",
                    object_type="person",
                    confidence=0.9,
                    score=75,
                    file_path=f"/tmp/clip_{thread_idx}_{r_idx}.mp4",
                    thumb_path=f"/tmp/thumb_{thread_idx}_{r_idx}.jpg"
                )
                db.insert_event(ev)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker_func, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0

    # Give queue a moment to drain completely
    time.sleep(1.0)

    events = db.query_events(limit=500)
    assert len(events) == num_threads * records_per_thread

    db.close()


def test_db_write_guard_rejects_pre_2020_timestamps(tmp_path: Path):
    """Verifies that events with timestamps prior to 2020 (such as 1970 epoch bugs) are rejected by DB write guard."""
    db_file = tmp_path / "guard_test_index.db"
    db = EventDatabase(db_file)

    # 1. Event with 1970 timestamp
    invalid_event = EventRecord(
        event_group_id="ev_bug_1970",
        camera_id="cam_webcam_0",
        start_time="1970-01-01T22:20:21.631756+00:00",
        end_time="1970-01-01T22:22:09.132884+00:00",
        object_type="person",
        confidence=0.88,
        score=100,
        status="raw",
        file_path="/tmp/clip_1970.mp4",
        thumb_path="/tmp/thumb_1970.jpg"
    )

    result = db.insert_event(invalid_event)
    assert result is False, "Database write guard must reject events before year 2020"

    time.sleep(0.2)
    queried = db.get_event("ev_bug_1970")
    assert queried is None, "Rejected event must not exist in database"

    # 2. Event with valid current timestamp
    valid_event = EventRecord(
        event_group_id="ev_valid_2026",
        camera_id="cam_webcam_0",
        start_time="2026-09-30T10:00:00Z",
        end_time="2026-09-30T10:00:20Z",
        object_type="person",
        confidence=0.88,
        score=85,
        status="raw",
        file_path="/tmp/clip_valid.mp4",
        thumb_path="/tmp/thumb_valid.jpg"
    )

    db.insert_event(valid_event)
    time.sleep(0.3)
    valid_queried = db.get_event("ev_valid_2026")
    assert valid_queried is not None, "Valid event must be written successfully"
    assert valid_queried.event_group_id == "ev_valid_2026"

    db.close()

