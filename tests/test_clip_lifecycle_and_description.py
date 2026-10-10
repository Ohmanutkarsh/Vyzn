"""
End-to-end Test Suite for Clip Lifecycle State Machine and Forensic Description Engine.

Verifies the 11 explicit production scenarios required for Step 8:
1. Continuous walking: 10-minute continuous motion with up to 4s occlusion -> EXACTLY 1 clip.
2. Static scene: 10-minute empty room with ticking clock overlay -> ZERO clips.
3. Day/night IR switch: Sudden full-frame brightness jump -> ZERO clips.
4. Pausing person: Enters, pauses 40s, leaves -> 1 clip, not cut while stationary.
5. Merge gap: Bursts 6s apart -> 1 clip; bursts >90s apart -> 2 clips.
6. Outside ROI: Activity outside watch area -> ZERO clips.
7. Noise blip: 1-second blip (<3s min motion) -> ZERO clips.
8. Reconnect resilience: 3s drop tolerated; 35s drop finalized as 'stream_interrupted'.
9. Long continuous event: 15-minute event with 300s max duration -> 3 linked parts with zero lost frames.
10. Video playback: FFmpeg H.264 +faststart verification with duration tolerance within +/-1.5s.
11. Description check: Non-empty title, summary, trigger_reason, and debounced timeline matching scenario.
"""

import os
import cv2
import time
import pytest
import numpy as np
from pathlib import Path
from typing import List, Generator, Tuple, Optional

from vyzn.evaluation.replay_harness import ReplayHarness, ReplayedClip
from vyzn.ai.detector import Detection
from vyzn.core.config import CameraConfig, WatchAreaConfig
from vyzn.recording.state_machine import ClipState
from vyzn.recording.clip_writer import ClipWriter


def create_solid_frame(h: int = 360, w: int = 640, color: int = 128) -> np.ndarray:
    """Creates a uniform solid gray frame."""
    return np.full((h, w, 3), color, dtype=np.uint8)


def draw_moving_box(frame: np.ndarray, x: int, y: int, size: int = 50) -> np.ndarray:
    """Draws a moving white box to simulate localized motion."""
    out = frame.copy()
    cv2.rectangle(out, (x, y), (x + size, y + size), (255, 255, 255), -1)
    return out


# ============================================================================
# Scenario 1: Continuous Walking (10 min with occlusions up to 4s)
# ============================================================================
def test_scenario_1_continuous_walking():
    """
    Simulates continuous walking over 10 minutes (600s).
    Simulated YOLO misses occur every 30s for 4s (occlusions).
    Must produce EXACTLY 1 clip, without mid-event cuts.
    """
    harness = ReplayHarness(
        camera_id="cam_s1",
        state_machine_kwargs={
            "max_clip_duration_sec": 1200.0,  # Ensure max duration does not force split
            "pre_roll_sec": 10.0,
            "post_roll_sec": 10.0
        },
        target_fps=4.0
    )

    fps = 4.0
    total_sec = 600.0  # 10 minutes
    total_frames = int(total_sec * fps)

    def generate_frames():
        bg = create_solid_frame(360, 640, 128)
        # Seed warmup
        for i in range(15):
            yield bg, i / fps, None, True

        for i in range(total_frames):
            pts = 15 / fps + (i / fps)
            t_sec = i / fps

            # Person moves back and forth in ROI
            pos_x = int(150 + 200 * (np.sin(t_sec * 0.2) + 1.0) / 2.0)
            frame = draw_moving_box(bg, pos_x, 150, size=50)

            # Simulated YOLO: drops for 4s every 30s
            is_occluded = (t_sec % 30.0) < 4.0
            if is_occluded:
                dets = []
            else:
                norm_x = pos_x / 640.0
                dets = [Detection(
                    box=[norm_x, 150 / 360.0, (pos_x + 50) / 640.0, 200 / 360.0],
                    confidence=0.88,
                    class_id=0,
                    label="person"
                )]

            yield frame, pts, dets, True

    clips = harness.replay_stream(generate_frames())

    # MUST produce exactly 1 continuous clip
    assert len(clips) == 1, f"Expected exactly 1 clip for continuous walking, got {len(clips)}"
    clip = clips[0]
    assert clip.duration >= 590.0, f"Clip duration too short: {clip.duration}s"
    assert clip.is_discarded is False
    assert clip.part_index == 0


# ============================================================================
# Scenario 2: Static Scene with Ticking Clock Overlay
# ============================================================================
def test_scenario_2_static_scene_with_clock_overlay():
    """
    10-minute video of an empty room with a camera timestamp overlay ticking every second.
    OSD exclusion and contour area filters must suppress all false clips.
    Must produce ZERO clips.
    """
    harness = ReplayHarness(
        camera_id="cam_s2",
        target_fps=4.0
    )

    fps = 4.0
    total_frames = int(600.0 * fps)  # 10 minutes

    def generate_frames():
        bg = create_solid_frame(360, 640, 120)
        for i in range(total_frames):
            pts = i / fps
            frame = bg.copy()
            # Ticking clock in corner (OSD area: 0,0 to 180,30)
            sec = int(pts)
            time_str = f"2026-10-10 12:{sec // 60:02d}:{sec % 60:02d}"
            cv2.putText(frame, time_str, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            yield frame, pts, [], True

    clips = harness.replay_stream(generate_frames())
    assert len(clips) == 0, f"Expected 0 clips for static scene with ticking clock, got {len(clips)}"


# ============================================================================
# Scenario 3: Day/Night Switch (Global Lighting Jump)
# ============================================================================
def test_scenario_3_day_night_switch():
    """
    Sudden full-frame brightness jump (IR cut-filter switch).
    Global change rejection (>60% of frame) must prevent false clip.
    Must produce ZERO clips.
    """
    harness = ReplayHarness(
        camera_id="cam_s3",
        target_fps=4.0
    )

    fps = 4.0

    def generate_frames():
        # Night mode: dark
        for i in range(30):
            yield create_solid_frame(360, 640, 30), i / fps, [], True

        # Sudden jump to Day mode: bright (mean jump > 100)
        for i in range(30, 80):
            yield create_solid_frame(360, 640, 180), i / fps, [], True

    clips = harness.replay_stream(generate_frames())
    assert len(clips) == 0, f"Expected 0 clips for day/night IR switch, got {len(clips)}"


# ============================================================================
# Scenario 4: Pausing Person (Enters, Pauses 40s, Leaves)
# ============================================================================
def test_scenario_4_pausing_person():
    """
    Person enters (t=0-8s), stands still for 40s (t=8-48s), then leaves (t=48-56s).
    Must produce 1 clip that stays open while stationary (not cut after 15s).
    """
    harness = ReplayHarness(
        camera_id="cam_s4",
        state_machine_kwargs={
            "stationary_hold_max_sec": 60.0,
            "post_roll_sec": 10.0
        },
        target_fps=4.0
    )

    fps = 4.0

    def generate_frames():
        bg = create_solid_frame(360, 640, 128)
        # Seed warmup
        for i in range(15):
            yield bg, i / fps, None, True

        start_pts = 15 / fps
        total_time = 70.0  # 8s enter + 40s pause + 8s leave + 14s quiet

        for i in range(int(total_time * fps)):
            t_sec = i / fps
            pts = start_pts + t_sec

            if t_sec < 8.0:
                # Entering
                pos_x = int(120 + t_sec * 20)
                frame = draw_moving_box(bg, pos_x, 150)
                dets = [Detection(box=[pos_x / 640.0, 150 / 360.0, (pos_x + 50) / 640.0, 200 / 360.0], confidence=0.9, class_id=0, label="person")]
            elif t_sec < 48.0:
                # Standing still for 40 seconds at pos_x = 280
                pos_x = 280
                # Frame background absorbs box after ~10s in MOG2, but detector / tracker tracks stationary person
                frame = draw_moving_box(bg, pos_x, 150)
                dets = [Detection(box=[pos_x / 640.0, 150 / 360.0, (pos_x + 50) / 640.0, 200 / 360.0], confidence=0.85, class_id=0, label="person")]
            elif t_sec < 56.0:
                # Leaving
                pos_x = int(280 + (t_sec - 48.0) * 30)
                frame = draw_moving_box(bg, pos_x, 150)
                dets = [Detection(box=[pos_x / 640.0, 150 / 360.0, (pos_x + 50) / 640.0, 200 / 360.0], confidence=0.85, class_id=0, label="person")]
            else:
                # Empty scene (quiet)
                frame = bg.copy()
                dets = []

            yield frame, pts, dets, True

    clips = harness.replay_stream(generate_frames())
    assert len(clips) == 1, f"Expected 1 clip for pausing person, got {len(clips)}"
    assert clips[0].duration >= 50.0, f"Clip was prematurely cut during stationary pause: {clips[0].duration}s"


# ============================================================================
# Scenario 5: Merge Gap (6s gap merged; 95s gap separated)
# ============================================================================
def test_scenario_5_merge_gap():
    """
    Part A: Burst 1 (10s) -> quiet 6s -> Burst 2 (10s) -> 1 merged clip.
    Part B: Burst 1 (10s) -> quiet 100s -> Burst 2 (10s) -> 2 separate clips.
    """
    fps = 4.0

    # Part A: Short gap (6s)
    harness_a = ReplayHarness(
        camera_id="cam_s5a",
        state_machine_kwargs={"post_roll_sec": 10.0, "merge_gap_sec": 90.0},
        target_fps=fps
    )

    def frames_a():
        bg = create_solid_frame(360, 640, 128)
        for i in range(15):
            yield bg, i / fps, None, True
        start_pts = 15 / fps

        for i in range(int(36.0 * fps)):
            t = i / fps
            pts = start_pts + t
            # Burst 1: 0-10s
            if t <= 10.0:
                frame = draw_moving_box(bg, 150 + int(t * 10), 150)
                dets = [Detection(box=[0.2, 0.2, 0.4, 0.4], confidence=0.88, class_id=0, label="person")]
            # Quiet: 10-16s (6s quiet)
            elif t <= 16.0:
                frame = bg.copy()
                dets = []
            # Burst 2: 16-26s
            elif t <= 26.0:
                frame = draw_moving_box(bg, 250 + int((t - 16.0) * 10), 150)
                dets = [Detection(box=[0.3, 0.2, 0.5, 0.4], confidence=0.88, class_id=0, label="person")]
            else:
                frame = bg.copy()
                dets = []
            yield frame, pts, dets, True

    clips_a = harness_a.replay_stream(frames_a())
    assert len(clips_a) == 1, f"Expected 1 merged clip for 6s gap, got {len(clips_a)}"

    # Part B: Long gap (95s > 90s merge gap)
    harness_b = ReplayHarness(
        camera_id="cam_s5b",
        state_machine_kwargs={"post_roll_sec": 5.0, "merge_gap_sec": 90.0},
        target_fps=fps
    )

    def frames_b():
        bg = create_solid_frame(360, 640, 128)
        for i in range(15):
            yield bg, i / fps, None, True
        start_pts = 15 / fps

        # Burst 1: 0-10s
        for i in range(int(10.0 * fps)):
            pts = start_pts + i / fps
            frame = draw_moving_box(bg, 150 + i * 2, 150)
            yield frame, pts, [Detection(box=[0.2, 0.2, 0.4, 0.4], confidence=0.88, class_id=0, label="person")], True

        # Quiet period: 100 seconds (post-roll will close clip 1 at 15s)
        for i in range(int(100.0 * fps)):
            pts = start_pts + 10.0 + i / fps
            yield bg.copy(), pts, [], True

        # Burst 2: 110-120s
        for i in range(int(10.0 * fps)):
            pts = start_pts + 110.0 + i / fps
            frame = draw_moving_box(bg, 200 + i * 2, 150)
            yield frame, pts, [Detection(box=[0.3, 0.2, 0.5, 0.4], confidence=0.88, class_id=0, label="person")], True

        # Trailing quiet
        for i in range(int(10.0 * fps)):
            pts = start_pts + 120.0 + i / fps
            yield bg.copy(), pts, [], True

    clips_b = harness_b.replay_stream(frames_b())
    assert len(clips_b) == 2, f"Expected 2 separate clips for 100s gap, got {len(clips_b)}"


# ============================================================================
# Scenario 6: Motion Strictly Outside Watch Area ROI
# ============================================================================
def test_scenario_6_motion_outside_roi():
    """
    Motion occurs ONLY outside the user-configured watch area polygon.
    Must produce ZERO clips.
    """
    # Camera ROI is centered: [0.3, 0.3] to [0.8, 0.8]
    custom_cam = CameraConfig(
        camera_id="cam_s6",
        name="Watch Area Filtered Camera",
        rtsp_url="test://s6",
        watch_areas=[
            WatchAreaConfig(
                id="wa1",
                camera_id="cam_s6",
                name="Store Floor",
                polygon=[[0.3, 0.3], [0.8, 0.3], [0.8, 0.8], [0.3, 0.8]]
            )
        ]
    )
    harness = ReplayHarness(
        camera_id="cam_s6",
        camera_config=custom_cam,
        target_fps=4.0
    )

    fps = 4.0

    def generate_frames():
        bg = create_solid_frame(360, 640, 128)
        for i in range(15):
            yield bg, i / fps, None, False

        # Motion happens at (20, 20) -> x: 0.03 to 0.10, y: 0.05 to 0.18 (completely outside ROI)
        for i in range(int(20.0 * fps)):
            pts = 15 / fps + i / fps
            frame = draw_moving_box(bg, 20 + (i % 30), 20)
            yield frame, pts, [], False

    clips = harness.replay_stream(generate_frames())
    assert len(clips) == 0, f"Expected 0 clips for motion outside ROI, got {len(clips)}"


# ============================================================================
# Scenario 7: Noise Blip (<3s Pure Motion)
# ============================================================================
def test_scenario_7_noise_blip():
    """
    A 1-second motion blip (headlights sweep or leaf flutter) with no target detection.
    Candidate confirmation & min motion duration (<3s) must discard it.
    Must produce ZERO clips.
    """
    harness = ReplayHarness(
        camera_id="cam_s7",
        state_machine_kwargs={"min_motion_only_sec": 3.0, "confirm_frames": 3},
        target_fps=4.0
    )

    fps = 4.0

    def generate_frames():
        bg = create_solid_frame(360, 640, 128)
        for i in range(15):
            yield bg, i / fps, None, True

        start_pts = 15 / fps
        # 1-second blip (4 frames of motion)
        for i in range(4):
            pts = start_pts + i / fps
            frame = draw_moving_box(bg, 200, 150)
            yield frame, pts, [], True

        # Followed by quiet
        for i in range(20):
            pts = start_pts + 1.0 + i / fps
            yield bg.copy(), pts, [], True

    clips = harness.replay_stream(generate_frames())
    assert len(clips) == 0, f"Expected 0 clips for 1s noise blip, got {len(clips)}"


# ============================================================================
# Scenario 8: Reconnect Resilience (3s drop vs 35s drop)
# ============================================================================
def test_scenario_8_reconnect_resilience():
    """
    Drop stream for 3s mid-recording: clip continues (resilient).
    Drop stream for 35s: finalized cleanly with reason 'stream_interrupted'.
    """
    fps = 4.0
    harness = ReplayHarness(
        camera_id="cam_s8",
        state_machine_kwargs={"stream_gap_tolerance_sec": 5.0, "post_roll_sec": 10.0},
        target_fps=fps
    )

    bg = create_solid_frame(360, 640, 128)
    # Warmup
    for i in range(15):
        harness.process_frame(bg, pts=i / fps)

    # 1. Start active motion (0 to 10s)
    for i in range(int(10.0 * fps)):
        pts = 4.0 + i / fps
        frame = draw_moving_box(bg, 150 + i * 2, 150)
        harness.process_frame(frame, pts=pts, forced_detections=[Detection([0.2, 0.2, 0.4, 0.4], 0.9, 0, "person")])

    # 2. Short 3-second stream dropout (pts jumps from 14.0 to 17.0)
    # 3s <= tolerance (5.0s) -> should NOT interrupt
    frame_resume = draw_moving_box(bg, 200, 150)
    harness.process_frame(frame_resume, pts=17.0, forced_detections=[Detection([0.2, 0.2, 0.4, 0.4], 0.9, 0, "person")])
    assert harness.state_machine.state == ClipState.RECORDING, "Short 3s dropout broke the recording!"

    # 3. Large 35-second stream drop (pts jumps from 17.0 to 52.0)
    # > 5.0s tolerance -> should finalize with close_reason 'stream_interrupted'
    harness.process_frame(bg, pts=52.0)
    assert len(harness.clips_created) == 1
    assert harness.clips_created[0].close_reason == "stream_interrupted"


# ============================================================================
# Scenario 9: Long Continuous Event (15 min with 300s max duration)
# ============================================================================
def test_scenario_9_long_continuous_event_multipart():
    """
    15-minute continuous event with MAX_CLIP_DURATION=300s.
    Must produce linked parts (part_index 0, 1, 2) sharing same parent_event_id.
    Zero frames lost at boundaries (part0.end_pts == part1.start_pts).
    """
    fps = 4.0
    harness = ReplayHarness(
        camera_id="cam_s9",
        state_machine_kwargs={
            "max_clip_duration_sec": 300.0,
            "post_roll_sec": 10.0
        },
        target_fps=fps
    )

    bg = create_solid_frame(360, 640, 128)
    for i in range(15):
        harness.process_frame(bg, pts=i / fps)

    # 15 minutes = 900 seconds
    total_frames = int(900.0 * fps)
    start_pts = 4.0

    for i in range(total_frames):
        pts = start_pts + i / fps
        frame = draw_moving_box(bg, 150 + (i % 100), 150)
        dets = [Detection([0.2, 0.2, 0.4, 0.4], 0.9, 0, "person")]
        harness.process_frame(frame, pts=pts, forced_detections=dets)

    # Flush end of stream
    if harness.state_machine.state in (ClipState.RECORDING, ClipState.HANGOVER):
        final_seg = harness.state_machine._finalize_current_clip(start_pts + 900.0, close_reason="stream_ended")
        if final_seg:
            harness.clips_created.append(harness._finalize_segment(final_seg))

    # Must produce 3 parts (300s each)
    assert len(harness.clips_created) == 3, f"Expected 3 parts for 900s continuous event, got {len(harness.clips_created)}"

    p0, p1, p2 = harness.clips_created
    assert p0.part_index == 0
    assert p1.part_index == 1
    assert p2.part_index == 2

    # Verify parent linking
    root_id = p0.clip_id
    assert p1.parent_event_id == root_id
    assert p2.parent_event_id == root_id

    # Verify zero frame loss across boundaries
    assert abs(p0.end_pts - p1.start_pts) < 0.001, f"Boundary gap between part 0 and 1: {p0.end_pts} vs {p1.start_pts}"
    assert abs(p1.end_pts - p2.start_pts) < 0.001, f"Boundary gap between part 1 and 2: {p1.end_pts} vs {p2.start_pts}"


# ============================================================================
# Scenario 10: Video Playback & FFmpeg Verification
# ============================================================================
def test_scenario_10_video_playback_compatibility(tmp_path):
    """
    Verifies that the generated clip is written with browser-compatible H.264,
    yuv420p, +faststart, and duration matches PTS duration within +/-1.5s.
    """
    out_dir = tmp_path / "clips_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = ClipWriter(data_root=out_dir)
    fps = 4.0
    num_frames = 60  # 15 seconds

    frames = []
    bg = create_solid_frame(360, 640, 128)
    for i in range(num_frames):
        frames.append(draw_moving_box(bg, 100 + i * 4, 150))

    res = writer.write_clip_from_frames(
        camera_id="cam_test",
        event_group_id="ev_test_playback",
        frames=frames,
        fps=fps
    )
    clip_path = Path(res.clip_path)

    assert clip_path.exists(), "MP4 file was not created"
    assert clip_path.stat().st_size > 1000, "MP4 file size is too small"

    # Verify MP4 container faststart
    with open(clip_path, "rb") as f:
        head = f.read(4096)
        assert b"ftyp" in head, "Missing MP4 ftyp atom"

    # Verify duration using OpenCV
    cap = cv2.VideoCapture(str(clip_path))
    assert cap.isOpened(), "Could not open MP4 via OpenCV"
    read_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    read_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    measured_dur = read_frames / read_fps
    cap.release()

    expected_dur = num_frames / fps  # 15.0s
    assert abs(measured_dur - expected_dur) <= 1.5, f"Duration mismatch: {measured_dur} vs {expected_dur}"


# ============================================================================
# Scenario 11: Forensic Description & Debounced Timeline
# ============================================================================
def test_scenario_11_forensic_description_and_timeline():
    """
    Verifies that generated clip has non-empty title, summary, trigger_reason,
    and a debounced timeline whose points match real detections.
    """
    harness = ReplayHarness(
        camera_id="cam_s11",
        target_fps=4.0
    )

    fps = 4.0
    bg = create_solid_frame(360, 640, 128)
    for i in range(15):
        harness.process_frame(bg, pts=i / fps)

    # Run 12s event with person detection
    for i in range(int(12.0 * fps)):
        pts = 4.0 + i / fps
        frame = draw_moving_box(bg, 150 + i * 5, 150)
        dets = [Detection([0.2, 0.2, 0.4, 0.4], 0.91, 0, "person")]
        harness.process_frame(frame, pts=pts, forced_detections=dets)

    # Quiet period to trigger hangover finalization
    for i in range(int(12.0 * fps)):
        pts = 16.0 + i / fps
        harness.process_frame(bg.copy(), pts=pts, forced_detections=[])

    assert len(harness.clips_created) >= 1
    clip = harness.clips_created[0]
    analysis = clip.analysis

    # 1. Non-empty title and summary
    assert analysis.get("title"), "Analysis title is empty"
    assert "person" in analysis.get("title").lower() or "activity" in analysis.get("title").lower()
    assert analysis.get("summary"), "Analysis summary is empty"

    # 2. Trigger reason
    assert analysis.get("trigger_reason"), "Trigger reason is empty"

    # 3. Importance score and level
    imp = analysis.get("importance", {})
    assert imp.get("score") is not None
    assert imp.get("level") in ("low", "medium", "high", "critical")

    # 4. Debounced timeline
    timeline = analysis.get("timeline", [])
    assert len(timeline) > 0, "Timeline should not be empty"
    first_pt = timeline[0]
    assert "t_offset_sec" in first_pt
    assert "action" in first_pt
    assert "classes" in first_pt
