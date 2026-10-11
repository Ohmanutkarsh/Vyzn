"""
VYZN Scoring Engine v2.0 - 13-Layer Threat Scoring & Tier Determination.
Deterministic, mathematically verified, fully explainable scoring pipeline.
Levels 1-5, Layers 0-12 with strict tier boundaries:
  - ALERT:  >= 70 (Immediate Telegram alert + Priority index)
  - REVIEW: 30 - 69 (Kept saved, never auto-deleted by 72h job)
  - LOW:    < 30 (Kept 72 hours, auto-purged by reaper)
"""

from __future__ import annotations
import math
import decimal
from typing import Tuple, Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from vyzn.core.events import DetectionCandidate
from vyzn.core.config import BusinessHours, ZonePolygon, get_scoring_config


def round_half_up(val: float) -> int:
    """Deterministic round half up implementation."""
    d = decimal.Decimal(str(round(val, 6)))
    return int(d.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP))


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
    """Checks if bounding box [x1, y1, x2, y2] intersects zone polygon."""
    if not zone.points or len(zone.points) < 3:
        return False
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    test_points = [
        (cx, cy),
        (cx, y2),
        (x1, y2),
        (x2, y2),
        (cx, (cy + y2) / 2.0),
    ]
    for px, py in test_points:
        if is_point_in_polygon(px, py, zone.points):
            return True
    return False


def is_foot_in_polygon(box: List[float], polygon_points: List[List[float]]) -> bool:
    """Evaluates whether the feet (bottom-centre of detection box) lies inside polygon."""
    if not polygon_points or len(polygon_points) < 3:
        return False
    x1, y1, x2, y2 = box
    foot_x = (x1 + x2) / 2.0
    foot_y = y2
    return is_point_in_polygon(foot_x, foot_y, polygon_points)


def is_time_after_hours(
    dt: datetime,
    schedule: BusinessHours,
    shoulder_minutes: int = 15,
    authorized_windows: Optional[List[Tuple[str, str]]] = None,
    tz_name: str = "Asia/Kolkata"
) -> bool:
    """
    Determines if given datetime is outside business hours.
    Timezone-aware with +/- 15 min shoulder neutrality and authorized window neutrality.
    """
    try:
        import pytz
        tz = pytz.timezone(tz_name)
        if dt.tzinfo is not None:
            local_dt = dt.astimezone(tz)
        else:
            local_dt = dt
    except Exception:
        if dt.tzinfo is not None:
            offset = timedelta(hours=5, minutes=30)
            local_dt = dt + offset
        else:
            local_dt = dt

    local_hour = local_dt.hour
    local_minute = local_dt.minute
    current_minutes = local_hour * 60 + local_minute

    # 1. Check authorized windows neutrality (e.g. [("06:00", "07:00")])
    if authorized_windows:
        for win_start, win_end in authorized_windows:
            try:
                sh, sm_m = map(int, win_start.split(":"))
                eh, em_m = map(int, win_end.split(":"))
                w_start = sh * 60 + sm_m
                w_end = eh * 60 + em_m
                if w_start <= w_end:
                    if w_start <= current_minutes < w_end:
                        return False  # Authorized window is neutral
                else:
                    if current_minutes >= w_start or current_minutes < w_end:
                        return False
            except Exception:
                pass

    if not schedule.enabled:
        # Default after-hours: 22:00 to 06:00
        return local_hour >= 22 or local_hour < 6

    start_minutes = schedule.start_hour * 60 + schedule.start_minute
    end_minutes = schedule.end_hour * 60 + schedule.end_minute

    # Shoulder neutrality: expand business hours by shoulder_minutes on both sides
    eff_start = max(0, start_minutes - shoulder_minutes)
    eff_end = min(1440, end_minutes + shoulder_minutes)

    if eff_start <= eff_end:
        is_business_hours = eff_start <= current_minutes < eff_end
    else:
        is_business_hours = current_minutes >= eff_start or current_minutes < eff_end

    return not is_business_hours


class ScoringEngine:
    """
    VYZN v2.0 Enterprise Risk & Severity Scoring Engine.
    Executes Layers 0 to 12 deterministically using config/scoring.json parameters.
    """

    def __init__(self, alert_threshold: int = 70):
        self.alert_threshold = alert_threshold
        self._cfg = get_scoring_config()

    def get_config(self) -> Dict[str, Any]:
        if not self._cfg:
            self._cfg = get_scoring_config(reload=True)
        return self._cfg

    @staticmethod
    def get_severity_tier(score: int) -> Dict[str, str]:
        """Maps final integer score to tier and UI severity label."""
        if score >= 70:
            tier = "alert"
        elif score >= 30:
            tier = "review"
        else:
            tier = "low"

        if score >= 85:
            label = "Critical"
            badge = "badge-critical"
            color = "#ef4444"
        elif score >= 70:
            label = "High"
            badge = "badge-high"
            color = "#f97316"
        elif score >= 50:
            label = "Medium"
            badge = "badge-medium"
            color = "#f59e0b"
        elif score >= 30:
            label = "Notable"
            badge = "badge-notable"
            color = "#38bdf8"
        else:
            label = "Low"
            badge = "badge-low"
            color = "#94a3b8"

        return {
            "tier": tier,
            "label": label,
            "color": color,
            "badge_class": badge
        }

    def evaluate(
        self,
        candidate: DetectionCandidate,
        camera_bias: int = 0,
        camera_override: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, bool, Dict[str, Any]]:
        """
        Evaluates candidate against Layers 0-12 and returns (final_score, should_alert, breakdown).
        """
        cfg = camera_override or self.get_config()
        l_cfg = cfg.get("level3_layers", {})

        # Extract candidate attributes
        obj_type = getattr(candidate, "object_type", "unclassified").lower()
        conf = float(getattr(candidate, "confidence", 0.0) or 0.0)
        motion_ratio = float(getattr(candidate, "motion_ratio", 0.0) or 0.0)
        track_dur = float(getattr(candidate, "track_duration_sec", 0.0) or 0.0)
        box = getattr(candidate, "bounding_box", [0.0, 0.0, 1.0, 1.0]) or [0.0, 0.0, 1.0, 1.0]
        is_night_ir = bool(getattr(candidate, "is_night_ir", False))
        is_after_hours = bool(getattr(candidate, "is_after_hours", False))
        is_restricted = bool(getattr(candidate, "is_in_restricted_zone", False))
        is_watch_area = bool(getattr(candidate, "is_watch_area", False))

        # Additional layer hints
        if getattr(candidate, "track_hits", None) is not None:
            track_hits = int(candidate.track_hits)
        elif getattr(candidate, "consecutive_frames", None) is not None:
            track_hits = int(candidate.consecutive_frames)
        else:
            track_hits = 5

        c_mean = float(getattr(candidate, "c_mean", None) if getattr(candidate, "c_mean", None) is not None else conf)
        c_std = float(getattr(candidate, "c_std", 0.0) or 0.0)
        id_switches = int(getattr(candidate, "id_switch_count", 0) or 0)
        bbox_height = float(getattr(candidate, "bbox_height_ratio", None) if getattr(candidate, "bbox_height_ratio", None) is not None else (box[3] - box[1] if len(box) >= 4 else 0.2))
        velocity_hint = float(getattr(candidate, "velocity_hint", 0.0) or 0.0)
        approach_restricted = bool(getattr(candidate, "approach_restricted", False))
        repeated_passes = bool(getattr(candidate, "repeated_passes", False))
        is_unattended = bool(getattr(candidate, "is_unattended", False))
        unattended_dur = float(getattr(candidate, "unattended_duration_sec", 0.0) or (track_dur if (is_unattended or obj_type == "carried_item") else 0.0))
        routine_prob = getattr(candidate, "routine_probability", None)
        days_history = int(getattr(candidate, "days_of_history", 0) or 0)
        staff_expected = bool(getattr(candidate, "staff_expected", False))
        is_authorized_window = bool(getattr(candidate, "is_authorized_window", False))
        is_shoulder_window = bool(getattr(candidate, "is_shoulder_window", False))
        d4_modifier_input = getattr(candidate, "d4_modifier", None)

        # Authorized & shoulder window neutrality
        if is_authorized_window or is_shoulder_window:
            is_after_hours = False

        # ── Layer 9: Reliability Multiplier R9 in [0.5, 1.0] ────────────────
        l9_cfg = l_cfg.get("layer9_reliability", {})
        r9 = 1.0
        if obj_type != "unclassified":
            if bbox_height < l9_cfg.get("small_bbox_height_ratio", 0.06):
                r9 *= l9_cfg.get("small_bbox_penalty", 0.70)
            if c_std > l9_cfg.get("high_conf_std_thresh", 0.20):
                r9 *= l9_cfg.get("high_conf_variance_penalty", 0.85)
            if id_switches >= 2:
                r9 *= l9_cfg.get("frequent_id_switch_penalty", 0.75)
            # Implausible aspect ratio in IR night
            if is_night_ir and len(box) >= 4:
                bw = max(0.01, box[2] - box[0])
                bh = max(0.01, box[3] - box[1])
                if bw / bh > 3.0:
                    r9 *= l9_cfg.get("implausible_ir_aspect_penalty", 0.80)

        r9 = max(l9_cfg.get("min_multiplier", 0.50), min(1.0, float(r9)))

        # ── Layer 0: Context & Confirmation Gating ──────────────────────────
        l0_cfg = l_cfg.get("layer0", {})
        conf_min_hits = l0_cfg.get("confirmed_min_hits", 5)
        conf_min_conf = l0_cfg.get("confirmed_min_confidence", 0.45)
        conf_min_rel = l0_cfg.get("confirmed_min_reliability", 0.80)

        is_confirmed = (
            track_hits >= conf_min_hits
            and (c_mean >= conf_min_conf or is_restricted)
            and r9 >= conf_min_rel
            and obj_type in ["person", "vehicle", "animal", "carried_item"]
        )

        # Threat floors (applied only to confirmed events, or unexplained motion in restricted after hours)
        floors_cfg = l_cfg.get("layer4_threat_floors", {})
        threat_floor = 0
        is_active_restricted = is_restricted and (is_after_hours or not staff_expected)
        if is_confirmed or (is_active_restricted and obj_type in ["person", "vehicle"] and track_hits >= 3):
            if obj_type == "person":
                if is_after_hours or is_active_restricted:
                    base_floor = float(floors_cfg.get("person_after_hours_or_restricted", 70))
                    if self.alert_threshold != 70:
                        threat_floor = float(self.alert_threshold)
                    else:
                        threat_floor = base_floor
            elif obj_type == "vehicle":
                if is_after_hours and is_restricted:
                    threat_floor = float(floors_cfg.get("vehicle_restricted_after_hours", 70))
                elif is_after_hours:
                    threat_floor = float(floors_cfg.get("vehicle_after_hours", 55))
            elif obj_type == "animal":
                if is_after_hours:
                    threat_floor = float(floors_cfg.get("animal_layer0", 30))
        elif obj_type == "unclassified" and is_restricted and is_after_hours and track_dur >= 3.0:
            threat_floor = float(floors_cfg.get("unexplained_motion_restricted_after_hours", 30))

        # ── Layer 1: Motion Extent (0-10 pts) ────────────────────────────────
        l1_cfg = l_cfg.get("layer1_motion_extent", {})
        l1_scale = l1_cfg.get("scale", 0.03)
        l1_max = l1_cfg.get("max_points", 10.0)
        l1 = l1_max * (1.0 - math.exp(-motion_ratio / max(1e-4, l1_scale)))
        l1 = max(0.0, min(float(l1_max), l1))

        # ── Layer 2: Classification Confidence (0-15 pts) ───────────────────
        l2_cfg = l_cfg.get("layer2_confidence", {})
        l2_min = l2_cfg.get("conf_min", 0.35)
        l2_range = l2_cfg.get("conf_range", 0.50)
        l2_max = l2_cfg.get("max_points", 15.0)
        if obj_type == "unclassified":
            l2 = 0.0
        else:
            norm_c = max(0.0, min(1.0, (c_mean - l2_min) / max(1e-4, l2_range)))
            l2 = l2_max * norm_c

        # ── Layer 3: Object Base Weight ─────────────────────────────────────
        l3_weights = l_cfg.get("layer3_object_weights", {
            "person": 20, "vehicle": 14, "animal": 5, "carried_item": 3, "unclassified": 0
        })
        l3 = float(l3_weights.get(obj_type, 0.0))

        # ── Layer 4: Nuisance Penalties ─────────────────────────────────────
        l4_penalties = l_cfg.get("layer4_nuisance_penalties", {
            "person": -12, "vehicle": -12, "animal": -4, "unclassified": -35, "unclassified_relaxed": -15
        })
        l4_pen = 0.0
        if obj_type == "unclassified":
            if is_restricted and is_after_hours:
                l4_pen = float(l4_penalties.get("unclassified_relaxed", -15))
            else:
                l4_pen = float(l4_penalties.get("unclassified", -35))
        elif not is_after_hours and not is_restricted and not is_authorized_window and not is_shoulder_window:
            l4_pen = float(l4_penalties.get(obj_type, 0.0))

        # ── Layer 5: Loitering (0-20 pts) ───────────────────────────────────
        dwell_sec = float(getattr(candidate, "dwell_sec", track_dur) if getattr(candidate, "dwell_sec", None) is not None else track_dur)
        if obj_type != "person":
            dwell_sec = 0.0
        if staff_expected and not is_after_hours:
            dwell_sec = 0.0

        l5_cfg = l_cfg.get("layer5_loitering", {})
        grace = l5_cfg.get("grace_period_sec", 10.0)
        rate = l5_cfg.get("rate_per_sec", 0.4)
        c_factor = l5_cfg.get("after_hours_context_factor", 1.0) if is_after_hours else l5_cfg.get("business_hours_context_factor", 0.5)
        l5 = rate * max(0.0, dwell_sec - grace) * c_factor
        l5 = max(0.0, min(float(l5_cfg.get("max_points", 20.0)), l5))

        # ── Layer 6: Zone Proximity ─────────────────────────────────────────
        l6_cfg = l_cfg.get("layer6_zone", {})
        restr_weight = l6_cfg.get("restricted_weight", 15.0)
        watch_weight = l6_cfg.get("watch_weight", 6.0)
        zone_pts = 0.0
        if is_restricted:
            zone_pts = restr_weight
        elif is_watch_area:
            zone_pts = watch_weight

        if staff_expected and not is_after_hours:
            l6 = 0.0
        else:
            l6 = zone_pts

        # ── Layer 7: Velocity Penalty ───────────────────────────────────────
        l7_cfg = l_cfg.get("layer7_velocity", {})
        if not (is_after_hours or is_restricted):
            if velocity_hint > l7_cfg.get("fast_thresh", 0.6):
                l7_pen = float(l7_cfg.get("fast_penalty", -10.0))
            elif velocity_hint > l7_cfg.get("moderate_thresh", 0.4):
                l7_pen = float(l7_cfg.get("moderate_penalty", -5.0))
            else:
                l7_pen = 0.0
        else:
            l7_pen = 0.0

        # ── Layer 8: Multi-frame Multiplier M8 ──────────────────────────────
        l8_cfg = l_cfg.get("layer8_multiframe_multipliers", {
            "1": 0.30, "2": 0.55, "3": 0.80, "4": 0.92, "5_plus": 1.00
        })
        if track_hits <= 1:
            m8 = float(l8_cfg.get("1", 0.30))
        elif track_hits == 2:
            m8 = float(l8_cfg.get("2", 0.55))
        elif track_hits == 3:
            m8 = float(l8_cfg.get("3", 0.80))
        elif track_hits == 4:
            m8 = float(l8_cfg.get("4", 0.92))
        else:
            m8 = float(l8_cfg.get("5_plus", 1.00))

        # ── Layer 10: Baseline Routine Activity [-15, +8] ───────────────────
        l10_cfg = l_cfg.get("layer10_baseline", {})
        cold_start = l10_cfg.get("cold_start_days", 7)
        if days_history < cold_start or routine_prob is None:
            l10 = 0.0
        elif routine_prob >= l10_cfg.get("routine_p_thresh_high", 0.70):
            l10 = float(l10_cfg.get("routine_penalty_high", -15.0))
        elif routine_prob >= l10_cfg.get("routine_p_thresh_med", 0.40):
            l10 = float(l10_cfg.get("routine_penalty_med", -8.0))
        elif routine_prob < l10_cfg.get("novel_p_thresh", 0.10) and days_history >= l10_cfg.get("min_days_history_for_novel", 14):
            l10 = float(l10_cfg.get("novel_bonus", 8.0))
        else:
            l10 = 0.0

        # ── Layer 11: Behavioral Pattern ────────────────────────────────────
        l11_cfg = l_cfg.get("layer11_behavior", {})
        l11 = 0.0
        if repeated_passes:
            l11 += float(l11_cfg.get("repeated_passes_bonus", 5.0))
        if approach_restricted:
            l11 += float(l11_cfg.get("approaching_restricted_bonus", 5.0))
        l11 = min(10.0, l11)

        # ── Layer 12: Unattended Object ─────────────────────────────────────
        l12_cfg = l_cfg.get("layer12_unattended_object", {})
        l12 = 0.0
        if l12_cfg.get("enabled", True):
            if (obj_type in ("carried_item", "unclassified") or is_unattended) and conf >= l12_cfg.get("min_confidence", 0.50):
                if unattended_dur >= 60.0:
                    l12 = float(l12_cfg.get("stationary_60s_bonus", 20.0))
                elif unattended_dur >= 30.0:
                    l12 = float(l12_cfg.get("stationary_30s_bonus", 10.0))

        # ── Level 4 Forensic Modifier D4 (0..37) ────────────────────────────
        d4_cfg = cfg.get("level4_forensic_modifiers", {})
        if d4_modifier_input is not None:
            d4 = float(d4_modifier_input)
        else:
            d4 = 0.0
            if obj_type == "person":
                d4 += float(d4_cfg.get("person_present", 5.0))
            if is_after_hours:
                d4 += float(d4_cfg.get("outside_business_hours", 10.0))
            if is_night_ir:
                d4 += float(d4_cfg.get("infrared_night", 4.0))
            if dwell_sec >= 30.0 and not (staff_expected and not is_after_hours):
                d4 += float(d4_cfg.get("loitering_30s", 6.0))
            if track_dur >= 45.0 and not (staff_expected and not is_after_hours):
                d4 += float(d4_cfg.get("extended_duration_45s", 4.0))
            max_d4 = float(d4_cfg.get("max_d4", 37.0))
            d4 = max(0.0, min(max_d4, d4))

        # ── Score Composition Formula ───────────────────────────────────────
        positives = l1 + l2 + l3 + l5 + l6 + l11 + l12
        adjust = l4_pen + l7_pen + l10 + min(0, camera_bias)
        raw3 = max(0.0, positives + adjust)
        s3 = raw3 * m8 * r9
        s_live = max(0.0, min(100.0, s3 + d4))

        # ── Caps & Floors Order ─────────────────────────────────────────────
        # 1. Caps: Unconfirmed (< 3 hits) or pure motion with no object -> cap at 29
        s_final = s_live
        if (not is_confirmed and track_hits < 3) or (obj_type == "unclassified" and not (is_restricted and is_after_hours)):
            s_final = min(s_final, 29.0)

        # 2. Floors: Applied ONLY to confirmed events or unexplained motion in restricted after hours
        if threat_floor > 0 and (is_confirmed or (obj_type == "unclassified" and is_restricted and is_after_hours)):
            s_final = max(s_final, float(threat_floor))

        # 3. Round half-up, clamp 0..100
        final_score = max(0, min(100, round_half_up(s_final)))
        score_raw = round(float(s_final), 2)

        # Tier assignment
        tiers_cfg = cfg.get("tiers", {})
        alert_thresh = self.alert_threshold if self.alert_threshold is not None else tiers_cfg.get("alert_threshold", 70)
        review_min = tiers_cfg.get("review_min_score", 30)

        if final_score >= alert_thresh:
            tier = "alert"
            should_alert = True
        elif final_score >= review_min:
            tier = "review"
            should_alert = False
        else:
            tier = "low"
            should_alert = False

        severity_info = self.get_severity_tier(final_score)

        breakdown: Dict[str, Any] = {
            "scoring_version": 2,
            "l0_is_after_hours": is_after_hours,
            "l0_is_confirmed": is_confirmed,
            "l0_threat_floor": threat_floor,
            "l1_motion": round(l1, 2),
            "l2_confidence": round(l2, 2),
            "l3_object_weight": round(l3, 2),
            "l4_nuisance_penalty": round(l4_pen, 2),
            "l4_threat_floor": threat_floor,
            "l5_loitering": round(l5, 2),
            "l6_zone_proximity": round(l6, 2),
            "l7_velocity_penalty": round(l7_pen, 2),
            "l8_multiframe_multiplier": round(m8, 2),
            "l9_reliability_multiplier": round(r9, 2),
            "l10_baseline_adjustment": round(l10, 2),
            "l11_behavior_pattern": round(l11, 2),
            "l12_unattended_object": round(l12, 2),
            "raw3": round(raw3, 2),
            "s3": round(s3, 2),
            "d4_modifier": round(d4, 2),
            "s_live": round(s_live, 2),
            "score_raw": score_raw,
            "final_score": final_score,
            "tier": tier,
            "severity_label": severity_info["label"],
            # Backwards compatibility fields
            "threat_floor": threat_floor,
            "subtotal": round(raw3, 2),
            "raw_score_before_confirmation": round(raw3, 2),
            "gate_l0_passed": is_after_hours or is_restricted,
            "should_alert": should_alert,
            "is_valid_detection": is_confirmed or (obj_type in ["person", "vehicle", "animal", "carried_item"] and conf >= 0.25),
            "severity_tier": severity_info["tier"],
            "camera_bias": camera_bias,
            "l4_adjustment": round(l4_pen, 2),
            "l5_persistence": round(l5, 2),
            "l6_zone_bonus": round(l6, 2),
            "l8_confirmation_multiplier": round(m8, 2),
        }

        return final_score, should_alert, breakdown
