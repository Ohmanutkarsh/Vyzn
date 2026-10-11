"""
Unit and Calibration Tests for VYZN Scoring System v2.0 (Step 8 Acceptance Suite).

Validates:
1. All 13 Calibration Scenarios (within tolerance +/- 5)
2. Monotonicity: higher confidence/dwell never lowers score unless penalty applies
3. Tier Boundaries: tested at 29, 30, 69, 70
4. Completeness: all layers 0-12 and levels 1-5 appear in every breakdown
5. Retention Job: low clip deleted at 72h, pinned/review/alert untouched, disk + DB removed
"""

import math
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from vyzn.core.events import DetectionCandidate, EventRecord
from vyzn.core.config import BusinessHours, ZonePolygon, get_scoring_config
from vyzn.scoring.engine import ScoringEngine, is_time_after_hours
from vyzn.storage.reaper import StorageReaperDaemon
from vyzn.core.database import EventDatabase


# -----------------------------------------------------------------------------
# 1. THE 13 CALIBRATION TEST SCENARIOS
# -----------------------------------------------------------------------------

def test_scenario_1_customer_walkthrough_business_hours():
    """1. Customer walks through, business hours, 25 s, conf 0.7, no dwell -> ~26 -> LOW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_aisle",
        object_type="person",
        confidence=0.70,
        motion_ratio=0.02,
        track_duration_sec=25.0,
        bounding_box=[0.2, 0.2, 0.4, 0.8],
        is_after_hours=False,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    candidate.dwell_sec = 0.0
    score, should_alert, bd = engine.evaluate(candidate)
    assert 21 <= score <= 31, f"Expected ~26 (+/-5), got {score}"
    assert bd["tier"] == "low"
    assert should_alert is False


def test_scenario_2_customer_lingers_shelf():
    """2. Customer lingers 40 s near a shelf -> ~42 -> REVIEW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_shelf",
        object_type="person",
        confidence=0.70,
        motion_ratio=0.02,
        track_duration_sec=40.0,
        bounding_box=[0.2, 0.2, 0.4, 0.8],
        is_after_hours=False,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, bd = engine.evaluate(candidate)
    assert 37 <= score <= 47, f"Expected ~42 (+/-5), got {score}"
    assert bd["tier"] == "review"
    assert should_alert is False


def test_scenario_3_staff_at_counter_baseline_learned():
    """3. Staff stands at counter 5 min (staff_expected zone, baseline learned) -> < 30 -> LOW (< 45 during cold start)"""
    engine = ScoringEngine(alert_threshold=70)
    # Learned baseline (routine_probability = 0.80, 28 days history)
    candidate_learned = DetectionCandidate(
        camera_id="cam_counter",
        object_type="person",
        confidence=0.80,
        motion_ratio=0.02,
        track_duration_sec=300.0,
        bounding_box=[0.3, 0.3, 0.5, 0.8],
        is_after_hours=False,
        is_in_restricted_zone=True,
        is_night_ir=False
    )
    candidate_learned.staff_expected = True
    candidate_learned.routine_probability = 0.80
    candidate_learned.days_of_history = 28

    score_learned, should_alert, bd = engine.evaluate(candidate_learned)
    assert score_learned < 30, f"Expected < 30 with baseline learned, got {score_learned}"
    assert bd["tier"] == "low"
    assert should_alert is False

    # Cold start (0 days history, routine_probability = None)
    candidate_cold = DetectionCandidate(
        camera_id="cam_counter",
        object_type="person",
        confidence=0.80,
        motion_ratio=0.02,
        track_duration_sec=300.0,
        bounding_box=[0.3, 0.3, 0.5, 0.8],
        is_after_hours=False,
        is_in_restricted_zone=True,
        is_night_ir=False
    )
    candidate_cold.staff_expected = True
    candidate_cold.days_of_history = 0

    score_cold, _, bd_cold = engine.evaluate(candidate_cold)
    assert score_cold < 45, f"Expected < 45 during cold start, got {score_cold}"
    assert bd_cold["tier"] in ("low", "review")


def test_scenario_4_vehicle_passes_through():
    """4. Vehicle passes through ROI 3 s, daytime -> < 20 -> LOW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_gate",
        object_type="vehicle",
        confidence=0.65,
        motion_ratio=0.05,
        track_duration_sec=3.0,
        bounding_box=[0.1, 0.3, 0.6, 0.7],
        is_after_hours=False,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    candidate.velocity_hint = 0.65  # Fast vehicle transit
    score, should_alert, bd = engine.evaluate(candidate)
    assert score < 20, f"Expected < 20 for moving vehicle, got {score}"
    assert bd["tier"] == "low"
    assert should_alert is False


def test_scenario_5_dog_walks_through():
    """5. Dog walks through, daytime -> < 20 -> LOW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_yard",
        object_type="animal",
        confidence=0.55,
        motion_ratio=0.02,
        track_duration_sec=3.0,
        bounding_box=[0.2, 0.4, 0.4, 0.6],
        is_after_hours=False,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, bd = engine.evaluate(candidate)
    assert score < 20, f"Expected < 20 for daytime animal, got {score}"
    assert bd["tier"] == "low"
    assert should_alert is False


def test_scenario_6_confirmed_person_after_hours_open_area():
    """6. Confirmed person after hours in open area -> 70-75 -> ALERT (via floor)"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_lobby",
        object_type="person",
        confidence=0.75,
        motion_ratio=0.03,
        track_duration_sec=5.0,
        bounding_box=[0.2, 0.2, 0.5, 0.8],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, bd = engine.evaluate(candidate)
    assert 70 <= score <= 75, f"Expected 70-75 via floor, got {score}"
    assert bd["tier"] == "alert"
    assert should_alert is True


def test_scenario_7_person_cash_counter_after_hours_dwell():
    """7. Person after hours in the cash-counter polygon, 60 s dwell -> 90-100 -> ALERT / Critical"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_counter",
        object_type="person",
        confidence=0.88,
        motion_ratio=0.06,
        track_duration_sec=60.0,
        bounding_box=[0.4, 0.3, 0.6, 0.8],
        is_after_hours=True,
        is_in_restricted_zone=True,
        is_night_ir=False
    )
    score, should_alert, bd = engine.evaluate(candidate)
    assert 90 <= score <= 100, f"Expected 90-100 (Critical), got {score}"
    assert bd["tier"] == "alert"
    assert bd["severity_label"] == "Critical"
    assert should_alert is True


def test_scenario_8_single_frame_person_ir_glare():
    """8. Single-frame 'person' at IR night (glare) -> <= 29 -> LOW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_night",
        object_type="person",
        confidence=0.42,
        motion_ratio=0.01,
        track_duration_sec=0.25,
        bounding_box=[0.1, 0.1, 0.3, 0.3],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=True
    )
    candidate.track_hits = 1  # Exactly single frame
    score, should_alert, bd = engine.evaluate(candidate)
    assert score <= 29, f"Expected <= 29 for single-frame glare, got {score}"
    assert bd["tier"] == "low"
    assert should_alert is False


def test_scenario_9_pure_motion_fan_curtain():
    """9. Pure motion, no object, business hours (fan/curtain) -> < 10 -> LOW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_shop",
        object_type="unclassified",
        confidence=0.0,
        motion_ratio=0.03,
        track_duration_sec=5.0,
        bounding_box=[0.0, 0.0, 1.0, 1.0],
        is_after_hours=False,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, bd = engine.evaluate(candidate)
    assert score < 10, f"Expected < 10 for pure background motion, got {score}"
    assert bd["tier"] == "low"
    assert should_alert is False


def test_scenario_10_unexplained_motion_restricted_after_hours():
    """10. Unexplained motion after hours in a restricted zone, 15 s, no detection -> 30 -> REVIEW (floor)"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_vault",
        object_type="unclassified",
        confidence=0.0,
        motion_ratio=0.04,
        track_duration_sec=15.0,
        bounding_box=[0.3, 0.3, 0.7, 0.7],
        is_after_hours=True,
        is_in_restricted_zone=True,
        is_night_ir=False
    )
    score, should_alert, bd = engine.evaluate(candidate)
    assert score == 30, f"Expected exact threat floor 30, got {score}"
    assert bd["tier"] == "review"
    assert should_alert is False


def test_scenario_11_backpack_unattended_business_hours():
    """11. Backpack left alone 90 s, business hours -> 35-55 -> REVIEW"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_floor",
        object_type="carried_item",
        confidence=0.70,
        motion_ratio=0.01,
        track_duration_sec=90.0,
        bounding_box=[0.4, 0.5, 0.6, 0.7],
        is_after_hours=False,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    candidate.is_unattended = True
    candidate.unattended_duration_sec = 90.0

    score, should_alert, bd = engine.evaluate(candidate)
    assert 35 <= score <= 55, f"Expected 35-55 for unattended backpack, got {score}"
    assert bd["tier"] == "review"
    assert should_alert is False


def test_scenario_12_person_inside_restricted_storeroom_daytime():
    """12. Person inside an always-restricted storeroom polygon during business hours -> >= 70 -> ALERT"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_store",
        object_type="person",
        confidence=0.80,
        motion_ratio=0.04,
        track_duration_sec=5.0,
        bounding_box=[0.2, 0.2, 0.5, 0.8],
        is_after_hours=False,
        is_in_restricted_zone=True,
        is_night_ir=False
    )
    candidate.staff_expected = False  # Always restricted

    score, should_alert, bd = engine.evaluate(candidate)
    assert score >= 70, f"Expected >= 70 for restricted storeroom breach, got {score}"
    assert bd["tier"] == "alert"
    assert should_alert is True


def test_scenario_13_cleaner_authorized_window_neutral():
    """13. Cleaner inside an authorized 06:00-07:00 window -> neutral -> 30-45 -> REVIEW, no alert"""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_office",
        object_type="person",
        confidence=0.75,
        motion_ratio=0.03,
        track_duration_sec=10.0,
        bounding_box=[0.2, 0.2, 0.4, 0.7],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    candidate.is_authorized_window = True  # Cleaner authorized window
    score, should_alert, bd = engine.evaluate(candidate)
    assert 30 <= score <= 45, f"Expected 30-45 (neutral Review), got {score}"
    assert bd["tier"] == "review"
    assert should_alert is False


# -----------------------------------------------------------------------------
# 2. MONOTONICITY & BOUNDARY CHECKS
# -----------------------------------------------------------------------------

def test_scoring_monotonicity():
    """Asserts that higher confidence or dwell never decreases score unless penalty applies."""
    engine = ScoringEngine(alert_threshold=70)

    # Varying confidence
    cand_low_conf = DetectionCandidate(
        camera_id="cam_1", object_type="person", confidence=0.40,
        motion_ratio=0.02, track_duration_sec=10.0, bounding_box=[0.1, 0.1, 0.4, 0.8],
        is_after_hours=False, is_in_restricted_zone=False
    )
    cand_high_conf = DetectionCandidate(
        camera_id="cam_1", object_type="person", confidence=0.80,
        motion_ratio=0.02, track_duration_sec=10.0, bounding_box=[0.1, 0.1, 0.4, 0.8],
        is_after_hours=False, is_in_restricted_zone=False
    )
    s1, _, _ = engine.evaluate(cand_low_conf)
    s2, _, _ = engine.evaluate(cand_high_conf)
    assert s2 >= s1, f"Higher confidence should not decrease score: {s2} vs {s1}"

    # Varying dwell
    cand_short_dwell = DetectionCandidate(
        camera_id="cam_1", object_type="person", confidence=0.70,
        motion_ratio=0.02, track_duration_sec=10.0, bounding_box=[0.1, 0.1, 0.4, 0.8],
        is_after_hours=False, is_in_restricted_zone=False
    )
    cand_long_dwell = DetectionCandidate(
        camera_id="cam_1", object_type="person", confidence=0.70,
        motion_ratio=0.02, track_duration_sec=40.0, bounding_box=[0.1, 0.1, 0.4, 0.8],
        is_after_hours=False, is_in_restricted_zone=False
    )
    s_short, _, _ = engine.evaluate(cand_short_dwell)
    s_long, _, _ = engine.evaluate(cand_long_dwell)
    assert s_long >= s_short, f"Longer dwell should not decrease score: {s_long} vs {s_short}"


def test_tier_boundaries():
    """Verifies tier assignment at exact boundary integers 29, 30, 69, 70."""
    tier_29 = ScoringEngine.get_severity_tier(29)
    assert tier_29["tier"] == "low"

    tier_30 = ScoringEngine.get_severity_tier(30)
    assert tier_30["tier"] == "review"

    tier_69 = ScoringEngine.get_severity_tier(69)
    assert tier_69["tier"] == "review"

    tier_70 = ScoringEngine.get_severity_tier(70)
    assert tier_70["tier"] == "alert"


def test_score_breakdown_contains_all_layers():
    """Asserts that all layers 0-12 and levels 1-5 appear in every score breakdown."""
    engine = ScoringEngine(alert_threshold=70)
    cand = DetectionCandidate(
        camera_id="cam_test", object_type="person", confidence=0.70,
        motion_ratio=0.02, track_duration_sec=5.0, bounding_box=[0.1, 0.1, 0.4, 0.7],
        is_after_hours=True, is_in_restricted_zone=False
    )
    _, _, bd = engine.evaluate(cand)

    required_keys = [
        "scoring_version",
        "l0_is_after_hours", "l0_is_confirmed", "l0_threat_floor",
        "l1_motion",
        "l2_confidence",
        "l3_object_weight",
        "l4_nuisance_penalty", "l4_threat_floor",
        "l5_loitering",
        "l6_zone_proximity",
        "l7_velocity_penalty",
        "l8_multiframe_multiplier",
        "l9_reliability_multiplier",
        "l10_baseline_adjustment",
        "l11_behavior_pattern",
        "l12_unattended_object",
        "raw3", "s3", "d4_modifier", "s_live",
        "score_raw", "final_score", "tier", "severity_label"
    ]
    for key in required_keys:
        assert key in bd, f"Missing layer breakdown key: {key}"


# -----------------------------------------------------------------------------
# 3. 72-HOUR RETENTION JOB LIFECYCLE TEST
# -----------------------------------------------------------------------------

def test_retention_job_lifecycle(tmp_path):
    """
    Validates retention job:
    - low tier clip older than 72h is auto-deleted (disk file + DB status)
    - pinned low clip is NOT deleted
    - review and alert tier clips are UNTOUCHED even after 72h
    """
    db_file = tmp_path / "test_retention.db"
    db = EventDatabase(db_file)
    reaper = StorageReaperDaemon(
        db=db,
        data_root=tmp_path,
        raw_retention_hours=72
    )

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=80)).isoformat()
    old_ms = int((now - timedelta(hours=80)).timestamp() * 1000)

    # 1. Expired low-tier clip (should be DELETED)
    f_low = tmp_path / "clip_low.mp4"
    f_low.write_bytes(b"dummy_video_content")
    rec_low = EventRecord(
        event_group_id="ev_low_expired",
        camera_id="cam_1",
        start_time=old_time,
        score=20,
        tier="low",
        file_path=str(f_low),
        thumb_path="",
        expires_at_ms=old_ms + (72 * 3600 * 1000) # expired 8 hours ago
    )
    db.insert_event(rec_low)

    # 2. Expired low-tier clip but PINNED (should be PRESERVED)
    f_pinned = tmp_path / "clip_pinned.mp4"
    f_pinned.write_bytes(b"dummy_video_content")
    rec_pinned = EventRecord(
        event_group_id="ev_low_pinned",
        camera_id="cam_1",
        start_time=old_time,
        score=20,
        tier="low",
        file_path=str(f_pinned),
        thumb_path="",
        starred=1,
        expires_at_ms=old_ms + (72 * 3600 * 1000)
    )
    db.insert_event(rec_pinned)

    # 3. Old REVIEW clip (should be UNTOUCHED)
    f_review = tmp_path / "clip_review.mp4"
    f_review.write_bytes(b"dummy_video_content")
    rec_review = EventRecord(
        event_group_id="ev_review_old",
        camera_id="cam_1",
        start_time=old_time,
        score=45,
        tier="review",
        file_path=str(f_review),
        thumb_path="",
        expires_at_ms=None
    )
    db.insert_event(rec_review)

    # 4. Old ALERT clip (should be UNTOUCHED)
    f_alert = tmp_path / "clip_alert.mp4"
    f_alert.write_bytes(b"dummy_video_content")
    rec_alert = EventRecord(
        event_group_id="ev_alert_old",
        camera_id="cam_1",
        start_time=old_time,
        score=85,
        tier="alert",
        file_path=str(f_alert),
        thumb_path="",
        expires_at_ms=None
    )
    db.insert_event(rec_alert)

    # Give writer thread a moment to commit
    time.sleep(0.5)

    # Run reaper sweep
    reaper.perform_sweep()

    # Verify:
    # 1. Expired low clip: physical file removed, status is deleted
    assert not f_low.exists(), "Expired low-tier file should be deleted from disk"
    ev_low = db.get_clip_by_id("ev_low_expired")
    assert ev_low is not None and ev_low["status"] == "deleted"

    # 2. Pinned low clip: physical file preserved, status remains raw/unreviewed
    assert f_pinned.exists(), "Pinned low-tier file MUST NOT be deleted"
    ev_pinned = db.get_clip_by_id("ev_low_pinned")
    assert ev_pinned is not None and ev_pinned["status"] in ("raw", "unreviewed")

    # 3. Old Review clip: preserved
    assert f_review.exists(), "Review clip MUST NOT be deleted by 72h job"
    ev_review = db.get_clip_by_id("ev_review_old")
    assert ev_review is not None and ev_review["status"] in ("raw", "unreviewed")

    # 4. Old Alert clip: preserved
    assert f_alert.exists(), "Alert clip MUST NOT be deleted by 72h job"
    ev_alert = db.get_clip_by_id("ev_alert_old")
    assert ev_alert is not None and ev_alert["status"] in ("raw", "unreviewed")
