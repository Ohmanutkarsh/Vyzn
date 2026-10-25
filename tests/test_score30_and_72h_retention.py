"""
Tests for:
1. Discarding any event/clip with threat score < 30 (no clip cut).
2. Lifelong retention for cut clips (score >= 30, expires_at_ms = None).
3. 72-hour continuous whole footage retention (StorageReaper purges full_footage older than 72h).
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest

from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord
from vyzn.recording.state_machine import ClipStateMachine, TickResult, FrameMetadata
from vyzn.storage.reaper import StorageReaperDaemon


@pytest.fixture
def temp_env():
    tmp_dir = tempfile.mkdtemp(prefix="vyzn_retention_test_")
    db_path = Path(tmp_dir) / "index.db"
    db = EventDatabase(db_path)
    yield Path(tmp_dir), db
    db.close()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_state_machine_discard_under_30(temp_env):
    tmp_path, db = temp_env
    sm = ClipStateMachine(camera_id="cam_test")
    dummy_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    now_pts = time.time()

    meta = FrameMetadata(
        pts=now_pts,
        motion_score=0.1,
        detections=[],
        active_tracks=[],
        has_motion=True,
        has_detection=False,
        has_track=False,
        is_activity=True
    )

    tick_low = TickResult(
        tick_start_pts=now_pts,
        tick_end_pts=now_pts + 3.0,
        score=25,
        score_raw=25.0,
        primary_object="person",
        max_confidence=0.5,
        peak_frame=dummy_frame,
        peak_pts=now_pts + 1.0,
        detections=[],
        tracks=[],
        events=[],
        frames=[dummy_frame],
        frame_metas=[meta],
        score_breakdown={"final_score": 25}
    )

    # Simulate active clip with score 25
    sm.clip_start_pts = now_pts - 10.0
    sm.highest_score = 25
    sm.last_active_window_end = now_pts + 3.0
    sm.first_active_window_start = now_pts
    sm.active_frames = [dummy_frame]
    sm.active_metas = [meta]
    sm.active_ticks = [tick_low]
    sm.primary_object = "person"

    seg_low = sm._close_active_clip(close_reason="test_close")
    assert seg_low is not None
    assert seg_low.is_discarded is True, "Score 25 must be discarded (score < 30)"

    # Simulate active clip with score 35
    sm.highest_score = 35
    sm.active_frames = [dummy_frame]
    sm.active_metas = [meta]
    sm.active_ticks = [tick_low]
    seg_high = sm._close_active_clip(close_reason="test_close")
    assert seg_high is not None
    assert seg_high.is_discarded is False, "Score 35 must NOT be discarded (score >= 30)"


def test_reaper_72h_full_footage_and_lifelong_clips(temp_env):
    tmp_path, db = temp_env

    # 1. Old continuous footage (> 72 hours ago)
    old_footage_dir = tmp_path / "full_footage" / "cam1" / "2026-10-20"
    old_footage_dir.mkdir(parents=True, exist_ok=True)
    old_file = old_footage_dir / "footage_20261020_000000.mp4"
    old_file.write_bytes(b"continuous_old_footage" * 100)
    past_ts = time.time() - (80 * 3600)
    os.utime(old_file, (past_ts, past_ts))

    # 2. Recent continuous footage (< 72 hours ago)
    recent_footage_dir = tmp_path / "full_footage" / "cam1" / "2026-10-25"
    recent_footage_dir.mkdir(parents=True, exist_ok=True)
    recent_file = recent_footage_dir / "footage_20261025_000000.mp4"
    recent_file.write_bytes(b"continuous_recent_footage" * 100)

    # 3. Cut clip with score 45 (lifelong retention: expires_at_ms = None)
    clip_dir = tmp_path / "clips" / "cam1" / "2026-10-20" / "ev_test_lifelong"
    clip_dir.mkdir(parents=True, exist_ok=True)
    clip_file = clip_dir / "clip.mp4"
    clip_file.write_bytes(b"cut_clip_video_data" * 100)
    os.utime(clip_file, (past_ts, past_ts))

    db.insert_event(EventRecord(
        event_group_id="ev_test_lifelong",
        camera_id="cam1",
        start_time="2026-10-20T10:00:00Z",
        score=45,
        tier="review",
        file_path=str(clip_file),
        thumb_path="",
        expires_at_ms=None
    ))
    db.flush()

    reaper = StorageReaperDaemon(db=db, data_root=tmp_path, raw_retention_hours=72)
    # Perform sweep
    reaper.perform_sweep()

    # Verify: Old continuous footage (>72h) was deleted
    assert not old_file.exists(), "Continuous footage older than 72 hours must be purged"
    # Verify: Recent continuous footage was kept
    assert recent_file.exists(), "Continuous footage under 72 hours must be kept"
    # Verify: Cut clip (score 45) was kept lifelong
    assert clip_file.exists(), "Cut clip must be kept lifelong and not purged by 72h routine"
    assert db.query_clips()["total"] == 1, "Database record for cut clip must remain intact"
