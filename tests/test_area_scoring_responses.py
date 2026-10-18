"""
Automated tests for Area-Based Risk Scoring:
1. Person in Alert Area:
   - Score increases a bit (+18 to +23 in L6, +8 confirmation boost, floor elevated to 70 after hours / 55 daytime)
   - Tier = 'alert', should_alert = True
2. Person in Review Area:
   - Score evaluated according to standard rules (+7 in L6)
   - Tier = 'review' (30-65), should_alert = False
3. Person in Ignore Area:
   - Score reduced significantly (-40 penalty, clamped strictly <= 15)
   - Tier = 'low', should_alert = False
   - State machine tick score clamped <= 15, no recording triggered
"""

import pytest
from vyzn.core.events import DetectionCandidate
from vyzn.scoring.engine import ScoringEngine
from vyzn.recording.state_machine import ClipStateMachine


def test_area_scoring_responses():
    engine = ScoringEngine()

    # 1. Person in Alert Area (Daytime)
    cand_alert_day = DetectionCandidate(
        camera_id='cam1',
        object_type='person',
        confidence=0.85,
        motion_ratio=0.03,
        track_duration_sec=4.0,
        bounding_box=[0.2, 0.2, 0.4, 0.8],
        is_after_hours=False,
        area_response='alert',
        is_in_alert_area=True
    )
    cand_alert_day.track_hits = 6
    cand_alert_day.c_mean = 0.85

    # 2. Person in Alert Area (After Hours)
    cand_alert_night = DetectionCandidate(
        camera_id='cam1',
        object_type='person',
        confidence=0.85,
        motion_ratio=0.03,
        track_duration_sec=4.0,
        bounding_box=[0.2, 0.2, 0.4, 0.8],
        is_after_hours=True,
        area_response='alert',
        is_in_alert_area=True
    )
    cand_alert_night.track_hits = 6
    cand_alert_night.c_mean = 0.85

    # 3. Person in Review Area (Daytime)
    cand_review = DetectionCandidate(
        camera_id='cam1',
        object_type='person',
        confidence=0.85,
        motion_ratio=0.03,
        track_duration_sec=4.0,
        bounding_box=[0.2, 0.2, 0.4, 0.8],
        is_after_hours=False,
        area_response='review',
        is_in_review_area=True
    )
    cand_review.track_hits = 6
    cand_review.c_mean = 0.85

    # 4. Person in Ignore Area (Daytime)
    cand_ignore = DetectionCandidate(
        camera_id='cam1',
        object_type='person',
        confidence=0.85,
        motion_ratio=0.03,
        track_duration_sec=4.0,
        bounding_box=[0.2, 0.2, 0.4, 0.8],
        is_after_hours=False,
        area_response='ignore',
        is_in_ignore_area=True
    )
    cand_ignore.track_hits = 6
    cand_ignore.c_mean = 0.85

    s_alert_day, a_alert_day, bd_alert_day = engine.evaluate(cand_alert_day)
    s_alert_night, a_alert_night, bd_alert_night = engine.evaluate(cand_alert_night)
    s_review, a_review, bd_review = engine.evaluate(cand_review)
    s_ignore, a_ignore, bd_ignore = engine.evaluate(cand_ignore)

    # Assert Alert Area behavior: score increases, tier is alert
    assert s_alert_day > s_review, f"Alert day score ({s_alert_day}) must be > review score ({s_review})"
    assert s_alert_night >= 70, f"Alert night score ({s_alert_night}) must be >= 70"
    assert a_alert_night is True, "Alert night must trigger alert"
    assert bd_alert_day["is_in_alert_area"] is True
    assert bd_alert_day["area_response"] == "alert"

    # Assert Review Area behavior: score is according (standard review range), tier is review
    assert 30 <= s_review < s_alert_day
    assert bd_review["tier"] == "review"
    assert a_review is False
    assert bd_review["is_in_review_area"] is True
    assert bd_review["area_response"] == "review"

    # Assert Ignore Area behavior: score reduced significantly (<= 15), tier is low, alert suppressed
    assert s_ignore <= 15
    assert bd_ignore["tier"] == "low"
    assert a_ignore is False
    assert bd_ignore["is_in_ignore_area"] is True
    assert bd_ignore["area_response"] == "ignore"

    # Assert State Machine with Ignore Area
    sm = ClipStateMachine(camera_id="cam1")
    sm.step(
        pts=1.0,
        frame_ref="dummy_frame",
        motion_score=0.04,
        detections=[cand_ignore],
        tracks=[],
        in_roi=True,
        live_score_breakdown=bd_ignore
    )
    tick = sm._flush_current_tick()
    assert tick is not None
    assert tick.score <= 15
