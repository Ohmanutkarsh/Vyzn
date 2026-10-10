"""
Offline Replay Harness for VYZN Video Pipeline Evaluation.

Enables reproducible, faster-than-real-time evaluation of the complete
motion gating, object tracking, clip state machine, and forensic description pipeline.
Feeds video files (MP4) or synthetic frame generators into the pipeline
using monotonic frame PTS timestamps without wall-clock drift.
"""

from __future__ import annotations
import os
import cv2
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, Generator, Callable
import numpy as np

from vyzn.motion.mog2_gate import MOG2MotionGate
from vyzn.recording.state_machine import (
    ClipStateMachine,
    ClipState,
    FinalizedClipSegment,
    FrameMetadata
)
from vyzn.recording.clip_writer import ClipWriter
from vyzn.recording.description_engine import ClipDescriptionEngine
from vyzn.ai.tracker import IOUTracker
from vyzn.ai.detector import BaseDetector, Detection
from vyzn.core.config import CameraConfig, WatchAreaConfig

logger = logging.getLogger("vyzn.evaluation.replay")


@dataclass
class ReplayStateTransition:
    pts: float
    from_state: str
    to_state: str
    reason: str


@dataclass
class FrameLogEntry:
    pts: float
    motion_score: float
    is_active: bool
    num_detections: int
    num_tracks: int
    state: str


@dataclass
class ReplayedClip:
    clip_id: str
    start_pts: float
    end_pts: float
    duration: float
    trigger_reason: str
    close_reason: str
    parent_event_id: Optional[str]
    part_index: int
    is_discarded: bool
    analysis: Dict[str, Any]
    output_mp4: Optional[str] = None


class ReplayHarness:
    """
    Offline video/synthetic replay test bench.
    Executes the full computer-vision & clip lifecycle stack.
    """

    def __init__(
        self,
        camera_id: str = "eval_cam_01",
        camera_config: Optional[CameraConfig] = None,
        state_machine_kwargs: Optional[Dict[str, Any]] = None,
        detector: Optional[BaseDetector] = None,
        write_clips_to_disk: bool = False,
        output_dir: Optional[Path] = None,
        target_fps: float = 4.0
    ):
        self.camera_id = camera_id
        self.target_fps = target_fps
        self.write_clips_to_disk = write_clips_to_disk
        self.output_dir = output_dir or Path("data/replay_eval")
        if self.write_clips_to_disk:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Camera & ROI
        self.camera_config = camera_config or CameraConfig(
            camera_id=camera_id,
            name="Evaluation Camera",
            rtsp_url="replay://eval",
            watch_areas=[
                WatchAreaConfig(
                    id="roi_main",
                    camera_id=camera_id,
                    name="Watch Area Main",
                    polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
                )
            ]
        )

        # Initialize MOG2 Motion Gate
        self.motion_gate = MOG2MotionGate(
            learning_rate=0.004,
            warmup_frames=15,  # Faster warmup for replay tests
            min_contour_area_ratio=0.003
        )
        self.motion_gate.set_camera_areas(
            camera_id,
            [w.polygon for w in self.camera_config.watch_areas]
        )

        # Initialize Tracker & Detector
        self.tracker = IOUTracker(
            iou_threshold=0.25,
            max_missed_frames=30
        )
        self.detector = detector

        # Initialize State Machine
        sm_kwargs = {
            "camera_id": camera_id,
            "target_fps": target_fps,
            "pre_roll_sec": 10.0,
            "post_roll_sec": 10.0,
            "merge_gap_sec": 90.0,
            "max_clip_duration_sec": 180.0,
            "min_motion_only_sec": 3.0,
            "stream_gap_tolerance_sec": 5.0,
            "stationary_hold_max_sec": 60.0
        }
        if state_machine_kwargs:
            sm_kwargs.update(state_machine_kwargs)

        self.state_machine = ClipStateMachine(**sm_kwargs)
        self.clip_writer = ClipWriter(data_root=self.output_dir) if write_clips_to_disk else None
        self.description_engine = ClipDescriptionEngine()

        # Telemetry & Logs
        self.transitions: List[ReplayStateTransition] = []
        self.frame_logs: List[FrameLogEntry] = []
        self.clips_created: List[ReplayedClip] = []
        self._prev_state: str = self.state_machine.state.value

    def process_frame(
        self,
        frame: np.ndarray,
        pts: float,
        forced_detections: Optional[List[Detection]] = None,
        in_roi: bool = True
    ) -> Optional[ReplayedClip]:
        """
        Processes a single frame at timestamp PTS.
        """
        # 1. Check for stream discontinuity / gap
        if self.state_machine.last_frame_pts > 0:
            pts_gap = pts - self.state_machine.last_frame_pts
            if pts_gap > self.state_machine.stream_gap_tolerance_sec:
                interrupted_seg = self.state_machine.handle_stream_gap(pts_gap)
                if interrupted_seg and not interrupted_seg.is_discarded:
                    clip = self._finalize_segment(interrupted_seg)
                    self.clips_created.append(clip)

        # 2. Motion Gate Analysis
        has_motion, motion_score, fg_mask = self.motion_gate.process_frame(
            camera_id=self.camera_id,
            frame=frame
        )

        # 3. Object Detection (if provided or detector configured)
        detections: List[Detection] = []
        if forced_detections is not None:
            detections = forced_detections
        elif self.detector is not None:
            detections = self.detector.detect(frame)

        # 4. Tracker Update
        active_tracks = self.tracker.update(detections, timestamp=pts)

        # 5. State Machine Transition Step
        prev_st = self.state_machine.state.value
        segment = self.state_machine.step(
            pts=pts,
            frame_ref=frame.copy() if self.write_clips_to_disk else None,
            motion_score=motion_score,
            detections=detections,
            tracks=active_tracks,
            in_roi=in_roi
        )
        curr_st = self.state_machine.state.value

        # Log transition if changed
        if curr_st != prev_st:
            self.transitions.append(ReplayStateTransition(
                pts=pts,
                from_state=prev_st,
                to_state=curr_st,
                reason=self.state_machine.trigger_reason or "state_transition"
            ))

        # Log per-frame telemetry
        self.frame_logs.append(FrameLogEntry(
            pts=pts,
            motion_score=motion_score,
            is_active=(motion_score >= 0.003 or len(detections) > 0 or len(active_tracks) > 0) and in_roi,
            num_detections=len(detections),
            num_tracks=len(active_tracks),
            state=curr_st
        ))

        # 6. Finalize clip if emitted
        if segment is not None and not segment.is_discarded:
            clip = self._finalize_segment(segment)
            self.clips_created.append(clip)
            return clip

        return None

    def _finalize_segment(self, segment: FinalizedClipSegment) -> ReplayedClip:
        """Invokes ClipWriter and ClipDescriptionEngine on completed segment."""
        out_mp4 = None
        keyframe_paths = []

        if self.write_clips_to_disk and self.clip_writer and segment.frames:
            write_res = self.clip_writer.write_clip_from_frames(
                camera_id=segment.camera_id,
                event_group_id=segment.event_group_id,
                frames=segment.frames,
                fps=self.target_fps
            )
            out_mp4 = str(write_res.clip_path)
            keyframe_paths = [str(k) for k in write_res.keyframe_paths]

        # Generate Forensic Analysis JSON
        analysis = self.description_engine.generate_description(
            segment=segment,
            fps=self.target_fps,
            keyframe_paths=keyframe_paths,
            camera_name=self.camera_config.name
        )

        return ReplayedClip(
            clip_id=segment.event_group_id,
            start_pts=segment.start_pts,
            end_pts=segment.end_pts,
            duration=round(segment.end_pts - segment.start_pts, 2),
            trigger_reason=segment.trigger_reason,
            close_reason=segment.close_reason,
            parent_event_id=segment.parent_event_id,
            part_index=segment.part_index,
            is_discarded=segment.is_discarded,
            analysis=analysis,
            output_mp4=out_mp4
        )

    def replay_stream(
        self,
        frame_generator: Generator[Tuple[np.ndarray, float, Optional[List[Detection]], bool], None, None]
    ) -> List[ReplayedClip]:
        """
        Replays frames from generator at maximal processing speed.
        Yields tuple: (frame, pts, optional_detections, in_roi)
        """
        for frame, pts, dets, in_roi in frame_generator:
            self.process_frame(frame, pts=pts, forced_detections=dets, in_roi=in_roi)

        # Flush any remaining clip in RECORDING / HANGOVER
        if self.state_machine.state in (ClipState.RECORDING, ClipState.HANGOVER):
            last_pts = self.state_machine.last_frame_pts
            final_seg = self.state_machine._finalize_current_clip(last_pts, close_reason="stream_ended")
            if final_seg and not final_seg.is_discarded:
                self.clips_created.append(self._finalize_segment(final_seg))

        return self.clips_created

    def replay_video_file(
        self,
        video_path: str | Path,
        max_duration_sec: Optional[float] = None
    ) -> List[ReplayedClip]:
        """
        Reads MP4 video file and runs offline replay evaluation.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video file: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_idx = 0

        def generator():
            nonlocal frame_idx
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                pts = frame_idx / fps
                if max_duration_sec and pts > max_duration_sec:
                    break
                yield frame, pts, None, True
                frame_idx += 1
            cap.release()

        return self.replay_stream(generator())
