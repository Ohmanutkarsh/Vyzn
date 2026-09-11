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
    """
    Verifies that an attacker flooding 50 false alarms cannot shift bias by > 5 pts instantaneously,
    and cannot bypass the limit with rapid successive calls within the 24-hour window.
    """
    calibrator = AdaptiveCalibrator(db=None, min_samples=10, max_penalty=25, max_slew_per_day=5)

    stats = {
        "reviewed": 50,
        "false_positive": 50,
        "confirmed_threat": 0,
        "fpr_fraction": 1.0
    }
    t0 = 100000.0

    # Call 1 at t0: Target ~ -22, but capped at -5
    bias_1, debug_1 = calibrator.compute_bayesian_bias_from_stats("cam_attack_target", stats, now_ts=t0)
    assert debug_1["slew_limited"] is True
    assert bias_1 == -5, f"Expected initial slew limited bias to -5, got {bias_1}"
    assert debug_1["remaining_24h_budget"] == 0

    # Call 2 at t0 + 10s: Rapid attack attempt MUST be completely blocked (remaining budget = 0)
    bias_2, debug_2 = calibrator.compute_bayesian_bias_from_stats("cam_attack_target", stats, now_ts=t0 + 10.0)
    assert debug_2["slew_limited"] is True
    assert bias_2 == -5, f"Rapid call must remain locked at -5, got {bias_2}"
    assert debug_2["remaining_24h_budget"] == 0

    # Call 3 at t0 + 3600s (1 hour later): Still blocked in same 24-hour window
    bias_3, debug_3 = calibrator.compute_bayesian_bias_from_stats("cam_attack_target", stats, now_ts=t0 + 3600.0)
    assert bias_3 == -5, f"1 hour later must still remain locked at -5, got {bias_3}"

    # Call 4 at t0 + 86401s (24 hours and 1 second later): Rolling window frees budget
    bias_4, debug_4 = calibrator.compute_bayesian_bias_from_stats("cam_attack_target", stats, now_ts=t0 + 86401.0)
    assert debug_4["slew_limited"] is True
    assert bias_4 == -10, f"Next day allowed step of 5 pts to -10, got {bias_4}"
    assert debug_4["remaining_24h_budget"] == 0


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

    # 1. Candidate: Valid creeping intruder with minimal motion and confidence near threshold
    creeping_burglar = DetectionCandidate(
        camera_id="cam_vault",
        object_type="person",
        confidence=0.36,               # Barely above 0.35 daylight threshold
        motion_ratio=0.005,            # Minimal creeping motion -> L1 = 1
        track_duration_sec=0.0,        # 0s persistence -> L5 = 0
        bounding_box=[0.4, 0.4, 0.6, 0.8],
        is_after_hours=True,
        is_in_restricted_zone=True,
        is_night_ir=False,
        timestamp=datetime.now(timezone.utc)
    )

    # Evaluate under severe negative camera bias (-25) with default threshold 70
    score, should_alert, breakdown = engine.evaluate(creeping_burglar, camera_bias=-25)
    assert breakdown["is_valid_detection"] is True
    # Invariant: Threat floor is anchored to alert_threshold (70)
    assert score >= 70, f"CRITICAL FAILURE: Creeping intruder score {score} fell below alert threshold 70"
    assert should_alert is True, "Creeping intruder alert must not be suppressed by camera bias"

    # 2. Re-evaluate under elevated threshold 80 (Option 1: floor anchored relative to threshold)
    high_threshold_engine = ScoringEngine(alert_threshold=80)
    ht_score, ht_alert, ht_breakdown = high_threshold_engine.evaluate(creeping_burglar, camera_bias=-25)
    assert ht_score >= 80, f"CRITICAL FAILURE: Creeping intruder score {ht_score} fell below elevated threshold 80"
    assert ht_alert is True, "Creeping intruder MUST alert even under elevated threshold"

    # 3. Stray animal after hours receives standard floor (50), NOT elevated threat floor
    stray_animal = DetectionCandidate(
        camera_id="cam_vault",
        object_type="animal",
        confidence=0.70,
        motion_ratio=0.02,
        track_duration_sec=0.5,
        bounding_box=[0.1, 0.1, 0.3, 0.3],
        is_after_hours=True,
        is_in_restricted_zone=False,
        is_night_ir=False,
        timestamp=datetime.now(timezone.utc)
    )
    anim_score, anim_alert, anim_breakdown = engine.evaluate(stray_animal, camera_bias=-10)
    assert anim_score <= 45, f"Animal score {anim_score} should remain below alert threshold"
    assert anim_alert is False, "Stray animal after hours must NOT fire false alarm"

    # 4. Critical Boundary Collision Regression Test: Minimum allowed OTA threshold (65)
    min_thresh_engine = ScoringEngine(alert_threshold=65)
    min_anim_score, min_anim_alert, _ = min_thresh_engine.evaluate(stray_animal, camera_bias=0)
    assert min_anim_score < 65, f"Animal score {min_anim_score} must not breach minimum threshold 65"
    assert min_anim_alert is False, "Stray animal must not fire false alert even at minimum allowed threshold 65"

    min_burglar_score, min_burglar_alert, _ = min_thresh_engine.evaluate(creeping_burglar, camera_bias=-25)
    assert min_burglar_score >= 65, f"Burglar score {min_burglar_score} must meet or exceed threshold 65"
    assert min_burglar_alert is True, "Burglar must alert at minimum allowed threshold 65"


def test_calibrator_cannot_influence_upstream_detection():
    """
    MATHEMATICAL INVARIANCE TEST:
    Verifies that camera_bias (even an extreme adversarial value of -100)
    has ZERO influence on upstream detector outputs:
    - Object candidate confidence is unmodified.
    - Upstream is_valid_detection remains True.
    - Upstream classification and bounding box coordinates are completely preserved.
    """
    engine = ScoringEngine(alert_threshold=70)

    candidate = DetectionCandidate(
        camera_id="cam_invariance_test",
        object_type="person",
        confidence=0.88,
        motion_ratio=0.08,
        track_duration_sec=3.0,
        bounding_box=[0.2, 0.2, 0.5, 0.8],
        is_after_hours=True,
        is_in_restricted_zone=True,
        is_night_ir=False,
        timestamp=datetime.now(timezone.utc)
    )

    # Evaluate with baseline camera_bias = 0
    score_clean, alert_clean, breakdown_clean = engine.evaluate(candidate, camera_bias=0)

    # Evaluate with extreme adversarial dampener camera_bias = -100
    score_dampened, alert_dampened, breakdown_dampened = engine.evaluate(candidate, camera_bias=-100)

    # Upstream properties MUST be identical
    assert breakdown_clean["is_valid_detection"] is True
    assert breakdown_dampened["is_valid_detection"] is True
    assert candidate.confidence == 0.88
    assert candidate.object_type == "person"
    assert candidate.bounding_box == [0.2, 0.2, 0.5, 0.8]

    # Inviolable floor MUST hold even with -100 camera bias
    assert score_dampened >= 70, f"Score {score_dampened} fell below threshold floor under bias -100"
    assert alert_dampened is True, "Alert must fire for verified intruder despite -100 bias"