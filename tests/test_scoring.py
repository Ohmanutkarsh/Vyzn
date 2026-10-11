"""
Tests for 13-Layer Scoring Engine v2.0 and Layer 0 Schedule/Zone Gating.
"""

import math
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
        motion_ratio=0.08,             # L1 = 10 * (1 - exp(-0.08 / 0.03)) = 9.31
        track_duration_sec=4.0,
        bounding_box=[0.2, 0.2, 0.4, 0.7],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    assert score >= 70
    assert should_alert is True
    assert breakdown["tier"] == "alert"
    assert abs(breakdown["l1_motion"] - round(10.0 * (1.0 - math.exp(-0.08 / 0.03)), 2)) < 0.1
    assert breakdown["l2_confidence"] == 15.0
    assert breakdown["l3_object_weight"] == 20.0
    assert breakdown["l4_threat_floor"] == 70.0


def test_unclassified_motion_nuisance_penalty():
    """Validates that unclassified motion (wind/shadows) suffers a -35 nuisance penalty and scores low."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_outdoor",
        object_type="unclassified",
        confidence=0.0,
        motion_ratio=0.04,
        track_duration_sec=0.5,
        bounding_box=[0.0, 0.0, 1.0, 1.0],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    assert score <= 10
    assert should_alert is False
    assert breakdown["tier"] == "low"
    assert breakdown["l4_nuisance_penalty"] == -35.0


def test_hard_floor_for_valid_detection():
    """Validates that confirmed person after hours receives threat floor of at least 70 points."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_indoor",
        object_type="person",
        confidence=0.50,               # Valid confidence >= 0.45
        motion_ratio=0.005,
        track_duration_sec=4.0,
        bounding_box=[0.1, 0.1, 0.2, 0.3],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    # Hard threat floor ensures it can never score below 70 after hours
    assert score >= 70
    assert should_alert is True
    assert breakdown["tier"] == "alert"


def test_layer_0_business_hours_suppression():
    """Validates that during business hours, public aisle customer movement does NOT trigger alerts and scores low/review."""
    engine = ScoringEngine(alert_threshold=70)
    candidate = DetectionCandidate(
        camera_id="cam_aisle",
        object_type="person",
        confidence=0.70,
        motion_ratio=0.02,
        track_duration_sec=10.0,
        bounding_box=[0.2, 0.2, 0.5, 0.8],
        is_after_hours=False,          # During business hours
        is_in_restricted_zone=False,   # Normal customer zone
        is_night_ir=False
    )
    score, should_alert, breakdown = engine.evaluate(candidate)

    # Recalibrated score stops over-scoring during business hours
    assert score < 70
    assert should_alert is False
    assert breakdown["tier"] in ("low", "review")


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
    assert breakdown["tier"] == "alert"


def test_point_in_polygon():
    """Validates 2D ray casting point in polygon function."""
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert is_point_in_polygon(0.5, 0.5, poly) is True
    assert is_point_in_polygon(1.5, 0.5, poly) is False
    assert is_point_in_polygon(-0.1, 0.5, poly) is False
