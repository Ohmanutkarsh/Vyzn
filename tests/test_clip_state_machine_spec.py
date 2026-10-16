"""
Synthetic tick timeline test suite verifying VYZN Clip State Machine specification:
(a) one burst
(b) two bursts 40s apart -> one clip
(c) two bursts 100s apart -> two clips
(d) exactly 90s quiet -> clip stays open, 93s -> closes
(e) pre/post-roll >= 10s
(f) a single low tick inside a burst -> no split
"""

import pytest
import numpy as np
from vyzn.recording.state_machine import ClipStateMachine, ClipState, TickResult, FrameMetadata


def create_tick(start_pts: float, end_pts: float, score: int, primary_obj: str = "person") -> TickResult:
    """Creates a synthetic 3-second tick with video time PTS."""
    frames = []
    metas = []
    for i in range(12):  # 4 fps across 3 seconds
        f_pts = start_pts + i * 0.25
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        meta = FrameMetadata(
            pts=f_pts,
            motion_score=0.08 if score >= 30 else 0.001,
            detections=[],
            active_tracks=[],
            has_motion=score >= 30,
            has_detection=score >= 30,
            has_track=score >= 30,
            is_activity=score >= 30,
            frame_ref=frame
        )
        frames.append(frame)
        metas.append(meta)

    return TickResult(
        tick_start_pts=start_pts,
        tick_end_pts=end_pts,
        score=score,
        score_raw=float(score),
        primary_object=primary_obj,
        max_confidence=0.88 if score >= 30 else 0.0,
        peak_frame=frames[0],
        peak_pts=start_pts + 1.0,
        frames=frames,
        frame_metas=metas,
        score_breakdown={"final_score": score, "s_live": score}
    )


def test_spec_a_one_burst():
    """(a) One burst: produces exactly 1 clip."""
    sm = ClipStateMachine(camera_id="cam_test_a")
    produced_clips = []

    # Pre-feed some rolling buffer frames before event
    for t in range(0, 30, 3):
        low_tick = create_tick(float(t), float(t + 3), score=10)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)

    assert sm.state == ClipState.IDLE
    assert len(produced_clips) == 0

    # Active burst: 4 ticks (PTS 30 to 42), scores >= 30
    pts = 30.0
    for score in [55, 75, 80, 60]:
        tick = create_tick(pts, pts + 3.0, score=score)
        res = sm.process_tick(tick)
        if res:
            produced_clips.append(res)
        assert sm.state == ClipState.ACTIVE
        pts += 3.0

    # Quiet period > 90s (31 low ticks of 3s = 93s)
    # last_active_window_end is 42.0. Quiet duration will exceed 90s when tick_end_pts > 42.0 + 90.0 = 132.0
    while pts <= 140.0:
        low_tick = create_tick(pts, pts + 3.0, score=15)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    assert len(produced_clips) == 1
    clip = produced_clips[0]
    assert clip.highest_score == 80
    assert clip.is_alert is True
    assert sm.state == ClipState.IDLE


def test_spec_b_two_bursts_40s_apart_one_clip():
    """(b) Two bursts 40s apart -> one single merged clip."""
    sm = ClipStateMachine(camera_id="cam_test_b")
    produced_clips = []

    # First burst: PTS 0 to 9 (scores 60)
    pts = 0.0
    for _ in range(3):
        tick = create_tick(pts, pts + 3.0, score=60)
        res = sm.process_tick(tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    assert sm.state == ClipState.ACTIVE
    # last_active_window_end is 9.0

    # 40s quiet gap: from PTS 9.0 to 48.0 (13 ticks of 3s = 39s)
    while pts < 48.0:
        low_tick = create_tick(pts, pts + 3.0, score=12)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)
        pts += 3.0
        # Clip must remain ACTIVE because quiet_duration (39s) <= 90s
        assert sm.state == ClipState.ACTIVE
        assert len(produced_clips) == 0

    # Second burst: PTS 48.0 to 60.0 (scores 70)
    for _ in range(4):
        tick = create_tick(pts, pts + 3.0, score=70)
        res = sm.process_tick(tick)
        if res:
            produced_clips.append(res)
        pts += 3.0
        assert sm.state == ClipState.ACTIVE

    # Now quiet period > 90s until close
    # last_active_window_end is 60.0. Closes when tick_end_pts > 60 + 90 = 150.0
    while pts <= 160.0:
        low_tick = create_tick(pts, pts + 3.0, score=10)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    assert len(produced_clips) == 1
    assert produced_clips[0].highest_score == 70
    assert sm.state == ClipState.IDLE


def test_spec_c_two_bursts_100s_apart_two_clips():
    """(c) Two bursts 100s apart -> two separate clips."""
    sm = ClipStateMachine(camera_id="cam_test_c")
    produced_clips = []

    # First burst: PTS 0 to 9.0
    pts = 0.0
    for _ in range(3):
        tick = create_tick(pts, pts + 3.0, score=50)
        res = sm.process_tick(tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    # 100s gap: ticks stay < 30
    # At PTS 102.0 (quiet duration = 102 - 9 = 93s > 90s), clip 1 must close
    while pts < 110.0:
        low_tick = create_tick(pts, pts + 3.0, score=10)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    assert len(produced_clips) == 1
    assert sm.state == ClipState.IDLE

    # Advance to PTS 120 (more than 100s after first burst end)
    while pts < 120.0:
        low_tick = create_tick(pts, pts + 3.0, score=10)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    # Second burst: PTS 120 to 132 (scores 65)
    for _ in range(4):
        tick = create_tick(pts, pts + 3.0, score=65)
        res = sm.process_tick(tick)
        if res:
            produced_clips.append(res)
        pts += 3.0
        assert sm.state == ClipState.ACTIVE

    # Close second clip with > 90s quiet
    while pts <= 230.0:
        low_tick = create_tick(pts, pts + 3.0, score=10)
        res = sm.process_tick(low_tick)
        if res:
            produced_clips.append(res)
        pts += 3.0

    assert len(produced_clips) == 2
    assert produced_clips[0].highest_score == 50
    assert produced_clips[1].highest_score == 65
    assert sm.state == ClipState.IDLE


def test_spec_d_exactly_90s_quiet_stays_open_93s_closes():
    """(d) Exactly 90s quiet -> clip stays open, 93s -> closes."""
    sm = ClipStateMachine(camera_id="cam_test_d")

    # Burst ends at PTS 6.0
    sm.process_tick(create_tick(0.0, 3.0, score=50))
    sm.process_tick(create_tick(3.0, 6.0, score=50))
    assert sm.state == ClipState.ACTIVE
    assert sm.last_active_window_end == 6.0

    # Feed 29 quiet ticks (PTS 6.0 to 93.0 -> quiet_duration = 87.0s)
    pts = 6.0
    for _ in range(29):
        res = sm.process_tick(create_tick(pts, pts + 3.0, score=10))
        assert res is None
        assert sm.state == ClipState.ACTIVE
        pts += 3.0

    # 30th quiet tick: PTS 93.0 to 96.0 -> quiet_duration = 96.0 - 6.0 = 90.0s EXACTLY!
    res_90 = sm.process_tick(create_tick(pts, pts + 3.0, score=10))
    pts += 3.0
    # At exactly 90.0s quiet, condition is quiet_duration > 90.0, so clip MUST STAY OPEN!
    assert res_90 is None
    assert sm.state == ClipState.ACTIVE
    assert sm.quiet_duration == 90.0

    # 31st quiet tick: PTS 96.0 to 99.0 -> quiet_duration = 99.0 - 6.0 = 93.0s!
    res_93 = sm.process_tick(create_tick(pts, pts + 3.0, score=10))
    # At 93.0s (> 90.0s), clip MUST CLOSE!
    assert res_93 is not None
    assert sm.state == ClipState.IDLE
    assert res_93.close_reason == "quiet_gap_exceeded"


def test_spec_e_pre_post_roll_at_least_10s():
    """(e) Pre-roll and post-roll are strictly >= 10s."""
    sm = ClipStateMachine(camera_id="cam_test_e")

    # Event burst from PTS 40.0 to 52.0
    # First active tick: PTS 40.0 to 43.0
    tick1 = create_tick(40.0, 43.0, score=50)
    sm.process_tick(tick1)
    assert sm.state == ClipState.ACTIVE

    first_active_start = sm.first_active_window_start
    assert first_active_start == 40.0

    # Pre-roll check: clip_start_pts <= first_active_start - 10.0
    pre_roll = first_active_start - sm.clip_start_pts
    assert pre_roll >= 10.0, f"Pre-roll was {pre_roll}s, expected >= 10s"

    # Continuation of burst to PTS 52.0
    sm.process_tick(create_tick(43.0, 46.0, score=55))
    sm.process_tick(create_tick(46.0, 49.0, score=60))
    sm.process_tick(create_tick(49.0, 52.0, score=50))
    last_active_end = sm.last_active_window_end
    assert last_active_end == 52.0

    # Feed quiet ticks until close
    pts = 52.0
    closed_segment = None
    while pts <= 160.0:
        res = sm.process_tick(create_tick(pts, pts + 3.0, score=10))
        if res:
            closed_segment = res
            break
        pts += 3.0

    assert closed_segment is not None
    # Post-roll check: end_pts - last_active_end >= 10.0
    post_roll = closed_segment.end_pts - last_active_end
    assert post_roll >= 10.0, f"Post-roll was {post_roll}s, expected >= 10s"


def test_spec_f_single_low_tick_inside_burst_no_split():
    """(f) A single low tick inside a burst -> no split."""
    sm = ClipStateMachine(camera_id="cam_test_f")
    produced_clips = []

    pts = 0.0
    # Burst 1: PTS 0 to 9 (scores 60)
    for _ in range(3):
        res = sm.process_tick(create_tick(pts, pts + 3.0, score=60))
        if res:
            produced_clips.append(res)
        pts += 3.0

    assert sm.state == ClipState.ACTIVE

    # Single low tick inside burst: PTS 9 to 12 (score 15 < 30)
    res_low = sm.process_tick(create_tick(pts, pts + 3.0, score=15))
    pts += 3.0
    assert res_low is None
    assert sm.state == ClipState.ACTIVE  # No split!

    # Burst resumes: PTS 12 to 24 (scores 65)
    for _ in range(4):
        res = sm.process_tick(create_tick(pts, pts + 3.0, score=65))
        if res:
            produced_clips.append(res)
        pts += 3.0
        assert sm.state == ClipState.ACTIVE

    # Feed quiet ticks to close
    while pts <= 130.0:
        res = sm.process_tick(create_tick(pts, pts + 3.0, score=10))
        if res:
            produced_clips.append(res)
        pts += 3.0

    # Exactly one clip produced, no split
    assert len(produced_clips) == 1
    assert produced_clips[0].highest_score == 65
    assert sm.state == ClipState.IDLE
