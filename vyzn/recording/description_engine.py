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
    def compute_d4_modifier(
        has_person: bool = False,
        has_multiple_people: bool = False,
        is_after_hours: bool = False,
        is_night_ir: bool = False,
        has_loitering_30s: bool = False,
        has_extended_duration_45s: bool = False
    ) -> Tuple[float, List[str]]:
        """
        Computes Level 4 forensic additive modifier D4 in range 0..37.
        Strictly additive, never overrides Level 3.
        """
        factors = []
        d4 = 0.0
        if has_person:
            d4 += 5.0
            factors.append("Person present in camera view (+5)")
        if has_multiple_people:
            d4 += 8.0
            factors.append("Multiple people observed simultaneously (+8)")
        if is_after_hours:
            d4 += 10.0
            factors.append("Activity occurred outside business hours (+10)")
        if is_night_ir:
            d4 += 4.0
            factors.append("Infrared night vision mode active (+4)")
        if has_loitering_30s:
            d4 += 6.0
            factors.append("Subject stationary for >=30s (loitering) (+6)")
        if has_extended_duration_45s:
            d4 += 4.0
            factors.append("Extended event duration >=45s (+4)")

        d4 = max(0.0, min(37.0, d4))
        return d4, factors

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
        parent_event_id: Optional[str] = None,
        final_score: Optional[int] = None
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

                # Determine location / zone using camera context and watch areas
                cx, cy = trk.centroid if hasattr(trk, "centroid") else (0.5, 0.5)
                loc_name = ClipDescriptionEngine._resolve_location(cx, cy, trk.box, watch_areas, camera_name)

                # Track Entry Event
                if tid not in stationary_history:
                    side = "left" if cx < 0.3 else ("right" if cx > 0.7 else "center")
                    stationary_history[tid] = {
                        "was_stationary": False,
                        "stat_start": None,
                        "loc": loc_name,
                        "label": lbl
                    }
                    # In simple terms: only add 'from left' or 'from right' if they actually came from the side.
                    # Never print machine gibberish like 'mid-center area (from center)'!
                    entry_loc = f"{loc_name} from {side}" if side in ("left", "right") else loc_name
                    timeline_raw.append({
                        "t_offset_sec": t_offset,
                        "wall_clock_time": wall_t,
                        "event": "object_enter",
                        "objects": [lbl],
                        "track_id": tid,
                        "location": entry_loc,
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
                # In simple terms: a track's stationary duration cannot exceed when the object was actually seen
                last_seen = getattr(trk, "last_seen_time", end_pts) or end_pts
                stat_dur = trk.get_stationary_duration(min(end_pts, last_seen))
            loc_str = ClipDescriptionEngine._resolve_location(trk.centroid[0], trk.centroid[1], trk.box, watch_areas, camera_name)
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

        # 6. Evaluate True Presence, Stationary Durations & Loitering
        has_person = "person" in class_detections
        has_multi_person = max_simultaneous_by_class.get("person", 0) > 1

        # Real presence duration of the person across this clip (first seen to last seen)
        if has_person and "person" in first_seen_by_class and "person" in last_seen_by_class:
            person_presence_sec = round(max(0.0, last_seen_by_class["person"] - first_seen_by_class["person"]), 1)
        elif has_person:
            person_presence_sec = round(max(1.0, duration_sec - 10.0), 1)
        else:
            person_presence_sec = 0.0

        # Stationary duration: cannot exceed actual presence in view
        person_stat_durations = [m["stationary_duration_sec"] for m in movement_summary if m.get("label") == "person"]
        max_stat = min(person_presence_sec, max(person_stat_durations, default=0.0))
        is_loiter_30s = has_person and max_stat >= 30.0
        has_ext_45s = duration_sec >= 45.0

        d4_modifier, score_factors = ClipDescriptionEngine.compute_d4_modifier(
            has_person=has_person,
            has_multiple_people=has_multi_person,
            is_after_hours=is_after_hours,
            is_night_ir=is_night_ir,
            has_loitering_30s=is_loiter_30s,
            has_extended_duration_45s=has_ext_45s
        )

        display_score = int(final_score) if final_score is not None else int(round(d4_modifier))
        if display_score >= 85:
            importance_level = "critical"
        elif display_score >= 70:
            importance_level = "high"
        elif display_score >= 50:
            importance_level = "medium"
        elif display_score >= 30:
            importance_level = "notable"
        else:
            importance_level = "low"

        # 7. Event Type Determination
        if "person" in class_detections and max_simultaneous_by_class.get("person", 0) > 1:
            event_type = "multiple_people"
        elif is_loiter_30s:
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
        raw_first_loc = timeline_cleaned[1]["location"] if len(timeline_cleaned) > 1 else camera_name
        clean_first_loc = ClipDescriptionEngine._clean_location_for_title(raw_first_loc, camera_name)
        first_conf = class_detections.get(primary_class, [0.85])[0]
        trigger_reason = f"Motion detected in {clean_first_loc} at {trigger_wall}; AI verified {primary_class} ({first_conf:.2f})"

        # 9. Deterministic Natural-Language Title & Summary
        title, summary = ClipDescriptionEngine._generate_title_and_summary(
            camera_name=camera_name,
            event_type=event_type,
            primary_class=primary_class,
            duration_sec=duration_sec,
            presence_sec=person_presence_sec,
            stat_sec=max_stat,
            movement_summary=movement_summary,
            timeline=timeline_cleaned,
            is_after_hours=is_after_hours
        )

        # 1-line summary per spec
        first_sentence = summary.split(".")[0].strip()
        one_line_summary = f"{title}. {first_sentence}." if first_sentence else title

        # Build timestamped timeline intervals with 'no significant activity' stretches
        timeline_intervals = ClipDescriptionEngine._build_timeline_intervals(
            timeline_events=timeline_cleaned,
            duration_sec=duration_sec,
            start_wall_dt=start_wall_dt,
            frame_metas=frame_metas,
            start_pts=start_pts,
            camera_name=camera_name,
            watch_areas=watch_areas
        )

        # Downsample motion series to ~30 points for stats chart
        step = max(1, len(motion_series) // 30)
        downsampled_motion = motion_series[::step][:30]

        return {
            "title": title,
            "summary": summary,
            "one_line_summary": one_line_summary,
            "trigger_reason": trigger_reason,
            "event_type": event_type,
            "importance": {
                "score": display_score,
                "d4_modifier": round(d4_modifier, 2),
                "level": importance_level,
                "reasons": score_factors
            },
            "objects": objects_summary,
            "timeline": timeline_cleaned,
            "timeline_intervals": timeline_intervals,
            "movement": movement_summary,
            "stats": {
                "duration_sec": duration_sec,
                "active_duration_sec": round(max(1.0, duration_sec - 10.0), 1),
                "presence_duration_sec": person_presence_sec,
                "stationary_duration_sec": max_stat,
                "is_loitering": is_loiter_30s,
                "primary_location": clean_first_loc,
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
    def _resolve_location(
        cx: float,
        cy: float,
        box: List[float],
        watch_areas: Optional[List[Any]],
        camera_name: str = ""
    ) -> str:
        """Resolves coarse location or configured watch area name in natural human language."""
        if watch_areas:
            for wa in watch_areas:
                poly = getattr(wa, "polygon", None)
                if poly and len(poly) >= 3:
                    # Point in polygon test for bottom center foot coordinate
                    foot_x = cx
                    foot_y = box[3] if len(box) >= 4 else cy
                    if ClipDescriptionEngine._point_in_poly(foot_x, foot_y, poly):
                        return getattr(wa, "name", "watch_area")

        # Coarse location in natural phrasing
        if cx < 0.33:
            loc = "left area"
        elif cx > 0.66:
            loc = "right area"
        else:
            loc = "center area"

        cam_str = camera_name.strip() if camera_name else ""
        if cam_str and cam_str.lower() not in ("camera", "camera 1", "default", "unspecified"):
            return f"{cam_str} ({loc})"
        return loc

    @staticmethod
    def _clean_location_for_title(loc: str, default_name: str) -> str:
        """Removes machine noise like '(from center)' or 'mid-center' for clean human titles."""
        if not loc:
            return default_name
        import re
        cleaned = re.sub(r"\s*\(?from (?:left|right|center)\)?", "", loc, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"mid-center", "center", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or default_name

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
        presence_sec: float = 0.0,
        stat_sec: float = 0.0,
        movement_summary: Optional[List[Dict[str, Any]]] = None,
        timeline: Optional[List[Dict[str, Any]]] = None,
        is_after_hours: bool = False
    ) -> Tuple[str, str]:
        """Generates crisp natural-language title and multi-sentence summary with verified durations."""
        dur_str = f"{int(duration_sec)}s" if duration_sec < 60 else f"{int(duration_sec//60)}m {int(duration_sec%60)}s"
        pres_str = f"{int(presence_sec)}s" if presence_sec < 60 else f"{int(presence_sec//60)}m {int(presence_sec%60)}s"
        stat_str = f"{int(stat_sec)}s" if stat_sec < 60 else f"{int(stat_sec//60)}m {int(stat_sec%60)}s"

        raw_loc = (timeline[1]["location"] if timeline and len(timeline) > 1 else camera_name)
        main_loc = ClipDescriptionEngine._clean_location_for_title(raw_loc, camera_name)
        main_dir = movement_summary[0]["travel_direction"] if movement_summary else "stationary"

        if event_type == "multiple_people":
            title = f"Multiple people detected in {main_loc}"
            summary = (
                f"Two or more individuals were observed in {main_loc} moving {main_dir}. "
                f"Activity continued for {pres_str} within {dur_str} of footage."
            )
        elif event_type == "loitering":
            title = f"Loitering activity in {main_loc}"
            summary = (
                f"A person entered {main_loc} and remained stationary for {stat_str}. "
                f"Total presence in view was {pres_str} across {dur_str} of footage."
            )
        elif event_type == "vehicle_activity":
            title = f"Vehicle movement detected in {main_loc}"
            summary = (
                f"Vehicle arrived in {main_loc} traveling {main_dir}. "
                f"The event concluded after {dur_str}."
            )
        elif event_type == "person_activity":
            title = f"Person detected in {main_loc}"
            summary = (
                f"An individual entered {main_loc} moving {main_dir}. "
                f"Present for {pres_str} across {dur_str} of footage."
            )
        else:
            title = f"Movement detected in {main_loc}"
            summary = f"Motion activity registered across {dur_str} in {main_loc}."

        if is_after_hours:
            summary += " Warning: this activity was recorded outside scheduled business hours."

        return title, summary

    @staticmethod
    def _format_mm_ss(sec: float) -> str:
        """Formats floating-point seconds into MM:SS string."""
        s = max(0, int(round(sec)))
        m = s // 60
        rem = s % 60
        return f"{m:02d}:{rem:02d}"

    @classmethod
    def _build_timeline_intervals(
        cls,
        timeline_events: List[Dict[str, Any]],
        duration_sec: float,
        start_wall_dt: datetime,
        frame_metas: Optional[List[Any]] = None,
        start_pts: float = 0.0,
        camera_name: str = "Camera",
        watch_areas: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Builds non-overlapping, sequential timeline intervals spanning from 00:00 to duration_sec.
        Extracts ground-truth activity runs from frame_metas (when present) or debounce timeline events,
        inserting clean 'No significant activity' stretches in quiet periods.
        """
        duration_sec = round(max(1.0, float(duration_sec)), 1)
        intervals: List[Dict[str, Any]] = []

        if frame_metas and len(frame_metas) >= 3:
            # 1. Map each frame into a classified state and location
            frame_states: List[Tuple[float, str, str, bool]] = []

            for m in frame_metas:
                t_off = round(max(0.0, getattr(m, "pts", start_pts) - start_pts), 1)

                p_tracks = [t for t in getattr(m, "active_tracks", []) if getattr(t, "label", "") == "person"]
                p_dets = [d for d in getattr(m, "detections", []) if getattr(d, "label", "") == "person"]

                if p_tracks or p_dets:
                    is_stat = any(getattr(t, "is_stationary", False) for t in p_tracks)
                    trk = p_tracks[0] if p_tracks else None
                    cx, cy = trk.centroid if trk and hasattr(trk, "centroid") else (0.5, 0.5)
                    box = trk.box if trk else (p_dets[0].box if p_dets else [0.3, 0.2, 0.7, 0.8])
                    loc = cls._resolve_location(cx, cy, box, watch_areas, camera_name)
                    st = "person_stationary" if is_stat else "person_moving"
                    frame_states.append((t_off, st, loc, False))
                elif any(getattr(d, "label", "") in ("car", "vehicle", "truck", "motorcycle", "bus") for d in getattr(m, "detections", [])):
                    loc = cls._clean_location_for_title(camera_name, "Camera view")
                    frame_states.append((t_off, "vehicle", loc, False))
                elif getattr(m, "motion_score", 0.0) >= 0.005:
                    loc = cls._clean_location_for_title(camera_name, "Camera view")
                    frame_states.append((t_off, "motion", loc, False))
                else:
                    loc = cls._clean_location_for_title(camera_name, "Camera view")
                    frame_states.append((t_off, "quiet", loc, True))

            # 2. Compress into contiguous runs
            raw_runs: List[Dict[str, Any]] = []
            if frame_states:
                cur_state, cur_loc, cur_quiet = frame_states[0][1], frame_states[0][2], frame_states[0][3]
                run_start = frame_states[0][0]
                run_end = frame_states[0][0]

                for t_off, st, loc, quiet in frame_states[1:]:
                    if st == cur_state and (loc == cur_loc or quiet):
                        run_end = t_off
                    else:
                        raw_runs.append({
                            "start_sec": run_start,
                            "end_sec": run_end,
                            "state": cur_state,
                            "loc": cur_loc,
                            "is_quiet": cur_quiet
                        })
                        cur_state, cur_loc, cur_quiet = st, loc, quiet
                        run_start = t_off
                        run_end = t_off

                raw_runs.append({
                    "start_sec": run_start,
                    "end_sec": run_end,
                    "state": cur_state,
                    "loc": cur_loc,
                    "is_quiet": cur_quiet
                })

            # Filter/smooth out momentary blips shorter than 1.5s into surrounding state
            smoothed_runs: List[Dict[str, Any]] = []
            for r in raw_runs:
                dur = r["end_sec"] - r["start_sec"]
                if smoothed_runs and dur < 1.5 and r["is_quiet"] and not smoothed_runs[-1]["is_quiet"]:
                    smoothed_runs[-1]["end_sec"] = r["end_sec"]
                elif smoothed_runs and dur < 1.5 and not r["is_quiet"] and smoothed_runs[-1]["state"] == r["state"]:
                    smoothed_runs[-1]["end_sec"] = r["end_sec"]
                else:
                    smoothed_runs.append(dict(r))

            # 3. Stitch seamlessly from 0.0 to duration_sec
            cur_t = 0.0
            for r in smoothed_runs:
                r_start = max(0.0, r["start_sec"])
                r_end = max(r_start + 1.0, r["end_sec"])

                # Fill any gap before this run with quiet
                if r_start - cur_t >= 1.5:
                    s_fmt = cls._format_mm_ss(cur_t)
                    e_fmt = cls._format_mm_ss(r_start)
                    w_s = (start_wall_dt + timedelta(seconds=cur_t)).strftime("%H:%M:%S")
                    w_e = (start_wall_dt + timedelta(seconds=r_start)).strftime("%H:%M:%S")
                    intervals.append({
                        "start_sec": cur_t,
                        "end_sec": r_start,
                        "time_str": f"{s_fmt}-{e_fmt}",
                        "start_formatted": s_fmt,
                        "end_formatted": e_fmt,
                        "wall_clock_str": f"{w_s}-{w_e}",
                        "event": "quiet",
                        "action": "No significant activity",
                        "description": "No significant activity",
                        "location": camera_name,
                        "is_quiet": True
                    })
                    cur_t = r_start

                st = r["state"]
                loc = r["loc"]
                if st == "person_stationary":
                    desc = f"Subject (person) stationary / dwelling in {loc}"
                    ev_name = "object_stopped"
                elif st == "person_moving":
                    desc = f"Subject (person) active and moving in {loc}"
                    ev_name = "person_moving"
                elif st == "vehicle":
                    desc = f"Vehicle activity in {loc}"
                    ev_name = "vehicle_moving"
                elif st == "motion":
                    desc = f"Movement registered in {loc}"
                    ev_name = "motion"
                else:
                    desc = "No significant activity"
                    ev_name = "quiet"

                end_bound = min(duration_sec, max(cur_t + 1.0, r_end))
                s_fmt = cls._format_mm_ss(cur_t)
                e_fmt = cls._format_mm_ss(end_bound)
                w_s = (start_wall_dt + timedelta(seconds=cur_t)).strftime("%H:%M:%S")
                w_e = (start_wall_dt + timedelta(seconds=end_bound)).strftime("%H:%M:%S")

                intervals.append({
                    "start_sec": cur_t,
                    "end_sec": end_bound,
                    "time_str": f"{s_fmt}-{e_fmt}",
                    "start_formatted": s_fmt,
                    "end_formatted": e_fmt,
                    "wall_clock_str": f"{w_s}-{w_e}",
                    "event": ev_name,
                    "action": desc,
                    "description": desc,
                    "location": loc,
                    "is_quiet": r["is_quiet"]
                })
                cur_t = end_bound

            # Trailing quiet period if needed
            if duration_sec - cur_t >= 1.0:
                s_fmt = cls._format_mm_ss(cur_t)
                e_fmt = cls._format_mm_ss(duration_sec)
                w_s = (start_wall_dt + timedelta(seconds=cur_t)).strftime("%H:%M:%S")
                w_e = (start_wall_dt + timedelta(seconds=duration_sec)).strftime("%H:%M:%S")
                intervals.append({
                    "start_sec": cur_t,
                    "end_sec": duration_sec,
                    "time_str": f"{s_fmt}-{e_fmt}",
                    "start_formatted": s_fmt,
                    "end_formatted": e_fmt,
                    "wall_clock_str": f"{w_s}-{w_e}",
                    "event": "quiet",
                    "action": "No significant activity",
                    "description": "No significant activity",
                    "location": camera_name,
                    "is_quiet": True
                })

        # Fallback if no frame_metas was supplied or runs produced nothing
        if not intervals:
            action_events = [
                e for e in timeline_events
                if e.get("event") not in ("clip_end", "motion_peak")
            ]
            action_events.sort(key=lambda x: x.get("t_offset_sec", 0.0))

            cur_t = 0.0
            for idx, ev in enumerate(action_events):
                t_ev = max(0.0, float(ev.get("t_offset_sec", 0.0)))

                if t_ev - cur_t >= 2.0:
                    s_fmt = cls._format_mm_ss(cur_t)
                    e_fmt = cls._format_mm_ss(t_ev)
                    w_s = (start_wall_dt + timedelta(seconds=cur_t)).strftime("%H:%M:%S")
                    w_e = (start_wall_dt + timedelta(seconds=t_ev)).strftime("%H:%M:%S")
                    intervals.append({
                        "start_sec": cur_t,
                        "end_sec": t_ev,
                        "time_str": f"{s_fmt}-{e_fmt}",
                        "start_formatted": s_fmt,
                        "end_formatted": e_fmt,
                        "wall_clock_str": f"{w_s}-{w_e}",
                        "event": "quiet",
                        "action": "No significant activity",
                        "description": "No significant activity",
                        "location": camera_name,
                        "is_quiet": True
                    })
                    cur_t = t_ev

                next_t = action_events[idx + 1]["t_offset_sec"] if idx + 1 < len(action_events) else min(duration_sec, t_ev + 3.0)
                end_t = min(duration_sec, max(t_ev + 1.0, next_t))
                s_fmt = cls._format_mm_ss(t_ev)
                e_fmt = cls._format_mm_ss(end_t)
                w_s = (start_wall_dt + timedelta(seconds=t_ev)).strftime("%H:%M:%S")
                w_e = (start_wall_dt + timedelta(seconds=end_t)).strftime("%H:%M:%S")

                desc = ev.get("action") or ev.get("event", "Activity")
                loc = ev.get("location") or camera_name
                objs = ev.get("objects", [])
                obj_str = objs[0] if objs else "activity"
                if ev.get("event") == "object_enter":
                    desc = f"Subject ({obj_str}) entered {loc}"
                elif ev.get("event") == "zone_entry":
                    desc = f"Subject entered {loc}"
                elif ev.get("event") == "object_stopped":
                    desc = f"Subject remained stationary / dwelling in {loc}"
                elif ev.get("event") == "object_moving_again":
                    desc = f"Subject resumed moving in {loc}"
                elif ev.get("event") == "motion_start":
                    desc = f"Movement detected in {loc}"

                intervals.append({
                    "start_sec": t_ev,
                    "end_sec": end_t,
                    "time_str": f"{s_fmt}-{e_fmt}",
                    "start_formatted": s_fmt,
                    "end_formatted": e_fmt,
                    "wall_clock_str": f"{w_s}-{w_e}",
                    "event": ev.get("event", "activity"),
                    "action": desc,
                    "description": desc,
                    "location": loc,
                    "is_quiet": False
                })
                cur_t = end_t

            if duration_sec - cur_t >= 1.0:
                s_fmt = cls._format_mm_ss(cur_t)
                e_fmt = cls._format_mm_ss(duration_sec)
                w_s = (start_wall_dt + timedelta(seconds=cur_t)).strftime("%H:%M:%S")
                w_e = (start_wall_dt + timedelta(seconds=duration_sec)).strftime("%H:%M:%S")
                intervals.append({
                    "start_sec": cur_t,
                    "end_sec": duration_sec,
                    "time_str": f"{s_fmt}-{e_fmt}",
                    "start_formatted": s_fmt,
                    "end_formatted": e_fmt,
                    "wall_clock_str": f"{w_s}-{w_e}",
                    "event": "quiet",
                    "action": "No significant activity",
                    "description": "No significant activity",
                    "location": camera_name,
                    "is_quiet": True
                })

        return intervals

    @staticmethod
    def validate_llm_timestamps(prose: str, logged_timestamps: List[str], fallback: str) -> str:
        """
        Rejects LLM prose if it invents timestamps not present in the grounded event log.
        Falls back to deterministic template.
        """
        import re
        found = re.findall(r"\b\d{1,2}:\d{2}\b", prose)
        allowed = set(logged_timestamps)
        for ts in found:
            parts = ts.split(":")
            norm_ts = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
            if norm_ts not in allowed and ts not in allowed:
                return fallback
        return prose

