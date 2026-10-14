"""
Explicit Clip Lifecycle State Machine for VYZN Edge Surveillance.
Implements: IDLE -> ACTIVE -> CLOSE.
Event-driven tick-based segmentation using frame PTS (video time).
Configured via config/config.json under "clip":
- score_interval_seconds = 3
- active_score_threshold = 30
- quiet_gap_seconds = 90
- pre_roll_seconds = 10
- post_roll_seconds = 10
- min_active_ticks = 1
- max_clip_seconds = 600
- preview_seconds = 6
"""

from __future__ import annotations
import enum
import logging
import decimal
import math  # Used for snapping clip cut timestamps outward to 2s keyframe boundaries
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
import numpy as np

from vyzn.core.config import get_clip_config, ClipConfig

logger = logging.getLogger("vyzn.recording.fsm")


class ClipState(enum.Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    # Legacy aliases for backwards compatibility
    CANDIDATE = "CANDIDATE"
    RECORDING = "ACTIVE"
    HANGOVER = "ACTIVE"
    FINALIZING = "FINALIZING"


@dataclass
class FrameMetadata:
    pts: float                       # Monotonic stream/frame timestamp (PTS)
    motion_score: float              # Smoothed foreground ratio in ROI
    detections: List[Any]            # Detections in this frame
    active_tracks: List[Any]         # Tracks in ROI
    has_motion: bool                 # Motion above threshold
    has_detection: bool              # Class of interest detected
    has_track: bool                  # Active/coasting track in ROI
    is_activity: bool                # motion OR detection OR track
    frame_ref: Optional[Any] = None  # Reference to frame array or compressed bytes
    events: List[Dict[str, Any]] = field(default_factory=list)  # Instantaneous grounded events at this PTS


@dataclass
class TickResult:
    """Represents one consolidated 3-second window score tick."""
    tick_start_pts: float
    tick_end_pts: float
    score: int
    score_raw: float = 0.0
    primary_object: str = "unclassified"
    max_confidence: float = 0.0
    peak_frame: Optional[Any] = None
    peak_pts: float = 0.0
    detections: List[Any] = field(default_factory=list)
    tracks: List[Any] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    frames: List[Any] = field(default_factory=list)
    frame_metas: List[FrameMetadata] = field(default_factory=list)
    score_breakdown: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalizedClipSegment:
    """Canonical finalized incident clip segment."""
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
    score: int = 0
    score_raw: float = 0.0
    tier: str = "low"
    severity_label: str = "Low"
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    ticks: List[TickResult] = field(default_factory=list)
    peak_frame_idx: int = 0
    peak_frame: Optional[Any] = None


class ClipStateMachine:
    """
    Dedicated per-camera state machine that governs clip lifecycle.
    Operates strictly on 3-second PTS ticks and rolling video buffer.
    """

    TARGET_CLASSES = {
        "person", "car", "motorcycle", "bicycle", "bus", "truck",
        "dog", "cat", "backpack", "handbag", "suitcase", "vehicle", "animal"
    }

    def __init__(
        self,
        camera_id: str,
        clip_config: Optional[ClipConfig] = None,
        target_fps: float = 4.0,
        **kwargs
    ):
        self.camera_id = camera_id
        cfg = clip_config or get_clip_config()

        # Read core parameters from config/config.json with support for legacy argument names
        self.score_interval_seconds = float(kwargs.get("score_interval_seconds", cfg.score_interval_seconds))
        self.active_score_threshold = int(kwargs.get("active_score_threshold", cfg.active_score_threshold))
        self.quiet_gap_seconds = float(kwargs.get("quiet_gap_seconds", kwargs.get("merge_gap_sec", cfg.quiet_gap_seconds)))
        self.pre_roll_seconds = float(kwargs.get("pre_roll_seconds", kwargs.get("pre_roll_sec", cfg.pre_roll_seconds)))
        self.post_roll_seconds = float(kwargs.get("post_roll_seconds", kwargs.get("post_roll_sec", cfg.post_roll_seconds)))
        self.min_active_ticks = int(kwargs.get("min_active_ticks", cfg.min_active_ticks))
        self.max_clip_seconds = float(kwargs.get("max_clip_seconds", kwargs.get("max_clip_duration_sec", cfg.max_clip_seconds)))
        self.preview_seconds = float(kwargs.get("preview_seconds", cfg.preview_seconds))
        self.target_fps = max(1.0, float(target_fps))

        # Backward compatibility properties
        self.pre_roll_sec = self.pre_roll_seconds
        self.post_roll_sec = self.post_roll_seconds
        self.merge_gap_sec = self.quiet_gap_seconds
        self.max_clip_duration_sec = self.max_clip_seconds
        # Tolerance in seconds before an RTSP stream gap is considered a dropped connection
        self.stream_gap_tolerance_sec: float = float(kwargs.get("stream_gap_tolerance_sec", 5.0))
        # Minimum duration of unclassified motion required to keep a clip (shorter blips are discarded)
        self.min_motion_only_sec: float = float(kwargs.get("min_motion_only_sec", 3.0))

        self.state: ClipState = ClipState.IDLE

        # Rolling buffer: keep at least ~30 seconds of video frames
        buffer_capacity = max(160, int(self.target_fps * 36))
        self.rolling_buffer: deque = deque(maxlen=buffer_capacity)

        # 3-second tick accumulator
        self.current_tick_frames: List[Any] = []
        self.current_tick_metas: List[FrameMetadata] = []
        self.current_tick_start_pts: Optional[float] = None
        self.current_tick_scores: List[float] = []
        self.current_tick_breakdowns: List[Dict[str, Any]] = []

        # State tracking
        self.consecutive_active_ticks: int = 0
        self.quiet_ticks: int = 0
        self.quiet_duration: float = 0.0

        # Active event state
        self.current_event_id: Optional[str] = None
        self.parent_event_id: Optional[str] = None
        self.current_part_index: int = 0
        self.first_active_window_start: float = 0.0
        self.last_active_window_end: float = 0.0
        self.clip_start_pts: float = 0.0
        self.trigger_pts: float = 0.0
        self.trigger_reason: str = ""
        self.alert_fired: bool = False

        # Active clip payload
        self.active_ticks: List[TickResult] = []
        self.active_frames: List[Any] = []
        self.active_metas: List[FrameMetadata] = []
        self.highest_score: int = 0
        self.primary_object: str = "unclassified"
        self.max_confidence: float = 0.0
        self.peak_breakdown: Dict[str, Any] = {}
        self.peak_frame: Optional[Any] = None
        self.peak_frame_pts: float = 0.0

        # Timestamp tracking
        self.last_frame_pts: float = 0.0
        self.last_active_pts: float = 0.0
        self.event_start_pts: float = 0.0

    @property
    def is_recording(self) -> bool:
        """Dashboard indicator: True while clip state is ACTIVE."""
        return self.state == ClipState.ACTIVE

    def _is_target_detection(self, det: Any) -> bool:
        label = getattr(det, "label", "").lower()
        conf = getattr(det, "confidence", 0.0)
        return label in self.TARGET_CLASSES and conf >= 0.25

    def _snap_cut_point(self, pts: float, is_start: bool) -> float:
        """
        Snaps cut points OUTWARD to ~2s segment/keyframe boundaries.
        Pre-roll is always >= 10s (never less).
        Post-roll is always >= 10s (never less).
        """
        segment_interval = 2.0
        if is_start:
            # Snap backward (earlier) to ensure pre-roll >= pre_roll_seconds
            snapped = math.floor(pts / segment_interval) * segment_interval
            return snapped
        else:
            # Snap forward (later) to ensure post-roll >= post_roll_seconds
            snapped = math.ceil(pts / segment_interval) * segment_interval
            return snapped

    def process_tick(self, tick: TickResult) -> Optional[FinalizedClipSegment]:
        """
        Executes state machine transition for a completed 3-second tick.
        Handles IDLE -> ACTIVE, resetting quiet timer, and CLOSING.
        """
        finalized_segment: Optional[FinalizedClipSegment] = None
        is_active_tick = (tick.score >= self.active_score_threshold)

        if self.state == ClipState.IDLE:
            if is_active_tick:
                self.consecutive_active_ticks += 1
                if self.consecutive_active_ticks >= self.min_active_ticks:
                    # Transition IDLE -> ACTIVE
                    self.state = ClipState.ACTIVE
                    self.first_active_window_start = tick.tick_start_pts
                    self.last_active_window_end = tick.tick_end_pts
                    self.last_active_pts = tick.tick_end_pts
                    self.trigger_pts = tick.peak_pts or tick.tick_start_pts
                    self.trigger_reason = f"Activity detected ({tick.primary_object}, score {tick.score})"
                    self.quiet_ticks = 0
                    self.quiet_duration = 0.0
                    self.alert_fired = False

                    # Snap cut point OUTWARD: pre-roll >= 10s
                    ideal_pre_pts = self.first_active_window_start - self.pre_roll_seconds
                    self.clip_start_pts = self._snap_cut_point(ideal_pre_pts, is_start=True)
                    # Enforce >= 10s rule
                    if (self.first_active_window_start - self.clip_start_pts) < self.pre_roll_seconds:
                        self.clip_start_pts = self.first_active_window_start - self.pre_roll_seconds

                    self.event_start_pts = self.clip_start_pts
                    self.current_event_id = f"ev_{self.camera_id}_{int(self.first_active_window_start)}"

                    # Initialize active clip with rolling pre-roll buffer (frames with pts >= clip_start_pts)
                    self.active_ticks = [tick]
                    pre_frames = [f for f, m in self.rolling_buffer if m.pts >= self.clip_start_pts and m.pts < tick.tick_start_pts]
                    pre_metas = [m for f, m in self.rolling_buffer if m.pts >= self.clip_start_pts and m.pts < tick.tick_start_pts]

                    self.active_frames = pre_frames + list(tick.frames)
                    self.active_metas = pre_metas + list(tick.frame_metas)

                    self.highest_score = tick.score
                    self.primary_object = tick.primary_object
                    self.max_confidence = tick.max_confidence
                    self.peak_breakdown = dict(tick.score_breakdown)
                    self.peak_frame = tick.peak_frame
                    self.peak_frame_pts = tick.peak_pts or tick.tick_start_pts

                    # Fire 70+ alert at event start!
                    if tick.score >= 70:
                        self.alert_fired = True
            else:
                self.consecutive_active_ticks = 0

        elif self.state == ClipState.ACTIVE:
            self.active_ticks.append(tick)
            self.active_frames.extend(tick.frames)
            self.active_metas.extend(tick.frame_metas)

            # Update highest score and peak frame
            if tick.score > self.highest_score:
                self.highest_score = tick.score
                self.peak_breakdown = dict(tick.score_breakdown)
                if tick.peak_frame is not None:
                    self.peak_frame = tick.peak_frame
                    self.peak_frame_pts = tick.peak_pts
            if tick.max_confidence > self.max_confidence:
                self.max_confidence = tick.max_confidence
                if tick.primary_object != "unclassified":
                    self.primary_object = tick.primary_object

            if is_active_tick:
                # While ACTIVE, any tick >= 30 updates last_active and resets quiet timer
                self.last_active_window_end = tick.tick_end_pts
                self.last_active_pts = tick.tick_end_pts
                self.quiet_ticks = 0
                self.quiet_duration = 0.0

                # Check if 70+ alert threshold crossed during active recording
                if tick.score >= 70 and not self.alert_fired:
                    self.alert_fired = True
            else:
                # Tick < 30: increment quiet timer
                self.quiet_ticks += 1
                self.quiet_duration = tick.tick_end_pts - self.last_active_window_end

                # CLOSE condition: quiet_duration > quiet_gap_seconds (i.e. > 90s, exactly 31 low ticks)
                if self.quiet_duration > self.quiet_gap_seconds:
                    finalized_segment = self._close_active_clip(close_reason="quiet_gap_exceeded")

            # Check max_clip_seconds (e.g. 600s or 300s) from the start of real activity
            if self.state == ClipState.ACTIVE and (tick.tick_end_pts - self.first_active_window_start) >= self.max_clip_seconds:
                finalized_segment = self._split_at_lowest_score_tick()

        return finalized_segment

    def _close_active_clip(self, close_reason: str, continue_recording: bool = False) -> FinalizedClipSegment:
        """
        Closes clip and trims back dead footage:
        Final clip = [first_active_window_start - 10s, last_active_window_end + 10s].
        """
        # Snap post-roll outward (>= 10s)
        ideal_end_pts = self.last_active_window_end + self.post_roll_seconds
        clip_end_pts = self._snap_cut_point(ideal_end_pts, is_start=False)
        if (clip_end_pts - self.last_active_window_end) < self.post_roll_seconds:
            clip_end_pts = self.last_active_window_end + self.post_roll_seconds

        # Trim frames past clip_end_pts so no clip ends with dead footage
        trimmed_frames = []
        trimmed_metas = []
        for f, m in zip(self.active_frames, self.active_metas):
            if m.pts <= clip_end_pts + 0.1:
                trimmed_frames.append(f)
                trimmed_metas.append(m)

        if not trimmed_frames and self.active_frames:
            trimmed_frames = list(self.active_frames)
            trimmed_metas = list(self.active_metas)

        # Peak frame index
        peak_idx = 0
        if self.peak_frame_pts and trimmed_metas:
            diffs = [abs(m.pts - self.peak_frame_pts) for m in trimmed_metas]
            peak_idx = int(np.argmin(diffs))

        # Scoring & tiering
        final_score = max(0, min(100, int(round(self.highest_score))))
        if final_score >= 70:
            tier = "alert"
            is_alert = True
            sev = "High" if final_score < 85 else "Critical"
        elif final_score >= 30:
            tier = "review"
            is_alert = False
            sev = "Notable" if final_score < 50 else "Medium"
        else:
            tier = "low"
            is_alert = False
            sev = "Low"

        # Check if this pure-motion burst was shorter than or equal to min_motion_only_sec (<=3s) without recognized targets
        active_dur = max(0.0, self.last_active_window_end - self.first_active_window_start)
        is_discarded = False
        if (self.primary_object in ("unclassified", "movement", "")) and active_dur <= self.min_motion_only_sec:
            is_discarded = True
        # In simple terms: if an event was split into parts and the very last trailing fragment has less than 3 seconds of footage, discard it so we do not save a 1-second useless stub
        if self.current_part_index > 0 and active_dur < self.score_interval_seconds:
            is_discarded = True

        segment = FinalizedClipSegment(
            event_group_id=self.current_event_id or f"ev_{self.camera_id}_{int(self.clip_start_pts)}",
            camera_id=self.camera_id,
            parent_event_id=self.parent_event_id,
            part_index=self.current_part_index,
            start_pts=self.clip_start_pts,
            end_pts=clip_end_pts,
            trigger_pts=self.trigger_pts,
            trigger_reason=self.trigger_reason,
            close_reason=close_reason,
            frames=trimmed_frames,
            frame_metas=trimmed_metas,
            highest_score=final_score,
            primary_object=self.primary_object,
            max_confidence=self.max_confidence,
            is_discarded=is_discarded,
            is_alert=is_alert,
            score=final_score,
            score_raw=float(final_score),
            tier=tier,
            severity_label=sev,
            score_breakdown=self.peak_breakdown,
            ticks=list(self.active_ticks),
            peak_frame_idx=peak_idx,
            # Explicitly check for None instead of bool coercion to safely handle numpy image arrays
            peak_frame=self.peak_frame if self.peak_frame is not None else (trimmed_frames[peak_idx] if trimmed_frames else None)
        )

        if not continue_recording:
            self.state = ClipState.IDLE
            self.active_ticks = []
            self.active_frames = []
            self.active_metas = []
            self.consecutive_active_ticks = 0
            self.quiet_ticks = 0
            self.quiet_duration = 0.0
            self.current_event_id = None
            self.parent_event_id = None
            self.current_part_index = 0

        return segment

    def _split_at_lowest_score_tick(self) -> FinalizedClipSegment:
        """
        Splits clip at max_clip_seconds at the lowest-score tick,
        marking the next clip 'continued'.
        """
        # Select candidates within the last 6s of the maximum duration limit
        split_window_start = self.first_active_window_start + max(0.0, self.max_clip_seconds - 6.0)
        candidates = [t for t in self.active_ticks if t.tick_end_pts >= split_window_start]
        if not candidates:
            candidates = self.active_ticks[-2:] if len(self.active_ticks) >= 2 else self.active_ticks
        # In simple terms: pick the tick with the lowest score; if scores are equal, pick the latest one closest to 300s
        split_tick = min(candidates, key=lambda t: (t.score, -t.tick_end_pts))
        split_pts = split_tick.tick_end_pts

        # Frames for this part end cleanly at split_pts
        trimmed_frames = [f for f, m in zip(self.active_frames, self.active_metas) if m.pts <= split_pts]
        trimmed_metas = [m for m in self.active_metas if m.pts <= split_pts]
        if not trimmed_frames and self.active_frames:
            trimmed_frames = list(self.active_frames)
            trimmed_metas = list(self.active_metas)

        segment = FinalizedClipSegment(
            event_group_id=self.current_event_id or f"ev_{self.camera_id}_{int(self.clip_start_pts)}",
            camera_id=self.camera_id,
            parent_event_id=self.parent_event_id,
            part_index=self.current_part_index,
            start_pts=self.clip_start_pts,
            end_pts=split_pts,
            trigger_pts=self.trigger_pts,
            trigger_reason=self.trigger_reason,
            close_reason="max_duration_split",
            frames=trimmed_frames,
            frame_metas=trimmed_metas,
            highest_score=self.highest_score,
            primary_object=self.primary_object,
            max_confidence=self.max_confidence,
            is_discarded=False,
            is_alert=self.alert_fired,
            score=self.highest_score,
            score_raw=float(self.highest_score),
            tier="review" if self.highest_score < 70 else "alert",
            severity_label="Medium" if self.highest_score < 70 else "High",
            score_breakdown=self.peak_breakdown,
            ticks=[t for t in self.active_ticks if t.tick_end_pts <= split_pts],
            peak_frame_idx=0,
            peak_frame=self.peak_frame if self.peak_frame is not None else (trimmed_frames[0] if trimmed_frames else None)
        )

        # Mark next part 'continued'
        self.parent_event_id = self.parent_event_id or segment.event_group_id
        self.current_part_index += 1
        self.current_event_id = f"{self.parent_event_id}_p{self.current_part_index}"
        self.clip_start_pts = split_pts
        self.first_active_window_start = split_pts
        self.trigger_reason = f"Continued from part {self.current_part_index}"

        # Carry forward remaining frames for next part
        self.active_ticks = [t for t in self.active_ticks if t.tick_start_pts >= split_pts]
        self.active_frames = [f for f, m in zip(self.active_frames, self.active_metas) if m.pts >= split_pts]
        self.active_metas = [m for m in self.active_metas if m.pts >= split_pts]

        return segment

    def on_stream_drop(self) -> Optional[FinalizedClipSegment]:
        """
        Called when RTSP stream drops: closes active clip immediately
        without counting the outage as quiet time.
        """
        if self.state == ClipState.ACTIVE:
            logger.info(f"[{self.camera_id}] Stream drop detected: closing active clip cleanly.")
            return self._close_active_clip(close_reason="stream_dropped")
        return None

    # This function handles sudden camera connection drops or video stream interruptions
    def handle_stream_gap(self, pts_gap: float) -> Optional[FinalizedClipSegment]:
        """Backward-compatible handler for stream gaps."""
        # If the stream paused for longer than our tolerance (e.g. 5 seconds) while recording, close the clip
        if pts_gap > self.stream_gap_tolerance_sec and self.state == ClipState.ACTIVE:
            return self._close_active_clip(close_reason="stream_interrupted")
        return None

    # This helper collects all frames accumulated in the current 3-second window and turns them into a completed tick
    def _flush_current_tick(self) -> Optional[TickResult]:
        """
        Gathers any frames currently waiting in the 3-second window accumulator
        into a completed TickResult so they are not lost upon shutdown or manual flush.
        """
        # If no frames arrived in this window, there is nothing to flush
        if not self.current_tick_frames:
            return None

        # Determine the start and end timestamp of this tick window
        tick_start = self.current_tick_start_pts or (self.current_tick_metas[0].pts if self.current_tick_metas else 0.0)
        tick_end = self.current_tick_metas[-1].pts if self.current_tick_metas else (tick_start + 3.0)

        # Calculate peak score across all frames in this window
        peak_score = max(self.current_tick_scores) if self.current_tick_scores else 0.0
        best_bd = max(self.current_tick_breakdowns, key=lambda b: b.get("final_score", b.get("s_live", 0)), default={})

        # Collect all detections and tracked objects across every frame in this window
        all_dets = []
        all_tracks = []
        for m in self.current_tick_metas:
            all_dets.extend(m.detections)
            all_tracks.extend(m.active_tracks)

        # In simple terms: check if any real target (person, vehicle, or animal) was seen during this 3-second window
        target_in_tick = any(
            self._is_target_detection(d) for d in all_dets
        ) or any(
            getattr(t, "label", "").lower() in ("person", "vehicle", "car", "motorcycle", "bicycle", "bus", "truck", "dog", "cat", "animal")
            for t in all_tracks
        )

        # Rule: A stationary person or tracked object must never be ignored (score floor >= 35),
        # but fleeting unconfirmed noise (like hair flutter or ceiling fan glitches) must NOT trigger the floor.
        has_confirmed_person = any(
            getattr(t, "label", "").lower() == "person" and getattr(t, "hits", 1) >= 2 and getattr(t, "confidence", 0.0) >= 0.40
            for t in all_tracks
        ) or any(
            getattr(d, "label", "").lower() == "person" and getattr(d, "confidence", 0.0) >= 0.50
            for d in all_dets
        )
        if has_confirmed_person:
            peak_score = max(peak_score, 35.0)
        elif not target_in_tick:
            # In simple terms: if the camera only sees background motion (like a spinning fan or hair moving)
            # with NO confirmed person or vehicle, cap the score at 20 (strictly below the active threshold of 30).
            # This ensures fan motion never starts a recording, and allows existing clips to close peacefully.
            peak_score = min(peak_score, 20.0)

        # Find the frame with the highest activity to use as the peak highlight snapshot
        peak_f = self.current_tick_frames[0]
        peak_pts = tick_start
        if self.current_tick_scores:
            best_idx = int(np.argmax(self.current_tick_scores))
            if best_idx < len(self.current_tick_frames):
                peak_f = self.current_tick_frames[best_idx]
                peak_pts = self.current_tick_metas[best_idx].pts

        # Determine what main object was seen (e.g. person, car)
        pri_obj = "unclassified"
        max_c = 0.0
        for d in all_dets:
            c = getattr(d, "confidence", 0.0)
            if c > max_c:
                max_c = c
                pri_obj = getattr(d, "label", "unclassified")
        for t in all_tracks:
            c = getattr(t, "confidence", 0.0)
            if c > max_c:
                max_c = c
                pri_obj = getattr(t, "label", "unclassified")

        # Collect any special events that happened in this window
        all_events = []
        for m in self.current_tick_metas:
            all_events.extend(m.events)

        # Assemble the completed 3-second tick result
        tick = TickResult(
            tick_start_pts=tick_start,
            tick_end_pts=tick_end,
            score=int(round(peak_score)),
            score_raw=float(peak_score),
            primary_object=pri_obj,
            max_confidence=max_c,
            peak_frame=peak_f,
            peak_pts=peak_pts,
            detections=all_dets,
            tracks=all_tracks,
            events=all_events,
            frames=list(self.current_tick_frames),
            frame_metas=list(self.current_tick_metas),
            score_breakdown=best_bd
        )

        # Clear out the window accumulator so it is ready for the next 3 seconds
        self.current_tick_frames = []
        self.current_tick_metas = []
        self.current_tick_scores = []
        self.current_tick_breakdowns = []
        self.current_tick_start_pts = None

        return tick

    # This method forces the clip to finish and save immediately (for example when shutting down or clicking stop)
    def _finalize_current_clip(self, pts: Optional[float] = None, close_reason: str = "flush") -> Optional[FinalizedClipSegment]:
        """
        Forces immediate finalization of the currently recorded clip.
        Flushes any pending frame ticks and gracefully seals the video segment.
        """
        # If there are frames queued in the current tick, evaluate them first
        if self.current_tick_frames:
            tick = self._flush_current_tick()
            if tick is not None:
                self.process_tick(tick)

        # If the state machine was actively recording, close the clip and return the final video data
        if self.state == ClipState.ACTIVE:
            # If no frames or ticks remain after a split boundary, do not create an empty duplicate clip
            if not self.active_frames and not self.active_ticks:
                return None
            seg = self._close_active_clip(close_reason=close_reason)
            # If the resulting segment was discarded (e.g. noise blip or tiny 1s tail), return None
            if seg is not None and seg.is_discarded:
                return None
            return seg
        return None

    # This is the main frame-by-frame processor called on every video frame from the camera
    def step(
        self,
        pts: float,
        frame_ref: Any,
        motion_score: float,
        detections: List[Any],
        tracks: List[Any],
        in_roi: bool = True,
        live_score_breakdown: Optional[Dict[str, Any]] = None,
        instant_events: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[FinalizedClipSegment]:
        """
        Processes one camera frame in stream-time (PTS).
        Buffers into rolling memory and aggregates frames into 3-second ticks.
        """
        self.last_frame_pts = pts
        # Check if motion or detections occurred inside our watch area
        has_motion = motion_score >= 0.005 and in_roi
        target_dets = [d for d in detections if self._is_target_detection(d)]
        has_detection = len(target_dets) > 0 and in_roi
        has_track = len(tracks) > 0 and in_roi
        is_active = (has_motion or has_detection or has_track) and in_roi

        # Create structured metadata for this individual video frame
        meta = FrameMetadata(
            pts=pts,
            motion_score=motion_score,
            detections=detections,
            active_tracks=tracks,
            has_motion=has_motion,
            has_detection=has_detection,
            has_track=has_track,
            is_activity=is_active,
            frame_ref=frame_ref,
            events=instant_events or []
        )

        # Store in rolling buffer so pre-roll footage is always preserved
        self.rolling_buffer.append((frame_ref, meta))

        # Start tracking timestamp for this 3-second window
        if self.current_tick_start_pts is None:
            self.current_tick_start_pts = pts

        # Accumulate frame into current 3-second tick window
        self.current_tick_frames.append(frame_ref)
        self.current_tick_metas.append(meta)

        # In simple terms: calculate score for this individual frame.
        # Prefer final_score which enforces safety caps for background motion (fans, trees).
        if live_score_breakdown is not None:
            f_score = float(live_score_breakdown.get("final_score", live_score_breakdown.get("s_live", 0.0)))
            bd = dict(live_score_breakdown)
        else:
            # Fallback calculation if running without full AI scoring engine
            if has_detection:
                f_score = 65.0
            elif has_track:
                f_score = 45.0
            elif has_motion:
                # In simple terms: background motion without any AI detected person or vehicle stays at 20 (below 30)
                f_score = 20.0
            else:
                f_score = 0.0
            bd = {"final_score": f_score, "s_live": f_score}

        self.current_tick_scores.append(f_score)
        self.current_tick_breakdowns.append(bd)

        # When the 3-second video window finishes, score the whole window and process clip transitions
        window_elapsed = pts - self.current_tick_start_pts
        if window_elapsed >= self.score_interval_seconds:
            tick = self._flush_current_tick()
            if tick is not None:
                # Set start of next tick to current PTS
                self.current_tick_start_pts = pts
                return self.process_tick(tick)

        return None
