"""
Master Edge Pipeline Coordinator.
Binds capture threads, MOG2 gating, shared inference worker, scoring, recording, and alerting.
"""

from __future__ import annotations
import time
import queue
import threading
import logging
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

from vyzn.core.config import EdgeSettings, CameraConfig
from vyzn.core.events import EventRecord, DetectionCandidate
from vyzn.core.database import EventDatabase
from vyzn.motion.mog2_gate import MOG2MotionGate
from vyzn.ai.detector import BaseDetector, MockDetector, YOLOv8Detector
from vyzn.ai.tracker import IOUTracker
from vyzn.scoring.engine import ScoringEngine, is_time_after_hours, check_box_intersects_zone
from vyzn.recording.clip_writer import ClipWriter
from vyzn.alerts.telegram import TelegramAlertProvider
from vyzn.alerts.dispatcher import AlertDispatcher
from vyzn.storage.reaper import StorageReaperDaemon
from vyzn.storage.cloud_sync import CloudSyncWorker
from vyzn.telemetry.heartbeat import TelemetryHeartbeatDaemon
from vyzn.capture.synthetic import SyntheticCameraThread
from vyzn.capture.stream_capture import RTSPCaptureThread

logger = logging.getLogger("vyzn.pipeline")


class EdgePipeline:
    """
    Central edge orchestrator executing multi-stream processing with zero GIL contention.
    """

    def __init__(
        self,
        settings: EdgeSettings,
        detector: Optional[BaseDetector] = None,
        use_synthetic: bool = False
    ):
        self.settings = settings
        self.use_synthetic = use_synthetic
        self.running = False

        # Core subsystems
        self.db = EventDatabase(self.settings.db_path)
        self.motion_gate = MOG2MotionGate(min_motion_ratio=self.settings.motion_gate_threshold)
        self.detector = detector or MockDetector()
        self.tracker = IOUTracker()
        self.scoring_engine = ScoringEngine(alert_threshold=self.settings.alert_score_threshold)
        self.clip_writer = ClipWriter(data_root=self.settings.data_dir)

        # Alerting
        alert_provider = TelegramAlertProvider(
            bot_token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id
        )
        self.dispatcher = AlertDispatcher(provider=alert_provider, cooldown_sec=45.0)

        # Storage & Observability Daemons
        self.reaper = StorageReaperDaemon(
            db=self.db,
            data_root=self.settings.data_dir,
            raw_retention_hours=self.settings.raw_retention_hours,
            disk_safety_threshold_pct=self.settings.disk_safety_threshold_pct
        )
        self.cloud_sync = CloudSyncWorker(
            db=self.db,
            sync_interval_sec=20,
            min_score=self.settings.alert_score_threshold
        )
        self.telemetry = TelemetryHeartbeatDaemon(
            settings=self.settings,
            db=self.db,
            pipeline_status_getter=self.get_telemetry_status
        )

        # Queues & Capture Threads
        self.frame_queue: queue.Queue = queue.Queue(maxsize=40)
        self.capture_threads: List[threading.Thread] = []

        # Ring buffers for pre-roll video (stores downscaled frames for ~10 seconds = 40 frames @ 4 fps)
        self.ring_buffers: Dict[str, deque] = {}
        # Active event buffers
        self.event_buffers: Dict[str, List] = {}
        self.active_event_ids: Dict[str, str] = {}
        self.active_event_scores: Dict[str, int] = {}
        self.active_event_start_times: Dict[str, str] = {}

        self.worker_thread: Optional[threading.Thread] = None

    def start(self):
        """Launches capture streams, inference worker, and support daemons."""
        self.running = True
        logger.info(f"Starting VYZN Edge Pipeline (Site: {self.settings.site_id})...")

        # 1. Start background daemons
        self.reaper.start()
        self.cloud_sync.start()
        self.telemetry.start()

        # 2. Launch capture threads
        for cam in self.settings.cameras:
            if not cam.enabled:
                continue

            self.ring_buffers[cam.camera_id] = deque(maxlen=int(cam.target_fps * 10))

            if self.use_synthetic:
                profile = "night_intruder" if cam.is_night_ir else "walking_person"
                thread = SyntheticCameraThread(
                    config=cam,
                    output_queue=self.frame_queue,
                    motion_profile=profile
                )
            else:
                thread = RTSPCaptureThread(
                    config=cam,
                    output_queue=self.frame_queue
                )

            self.capture_threads.append(thread)
            thread.start()

        # 3. Launch shared sequential AI worker
        self.worker_thread = threading.Thread(
            target=self._inference_worker_loop,
            name="Shared-Inference-Worker",
            daemon=True
        )
        self.worker_thread.start()
        logger.info(f"Pipeline started with {len(self.capture_threads)} capture streams.")

    def _inference_worker_loop(self):
        """Sequential inference worker pulling decimated frames from shared queue."""
        logger.info("Shared inference worker started.")

        while self.running:
            try:
                item = self.frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            camera_id, frame_time, frame, is_night_ir = item

            # Update pre-roll buffer
            if camera_id in self.ring_buffers:
                self.ring_buffers[camera_id].append(frame)

            # 1. Motion Pre-Filter (MOG2)
            has_motion, motion_ratio, _ = self.motion_gate.process_frame(camera_id, frame)

            # 2. If no motion and no active event, skip deep learning inference
            if not has_motion and camera_id not in self.active_event_ids:
                self.frame_queue.task_done()
                continue

            # 3. Run Object Detection on motion frame
            detections = self.detector.detect(frame)

            # 4. Update IoU Tracker
            active_tracks = self.tracker.update(detections, timestamp=frame_time)

            # 5. Find camera config
            cam_config = next((c for c in self.settings.cameras if c.camera_id == camera_id), None)
            now_dt = datetime.now(timezone.utc)
            after_hours = is_time_after_hours(now_dt, cam_config.business_hours) if cam_config else True

            # 6. Evaluate Candidate Threat Level
            best_candidate = None
            highest_score = 0
            should_alert_flag = False

            if active_tracks:
                for track in active_tracks:
                    in_restricted_zone = False
                    if cam_config and cam_config.restricted_zones:
                        for zone in cam_config.restricted_zones:
                            if check_box_intersects_zone(track.box, zone):
                                in_restricted_zone = True
                                break

                    candidate = DetectionCandidate(
                        camera_id=camera_id,
                        object_type=track.label,
                        confidence=track.confidence,
                        motion_ratio=motion_ratio,
                        track_duration_sec=track.duration_sec,
                        bounding_box=track.box,
                        is_after_hours=after_hours,
                        is_in_restricted_zone=in_restricted_zone,
                        is_night_ir=is_night_ir,
                        timestamp=now_dt
                    )

                    score, alert, breakdown = self.scoring_engine.evaluate(candidate)
                    if score > highest_score:
                        highest_score = score
                        should_alert_flag = alert
                        best_candidate = candidate
            elif has_motion:
                # Unclassified motion
                candidate = DetectionCandidate(
                    camera_id=camera_id,
                    object_type="unclassified",
                    confidence=0.0,
                    motion_ratio=motion_ratio,
                    track_duration_sec=0.0,
                    bounding_box=[0, 0, 1, 1],
                    is_after_hours=after_hours,
                    is_in_restricted_zone=False,
                    is_night_ir=is_night_ir,
                    timestamp=now_dt
                )
                score, alert, _ = self.scoring_engine.evaluate(candidate)
                highest_score = score
                best_candidate = candidate

            # 7. Event Assembly & Recording Logic
            if highest_score >= 40 and best_candidate:
                # Initiate or extend event
                if camera_id not in self.active_event_ids:
                    event_id = f"ev_{camera_id}_{int(time.time())}"
                    self.active_event_ids[camera_id] = event_id
                    self.active_event_scores[camera_id] = highest_score
                    self.active_event_start_times[camera_id] = now_dt.isoformat()
                    # Initialize event buffer with pre-roll
                    self.event_buffers[camera_id] = list(self.ring_buffers.get(camera_id, []))

                self.event_buffers[camera_id].append(frame)
                self.active_event_scores[camera_id] = max(
                    self.active_event_scores[camera_id],
                    highest_score
                )

                # If event duration reaches ~8 seconds (32 frames @ 4 fps) or alert fires
                if len(self.event_buffers[camera_id]) >= 32 or should_alert_flag:
                    self._finalize_event(
                        camera_id=camera_id,
                        candidate=best_candidate,
                        should_alert=should_alert_flag
                    )

            elif camera_id in self.active_event_ids:
                # Trailing frames to conclude event
                self.event_buffers[camera_id].append(frame)
                if len(self.event_buffers[camera_id]) >= 20:
                    self._finalize_event(
                        camera_id=camera_id,
                        candidate=best_candidate,
                        should_alert=False
                    )

            self.frame_queue.task_done()

    def _finalize_event(
        self,
        camera_id: str,
        candidate: Optional[DetectionCandidate],
        should_alert: bool
    ):
        event_id = self.active_event_ids.pop(camera_id, None)
        if not event_id:
            return

        frames = self.event_buffers.pop(camera_id, [])
        score = self.active_event_scores.pop(camera_id, 50)
        start_time = self.active_event_start_times.pop(camera_id, datetime.now(timezone.utc).isoformat())
        end_time = datetime.now(timezone.utc).isoformat()

        # Write fMP4 clip and thumbnail
        clip_path, thumb_path = self.clip_writer.write_clip_from_frames(
            camera_id=camera_id,
            event_group_id=event_id,
            frames=frames,
            fps=4.0
        )

        obj_type = candidate.object_type if candidate else "unclassified"
        conf = candidate.confidence if candidate else 0.0

        record = EventRecord(
            event_group_id=event_id,
            camera_id=camera_id,
            start_time=start_time,
            end_time=end_time,
            object_type=obj_type,
            confidence=conf,
            score=score,
            status="raw",
            file_path=clip_path,
            thumb_path=thumb_path
        )

        # Save to SQLite index
        self.db.insert_event(record)
        self.db.log_audit("EVENT_RECORDED", event_id, f"Score: {score}, Obj: {obj_type}")

        # Alert dispatch if verified
        if should_alert or score >= self.settings.alert_score_threshold:
            self.dispatcher.dispatch(record, clip_path, thumb_path)

    def get_telemetry_status(self) -> Dict:
        """Collects live pipeline state for the telemetry daemon."""
        return {
            "active_cameras": len([t for t in self.capture_threads if getattr(t, "is_connected", False)]),
            "queue_depth": self.frame_queue.qsize(),
            "events_active": len(self.active_event_ids)
        }

    def update_camera_zones(self, camera_id: str, zones: List[ZonePolygon]):
        """Dynamically hot-reloads restricted polygon zones for a camera."""
        cam_config = next((c for c in self.settings.cameras if c.camera_id == camera_id), None)
        if cam_config:
            cam_config.restricted_zones = zones
            logger.info(f"Dynamically updated {len(zones)} restricted zones for camera {camera_id}.")

    def stop(self):
        """Stops all threads and closes database."""
        self.running = False
        for t in self.capture_threads:
            if hasattr(t, "stop"):
                t.stop()
        for t in self.capture_threads:
            t.join(timeout=2.0)

        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)

        self.reaper.stop()
        self.cloud_sync.stop()
        self.telemetry.stop()
        self.db.close()
        logger.info("VYZN Edge Pipeline stopped cleanly.")
