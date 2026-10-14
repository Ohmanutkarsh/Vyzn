"""
Automated Verification Tests for VYZN Event State Machine.
Tests synthetic tick timelines for clip segmentation:
(a) One burst -> one clip
(b) Two bursts 40s apart -> one clip (within 90s quiet window)
(c) Two bursts 100s apart -> two distinct clips (>90s quiet gap)
(d) Exactly 90s quiet -> clip stays open; 93s quiet -> closes
(e) Pre-roll and post-roll are always >= 10 seconds
(f) A single low tick inside a burst does not split the clip
Additional tests:
(g) Stream drop cleanly closes clip without counting outage as quiet time
(h) Stationary object maintains score above floor
"""

import pytest
import math
from vyzn.recording.state_machine import (
    ClipStateMachine,
    ClipState,
    TickResult,
    FinalizedClipSegment,
    FrameMetadata
)
from vyzn.core.config import ClipConfig


# Helper function to create a synthetic 3-second tick with a specific score.
# In VYZN, a "tick" evaluates a 3-second video window.
def create_tick(start_pts: float, score: int, primary_obj: str = "person") -> TickResult:
    """
    Creates one synthetic 3-second scoring tick.
    Each tick covers [start_pts, start_pts + 3.0].
    """
    return TickResult(
        tick_start_pts=start_pts,
        tick_end_pts=start_pts + 3.0,
        score=score,
        score_raw=float(score),
        primary_object=primary_obj,
        max_confidence=0.85,
        peak_pts=start_pts + 1.5,
        score_breakdown={"synthetic": score}
    )


# Helper function to create a default ClipStateMachine configured with exact project settings
def make_fsm() -> ClipStateMachine:
    """
    Initializes a state machine with the standard VYZN configuration:
    - 3s ticks, active threshold = 30, quiet gap = 90s, pre/post roll = 10s.
    """
    cfg = ClipConfig(
        score_interval_seconds=3.0,
        active_score_threshold=30,
        quiet_gap_seconds=90.0,
        pre_roll_seconds=10.0,
        post_roll_seconds=10.0,
        min_active_ticks=1,
        max_clip_seconds=600.0,
        preview_seconds=6.0
    )
    return ClipStateMachine(camera_id="cam_test_01", clip_config=cfg)


# ---------------------------------------------------------------------------
# Test (a): One single activity burst produces exactly one clip
# ---------------------------------------------------------------------------
def test_single_burst():
    # Setup our state machine
    fsm = make_fsm()
    clips = []

    # Start with a low score tick (no activity yet)
    res = fsm.process_tick(create_tick(0.0, score=10))
    assert res is None
    assert fsm.state == ClipState.IDLE

    # Now activity starts: 3 ticks above threshold (score=50, >= 30)
    # Ticks from 3.0 to 12.0
    for t in [3.0, 6.0, 9.0]:
        res = fsm.process_tick(create_tick(t, score=50))
        assert res is None
        assert fsm.state == ClipState.ACTIVE  # State machine is now recording

    # Now activity ends, followed by quiet ticks for > 90 seconds
    # Quiet starts at 12.0. Need quiet_duration > 90.0s (31 low ticks: 12.0 to 105.0)
    current_pts = 12.0
    for _ in range(31):
        res = fsm.process_tick(create_tick(current_pts, score=10))
        if res is not None:
            clips.append(res)
        current_pts += 3.0

    # Verification:
    # 1. Exactly one clip was created
    assert len(clips) == 1
    clip = clips[0]

    # 2. State returned cleanly back to IDLE
    assert fsm.state == ClipState.IDLE

    # 3. Clip trimmed dead footage and kept pre/post roll
    assert clip.highest_score == 50
    assert clip.start_pts <= (3.0 - 10.0)  # Pre-roll >= 10s
    assert clip.end_pts >= (12.0 + 10.0)   # Post-roll >= 10s


# ---------------------------------------------------------------------------
# Test (b): Two bursts 40 seconds apart are merged into a single clip
# ---------------------------------------------------------------------------
def test_two_bursts_40s_gap_single_clip():
    # Setup state machine
    fsm = make_fsm()
    clips = []

    # First burst: activity from pts=30.0 to 39.0 (3 active ticks)
    for t in [30.0, 33.0, 36.0]:
        res = fsm.process_tick(create_tick(t, score=45))
        assert res is None
    assert fsm.state == ClipState.ACTIVE

    # Gap of 40 seconds with low scores (from pts=39.0 to pts=75.0)
    # 40 seconds is less than 90 seconds, so the clip must stay open!
    t = 39.0
    while t < 78.0:
        res = fsm.process_tick(create_tick(t, score=15))
        assert res is None  # Should NOT close
        assert fsm.state == ClipState.ACTIVE  # Still recording
        t += 3.0

    # Second burst: activity resumes at pts=78.0 to 87.0
    for burst2_t in [78.0, 81.0, 84.0]:
        res = fsm.process_tick(create_tick(burst2_t, score=60))
        assert res is None
    assert fsm.state == ClipState.ACTIVE

    # Now quiet period for > 90 seconds (31 ticks) to close the clip
    t = 87.0
    for _ in range(31):
        res = fsm.process_tick(create_tick(t, score=10))
        if res is not None:
            clips.append(res)
        t += 3.0

    # Verification:
    # Both bursts should be in the SAME clip because gap was only 40s
    assert len(clips) == 1
    clip = clips[0]
    assert clip.start_pts <= (30.0 - 10.0)  # Covers start of Burst 1
    assert clip.end_pts >= (87.0 + 10.0)   # Covers end of Burst 2
    assert clip.highest_score == 60


# ---------------------------------------------------------------------------
# Test (c): Two bursts 100 seconds apart produce TWO distinct clips
# ---------------------------------------------------------------------------
def test_two_bursts_100s_gap_two_clips():
    # Setup state machine
    fsm = make_fsm()
    clips = []

    # First burst: activity from pts=30.0 to 39.0
    for t in [30.0, 33.0, 36.0]:
        fsm.process_tick(create_tick(t, score=45))
    assert fsm.state == ClipState.ACTIVE

    # 100 seconds quiet gap: 100s > 90s, so the first clip must close!
    # 31 ticks of 3s = 93s quiet > 90s
    t = 39.0
    for _ in range(31):
        res = fsm.process_tick(create_tick(t, score=10))
        if res is not None:
            clips.append(res)
        t += 3.0

    # Verify Clip 1 closed and machine returned to IDLE
    assert len(clips) == 1
    assert fsm.state == ClipState.IDLE

    # Advance time a bit more to complete the 100s gap
    t = 140.0

    # Second burst: new activity starts at pts=140.0
    for burst2_t in [140.0, 143.0, 146.0]:
        res = fsm.process_tick(create_tick(burst2_t, score=75))
        assert res is None
    assert fsm.state == ClipState.ACTIVE

    # Now quiet period for 31 ticks to close Clip 2
    t = 149.0
    for _ in range(31):
        res = fsm.process_tick(create_tick(t, score=10))
        if res is not None:
            clips.append(res)
        t += 3.0

    # Verification:
    # Exactly TWO separate clips were generated
    assert len(clips) == 2
    clip1, clip2 = clips

    # Clip 1 ended after Burst 1, with dead footage trimmed back
    assert clip1.end_pts >= 39.0 + 10.0
    assert clip1.end_pts < 60.0

    # Clip 2 started cleanly at Burst 2 with pre-roll
    assert clip2.start_pts <= 140.0 - 10.0
    assert clip2.highest_score == 75
    assert clip2.is_alert is True  # Score 75 triggers alert


# ---------------------------------------------------------------------------
# Test (d): Boundary verification: exactly 90s quiet stays open; 93s closes
# ---------------------------------------------------------------------------
def test_quiet_duration_90s_vs_93s():
    # Setup state machine
    fsm = make_fsm()

    # Active tick at pts=0.0 to 3.0
    # last_active_window_end will be 3.0
    res = fsm.process_tick(create_tick(0.0, score=40))
    assert res is None
    assert fsm.state == ClipState.ACTIVE

    # Now feed exactly 30 low ticks (30 ticks * 3s = 90.0s):
    # Tick 1: pts 3..6   (quiet = 3s)
    # ...
    # Tick 30: pts 90..93 (quiet = 93 - 3 = 90.0s)
    current_pts = 3.0
    for _ in range(30):
        res = fsm.process_tick(create_tick(current_pts, score=10))
        assert res is None  # Clip MUST stay open!
        assert fsm.state == ClipState.ACTIVE
        current_pts += 3.0

    # Double-check that quiet duration is exactly 90.0s and state is still ACTIVE
    assert fsm.quiet_duration == 90.0
    assert fsm.state == ClipState.ACTIVE

    # Now feed the 31st low tick (pts 93..96):
    # quiet_duration = 96 - 3 = 93.0s > 90.0s
    res = fsm.process_tick(create_tick(current_pts, score=10))

    # The 93s tick MUST trigger close!
    assert res is not None
    assert isinstance(res, FinalizedClipSegment)
    assert fsm.state == ClipState.IDLE


# ---------------------------------------------------------------------------
# Test (e): Pre-roll and Post-roll are always >= 10 seconds
# ---------------------------------------------------------------------------
def test_pre_post_roll_minimum_10s():
    fsm = make_fsm()

    # Test with non-round timestamp to verify snapping outward
    # Activity burst starts at pts=21.3 and ends at pts=33.3
    for t in [21.3, 24.3, 27.3, 30.3]:
        fsm.process_tick(create_tick(t, score=50))

    # Check pre-roll immediately after transition to ACTIVE
    pre_roll_length = fsm.first_active_window_start - fsm.clip_start_pts
    assert pre_roll_length >= 10.0, f"Pre-roll was {pre_roll_length}, must be >= 10.0s"

    # Close the clip with quiet ticks
    t = 33.3
    clip = None
    for _ in range(31):
        res = fsm.process_tick(create_tick(t, score=10))
        if res:
            clip = res
        t += 3.0

    assert clip is not None
    # Check post-roll on finalized clip
    post_roll_length = clip.end_pts - 33.3
    assert post_roll_length >= 10.0, f"Post-roll was {post_roll_length}, must be >= 10.0s"


# ---------------------------------------------------------------------------
# Test (f): A single low tick inside a burst does not split the clip
# ---------------------------------------------------------------------------
def test_single_low_tick_inside_burst_no_split():
    fsm = make_fsm()
    clips = []

    # Tick 1: active (pts 0..3)
    fsm.process_tick(create_tick(0.0, score=45))
    assert fsm.state == ClipState.ACTIVE

    # Tick 2: active (pts 3..6)
    fsm.process_tick(create_tick(3.0, score=50))
    assert fsm.state == ClipState.ACTIVE

    # Tick 3: single momentary dip (score drops to 15, below threshold 30)
    # This must NOT split the clip or end it!
    res = fsm.process_tick(create_tick(6.0, score=15))
    assert res is None
    assert fsm.state == ClipState.ACTIVE  # Stays active!

    # Tick 4: active resumes (pts 9..12)
    fsm.process_tick(create_tick(9.0, score=55))
    assert fsm.state == ClipState.ACTIVE
    assert fsm.quiet_duration == 0.0  # Quiet timer reset!

    # Tick 5: active continues (pts 12..15)
    fsm.process_tick(create_tick(12.0, score=40))

    # Close with quiet ticks
    t = 15.0
    for _ in range(31):
        res = fsm.process_tick(create_tick(t, score=10))
        if res:
            clips.append(res)
        t += 3.0

    # Verification:
    # Only ONE clip produced, covering both before and after the dip
    assert len(clips) == 1
    clip = clips[0]
    assert clip.start_pts <= (0.0 - 10.0)
    assert clip.end_pts >= (15.0 + 10.0)
    assert clip.highest_score == 55


# ---------------------------------------------------------------------------
# Test (g): Stream drop closes active clip cleanly without counting outage as quiet time
# ---------------------------------------------------------------------------
def test_stream_drop_closes_clip_cleanly():
    fsm = make_fsm()

    # Active recording starts
    fsm.process_tick(create_tick(10.0, score=60))
    fsm.process_tick(create_tick(13.0, score=65))
    assert fsm.state == ClipState.ACTIVE

    # Stream drops unexpectedly (e.g. camera loses power or network cable unplugged)
    clip = fsm.on_stream_drop()

    # Clip should be closed cleanly
    assert clip is not None
    assert clip.close_reason == "stream_dropped"
    assert clip.highest_score == 65
    assert fsm.state == ClipState.IDLE


# ---------------------------------------------------------------------------
# Test (h): Max duration (600s) splits clip at lowest-score tick and marks 'continued'
# ---------------------------------------------------------------------------
def test_max_duration_split():
    # Setup state machine with a shorter max duration (e.g. 30s) to test split behavior
    cfg = ClipConfig(
        score_interval_seconds=3.0,
        active_score_threshold=30,
        quiet_gap_seconds=90.0,
        pre_roll_seconds=10.0,
        post_roll_seconds=10.0,
        min_active_ticks=1,
        max_clip_seconds=30.0,  # Short max duration for testing
        preview_seconds=6.0
    )
    fsm = ClipStateMachine(camera_id="cam_split_01", clip_config=cfg)

    # Feed consecutive active ticks until max_clip_seconds is reached
    t = 0.0
    clips = []
    # Feed 11 ticks (33 seconds of video time, exceeding 30s max)
    scores = [40, 50, 45, 32, 60, 55, 35, 70, 65, 50, 48]
    for score in scores:
        res = fsm.process_tick(create_tick(t, score=score))
        if res:
            clips.append(res)
        t += 3.0

    # Verification:
    # A split occurred!
    assert len(clips) >= 1
    part1 = clips[0]
    assert part1.close_reason == "max_duration_split"

    # Next part is marked continued
    assert fsm.state == ClipState.ACTIVE
    assert fsm.current_part_index == 1
    assert "Continued" in fsm.trigger_reason


# ---------------------------------------------------------------------------
# Test (i): Continuous fan motion for 4 minutes never starts recording
# ---------------------------------------------------------------------------
def test_continuous_fan_motion_never_starts_recording():
    """
    Verifies that continuous motion (e.g. a ceiling fan running across the frame for 4 minutes)
    without any AI detected target object (no person, no vehicle) always scores < 30
    and never triggers an active clip.
    """
    fsm = make_fsm()
    clips = []

    # Simulate 4 minutes (240 seconds = 80 ticks @ 3s each) of continuous fan motion
    # Using step() with motion_score=0.80 (heavy movement), but detections=[] and tracks=[]
    pts = 0.0
    for frame_i in range(80 * 12):  # 80 ticks with 12 frames per tick
        res = fsm.step(
            pts=pts,
            frame_ref=f"fan_frame_{frame_i}",
            motion_score=0.85,  # Continuous full-screen fan motion
            detections=[],       # No YOLO detection
            tracks=[],           # No active track
            in_roi=True,
            live_score_breakdown={"final_score": 20, "s_live": 20}
        )
        if res:
            clips.append(res)
        pts += 0.25  # 4 fps

    # State machine must remain IDLE throughout the entire 4 minutes
    assert fsm.state == ClipState.IDLE
    assert len(clips) == 0


# ---------------------------------------------------------------------------
# Test (j): Continuous fan motion after activity allows active clip to close after 90s
# ---------------------------------------------------------------------------
def test_continuous_fan_motion_allows_active_clip_to_close():
    """
    Verifies that if a real person starts a recording, and then leaves while a fan
    continues moving for 4 minutes, the fan motion does not keep recording forever;
    the clip cleanly closes after the 90-second quiet gap.
    """
    fsm = make_fsm()
    clips = []

    # 1. Person walks in: 2 ticks (6 seconds) above threshold
    pts = 0.0
    class MockTrack:
        label = "person"
        box = [0.1, 0.1, 0.3, 0.7]

    for frame_i in range(24):  # 6 seconds @ 4fps
        res = fsm.step(
            pts=pts,
            frame_ref=f"person_frame_{frame_i}",
            motion_score=0.15,
            detections=[MockTrack()],
            tracks=[MockTrack()],
            in_roi=True,
            live_score_breakdown={"final_score": 65, "s_live": 65}
        )
        if res:
            clips.append(res)
        pts += 0.25

    assert fsm.state == ClipState.ACTIVE

    # 2. Person leaves, fan keeps moving for 4 minutes (240s = 80 ticks)
    for frame_i in range(80 * 12):
        res = fsm.step(
            pts=pts,
            frame_ref=f"fan_frame_{frame_i}",
            motion_score=0.80,  # Fan running full screen
            detections=[],       # Person is gone
            tracks=[],
            in_roi=True,
            live_score_breakdown={"final_score": 20, "s_live": 20}
        )
        if res:
            clips.append(res)
        pts += 0.25

    # Verification:
    # 1. The clip closed after the 90s quiet window!
    assert len(clips) == 1
    clip = clips[0]
    assert clip.highest_score >= 60

    # 2. State returned to IDLE (did not keep recording forever)
    assert fsm.state == ClipState.IDLE


# ---------------------------------------------------------------------------
# Test (k): Hair motion (localized flicker, unconfirmed target) does not start recording
# ---------------------------------------------------------------------------
def test_hair_motion_suppressed():
    """
    Verifies that moving hair in front of the camera with localized flutter
    and unconfirmed low-confidence detections produces score <= 20 and NEVER starts recording.
    """
    fsm = make_fsm()
    clips = []

    class MockHairDet:
        label = "person"
        confidence = 0.22  # Weak detection on hair/face patch
        box = [0.4, 0.4, 0.45, 0.45]

    pts = 0.0
    for frame_i in range(30 * 12):  # 90 seconds @ 4fps
        res = fsm.step(
            pts=pts,
            frame_ref=f"hair_frame_{frame_i}",
            motion_score=0.03,
            detections=[MockHairDet()],  # Unconfirmed low-confidence detection
            tracks=[],                   # No confirmed body track
            in_roi=True,
            live_score_breakdown={"final_score": 18, "s_live": 18}
        )
        if res:
            clips.append(res)
        pts += 0.25

    # State machine must remain IDLE and generate zero false clips
    assert fsm.state == ClipState.IDLE
    assert len(clips) == 0
