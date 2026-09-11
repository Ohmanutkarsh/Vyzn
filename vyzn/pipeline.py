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
from vyzn.privacy.dpdp import PrivacyMasker
from vyzn.scoring.calibrator import AdaptiveCalibrator
from vyzn.telemetry.ota_sync import OTASyncWorker

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
        self.privacy_masker = PrivacyMasker()
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

        self.calibrator = AdaptiveCalibrator(db=self.db)
        self.ota_sync = OTASyncWorker(
            settings=self.settings,
            pipeline=self,
            db=self.db,
            sync_interval_sec=30.0
        )

        # Queues & Capture Threads
        self.frame_queue: queue.Queue = queue.Queue(maxsize=40)
        self.capture_threads: List[threading.Thread] = []

        # Ring buffers for pre-roll video (stores downscaled frames for ~10 seconds = 40 frames @ 4 fps)
        self.ring_buffers: Dict[str, deque] = {}
        # Active event buffers and tracking state
        self.event_buffers: Dict[str, List] = {}
        self.active_event_ids: Dict[str, str] = {}
        self.active_event_scores: Dict[str, int] = {}
        self.active_event_start_times: Dict[str, str] = {}
        self.active_event_last_motion: Dict[str, float] = {}
        self.active_event_alert_sent: Dict[str, bool] = {}
        self.active_event_best_candidates: Dict[str, Optional[DetectionCandidate]] = {}

        self.worker_thread: Optional[threading.Thread] = None

    def start(self):
        """Launches capture streams, inference worker, and support daemons."""
        self.running = True
        logger.info(f"Starting VYZN Edge Pipeline (Site: {self.settings.site_id})...")

        # 1. Start background daemons
        self.reaper.start()
        self.cloud_sync.start()
        self.telemetry.start()
        self.ota_sync.start()

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

            # DPDP Act 2023: Apply real-time privacy masking before storage or inference
            cam_config = next((c for c in self.settings.cameras if c.camera_id == camera_id), None)
            if cam_config and getattr(cam_config, "privacy_zones", None):
                p_polys = [pz.points for pz in cam_config.privacy_zones if pz.points]
                if p_polys:
                    frame = self.privacy_masker.apply_mask(frame, p_polys)

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

                    cam_bias = self.calibrator.get_camera_bias(camera_id)
                    score, alert, breakdown = self.scoring_engine.evaluate(candidate, camera_bias=cam_bias)
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
                cam_bias = self.calibrator.get_camera_bias(camera_id)
                score, alert, _ = self.scoring_engine.evaluate(candidate, camera_bias=cam_bias)
                highest_score = score
                best_candidate = candidate

            # 7. Event Assembly & Grace Period Logic
            is_active_motion = (highest_score >= 40 and best_candidate is not None)

            if is_active_motion:
                # Start new event if not already tracking one
                if camera_id not in self.active_event_ids:
                    event_id = f"ev_{camera_id}_{int(time.time())}"
                    self.active_event_ids[camera_id] = event_id
                    self.active_event_scores[camera_id] = highest_score
                    self.active_event_start_times[camera_id] = now_dt.isoformat()
                    self.active_event_alert_sent[camera_id] = False
                    self.active_event_best_candidates[camera_id] = best_candidate
                    # Pre-fill event buffer with pre-roll history (~10s = 40 frames)
                    self.event_buffers[camera_id] = list(self.ring_buffers.get(camera_id, []))

                # Append current frame and update state
                self.event_buffers[camera_id].append(frame)
                self.active_event_last_motion[camera_id] = frame_time
                if highest_score > self.active_event_scores[camera_id]:
                    self.active_event_scores[camera_id] = highest_score
                    self.active_event_best_candidates[camera_id] = best_candidate

                # Trigger alert dispatch once per event as soon as threshold is met
                if should_alert_flag and not self.active_event_alert_sent.get(camera_id, False):
                    self.active_event_alert_sent[camera_id] = True

                # Cap maximum segment duration (24 frames ≈ 6 seconds @ 4 fps)
                if len(self.event_buffers[camera_id]) >= 24:
                    self._finalize_event(camera_id)

            elif camera_id in self.active_event_ids:
                # Trailing frames during grace period (motion has paused)
                self.event_buffers[camera_id].append(frame)
                last_m_time = self.active_event_last_motion.get(camera_id, frame_time)

                # Close event if quiet for > 2.5 seconds or reached segment limit
                if (frame_time - last_m_time > 2.5) or (len(self.event_buffers[camera_id]) >= 24):
                    self._finalize_event(camera_id)

            self.frame_queue.task_done()

    def _finalize_event(self, camera_id: str):
        """Finalizes an event segment, encodes crash-safe fMP4, indexes to SQLite, and dispatches alert."""
        event_id = self.active_event_ids.pop(camera_id, None)
        if not event_id:
            return

        frames = self.event_buffers.pop(camera_id, [])
        score = self.active_event_scores.pop(camera_id, 50)
        start_time = self.active_event_start_times.pop(camera_id, datetime.now(timezone.utc).isoformat())
        self.active_event_last_motion.pop(camera_id, None)
        alert_sent = self.active_event_alert_sent.pop(camera_id, False)
        candidate = self.active_event_best_candidates.pop(camera_id, None)
        end_time = datetime.now(timezone.utc).isoformat()

        if len(frames) < 6:
            return

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

        # Dispatch alert if score qualifies
        if alert_sent or score >= self.settings.alert_score_threshold:
            self.dispatcher.dispatch(record, clip_path, thumb_path)

    def get_telemetry_status(self) -> Dict:
        """Collects live pipeline state for the telemetry daemon."""
        return {
            "active_cameras": len([t for t in self.capture_threads if getattr(t, "is_connected", False)]),
            "queue_depth": self.frame_queue.qsize(),
            "events_active": len(self.active_event_ids),
            "config_hash": getattr(self.ota_sync, "current_config_hash", "")
        }

    def update_camera_zones(self, camera_id: str, zones: List[ZonePolygon]):
        """Dynamically hot-reloads restricted polygon zones for a camera via atomic replacement."""
        for idx, cam in enumerate(self.settings.cameras):
            if cam.camera_id == camera_id:
                new_cam = CameraConfig(
                    camera_id=cam.camera_id,
                    name=cam.name,
                    rtsp_url=cam.rtsp_url,
                    substream_url=cam.substream_url,
                    target_fps=cam.target_fps,
                    input_resolution=cam.input_resolution,
                    enabled=cam.enabled,
                    is_night_ir=cam.is_night_ir,
                    restricted_zones=list(zones),
                    privacy_masks=list(cam.privacy_masks),
                    business_hours=cam.business_hours
                )
                new_cameras = list(self.settings.cameras)
                new_cameras[idx] = new_cam
                self.settings.cameras = new_cameras
                logger.info(f"Dynamically updated {len(zones)} restricted zones for camera {camera_id} (atomic swap).")
                break

    def stop(self):
        """Stops all threads and closes database."""
        self.running = False

        # Flush any active events currently in progress before terminating
        for cam_id in list(self.active_event_ids.keys()):
            try:
                self._finalize_event(cam_id)
            except Exception as e:
                logger.error(f"Error finalizing event for {cam_id} on stop: {e}")

        for t in self.capture_threads:
            if hasattr(t, "stop"):
                t.stop()
        for t in self.capture_threads:
            t.join(timeout=2.0)

        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)

        self.ota_sync.stop()
        self.reaper.stop()
        self.cloud_sync.stop()
        self.telemetry.stop()
        self.db.close()
        logger.info("VYZN Edge Pipeline stopped cleanly.")
