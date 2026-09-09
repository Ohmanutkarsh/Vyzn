"""
Tests for 5-Layer Scoring Engine and Layer 0 Schedule/Zone Gating.
"""

# Standard assertion tests
from datetime import datetime, timezone
from vyzn.core.events import DetectionCandidate
from vyzn.scoring.engine import (
    ScoringEngine,
    is_point_in_polygon,
    check_box_intersects_zone,
    is_time_after_hours
)
from vyzn.core.config import BusinessHours, ZonePolygon


def test_after_hours_intruder_high_score():
    """Validates that a confirmed person intruder after hours generates a high alert score (>= 70)."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_shutter",
        object_type="person",
        confidence=0.85,
        motion_ratio=0.08,             # 8% motion -> L1 = 16
        track_duration_sec=4.0,        # 4s persistence -> L5 = 12
        bounding_box=[0.2, 0.2, 0.4, 0.7],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    assert score >= 70
    assert should_alert is True
    assert breakdown["l1_motion"] == 16
    assert breakdown["l2_confidence"] == 26  # round(0.85 * 30) = 26
    assert breakdown["l3_object_weight"] == 40
    assert breakdown["subtotal"] >= 80


def test_unclassified_motion_nuisance_penalty():
    """Validates that unclassified motion (wind/shadows) suffers a -35 nuisance penalty and scores low."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_outdoor",
        object_type="unclassified",
        confidence=0.0,
        motion_ratio=0.04,             # 4% motion -> L1 = 8
        track_duration_sec=0.5,        # 0.5s -> L5 = 2
        bounding_box=[0.0, 0.0, 1.0, 1.0],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    # Subtotal 123 = 8 + 0 + 0 = 8.
    # L4 penalty: max(0, 8 - 35) = 0.
    # Total score = 0 + 2 = 2.
    assert score <= 10
    assert should_alert is False
    assert breakdown["l4_adjustment"] == -35


def test_hard_floor_for_valid_detection():
    """Validates that any confirmed valid detection receives a hard floor of at least 50 points."""
    engine = ScoringEngine(alert_threshold=70)
    # Low confidence person just passing threshold
    candidate = DetectionCandidate(
        camera_id="cam_indoor",
        object_type="person",
        confidence=0.36,               # Above day threshold (0.35)
        motion_ratio=0.005,            # Tiny motion -> L1 = 1
        track_duration_sec=0.0,        # 0s -> L5 = 0
        bounding_box=[0.1, 0.1, 0.2, 0.3],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    # Subtotal 123 = 1 + 11 + 40 = 52.
    # Hard floor ensures it can never score below 50.
    assert score >= 50


def test_layer_0_business_hours_suppression():
    """Validates that during business hours, public aisle movement does NOT trigger alerts."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_aisle",
        object_type="person",
        confidence=0.90,
        motion_ratio=0.10,
        track_duration_sec=5.0,
        bounding_box=[0.2, 0.2, 0.5, 0.8],
        is_after_hours=False,          # During business hours
        is_in_restricted_zone=False,   # Normal customer zone
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    # Score is high (>=70) due to clear person detection
    assert score >= 70
    # BUT alert is suppressed due to Layer 0 gate
    assert should_alert is False
    assert breakdown["gate_l0_passed"] is False


def test_layer_0_restricted_zone_trigger():
    """Validates that during business hours, movement inside a restricted zone (cash drawer) DOES alert."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_counter",
        object_type="person",
        confidence=0.90,
        motion_ratio=0.06,
        track_duration_sec=5.0,
        bounding_box=[0.65, 0.45, 0.80, 0.65],
        is_after_hours=False,          # During business hours
        is_in_restricted_zone=True,    # Inside cash drawer polygon
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    assert score >= 70
    assert should_alert is True
    assert breakdown["gate_l0_passed"] is True


def test_point_in_polygon():
    """Validates 2D ray casting point in polygon function."""
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert is_point_in_polygon(0.5, 0.5, poly) is True
    assert is_point_in_polygon(1.5, 0.5, poly) is False
    assert is_point_in_polygon(-0.1, 0.5, poly) is False
