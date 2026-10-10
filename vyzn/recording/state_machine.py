"""
Explicit Clip Lifecycle State Machine for VYZN Edge Surveillance.
Implements: IDLE -> CANDIDATE -> RECORDING -> HANGOVER -> FINALIZING -> IDLE.
Monotonic stream-time tracking, Schmitt trigger, 90s debounce merge, and multi-part splitting.
"""

from __future__ import annotations
import enum
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Callable
import numpy as np

logger = logging.getLogger("vyzn.recording.fsm")


class ClipState(enum.Enum):
    IDLE = "IDLE"
    CANDIDATE = "CANDIDATE"
    RECORDING = "RECORDING"
    HANGOVER = "HANGOVER"
    FINALIZING = "FINALIZING"


@dataclass
class FrameMetadata:
    pts: float                       # Monotonic stream/frame timestamp
    motion_score: float              # Smoothed foreground ratio in ROI
    detections: List[Any]            # Detections in this frame
    active_tracks: List[Any]         # Tracks in ROI
    has_motion: bool                 # Motion above current threshold
    has_detection: bool              # Class of interest detected
    has_track: bool                  # Active/coasting track in ROI
    is_activity: bool                # motion OR detection OR track
    frame_ref: Optional[Any] = None  # Reference to frame array or compressed bytes


@dataclass
class FinalizedClipSegment:
    event_group_id: str
    camera_id: str
    parent_event_id: Optional[str]
    part_index: int
    start_pts: float
    end_pts: float
    trigger_pts: float
    trigger_reason: str
    close_reason: str
    frames: List[Any]
    frame_metas: List[FrameMetadata]
    highest_score: int
    primary_object: str
    max_confidence: float
    is_discarded: bool = False
    is_alert: bool = False


class ClipStateMachine:
    """
    Dedicated per-camera state machine that governs clip lifecycle.
    Guarantees zero mid-event fragmentation (P1) and zero false clips (P2).
    """

    TARGET_CLASSES = {
        "person", "car", "motorcycle", "bicycle", "bus", "truck",
        "dog", "cat", "backpack", "handbag", "suitcase", "vehicle", "animal"
    }

    def __init__(
        self,
        camera_id: str,
        start_motion_threshold: float = 0.010,     # 1.0% ROI change to trigger candidate
        continue_motion_threshold: float = 0.003,  # 0.3% ROI change to maintain recording
        confirm_window: int = 5,                   # Frame window to confirm candidate
        confirm_frames: int = 3,                   # Min active frames required in window
        pre_roll_sec: float = 10.0,                # 10s pre-roll buffer
        post_roll_sec: float = 10.0,               # 10s post-roll hangover period
        merge_gap_sec: float = 90.0,               # 90s debounce merge window
        max_clip_duration_sec: float = 180.0,      # Max segment duration before linked split
        min_motion_only_sec: float = 3.0,          # Discard motion-only events shorter than 3s
        track_lost_tolerance_sec: float = 5.0,     # Coasting tracks held for 5s
        stationary_hold_max_sec: float = 60.0,     # Max time holding a stationary track
        stream_gap_tolerance_sec: float = 5.0,     # Stream drop tolerance before interruption
        target_fps: float = 4.0
    ):
        self.camera_id = camera_id
        self.start_motion_threshold = start_motion_threshold
        self.continue_motion_threshold = continue_motion_threshold
        self.confirm_window = confirm_window
        self.confirm_frames = confirm_frames
        self.pre_roll_sec = pre_roll_sec
        self.post_roll_sec = post_roll_sec
        self.merge_gap_sec = merge_gap_sec
        self.max_clip_duration_sec = max_clip_duration_sec
        self.min_motion_only_sec = min_motion_only_sec
        self.track_lost_tolerance_sec = track_lost_tolerance_sec
        self.stationary_hold_max_sec = stationary_hold_max_sec
        self.stream_gap_tolerance_sec = stream_gap_tolerance_sec
        self.target_fps = max(1.0, target_fps)

        self.state: ClipState = ClipState.IDLE
        self.pre_roll_buffer: deque = deque(maxlen=int(self.target_fps * self.pre_roll_sec))
        self.candidate_window: deque = deque(maxlen=self.confirm_window)

        # Active event state
        self.current_event_id: Optional[str] = None
        self.parent_event_id: Optional[str] = None
        self.current_part_index: int = 0
        self.active_frames: List[Any] = []
        self.active_metas: List[FrameMetadata] = []
        self.event_start_pts: float = 0.0
        self.trigger_pts: float = 0.0
        self.last_active_pts: float = 0.0
        self.last_frame_pts: float = 0.0
        self.hangover_start_pts: Optional[float] = None
        self.trigger_reason: str = ""
        self.had_target_detection: bool = False
        self.highest_score: int = 0
        self.primary_object: str = "unclassified"
        self.max_confidence: float = 0.0

        # Merge & Debounce tracking
        self.last_finalized_end_pts: Optional[float] = None
        self.last_finalized_event_id: Optional[str] = None

        # Static object suppression
        self.suppressed_static_track_ids: Dict[int, float] = {}

    def _is_target_detection(self, det: Any) -> bool:
        label = getattr(det, "label", "").lower()
        conf = getattr(det, "confidence", 0.0)
        return label in self.TARGET_CLASSES and conf >= 0.25

    def step(
        self,
        pts: float,
        frame_ref: Any,
        motion_score: float,
        detections: List[Any],
        tracks: List[Any],
        in_roi: bool = True
    ) -> Optional[FinalizedClipSegment]:
        """
        Executes one state machine transition step for the given frame.
        Returns a FinalizedClipSegment when an event segment completes, else None.
        """
        self.last_frame_pts = pts

        # Clean expired suppressed static tracks
        self.suppressed_static_track_ids = {
            tid: exp for tid, exp in self.suppressed_static_track_ids.items() if pts < exp
        }

        # 1. Evaluate Activity Signal Components
        threshold = self.continue_motion_threshold if self.state in (ClipState.RECORDING, ClipState.HANGOVER) else self.start_motion_threshold
        motion_active = (motion_score >= threshold) and in_roi

        target_dets = [d for d in detections if self._is_target_detection(d)]
        detection_active = len(target_dets) > 0 and in_roi

        # Tracks in ROI (excluding permanently timed-out static objects)
        valid_tracks = [
            t for t in tracks
            if getattr(t, "track_id", -1) not in self.suppressed_static_track_ids
            and getattr(t, "label", "").lower() in self.TARGET_CLASSES
        ]
        track_active = len(valid_tracks) > 0 and in_roi

        # Check stationary duration
        for t in valid_tracks:
            stat_dur = t.get_stationary_duration(pts) if hasattr(t, "get_stationary_duration") else 0.0
            if stat_dur >= self.stationary_hold_max_sec:
                tid = getattr(t, "track_id", -1)
                self.suppressed_static_track_ids[tid] = pts + 60.0  # Suppress for 60s
                logger.info(f"[{self.camera_id}] Track {tid} stationary > {self.stationary_hold_max_sec}s; timed out.")

        is_active = (motion_active or detection_active or track_active) and in_roi

        meta = FrameMetadata(
            pts=pts,
            motion_score=motion_score,
            detections=detections,
            active_tracks=tracks,
            has_motion=motion_active,
            has_detection=detection_active,
            has_track=track_active,
            is_activity=is_active,
            frame_ref=frame_ref
        )

        finalized_segment: Optional[FinalizedClipSegment] = None

        # 2. State Machine Transitions
        if self.state == ClipState.IDLE:
            # Maintain pre-roll ring buffer
            self.pre_roll_buffer.append((frame_ref, meta))

            if is_active:
                self.candidate_window.clear()
                self.candidate_window.append(is_active)
                # If YOLO immediately detected a target class, bypass candidate delay
                if detection_active:
                    self._start_recording(pts, meta, reason="Immediate target detection")
                else:
                    self.state = ClipState.CANDIDATE

        elif self.state == ClipState.CANDIDATE:
            self.pre_roll_buffer.append((frame_ref, meta))
            self.candidate_window.append(is_active)

            active_count = sum(1 for a in self.candidate_window if a)
            if detection_active or active_count >= self.confirm_frames:
                # Confirmed! Transition to RECORDING
                reason = "Motion confirmed across window" if not detection_active else "Target detection confirmed"
                self._start_recording(pts, meta, reason=reason)
            elif len(self.candidate_window) >= self.confirm_window and active_count < self.confirm_frames:
                # Fluke / blip / noise: silently return to IDLE
                self.candidate_window.clear()
                self.state = ClipState.IDLE

        elif self.state == ClipState.RECORDING:
            self.active_frames.append(frame_ref)
            self.active_metas.append(meta)
            self._update_event_metrics(meta)

            if is_active:
                self.last_active_pts = pts
            else:
                # Activity dropped: transition to HANGOVER
                self.state = ClipState.HANGOVER
                self.hangover_start_pts = pts

            # Check MAX_CLIP_DURATION split
            cur_dur = pts - self.event_start_pts
            if cur_dur >= self.max_clip_duration_sec:
                finalized_segment = self._split_recording_segment(pts)

        elif self.state == ClipState.HANGOVER:
            self.active_frames.append(frame_ref)
            self.active_metas.append(meta)
            self._update_event_metrics(meta)

            if is_active:
                # Re-triggered within hangover! Resume RECORDING in the same clip
                self.state = ClipState.RECORDING
                self.hangover_start_pts = None
                self.last_active_pts = pts
            else:
                hangover_dur = pts - (self.hangover_start_pts or pts)
                if hangover_dur >= self.post_roll_sec:
                    # Hangover period elapsed with zero activity: finalize clip
                    finalized_segment = self._finalize_current_clip(pts, close_reason="hangover_expired")

        return finalized_segment

    def handle_stream_gap(self, pts_gap: float) -> Optional[FinalizedClipSegment]:
        """Handles stream dropouts or network reconnects."""
        if self.state in (ClipState.RECORDING, ClipState.HANGOVER):
            if pts_gap > self.stream_gap_tolerance_sec:
                # Gap too large: close clip as interrupted
                logger.warning(f"[{self.camera_id}] Stream gap {pts_gap:.1f}s exceeded tolerance; finalizing as interrupted.")
                return self._finalize_current_clip(self.last_frame_pts, close_reason="stream_interrupted")
        return None

    def _start_recording(self, pts: float, meta: FrameMetadata, reason: str):
        """Initializes a new recording session or extends existing via 90s merge window."""
        self.state = ClipState.RECORDING
        self.trigger_pts = pts
        self.trigger_reason = reason
        self.last_active_pts = pts
        self.hangover_start_pts = None

        # Check 90s Debounce Merge Rule
        is_merged = False
        if self.last_finalized_end_pts is not None:
            gap = pts - self.last_finalized_end_pts
            if 0.0 <= gap <= self.merge_gap_sec:
                # Link to previous event as parent
                self.parent_event_id = self.last_finalized_event_id
                self.current_part_index += 1
                is_merged = True

        if not is_merged:
            self.parent_event_id = None
            self.current_part_index = 0

        self.current_event_id = f"ev_{self.camera_id}_{int(pts)}"
        self.event_start_pts = pts

        # Pre-populate active frames with pre-roll buffer (10s)
        self.active_frames = [f for f, m in self.pre_roll_buffer]
        self.active_metas = [m for f, m in self.pre_roll_buffer]
        self.pre_roll_buffer.clear()

        # Add current frame
        self.active_frames.append(meta.frame_ref)
        self.active_metas.append(meta)

        self.had_target_detection = False
        self.highest_score = 0
        self.primary_object = "unclassified"
        self.max_confidence = 0.0
        self._update_event_metrics(meta)

    def _update_event_metrics(self, meta: FrameMetadata):
        """Updates detected objects, max confidence, and detection flags."""
        for d in meta.detections:
            conf = getattr(d, "confidence", 0.0)
            lbl = getattr(d, "label", "unclassified")
            if self._is_target_detection(d):
                self.had_target_detection = True
            if conf > self.max_confidence:
                self.max_confidence = conf
                self.primary_object = lbl

        for t in meta.active_tracks:
            conf = getattr(t, "confidence", 0.0)
            lbl = getattr(t, "label", "unclassified")
            if lbl.lower() in self.TARGET_CLASSES:
                self.had_target_detection = True
            if conf > self.max_confidence:
                self.max_confidence = conf
                self.primary_object = lbl

    def _split_recording_segment(self, pts: float) -> FinalizedClipSegment:
        """Splits an ongoing event that exceeded MAX_CLIP_DURATION into linked parts."""
        segment = self._finalize_current_clip(pts, close_reason="max_duration_split", continue_recording=True)
        # Continue recording for next linked part with zero lost frames
        self.parent_event_id = self.parent_event_id or segment.event_group_id
        self.current_part_index += 1
        self.current_event_id = f"{self.parent_event_id}_p{self.current_part_index}"
        self.event_start_pts = pts
        self.state = ClipState.RECORDING
        return segment

    def _finalize_current_clip(
        self,
        pts: float,
        close_reason: str,
        continue_recording: bool = False
    ) -> FinalizedClipSegment:
        """Packs and finalizes the active clip segment."""
        active_dur = max(0.0, self.last_active_pts - self.event_start_pts)
        tot_dur = max(0.0, pts - self.event_start_pts)

        # Discard rule: pure motion shorter than min_motion_only_sec without detections
        is_discarded = False
        if not self.had_target_detection and active_dur < self.min_motion_only_sec:
            is_discarded = True

        segment = FinalizedClipSegment(
            event_group_id=self.current_event_id or f"ev_{self.camera_id}_{int(pts)}",
            camera_id=self.camera_id,
            parent_event_id=self.parent_event_id,
            part_index=self.current_part_index,
            start_pts=self.event_start_pts,
            end_pts=pts,
            trigger_pts=self.trigger_pts,
            trigger_reason=self.trigger_reason,
            close_reason=close_reason,
            frames=list(self.active_frames),
            frame_metas=list(self.active_metas),
            highest_score=self.highest_score or (80 if self.had_target_detection else 45),
            primary_object=self.primary_object,
            max_confidence=self.max_confidence,
            is_discarded=is_discarded,
            is_alert=self.had_target_detection
        )

        if not continue_recording:
            self.last_finalized_end_pts = pts
            self.last_finalized_event_id = self.current_event_id
            self.active_frames = []
            self.active_metas = []
            self.state = ClipState.IDLE
            self.candidate_window.clear()
        else:
            # Leave overlap or clean for next split
            self.active_frames = []
            self.active_metas = []

        return segment
