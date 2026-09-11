"""
Unit tests for AdaptiveCalibrator:
Verifies Bayesian Beta-Binomial estimator, sample-size gating, anti-gaming slew rate limiting,
rolling 30-day window decay, and hard-floor preservation for confirmed detections.
"""

import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord, DetectionCandidate
from vyzn.scoring.calibrator import AdaptiveCalibrator
from vyzn.scoring.engine import ScoringEngine


def test_calibrator_sample_gating_and_bayesian_estimation(tmp_path):
    db = EventDatabase(tmp_path / "events.db")
    calibrator = AdaptiveCalibrator(db=db, min_samples=15, max_penalty=25, max_slew_per_day=10)

    # 1. Under minimum sample threshold (only 5 events, all false positives)
    for i in range(5):
        ev = EventRecord(
            event_group_id=f"ev_gate_{i}",
            camera_id="cam_gate_test",
            start_time=datetime.now(timezone.utc).isoformat(),
            end_time=None,
            object_type="unclassified",
            confidence=0.1,
            score=55,
            user_triage="false_positive",
            file_path="dummy.mp4",
            thumb_path="dummy.jpg"
        )
        db.execute_sync(
            "INSERT INTO events (event_group_id, camera_id, start_time, object_type, confidence, score, user_triage, file_path, thumb_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ev.event_group_id, ev.camera_id, ev.start_time, ev.object_type, ev.confidence, ev.score, ev.user_triage, ev.file_path, ev.thumb_path)
        )

    # Sample size = 5 < 15 -> Gated, bias MUST be 0
    bias = calibrator.get_camera_bias("cam_gate_test")
    assert bias == 0, f"Expected 0 bias due to sample gating, got {bias}"
    metrics = calibrator.get_camera_metrics("cam_gate_test")
    assert metrics["gated"] is True
    assert "Sample size 5 < 15" in metrics["reason"]

    # 2. Add 15 more events (10 false positives, 5 confirmed threats) -> Total = 20 (15 FP, 5 TP)
    for i in range(5, 15):
        db.execute_sync(
            "INSERT INTO events (event_group_id, camera_id, start_time, object_type, confidence, score, user_triage, file_path, thumb_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"ev_fp_{i}", "cam_gate_test", datetime.now(timezone.utc).isoformat(), "unclassified", 0.1, 55, "false_positive", "dummy.mp4", "dummy.jpg")
        )
    for i in range(15, 20):
        db.execute_sync(
            "INSERT INTO events (event_group_id, camera_id, start_time, object_type, confidence, score, user_triage, file_path, thumb_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"ev_tp_{i}", "cam_gate_test", datetime.now(timezone.utc).isoformat(), "person", 0.8, 85, "confirmed_threat", "dummy.mp4", "dummy.jpg")
        )

    calibrator.refresh(force=True)
    bias = calibrator.get_camera_bias("cam_gate_test")
    metrics = calibrator.get_camera_metrics("cam_gate_test")

    # Sample size = 20 >= 15 -> Gating released
    assert metrics["gated"] is False
    assert metrics["reviewed"] == 20
    # Beta-Binomial: post_alpha = 2 + 15 = 17, post_beta = 18 + 5 = 23, total = 40. theta = 17/40 = 0.425
    # Raw target penalty = int(round(0.425 * 30)) = 13.
    # Initial slew limit allows max_slew_per_day (10 pts)
    assert bias < 0, f"Expected negative bias, got {bias}"
    assert bias in (-10, -13), f"Expected dampened Bayesian bias, got {bias}"

    db.close()


def test_anti_gaming_slew_rate_limiter():
    """Verifies that an attacker flooding 50 false alarms cannot shift bias by > 5 pts instantaneously."""
    calibrator = AdaptiveCalibrator(db=None, min_samples=10, max_penalty=25, max_slew_per_day=5)

    # Simulate 50 false alarms, 0 threats
    stats = {
        "reviewed": 50,
        "false_positive": 50,
        "confirmed_threat": 0,
        "fpr_fraction": 1.0
    }
    bias, debug = calibrator.compute_bayesian_bias_from_stats("cam_attack_target", stats)

    # Target bias would be -min(25, round(theta * 30)) ~ -22
    # But slew rate limiter MUST restrict it to max -5
    assert debug["slew_limited"] is True
    assert bias == -5, f"Expected slew limited bias to -5, got {bias}"


def test_rolling_window_decays_old_nuisance(tmp_path):
    """Verifies that events older than window_days are excluded from the Bayesian calculation."""
    db = EventDatabase(tmp_path / "events_window.db")
    calibrator = AdaptiveCalibrator(db=db, min_samples=15, window_days=30)

    # Insert 20 false positives from 45 days ago (outside 30-day window)
    old_time = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    for i in range(20):
        db.execute_sync(
            "INSERT INTO events (event_group_id, camera_id, start_time, object_type, confidence, score, user_triage, file_path, thumb_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"ev_old_{i}", "cam_scaffold", old_time, "unclassified", 0.1, 55, "false_positive", "dummy.mp4", "dummy.jpg")
        )

    # In rolling 30-day window, count should be 0
    stats = db.get_camera_triage_statistics("cam_scaffold", window_days=30)
    assert stats["reviewed"] == 0, f"Expected 0 reviews in 30d window, got {stats['reviewed']}"

    bias = calibrator.get_camera_bias("cam_scaffold")
    assert bias == 0, f"Expected 0 bias for decayed events, got {bias}"

    db.close()


def test_hard_floor_inviolability_under_severe_camera_bias():
    """
    CRITICAL SECURITY INVARIANT:
    Ensures that even under maximum negative camera bias (-25), a genuine human detection
    NEVER falls below the hard floor of 50.
    """
    engine = ScoringEngine(alert_threshold=70)

    # Candidate: Valid human intruder detection
    valid_candidate = DetectionCandidate(
        camera_id="cam_vault",
        object_type="person",
        confidence=0.85,
        motion_ratio=0.08,
        track_duration_sec=3.0,
        bounding_box=[0.4, 0.4, 0.6, 0.8],
        is_after_hours=True,
        is_in_restricted_zone=True,
        is_night_ir=False,
        timestamp=datetime.now(timezone.utc)
    )

    # Evaluate with maximum adversarial camera bias
    score, should_alert, breakdown = engine.evaluate(valid_candidate, camera_bias=-25)

    assert breakdown["is_valid_detection"] is True
    # Invariant: Valid detections cannot score below 50
    assert score >= 50, f"CRITICAL FAILURE: Valid detection fell below hard floor: {score}"
    assert breakdown["camera_bias"] == -25
    # Since confidence is high and track is 3s, person scores 40 + confidence (26) + motion (16) = 82 >= 70 alert!
    assert should_alert is True, "Valid intruder alert must not be suppressed by camera bias"