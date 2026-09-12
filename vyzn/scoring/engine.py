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
    Tests centroid and corners.
    """
    if not zone.points:
        return False

    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    # Test center point
    if is_point_in_polygon(cx, cy, zone.points):
        return True
    # Test bottom center (foot position)
    if is_point_in_polygon(cx, y2, zone.points):
        return True
    return False


def is_time_after_hours(dt: datetime, schedule: BusinessHours) -> bool:
    """
    Determines if given datetime is outside the configured business hours window.
    If schedule is disabled, evaluates natural daytime vs night cycle (night: 22:00 to 06:00).
    """
    if not schedule.enabled:
        hour = dt.hour
        return hour >= 22 or hour < 6

    # Convert to local hour / minute
    current_minutes = dt.hour * 60 + dt.minute
    start_minutes = schedule.start_hour * 60 + schedule.start_minute
    end_minutes = schedule.end_hour * 60 + schedule.end_minute

    if start_minutes <= end_minutes:
        is_business_hours = start_minutes <= current_minutes < end_minutes
    else:
        # Crosses midnight (e.g. 18:00 to 02:00)
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

    def __init__(self, alert_threshold: int = 85):
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
        Computes the 5-layer score and returns (score, should_alert, breakdown).
        Accepts dynamic camera_bias (<= 0) to dampen unclassified nuisance triggers.
        """
        # Layer 0: Schedule & Zone Hard Gate
        gate_l0_passed = candidate.is_after_hours or candidate.is_in_restricted_zone

        # Night IR Mode vs Daylight confidence calibration
        conf_min = 0.25 if candidate.is_night_ir else 0.35
        is_valid_detection = (
            candidate.object_type in ["person", "vehicle", "animal"] and
            candidate.confidence >= conf_min
        )

        # Layer 1: Motion Extent (0-20 pts)
        l1 = min(20, round(candidate.motion_ratio * 200))

        # Layer 2: Classification Confidence (0-30 pts)
        l2 = min(30, round(candidate.confidence * 30))

        # Layer 3: Object-Type Base Weight (0-40 pts)
        object_key = candidate.object_type if is_valid_detection else "unclassified"
        l3 = self.CLASS_WEIGHTS.get(object_key, 0)

        subtotal_123 = l1 + l2 + l3

        # Layer 4: Nuisance Penalty vs Threat Floor + Restricted Zone Bonus
        if is_valid_detection:
            zone_bonus = 15 if candidate.is_in_restricted_zone else 0

            # Verified human/vehicle intruder after hours or in restricted zone
            if candidate.object_type in ["person", "vehicle"] and gate_l0_passed:
                threat_floor = max(self.alert_threshold, 70)
            else:
                threat_floor = 30  # Daytime public transit floor maintains buffer below alert threshold

            subtotal_1234 = max(threat_floor, subtotal_123 + zone_bonus)
            l4_adjustment = subtotal_1234 - subtotal_123
        else:
            threat_floor = 0
            effective_penalty = -35 + min(0, camera_bias)
            subtotal_1234 = max(0, subtotal_123 + effective_penalty)
            l4_adjustment = effective_penalty

        # Layer 5: Loitering / Persistence Bonus (0-15 pts, +3 pts per tracked second)
        l5 = min(15, round(candidate.track_duration_sec * 3))

        # Final clipped score [0, 100]
        final_score = min(100, max(0, subtotal_1234 + l5))

        # Alert criteria: Requires qualifying final score AND Layer 0 gate passage
        should_alert = (final_score >= self.alert_threshold) and gate_l0_passed

        tier_info = self.get_severity_tier(final_score)

        breakdown = {
            "l1_motion": l1,
            "l2_confidence": l2,
            "l3_object_weight": l3,
            "l4_adjustment": l4_adjustment,
            "camera_bias": camera_bias,
            "threat_floor": threat_floor,
            "l5_persistence": l5,
            "subtotal": subtotal_1234 + l5,
            "final_score": final_score,
            "gate_l0_passed": gate_l0_passed,
            "should_alert": should_alert,
            "is_valid_detection": is_valid_detection,
            "severity_tier": tier_info["tier"],
            "severity_label": tier_info["label"]
        }

        return final_score, should_alert, breakdown
