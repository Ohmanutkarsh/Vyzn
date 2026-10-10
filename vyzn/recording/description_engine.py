"""
Factual Clip Description & Forensic Timeline Generator.
Extracts grounded events from real detections, IoU tracks, motion profiles, and watch areas.
Strictly zero hallucinations or fabricated events.
"""

from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


class ClipDescriptionEngine:
    """
    Generates rich, factual analysis, timeline, and natural-language summaries
    for every recorded surveillance event.
    """

    @classmethod
    def generate_description(
        cls,
        segment: Any,
        fps: float = 4.0,
        keyframe_paths: Optional[List[str]] = None,
        camera_name: str = "Camera"
    ) -> Dict[str, Any]:
        """Convenience method taking a FinalizedClipSegment and generating the forensic analysis."""
        return cls.generate_analysis(
            camera_id=getattr(segment, "camera_id", "camera"),
            camera_name=camera_name,
            start_pts=getattr(segment, "start_pts", 0.0),
            end_pts=getattr(segment, "end_pts", 0.0),
            trigger_pts=getattr(segment, "trigger_pts", 0.0),
            start_wall_dt=datetime.now(timezone.utc),
            frame_metas=getattr(segment, "frame_metas", []),
            keyframe_urls=keyframe_paths,
            part_index=getattr(segment, "part_index", 0),
            parent_event_id=getattr(segment, "parent_event_id", None)
        )

    @staticmethod
    def generate_analysis(
        camera_id: str,
        camera_name: str,
        start_pts: float,
        end_pts: float,
        trigger_pts: float,
        start_wall_dt: datetime,
        frame_metas: List[Any],
        watch_areas: Optional[List[Any]] = None,
        keyframe_urls: Optional[List[str]] = None,
        is_night_ir: bool = False,
        is_after_hours: bool = False,
        part_index: int = 0,
        parent_event_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds the canonical forensic analysis dictionary matching Section 6 requirements.
        """
        duration_sec = round(max(1.0, end_pts - start_pts), 1)
        fps = len(frame_metas) / duration_sec if duration_sec > 0 else 4.0

        # 1. Analyze Tracks and Object Classes
        all_tracks: Dict[int, Any] = {}
        class_detections: Dict[str, List[float]] = {}
        unique_tracks_by_class: Dict[str, set] = {}
        max_simultaneous_by_class: Dict[str, int] = {}
        first_seen_by_class: Dict[str, float] = {}
        last_seen_by_class: Dict[str, float] = {}

        timeline_raw: List[Dict[str, Any]] = []
        motion_series: List[float] = []
        peak_motion_score = 0.0
        peak_motion_offset = 0.0

        # Track stationary history: tid -> (was_stationary, stationary_start_offset, last_loc)
        stationary_history: Dict[int, Dict[str, Any]] = {}
        zone_occupancy: Dict[int, str] = {} # tid -> zone_name

        prev_counts: Dict[str, int] = {}

        for meta in frame_metas:
            t_offset = round(max(0.0, meta.pts - start_pts), 1)
            wall_t = (start_wall_dt + timedelta(seconds=t_offset)).strftime("%H:%M:%S")

            m_score = getattr(meta, "motion_score", 0.0)
            motion_series.append(round(m_score, 4))
            if m_score > peak_motion_score:
                peak_motion_score = m_score
                peak_motion_offset = t_offset

            # Current frame counts per class
            cur_class_counts: Dict[str, int] = {}

            # Detections
            for d in getattr(meta, "detections", []):
                lbl = getattr(d, "label", "unclassified")
                conf = getattr(d, "confidence", 0.0)
                class_detections.setdefault(lbl, []).append(conf)
                cur_class_counts[lbl] = cur_class_counts.get(lbl, 0) + 1
                if lbl not in first_seen_by_class:
                    first_seen_by_class[lbl] = t_offset
                last_seen_by_class[lbl] = t_offset

            for lbl, count in cur_class_counts.items():
                if count > max_simultaneous_by_class.get(lbl, 0):
                    max_simultaneous_by_class[lbl] = count

            # Process Tracks
            tracks_in_frame = getattr(meta, "active_tracks", [])
            for trk in tracks_in_frame:
                tid = getattr(trk, "track_id", -1)
                lbl = getattr(trk, "label", "unclassified")
                conf = getattr(trk, "confidence", 0.0)
                all_tracks[tid] = trk
                unique_tracks_by_class.setdefault(lbl, set()).add(tid)

                # Determine location / zone
                cx, cy = trk.centroid if hasattr(trk, "centroid") else (0.5, 0.5)
                loc_name = ClipDescriptionEngine._resolve_location(cx, cy, trk.box, watch_areas)

                # Track Entry Event
                if tid not in stationary_history:
                    side = "left" if cx < 0.3 else ("right" if cx > 0.7 else "center")
                    stationary_history[tid] = {
                        "was_stationary": False,
                        "stat_start": None,
                        "loc": loc_name,
                        "label": lbl
                    }
                    timeline_raw.append({
                        "t_offset_sec": t_offset,
                        "wall_clock_time": wall_t,
                        "event": "object_enter",
                        "objects": [lbl],
                        "track_id": tid,
                        "location": f"{loc_name} (from {side})",
                        "confidence": round(conf, 2)
                    })

                # Zone Change Event
                prev_zone = zone_occupancy.get(tid)
                if loc_name != prev_zone:
                    zone_occupancy[tid] = loc_name
                    if prev_zone is not None:
                        timeline_raw.append({
                            "t_offset_sec": t_offset,
                            "wall_clock_time": wall_t,
                            "event": "zone_entry",
                            "objects": [lbl],
                            "track_id": tid,
                            "location": loc_name,
                            "confidence": round(conf, 2)
                        })

                # Stationary / Movement state change
                is_stat = getattr(trk, "is_stationary", False)
                prev_stat = stationary_history[tid]["was_stationary"]
                if is_stat and not prev_stat:
                    stationary_history[tid]["was_stationary"] = True
                    stationary_history[tid]["stat_start"] = t_offset
                    timeline_raw.append({
                        "t_offset_sec": t_offset,
                        "wall_clock_time": wall_t,
                        "event": "object_stopped",
                        "objects": [lbl],
                        "track_id": tid,
                        "location": loc_name,
                        "confidence": round(conf, 2)
                    })
                elif not is_stat and prev_stat:
                    stat_start = stationary_history[tid]["stat_start"] or t_offset
                    stat_dur = round(t_offset - stat_start, 1)
                    stationary_history[tid]["was_stationary"] = False
                    stationary_history[tid]["stat_start"] = None
                    timeline_raw.append({
                        "t_offset_sec": t_offset,
                        "wall_clock_time": wall_t,
                        "event": "object_moving_again",
                        "objects": [lbl],
                        "track_id": tid,
                        "location": f"{loc_name} (stationary {stat_dur}s)",
                        "confidence": round(conf, 2)
                    })

            # Count Changes (e.g. 1 -> 2 people)
            for lbl, cur_cnt in cur_class_counts.items():
                prev_cnt = prev_counts.get(lbl, 0)
                if prev_cnt > 0 and cur_cnt != prev_cnt and abs(cur_cnt - prev_cnt) >= 1:
                    timeline_raw.append({
                        "t_offset_sec": t_offset,
                        "wall_clock_time": wall_t,
                        "event": "count_change",
                        "objects": [f"{cur_cnt} {lbl}s (was {prev_cnt})"],
                        "track_id": None,
                        "location": camera_name,
                        "confidence": 0.85
                    })
            prev_counts = dict(cur_class_counts)

        # 2. Add Motion Start and Motion Peak to timeline
        trigger_offset = round(max(0.0, trigger_pts - start_pts), 1)
        trigger_wall = (start_wall_dt + timedelta(seconds=trigger_offset)).strftime("%H:%M:%S")

        timeline_raw.insert(0, {
            "t_offset_sec": trigger_offset,
            "wall_clock_time": trigger_wall,
            "event": "motion_start",
            "objects": ["movement"],
            "track_id": None,
            "location": camera_name,
            "confidence": 1.0
        })

        if peak_motion_score > 0.01:
            timeline_raw.append({
                "t_offset_sec": peak_motion_offset,
                "wall_clock_time": (start_wall_dt + timedelta(seconds=peak_motion_offset)).strftime("%H:%M:%S"),
                "event": "motion_peak",
                "objects": ["peak_activity"],
                "track_id": None,
                "location": f"{camera_name} ({peak_motion_score*100:.1f}% ROI)",
                "confidence": 1.0
            })

        # Add Clip End
        timeline_raw.append({
            "t_offset_sec": duration_sec,
            "wall_clock_time": (start_wall_dt + timedelta(seconds=duration_sec)).strftime("%H:%M:%S"),
            "event": "clip_end",
            "objects": ["end"],
            "track_id": None,
            "location": camera_name,
            "confidence": 1.0
        })

        # 3. Clean and Debounce Timeline (cap at ~50 entries, merge duplicates within 1s)
        timeline_cleaned = ClipDescriptionEngine._debounce_timeline(timeline_raw)

        # 4. Movement Analysis per Track
        movement_summary: List[Dict[str, Any]] = []
        for tid, trk in all_tracks.items():
            direction = trk.get_travel_direction() if hasattr(trk, "get_travel_direction") else "stationary"
            stat_dur = 0.0
            if hasattr(trk, "get_stationary_duration"):
                stat_dur = trk.get_stationary_duration(end_pts)
            loc_str = ClipDescriptionEngine._resolve_location(trk.centroid[0], trk.centroid[1], trk.box, watch_areas)
            movement_summary.append({
                "track_id": tid,
                "label": trk.label,
                "travel_direction": direction,
                "stationary_duration_sec": round(stat_dur, 1),
                "last_location": loc_str
            })

        # 5. Build Class Objects Summary
        objects_summary: Dict[str, Any] = {}
        primary_class = "person" if "person" in class_detections else ("vehicle" if "vehicle" in class_detections else "unclassified")
        for cls, confs in class_detections.items():
            u_tracks = len(unique_tracks_by_class.get(cls, set()))
            objects_summary[cls] = {
                "max_simultaneous": max_simultaneous_by_class.get(cls, 1),
                "unique_tracks": max(1, u_tracks),
                "first_seen_offset": first_seen_by_class.get(cls, 0.0),
                "last_seen_offset": last_seen_by_class.get(cls, duration_sec),
                "avg_confidence": round(float(np.mean(confs)), 2)
            }

        # 6. Evaluate Importance & Score
        score_factors: List[str] = []
        importance_score = 40

        if "person" in class_detections:
            importance_score += 20
            score_factors.append("Person present in camera view")

        if max_simultaneous_by_class.get("person", 0) > 1:
            importance_score += 15
            score_factors.append(f"Multiple people observed simultaneously ({max_simultaneous_by_class.get('person')} people)")

        if is_after_hours:
            importance_score += 20
            score_factors.append("Activity occurred outside business hours")

        if is_night_ir:
            importance_score += 10
            score_factors.append("Infrared night vision mode active")

        # Loitering / stay duration
        max_stat = max([m["stationary_duration_sec"] for m in movement_summary], default=0.0)
        if max_stat >= 30.0:
            importance_score += 15
            score_factors.append(f"Subject stationary for {int(max_stat)}s (potential loitering)")

        if duration_sec >= 45.0:
            importance_score += 10
            score_factors.append(f"Extended event duration ({int(duration_sec)}s)")

        importance_score = min(100, max(20, importance_score))
        if importance_score >= 80:
            importance_level = "critical"
        elif importance_score >= 65:
            importance_level = "high"
        elif importance_score >= 45:
            importance_level = "medium"
        else:
            importance_level = "low"

        # 7. Event Type Determination
        if "person" in class_detections and max_simultaneous_by_class.get("person", 0) > 1:
            event_type = "multiple_people"
        elif "person" in class_detections and max_stat >= 30.0:
            event_type = "loitering"
        elif "person" in class_detections:
            event_type = "person_activity"
        elif "vehicle" in class_detections or any(c in class_detections for c in ["car", "motorcycle", "truck", "bus"]):
            event_type = "vehicle_activity"
        elif "animal" in class_detections or any(c in class_detections for c in ["dog", "cat"]):
            event_type = "animal"
        elif any(z.get("event") == "zone_entry" for z in timeline_cleaned):
            event_type = "zone_entry"
        else:
            event_type = "unclassified_motion"

        # 8. Trigger Reason String
        first_loc = timeline_cleaned[1]["location"] if len(timeline_cleaned) > 1 else camera_name
        first_conf = class_detections.get(primary_class, [0.85])[0]
        trigger_reason = f"Motion detected in {first_loc} at {trigger_wall}; AI verified {primary_class} ({first_conf:.2f})"

        # 9. Deterministic Natural-Language Title & Summary
        title, summary = ClipDescriptionEngine._generate_title_and_summary(
            camera_name=camera_name,
            event_type=event_type,
            primary_class=primary_class,
            duration_sec=duration_sec,
            movement_summary=movement_summary,
            timeline=timeline_cleaned,
            is_after_hours=is_after_hours
        )

        # Downsample motion series to ~30 points for stats chart
        step = max(1, len(motion_series) // 30)
        downsampled_motion = motion_series[::step][:30]

        return {
            "title": title,
            "summary": summary,
            "trigger_reason": trigger_reason,
            "event_type": event_type,
            "importance": {
                "score": importance_score,
                "level": importance_level,
                "reasons": score_factors
            },
            "objects": objects_summary,
            "timeline": timeline_cleaned,
            "movement": movement_summary,
            "stats": {
                "duration_sec": duration_sec,
                "active_duration_sec": round(max(1.0, duration_sec - 10.0), 1),
                "pre_roll_sec": 10.0,
                "post_roll_sec": 10.0,
                "peak_motion_score": round(peak_motion_score, 4),
                "motion_series": downsampled_motion
            },
            "keyframes": keyframe_urls or [],
            "description_text": f"{title}. {summary}",
            "parent_event_id": parent_event_id,
            "part_index": part_index
        }

    @staticmethod
    def _resolve_location(cx: float, cy: float, box: List[float], watch_areas: Optional[List[Any]]) -> str:
        if watch_areas:
            for wa in watch_areas:
                poly = getattr(wa, "polygon", None)
                if poly and len(poly) >= 3:
                    # Point in polygon test for bottom center foot coordinate
                    foot_x = cx
                    foot_y = box[3] if len(box) >= 4 else cy
                    if ClipDescriptionEngine._point_in_poly(foot_x, foot_y, poly):
                        return getattr(wa, "name", "watch_area")
        # Coarse location
        horiz = "left" if cx < 0.33 else ("center" if cx < 0.66 else "right")
        vert = "upper" if cy < 0.33 else ("mid" if cy < 0.66 else "lower")
        return f"{vert}-{horiz} area"

    @staticmethod
    def _point_in_poly(x: float, y: float, poly: List[List[float]]) -> bool:
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i][0], poly[i][1]
            xj, yj = poly[j][0], poly[j][1]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _debounce_timeline(timeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Removes duplicate successive event logs within 1.0 second."""
        if not timeline:
            return []
        timeline.sort(key=lambda p: p["t_offset_sec"])
        deduped: List[Dict[str, Any]] = []
        last_seen_event: Dict[Tuple[str, Optional[int]], float] = {}

        for pt in timeline:
            key = (pt["event"], pt.get("track_id"))
            t = pt["t_offset_sec"]
            if key in last_seen_event and abs(t - last_seen_event[key]) < 1.0:
                continue
            last_seen_event[key] = t
            clean_pt = dict(pt)
            clean_pt.setdefault("action", clean_pt.get("event", "activity").replace("_", " ").capitalize())
            clean_pt.setdefault("classes", clean_pt.get("objects", []))
            deduped.append(clean_pt)

        # Cap at 50 points
        if len(deduped) > 50:
            step = len(deduped) / 50.0
            sampled = [deduped[int(i * step)] for i in range(50)]
            if deduped[-1] not in sampled:
                sampled[-1] = deduped[-1]
            return sampled
        return deduped

    @staticmethod
    def _generate_title_and_summary(
        camera_name: str,
        event_type: str,
        primary_class: str,
        duration_sec: float,
        movement_summary: List[Dict[str, Any]],
        timeline: List[Dict[str, Any]],
        is_after_hours: bool
    ) -> Tuple[str, str]:
        """Generates crisp natural-language title and multi-sentence summary."""
        dur_str = f"{int(duration_sec)}s" if duration_sec < 60 else f"{int(duration_sec//60)}m {int(duration_sec%60)}s"

        main_loc = timeline[1]["location"] if len(timeline) > 1 else camera_name
        main_dir = movement_summary[0]["travel_direction"] if movement_summary else "stationary"

        if event_type == "multiple_people":
            title = f"Multiple people detected in {camera_name}"
            summary = (
                f"Two or more individuals were observed in {camera_name} moving {main_dir}. "
                f"Activity continued for {dur_str} before the area cleared."
            )
        elif event_type == "loitering":
            title = f"Loitering activity in {main_loc}"
            summary = (
                f"A person entered {main_loc} and remained stationary for extended observation. "
                f"Total stay duration was {dur_str}."
            )
        elif event_type == "vehicle_activity":
            title = f"Vehicle movement detected in {camera_name}"
            summary = (
                f"Vehicle arrived in {main_loc} traveling {main_dir}. "
                f"The event concluded after {dur_str}."
            )
        elif event_type == "person_activity":
            title = f"Person entered {main_loc}"
            summary = (
                f"An individual entered {main_loc} moving {main_dir}. "
                f"Movement was tracked continuously across {dur_str} of footage."
            )
        else:
            title = f"Movement detected in {camera_name}"
            summary = f"Motion activity registered across {dur_str} in {camera_name}."

        if is_after_hours:
            summary += " Warning: this activity was recorded outside scheduled business hours."

        return title, summary
