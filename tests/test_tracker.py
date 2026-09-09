"""
Tests for lightweight pure NumPy IoU Tracker and occlusion coasting.
"""

from vyzn.ai.tracker import IOUTracker, calculate_iou
from vyzn.ai.detector import Detection


def test_iou_calculation():
    box1 = [0.0, 0.0, 1.0, 1.0]
    box2 = [0.5, 0.0, 1.5, 1.0]
    # Intersection: [0.5, 0.0, 1.0, 1.0] = 0.5 * 1.0 = 0.5
    # Union: 1.0 + 1.0 - 0.5 = 1.5
    # IoU = 0.5 / 1.5 = 0.3333...
    iou = calculate_iou(box1, box2)
    assert abs(iou - (1.0 / 3.0)) < 1e-4

    # Disjoint boxes
    box3 = [2.0, 2.0, 3.0, 3.0]
    assert calculate_iou(box1, box3) == 0.0


def test_tracker_continuity_and_coasting():
    tracker = IOUTracker(iou_threshold=0.3, max_missed_frames=10)

    # Frame 1: Detection appears
    d1 = [Detection(box=[0.1, 0.1, 0.3, 0.5], confidence=0.9, class_id=0, label="person")]
    tracks = tracker.update(d1, timestamp=100.0)
    assert len(tracks) == 1
    tid = tracks[0].track_id

    # Frame 2: Detection moves slightly (matched to same track)
    d2 = [Detection(box=[0.12, 0.1, 0.32, 0.5], confidence=0.9, class_id=0, label="person")]
    tracks = tracker.update(d2, timestamp=100.5)
    assert len(tracks) == 1
    assert tracks[0].track_id == tid
    assert tracks[0].frames_seen == 2
    assert tracks[0].duration_sec == 0.5

    # Frames 3-7: Object occluded behind shelf (no detections)
    for t_step in range(1, 6):
        active_tracks = tracker.update([], timestamp=100.5 + t_step * 0.2)
        assert len(active_tracks) == 0  # Not active in this frame
        assert tid in tracker.tracks    # But held in coasting memory
        assert tracker.tracks[tid].missed_frames == t_step

    # Frame 8: Object reappears slightly displaced (coasting match!)
    d3 = [Detection(box=[0.14, 0.1, 0.34, 0.5], confidence=0.88, class_id=0, label="person")]
    tracks = tracker.update(d3, timestamp=102.0)
    assert len(tracks) == 1
    assert tracks[0].track_id == tid    # ID preserved! No ID churn!
    assert tracks[0].missed_frames == 0
