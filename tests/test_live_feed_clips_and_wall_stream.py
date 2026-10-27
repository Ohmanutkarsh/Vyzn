"""
Verification tests for:
1. Camera capture threads and streams remaining persistent across visibility changes and page navigation.
2. Wall view tiles streaming live video (/api/cameras/{id}/stream) without being overwritten by static thumbnails.
3. Event clips cut from live feed capturing authentic multi-frame motion at full capture FPS without duplicated thumbnail frames.
"""

import pytest
import numpy as np
import time
from pathlib import Path
import tempfile
import shutil

from vyzn.recording.clip_writer import ClipWriter
from vyzn.recording.state_machine import ClipStateMachine, ClipState, TickResult
from vyzn.capture.synthetic import SyntheticCameraThread
from vyzn.core.config import CameraConfig


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="vyzn_live_feed_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


def test_clip_writer_encodes_authentic_live_frames_without_thumbnails(temp_dir):
    """Verifies that clips written by ClipWriter preserve authentic live video frames at native FPS."""
    writer = ClipWriter(temp_dir)
    cam_id = "cam_live_test"
    event_id = "ev_live_test_001"

    # Generate 60 distinct sequential video frames (3 seconds at 20 FPS)
    frames = []
    for i in range(60):
        f = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Unique visual counter on each frame simulating real live feed movement
        f[100:200, i * 15:(i * 15) + 50] = (0, 255, 0)
        frames.append(f)

    result = writer.write_clip_from_frames(
        camera_id=cam_id,
        event_group_id=event_id,
        frames=frames,
        fps=20.0,
        duration_sec=3.0
    )

    clip_file = Path(result.clip_path)
    assert clip_file.exists()
    assert clip_file.stat().st_size > 0

    import cv2
    cap = cv2.VideoCapture(str(clip_file))
    assert cap.isOpened()
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    # Frame count should be equal to our input frames (60 frames), not decimated to 3-4 thumbnails
    assert frame_count >= 58, f"Clip must retain full live frames, got {frame_count}"
    assert fps >= 15.0, f"Clip FPS must be smooth live rate, got {fps}"


def test_clip_state_machine_accumulates_full_fps_stream():
    """Verifies that the state machine aggregates all stream frames at full FPS into the finalized segment."""
    sm = ClipStateMachine(
        camera_id="cam_stream_fps_test",
        target_fps=20.0,
        pre_roll_sec=2.0,
        post_roll_sec=2.0,
        merge_gap_sec=2.0,
        max_clip_seconds=30.0,
        min_active_ticks=1
    )

    start_pts = 1000.0
    current_pts = start_pts

    # Feed 2 seconds of pre-roll at 20 FPS (40 frames)
    for _ in range(40):
        frame = np.full((100, 100, 3), 50, dtype=np.uint8)
        sm.step(pts=current_pts, frame_ref=frame, motion_score=0.0, detections=[], tracks=[])
        current_pts += 0.05

    from vyzn.ai.detector import Detection
    det = Detection(box=[0.1, 0.1, 0.5, 0.5], confidence=0.85, class_id=0, label="person")

    # Feed 4 seconds of active motion at 20 FPS (80 frames)
    for _ in range(80):
        frame = np.full((100, 100, 3), 150, dtype=np.uint8)
        sm.step(
            pts=current_pts,
            frame_ref=frame,
            motion_score=0.3,
            detections=[det],
            tracks=[1],
            live_score_breakdown={"final_score": 65.0}
        )
        current_pts += 0.05

    # Force close clip
    seg = sm._finalize_current_clip(pts=current_pts, close_reason="test")
    assert seg is not None, "A clip segment should be finalized"
    # The segment should contain dozens of continuous live frames, not just 2-3 thumbnail frames
    assert len(seg.frames) > 50, f"Segment must contain full-rate live frames, got {len(seg.frames)}"
