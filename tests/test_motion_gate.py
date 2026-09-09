"""
Tests for downscaled MOG2 motion pre-filtering.
"""

import numpy as np
import cv2
from vyzn.motion.mog2_gate import MOG2MotionGate


def test_mog2_static_vs_motion():
    gate = MOG2MotionGate(history=50, var_threshold=16.0, min_motion_ratio=0.01)
    cam_id = "cam_test"

    # Static background: 100 identical frames to train MOG2
    static_frame = np.full((360, 640, 3), 128, dtype=np.uint8)
    for _ in range(30):
        has_motion, ratio, _ = gate.process_frame(cam_id, static_frame)

    # Frame 31: Still static -> should have near-zero motion
    has_motion, ratio, _ = gate.process_frame(cam_id, static_frame)
    assert has_motion is False
    assert ratio < 0.01

    # Frame 32: Introduce large moving rectangle (e.g. 100x100 pixels = ~4% of 360x640)
    motion_frame = static_frame.copy()
    cv2.rectangle(motion_frame, (100, 100), (250, 250), (255, 255, 255), -1)

    has_motion, ratio, mask = gate.process_frame(cam_id, motion_frame)
    assert has_motion is True
    assert ratio >= 0.01
    assert cv2.countNonZero(mask) > 1000
