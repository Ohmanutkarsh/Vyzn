# ==============================================================================
# VYZN AI THREAT SCORING ENGINE (THE BRAIN & JUDGE)
#
# WHY THIS EXISTS (FOR NON-PROGRAMMERS):
# Standard CCTV cameras send hundreds of annoying false alarms (spiders, car lights,
# shadows, wind). Nobody wants their phone buzzing 500 times a night.
#
# This Scoring Engine evaluates every single movement from 0 to 100 points:
# - ALERT (Score >= 70): Real emergency! Sends immediate Telegram alert to your phone.
# - REVIEW (Score 30 to 69): Kept saved on the website for you to see. Never auto-deleted.
# - LOW (Score < 30): Harmless noise (bugs, shadows). Auto-purged after 72 hours.
# ==============================================================================

from __future__ import annotations
import math
import decimal
from typing import Tuple, Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from vyzn.core.events import DetectionCandidate
from vyzn.core.config import BusinessHours, ZonePolygon, get_scoring_config


# ------------------------------------------------------------------------------
# MATH HELPER: Round half up (0.5 always rounds up to 1, guaranteeing exact scores)
# ------------------------------------------------------------------------------
def round_half_up(val: float) -> int:
    d = decimal.Decimal(str(round(val, 6)))
    return int(d.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP))


# ------------------------------------------------------------------------------
# GEOMETRY HELPER: Check if a point (X, Y) is inside a drawn polygon area
# Uses the classic "Ray Casting" algorithm: imagine shooting a laser from the
# point to infinity. If it crosses the fence an odd number of times, it's inside!
# ------------------------------------------------------------------------------
def is_point_in_polygon(x: float, y: float, polygon_points: List[List[float]]) -> bool:
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


# ------------------------------------------------------------------------------
# BOUNDING BOX HELPER: Check if a detected person or car box touches a watch area
# ------------------------------------------------------------------------------
def check_box_intersects_zone(box: List[float], zone: ZonePolygon) -> bool:
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
        # ==============================================================================
        # STEP 1: LOAD RISK SCORING RULES & READ DETECTION DATA
        # ------------------------------------------------------------------------------
        # The AI grabs the rules configuration (or custom overrides for this specific camera)
        # and extracts everything the camera just detected:
        # - What was seen? (person, car, animal, carried bag, or unexplained motion)
        # - How confident is the AI model? (0% to 100%)
        # - Where is the object located on screen? (x, y coordinates and box size)
        # - Is the camera in night infrared mode? Is it after business hours?
        # ==============================================================================
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
        area_resp = str(getattr(candidate, "area_response", "") or "").lower().strip()
        is_alert_area = bool(getattr(candidate, "is_in_alert_area", False)) or (area_resp == "alert")
        is_review_area = bool(getattr(candidate, "is_in_review_area", False)) or (area_resp == "review")
        is_ignore_area = bool(getattr(candidate, "is_in_ignore_area", False)) or (area_resp == "ignore")

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

        # Authorized & shoulder window neutrality (e.g., scheduled morning trash pickup or guards)
        if is_authorized_window or is_shoulder_window:
            is_after_hours = False

        # ==============================================================================
        # STEP 2 (LAYER 9): CAMERA RELIABILITY MULTIPLIER (R9)
        # ------------------------------------------------------------------------------
        # Real-world CCTV cameras have glitches: rain drops, spider webs, headlights,
        # or tiny distant objects.
        # This layer checks if the detection looks "suspiciously fake or noisy":
        # - Is the box tiny (less than 6% of the screen height)? Penalty applied.
        # - Is AI confidence wildly flickering up and down? Penalty applied.
        # - In night vision, does the shape look like an impossible wide streak (car headlight glare)?
        # Multiplier scales the score between 0.5 (half confidence) and 1.0 (clean detection).
        # ==============================================================================
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

        # ==============================================================================
        # STEP 3 (LAYER 0): CONFIRMATION GATE & MINIMUM THREAT FLOORS
        # ------------------------------------------------------------------------------
        # To avoid buzzing the user's phone on single-frame glitches, an event must be
        # "CONFIRMED": seen for at least 5 frames with solid confidence and clean image.
        # If an intruder (person or vehicle) enters a restricted zone or appears after
        # hours, we set a "threat floor" (e.g., minimum score 70) so critical threats
        # cannot be accidentally dismissed.
        # ==============================================================================
        l0_cfg = l_cfg.get("layer0", {})
        conf_min_hits = l0_cfg.get("confirmed_min_hits", 5)
        conf_min_conf = l0_cfg.get("confirmed_min_confidence", 0.45)
        conf_min_rel = l0_cfg.get("confirmed_min_reliability", 0.80)

        # In simple terms: a real target must have verified confidence (>= 0.35 in restricted, >= 0.45 elsewhere)
        # to avoid hair or spinning fan flicker from being falsely confirmed as an intruder.
        min_required_conf = 0.35 if is_restricted else conf_min_conf
        is_confirmed = (
            track_hits >= conf_min_hits
            and c_mean >= min_required_conf
            and r9 >= conf_min_rel
            and obj_type in ["person", "vehicle", "animal", "carried_item"]
        )

        # Threat floors (applied only to confirmed events, or unexplained motion in restricted after hours)
        floors_cfg = l_cfg.get("layer4_threat_floors", {})
        threat_floor = 0
        if not is_ignore_area:
            is_active_restricted = (is_restricted or is_alert_area) and (is_after_hours or not staff_expected)
            if is_confirmed or (is_active_restricted and obj_type in ["person", "vehicle"] and track_hits >= 3 and c_mean >= 0.40):
                if obj_type == "person":
                    if is_after_hours or is_active_restricted:
                        base_floor = float(floors_cfg.get("person_after_hours_or_restricted", 70))
                        if self.alert_threshold != 70:
                            threat_floor = float(self.alert_threshold)
                        else:
                            threat_floor = base_floor
                    elif is_alert_area:
                        threat_floor = float(floors_cfg.get("person_alert_area_daytime", 55))
                elif obj_type == "vehicle":
                    if is_after_hours and (is_restricted or is_alert_area):
                        threat_floor = float(floors_cfg.get("vehicle_restricted_after_hours", 70))
                    elif is_after_hours:
                        threat_floor = float(floors_cfg.get("vehicle_after_hours", 55))
                elif obj_type == "animal":
                    if is_after_hours:
                        threat_floor = float(floors_cfg.get("animal_layer0", 30))
            elif obj_type == "unclassified" and (is_restricted or is_alert_area) and is_after_hours and track_dur >= 3.0:
                threat_floor = float(floors_cfg.get("unexplained_motion_restricted_after_hours", 30))

        # ==============================================================================
        # STEP 4 (LAYER 1): MOTION EXTENT (0 to 10 points)
        # ------------------------------------------------------------------------------
        # Measures how much of the camera's field of view is moving. A tiny flutter of leaves
        # gets near 0 points; a full human body moving across the yard gets up to 10 points.
        # ==============================================================================
        l1_cfg = l_cfg.get("layer1_motion_extent", {})
        l1_scale = l1_cfg.get("scale", 0.03)
        l1_max = l1_cfg.get("max_points", 10.0)
        l1 = l1_max * (1.0 - math.exp(-motion_ratio / max(1e-4, l1_scale)))
        l1 = max(0.0, min(float(l1_max), l1))

        # ==============================================================================
        # STEP 5 (LAYER 2): AI CLASSIFICATION CONFIDENCE (0 to 15 points)
        # ------------------------------------------------------------------------------
        # The clearer the AI model sees the object (e.g. 95% confident it's a person),
        # the more points it earns (up to 15 points).
        # ==============================================================================
        l2_cfg = l_cfg.get("layer2_confidence", {})
        l2_min = l2_cfg.get("conf_min", 0.35)
        l2_range = l2_cfg.get("conf_range", 0.50)
        l2_max = l2_cfg.get("max_points", 15.0)
        if obj_type == "unclassified":
            l2 = 0.0
        else:
            norm_c = max(0.0, min(1.0, (c_mean - l2_min) / max(1e-4, l2_range)))
            l2 = l2_max * norm_c

        # ==============================================================================
        # STEP 6 (LAYER 3): OBJECT BASE WEIGHT
        # ------------------------------------------------------------------------------
        # Humans are inherently higher security risks than cars, and cars are higher than cats.
        # Persons get 20 points, vehicles 14 points, animals 5 points, unknown motion 0 points.
        # ==============================================================================
        l3_weights = l_cfg.get("layer3_object_weights", {
            "person": 20, "vehicle": 14, "animal": 5, "carried_item": 3, "unclassified": 0
        })
        l3 = float(l3_weights.get(obj_type, 0.0))

        # ==============================================================================
        # STEP 7 (LAYER 4): NUISANCE DEDUCTIONS (FILTERING EVERYDAY DAYTIME NOISE)
        # ------------------------------------------------------------------------------
        # During broad daylight in open areas, people and cars are normal.
        # We subtract points (-12 pts) so normal daytime foot traffic doesn't spam alerts.
        # Unknown random motion gets a heavy penalty (-35 pts) to kill false alarms.
        # ==============================================================================
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

        # ==============================================================================
        # STEP 8 (LAYER 5): LOITERING / DWELL TIME (0 to 20 points)
        # ------------------------------------------------------------------------------
        # Someone walking past a gate in 3 seconds is normal.
        # Someone standing still near a boundary for over 10 seconds (grace period) accumulates
        # points steadily (0.4 points per second, up to 20 points).
        # ==============================================================================
        dwell_sec = float(getattr(candidate, "dwell_sec", track_dur) if getattr(candidate, "dwell_sec", None) is not None else track_dur)
        # In simple terms: loitering / dwell time can ONLY accumulate for confirmed person targets.
        # Fleeting unconfirmed noise (like hair flutter or spinning fan motion) must NEVER accumulate loitering points.
        if obj_type != "person" or not is_confirmed:
            dwell_sec = 0.0
        if staff_expected and not is_after_hours:
            dwell_sec = 0.0

        l5_cfg = l_cfg.get("layer5_loitering", {})
        grace = l5_cfg.get("grace_period_sec", 10.0)
        rate = l5_cfg.get("rate_per_sec", 0.4)
        c_factor = l5_cfg.get("after_hours_context_factor", 1.0) if is_after_hours else l5_cfg.get("business_hours_context_factor", 0.5)
        l5 = rate * max(0.0, dwell_sec - grace) * c_factor
        l5 = max(0.0, min(float(l5_cfg.get("max_points", 20.0)), l5))

        # ==============================================================================
        # STEP 9 (LAYER 6): ZONE PROXIMITY (RESTRICTED OR WATCH AREAS)
        # ==============================================================================
        # STEP 9 (LAYER 6): ZONE PROXIMITY & AREA RESPONSE
        # ------------------------------------------------------------------------------
        # If the user drew a polygon zone on the camera view:
        # - Alert Area: Score increases a bit (+18 to +23 points).
        # - Review Area: Score is according (+7 points).
        # - Ignore Area: Score is reduced significantly (-40 points).
        # ==============================================================================
        l6_cfg = l_cfg.get("layer6_zone", {})
        restr_weight = float(l6_cfg.get("restricted_weight", 18.0))
        watch_weight = float(l6_cfg.get("watch_weight", 7.0))
        ignore_penalty = float(l6_cfg.get("ignore_penalty", -40.0))
        zone_pts = 0.0

        if is_ignore_area:
            zone_pts = ignore_penalty
        elif is_alert_area or is_restricted:
            zone_pts = restr_weight
            if is_after_hours:
                zone_pts += 5.0
        elif is_review_area or is_watch_area:
            zone_pts = watch_weight

        if staff_expected and not is_after_hours and not is_ignore_area:
            l6 = 0.0
        else:
            l6 = zone_pts

        # ==============================================================================
        # STEP 10 (LAYER 7): VELOCITY PENALTY (FAST PASSING OBJECTS)
        # ------------------------------------------------------------------------------
        # A car driving fast on a nearby street visible at the camera border isn't a threat.
        # During daytime, high speed objects receive a negative deduction (-5 to -10 points).
        # ==============================================================================
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

        # ==============================================================================
        # STEP 11 (LAYER 8): MULTI-FRAME MULTIPLIER (M8)
        # ------------------------------------------------------------------------------
        # Single-frame detections (1 frame) get scaled down to 30% (0.30) to eliminate
        # camera glitch spikes. As the object stays tracked for 5+ frames, it scales to 100% (1.0).
        # ==============================================================================
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

        # ==============================================================================
        # STEP 12 (LAYER 10): HISTORICAL ROUTINE BASELINE (-15 to +8 points)
        # ------------------------------------------------------------------------------
        # Learns patterns over time: if a milk delivery van arrives every day at 6:00 AM,
        # it is recognized as routine (-15 points penalty). If something novel happens at 3:00 AM,
        # it receives a bonus (+8 points).
        # ==============================================================================
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

        # ==============================================================================
        # STEP 13 (LAYER 11): BEHAVIORAL PATTERN (REPEATED PASSES OR APPROACHING ZONE)
        # ------------------------------------------------------------------------------
        # If someone walks back and forth pacing repeatedly (+5 points) or heads directly
        # towards the restricted boundary (+5 points), add extra risk points.
        # ==============================================================================
        l11_cfg = l_cfg.get("behavior", {}) if "behavior" in l_cfg else l_cfg.get("layer11_behavior", {})
        l11 = 0.0
        if repeated_passes:
            l11 += float(l11_cfg.get("repeated_passes_bonus", 5.0))
        if approach_restricted:
            l11 += float(l11_cfg.get("approaching_restricted_bonus", 5.0))
        l11 = min(10.0, l11)

        # ==============================================================================
        # STEP 14 (LAYER 12): UNATTENDED OBJECT (ABANDONED BAGS OR PACKAGES)
        # ------------------------------------------------------------------------------
        # If a backpack or box is left behind without an owner:
        # - Left alone for 30 seconds -> +10 points.
        # - Left alone for 60 seconds -> +20 points.
        # ==============================================================================
        l12_cfg = l_cfg.get("layer12_unattended_object", {})
        l12 = 0.0
        if l12_cfg.get("enabled", True):
            if (obj_type in ("carried_item", "unclassified") or is_unattended) and conf >= l12_cfg.get("min_confidence", 0.50):
                if unattended_dur >= 60.0:
                    l12 = float(l12_cfg.get("stationary_60s_bonus", 20.0))
                elif unattended_dur >= 30.0:
                    l12 = float(l12_cfg.get("stationary_30s_bonus", 10.0))

        # ==============================================================================
        # STEP 15 (LEVEL 4): FORENSIC CONTEXT MODIFIERS (D4: 0 to 37 points)
        # ------------------------------------------------------------------------------
        # Additional situational awareness points:
        # - Person present: +5
        # - Outside business hours: +10
        # - Infrared night mode: +4
        # - Loitering 30+ seconds: +6
        # ==============================================================================
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
            if dwell_sec >= 30.0 and is_confirmed and not (staff_expected and not is_after_hours):
                d4 += float(d4_cfg.get("loitering_30s", 6.0))
            if track_dur >= 45.0 and is_confirmed and not (staff_expected and not is_after_hours):
                d4 += float(d4_cfg.get("extended_duration_45s", 4.0))
            max_d4 = float(d4_cfg.get("max_d4", 37.0))
            d4 = max(0.0, min(max_d4, d4))

        # ==============================================================================
        # STEP 16: FINAL MATHEMATICAL SCORE CALCULATION & CLAMPING
        # ------------------------------------------------------------------------------
        # 1. Add all positive points (motion, confidence, object type, dwell, zones, etc.).
        # 2. Add adjustments (nuisance deductions, speed penalties, routine penalty).
        # 3. Multiply by multi-frame stability (M8) and camera reliability (R9).
        # 4. Add forensic modifiers (D4).
        # 5. Cap unconfirmed glitches and background noise at max 20 (strictly below the 30 active threshold).
        # 6. Apply threat floor only when real confirmed targets are detected in restricted zones.
        # 7. Clamp final score strictly between 0 and 100.
        # ==============================================================================
        positives = l1 + l2 + l3 + l5 + l6 + l11 + l12
        adjust = l4_pen + l7_pen + l10 + min(0, camera_bias)
        raw3 = max(0.0, positives + adjust)
        s3 = raw3 * m8 * r9
        s_live = max(0.0, min(100.0, s3 + d4))

        # ── Caps & Floors Order ─────────────────────────────────────────────
        # In simple terms:
        # - Ignore Area: Score is reduced significantly (capped at <= 15, below the 30 active recording threshold).
        # - Alert Area: Score increases a bit (+8 boost, threat floor elevated to 70 after hours / 55 daytime).
        # - Review Area: Scored according to standard rules without artificial inflation.
        # - Unconfirmed glitches / background noise: Strictly capped at 20.
        if is_ignore_area:
            threat_floor = 0.0
            s_final = max(0.0, min(15.0, s_live - 35.0))
        else:
            s_final = s_live
            if is_alert_area and is_confirmed:
                s_final = min(100.0, s_final + 8.0)

            if not is_confirmed:
                s_final = min(s_final, 20.0)
            if obj_type == "unclassified" and not (is_restricted and is_after_hours and track_dur >= 3.0 and r9 >= 0.85):
                s_final = min(s_final, 20.0)

            # In simple terms: apply threat floor for confirmed targets or unexplained sustained motion inside restricted zone after hours
            if threat_floor > 0 and (is_confirmed or (obj_type == "unclassified" and (is_restricted or is_alert_area) and is_after_hours and track_dur >= 3.0 and r9 >= 0.85)):
                s_final = max(s_final, float(threat_floor))

        # Round to nearest whole number and ensure it stays between 0 and 100
        final_score = max(0, min(100, round_half_up(s_final)))
        score_raw = round(float(s_final), 2)

        # ==============================================================================
        # STEP 17: TIER ASSIGNMENT (ALERT vs REVIEW vs LOW)
        # ------------------------------------------------------------------------------
        # - Score >= 70: TIER = "ALERT" -> Immediate Telegram alert to owner/guard with photo.
        # - Score 30-69: TIER = "REVIEW" -> Saved in dashboard for security guard to review.
        # - Score < 30:  TIER = "LOW" -> Minor motion/nuisance; auto-deleted by disk cleaner.
        # ==============================================================================
        tiers_cfg = cfg.get("tiers", {})
        alert_thresh = self.alert_threshold if self.alert_threshold is not None else tiers_cfg.get("alert_threshold", 70)
        review_min = tiers_cfg.get("review_min_score", 30)

        if is_ignore_area:
            tier = "low"
            should_alert = False
        elif final_score >= alert_thresh:
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
            # Area response flags
            "is_in_alert_area": is_alert_area,
            "is_in_review_area": is_review_area,
            "is_in_ignore_area": is_ignore_area,
            "area_response": area_resp,
            # Backwards compatibility fields
            "threat_floor": threat_floor,
            "subtotal": round(raw3, 2),
            "raw_score_before_confirmation": round(raw3, 2),
            "gate_l0_passed": is_after_hours or is_restricted or is_alert_area,
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
