"""
5-Layer Scoring Engine implementation matching SCORING_SPEC.md.
Evaluates threat level, applies noise penalties, and executes Layer 0 schedule/zone gating.
"""

from __future__ import annotations
from typing import Tuple, Dict, Any, List
from datetime import datetime, timezone
from vyzn.core.events import DetectionCandidate
from vyzn.core.config import BusinessHours, ZonePolygon


def is_point_in_polygon(x: float, y: float, polygon_points: List[List[float]]) -> bool:
    """Standard ray-casting algorithm for 2D point-in-polygon test."""
    n = len(polygon_points)
    if n < 3:
        return False

    inside = False
    p1x, p1y = polygon_points[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon_points[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def check_box_intersects_zone(box: List[float], zone: ZonePolygon) -> bool:
    """
    Checks if detection bounding box [x1, y1, x2, y2] intersects zone polygon.
    Tests 5 key points: all 4 corners + centroid.
    Normalized coordinates [0.0, 1.0].
    """
    if not zone.points or len(zone.points) < 3:
        return False
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    # Test 5 key points for robust intersection
    test_points = [
        (cx, cy),          # Centroid
        (cx, y2),          # Bottom center (foot position — most important)
        (x1, y2),          # Bottom-left corner
        (x2, y2),          # Bottom-right corner
        (cx, (cy + y2) / 2),  # Lower mid-body
    ]
    for px, py in test_points:
        if is_point_in_polygon(px, py, zone.points):
            return True
    return False


def is_foot_in_polygon(box: List[float], polygon_points: List[List[float]]) -> bool:
    """
    Evaluates whether the person's feet (bottom-centre of detection bounding box)
    lies inside the normalized polygon. Per Section 6.4 of specification.
    box: [x1, y1, x2, y2] in normalized coordinates 0.0 to 1.0.
    """
    if not polygon_points or len(polygon_points) < 3:
        return False
    x1, y1, x2, y2 = box
    foot_x = (x1 + x2) / 2.0
    foot_y = y2
    return is_point_in_polygon(foot_x, foot_y, polygon_points)


def is_time_after_hours(dt: datetime, schedule: BusinessHours) -> bool:
    """
    Determines if given datetime is outside configured business hours.
    Always converts to IST (Asia/Kolkata, UTC+5:30) for comparison since
    business hours are configured in local Indian time.
    """
    # Convert to IST: add 5 hours 30 minutes (330 minutes)
    try:
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
        if dt.tzinfo is not None:
            local_dt = dt.astimezone(IST)
        else:
            local_dt = dt  # Assume already local if naive
        local_hour = local_dt.hour
        local_minute = local_dt.minute
    except ImportError:
        # pytz not available: manual UTC+5:30 offset
        import datetime as _dt
        if dt.tzinfo is not None:
            offset = _dt.timedelta(hours=5, minutes=30)
            local_dt = dt + offset
        else:
            local_dt = dt
        local_hour = local_dt.hour
        local_minute = local_dt.minute
    if not schedule.enabled:
        return local_hour >= 22 or local_hour < 6
    current_minutes = local_hour * 60 + local_minute
    start_minutes = schedule.start_hour * 60 + schedule.start_minute
    end_minutes = schedule.end_hour * 60 + schedule.end_minute
    if start_minutes <= end_minutes:
        is_business_hours = start_minutes <= current_minutes < end_minutes
    else:
        is_business_hours = current_minutes >= start_minutes or current_minutes < end_minutes
    return not is_business_hours


class ScoringEngine:
    """
    4-Tier Enterprise Video Surveillance Risk & Severity Scoring Engine:
    Tier 1: Normal Activity (0 - 35 pts) -> Daytime public motion, transit. Zero alerts.
    Tier 2: Elevated Activity (36 - 65 pts) -> Daytime dwell, boundary proximity. Audit indexed.
    Tier 3: Suspicious Activity (66 - 84 pts) -> Prolonged loitering, soft perimeter breach. Amber UI badge.
    Tier 4: Critical Threat (85 - 100 pts) -> Hard Geofence violation, after-hours intrusion. Automatic Telegram alert.
    """

    CLASS_WEIGHTS = {
        "person": 40,
        "vehicle": 35,
        "animal": 15,
        "unclassified": 0
    }

    def __init__(self, alert_threshold: int = 70):
        self.alert_threshold = alert_threshold

    @staticmethod
    def get_severity_tier(score: int) -> Dict[str, str]:
        """Returns industry-standard 4-tier risk classification."""
        if score >= 85:
            return {"tier": "critical", "label": "Critical Threat", "color": "#ef4444", "badge_class": "badge-critical"}
        elif score >= 66:
            return {"tier": "suspicious", "label": "Suspicious Activity", "color": "#f59e0b", "badge_class": "badge-suspicious"}
        elif score >= 36:
            return {"tier": "elevated", "label": "Elevated Activity", "color": "#38bdf8", "badge_class": "badge-elevated"}
        else:
            return {"tier": "normal", "label": "Normal Activity", "color": "#94a3b8", "badge_class": "badge-normal"}

    def evaluate(
        self,
        candidate: DetectionCandidate,
        camera_bias: int = 0
    ) -> Tuple[int, bool, Dict[str, Any]]:
        """
        Computes the 5-layer score per SCORING_SPEC.md + 3 additional precision layers.
        Returns (score, should_alert, breakdown).
        Layer 0:  Schedule & Zone Hard Gate (gating condition)
        Layer 1:  Motion Extent (0-20 pts)
        Layer 2:  Classification Confidence (0-30 pts) with IR calibration
        Layer 3:  Object-Type Base Weight (0-40 pts)
        Layer 4:  Nuisance Penalty vs Hard Floor (50 pts for valid detections)
        Layer 5:  Persistence/Loitering Bonus (0-15 pts)
        Layer 6:  Zone Proximity Bonus — inside restricted zone (+15 pts)
        Layer 7:  Velocity Penalty — fast-moving objects are transit, not threats (-10 pts)
        Layer 8:  Consecutive-frame confirmation — dampens single-frame spikes
        """
        # ── Layer 0: Hard Gate ──────────────────────────────────────────────
        gate_l0_passed = candidate.is_after_hours or candidate.is_in_restricted_zone
        # Night IR vs daylight confidence floor
        conf_min = 0.25 if candidate.is_night_ir else 0.35
        is_valid_detection = (
            candidate.object_type in ["person", "vehicle", "animal"]
            and candidate.confidence >= conf_min
        )
        # ── Layer 1: Motion Extent (0–20 pts) ───────────────────────────────
        l1 = min(20, round(candidate.motion_ratio * 200))
        # ── Layer 2: Confidence (0–30 pts) ──────────────────────────────────
        l2 = min(30, round(candidate.confidence * 30))
        # ── Layer 3: Object-Type Base Weight (0–40 pts) ─────────────────────
        object_key = candidate.object_type if is_valid_detection else "unclassified"
        l3 = self.CLASS_WEIGHTS.get(object_key, 0)
        subtotal_123 = l1 + l2 + l3
        # ── Layer 4: Nuisance Penalty vs Valid Floor ─────────────────────────
        if is_valid_detection:
            if candidate.object_type in ["person", "vehicle"] and gate_l0_passed:
                threat_floor = max(self.alert_threshold, 70)
            elif candidate.object_type in ["person", "vehicle"]:
                threat_floor = 50
            else:
                threat_floor = 30  # Non-priority (animals) maintains buffer below alert threshold
            subtotal_1234 = max(threat_floor, subtotal_123)
            l4_adjustment = subtotal_1234 - subtotal_123
        else:
            # Unclassified motion: apply -35 nuisance penalty + camera bias dampening
            effective_penalty = -35 + min(0, camera_bias)
            subtotal_1234 = max(0, subtotal_123 + effective_penalty)
            threat_floor = 0
            l4_adjustment = effective_penalty
        # ── Layer 5: Persistence Bonus (0–15 pts, +3 pts/sec) ────────────────
        # Uses track_duration_sec from IoU tracker
        l5 = min(15, round(candidate.track_duration_sec * 3))
        # ── Layer 6: Zone Proximity Bonus (+15 pts if inside restricted zone) ─
        # Applies only to valid detections in restricted zones
        l6_zone_bonus = 0
        if is_valid_detection and candidate.is_in_restricted_zone:
            l6_zone_bonus = 15
        # ── Layer 7: Velocity Penalty (fast transit = not a threat) ───────────
        # velocity_hint is optional — 0.0 = stationary, 1.0 = fast
        # If not provided, no penalty (default safe behavior)
        l7_velocity_penalty = 0
        velocity_hint = getattr(candidate, "velocity_hint", 0.0) or 0.0
        if is_valid_detection and velocity_hint > 0.6:
            # Fast-moving object (transit, not loitering) — reduce score
            l7_velocity_penalty = -10
        elif is_valid_detection and velocity_hint > 0.4:
            l7_velocity_penalty = -5
        # ── Layer 8: Consecutive Frame Confirmation ───────────────────────────
        # Smooths single-frame spikes. 
        # consecutive_frames is optional on the candidate — if not available, no dampening.
        # 0-1 frames: apply 0.75x multiplier (reduce spike alerts)
        # 2 frames:   apply 0.90x multiplier
        # 3+ frames:  full score (no dampening)
        consecutive_frames = getattr(candidate, "consecutive_frames", 3) or 3
        if consecutive_frames <= 1:
            confirmation_multiplier = 0.75
        elif consecutive_frames == 2:
            confirmation_multiplier = 0.90
        else:
            confirmation_multiplier = 1.0
        # ── Final Score Assembly ──────────────────────────────────────────────
        raw_score = subtotal_1234 + l5 + l6_zone_bonus + l7_velocity_penalty
        final_score = min(100, max(0, round(raw_score * confirmation_multiplier)))
        # ── Alert Decision ────────────────────────────────────────────────────
        # SPEC: Alert threshold = 70 (not 85)
        # Must also pass Layer 0 gate
        should_alert = (final_score >= self.alert_threshold) and gate_l0_passed
        tier_info = self.get_severity_tier(final_score)
        breakdown = {
            "l1_motion": l1,
            "l2_confidence": l2,
            "l3_object_weight": l3,
            "l4_adjustment": l4_adjustment,
            "l5_persistence": l5,
            "l6_zone_bonus": l6_zone_bonus,
            "l7_velocity_penalty": l7_velocity_penalty,
            "l8_confirmation_multiplier": confirmation_multiplier,
            "camera_bias": camera_bias,
            "threat_floor": threat_floor,
            "subtotal": subtotal_1234 + l5,
            "subtotal_before_layers6_8": subtotal_1234 + l5,
            "raw_score_before_confirmation": raw_score,
            "final_score": final_score,
            "gate_l0_passed": gate_l0_passed,
            "should_alert": should_alert,
            "is_valid_detection": is_valid_detection,
            "severity_tier": tier_info["tier"],
            "severity_label": tier_info["label"]
        }
        return final_score, should_alert, breakdown
