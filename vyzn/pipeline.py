"""
Master Edge Pipeline Coordinator.
Binds capture threads, MOG2 gating, shared inference worker, scoring, recording, and alerting.
"""

from __future__ import annotations
import os
import json
import time
import queue
import threading
import logging
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

from vyzn.core.config import EdgeSettings, CameraConfig, ZonePolygon, WatchAreaConfig
from vyzn.core.events import EventRecord, DetectionCandidate
from vyzn.core.database import EventDatabase
from vyzn.motion.mog2_gate import MOG2MotionGate
from vyzn.ai.detector import BaseDetector, MockDetector, YOLOv8Detector
from vyzn.ai.tracker import IOUTracker
from vyzn.scoring.engine import ScoringEngine, is_time_after_hours, check_box_intersects_zone, is_foot_in_polygon
from vyzn.recording.clip_writer import ClipWriter
from vyzn.recording.state_machine import ClipStateMachine, ClipState, FinalizedClipSegment
from vyzn.recording.description_engine import ClipDescriptionEngine
from vyzn.alerts.telegram import TelegramAlertProvider, start_telegram_poller, stop_telegram_poller
from vyzn.alerts.dispatcher import AlertDispatcher
from vyzn.storage.reaper import StorageReaperDaemon
from vyzn.storage.cloud_sync import CloudSyncWorker
from vyzn.telemetry.heartbeat import TelemetryHeartbeatDaemon
from vyzn.capture.synthetic import SyntheticCameraThread
from vyzn.capture.stream_capture import RTSPCaptureThread
from vyzn.privacy.dpdp import PrivacyMasker
from vyzn.scoring.calibrator import AdaptiveCalibrator
from vyzn.telemetry.ota_sync import OTASyncWorker
from vyzn.core.resource_governor import ResourceGovernor
import cv2
import numpy as np

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
            disk_safety_threshold_pct=self.settings.disk_safety_threshold_pct,
            max_quota_gb=getattr(self.settings, "max_storage_quota_gb", 20.0)
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
        self.resource_governor = ResourceGovernor()

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
        self.active_event_first_motion: Dict[str, float] = {}
        self.active_event_last_motion: Dict[str, float] = {}
        self.active_event_motion_counts: Dict[str, int] = {}
        self.active_event_alert_sent: Dict[str, bool] = {}
        self.active_event_best_candidates: Dict[str, Optional[DetectionCandidate]] = {}

        # Explicit Clip State Machines & Alert tracking
        self.state_machines: Dict[str, ClipStateMachine] = {}
        self.dispatched_alert_events: set = set()

        # Initialize motion gate camera watch areas
        for cam in self.settings.cameras:
            areas = getattr(cam, "watch_areas", None)
            if areas:
                self.motion_gate.set_camera_areas(cam.camera_id, [a.polygon for a in areas if a.polygon])
            elif getattr(cam, "restricted_zones", None):
                self.motion_gate.set_camera_areas(cam.camera_id, [z.points for z in cam.restricted_zones if z.points])
            if getattr(cam, "osd_exclude_polygon", None):
                self.motion_gate.set_osd_polygons(cam.camera_id, [cam.osd_exclude_polygon])

        self.worker_thread: Optional[threading.Thread] = None

    def _get_or_create_state_machine(self, camera_id: str) -> ClipStateMachine:
        if camera_id not in self.state_machines:
            cam_cfg = next((c for c in self.settings.cameras if c.camera_id == camera_id), None)
            target_fps = float(getattr(cam_cfg, "ai_inference_fps", getattr(cam_cfg, "target_fps", 4.0)) or 4.0)
            self.state_machines[camera_id] = ClipStateMachine(
                camera_id=camera_id,
                start_motion_threshold=getattr(cam_cfg, "start_motion_threshold", None) or self.settings.start_motion_threshold,
                continue_motion_threshold=getattr(cam_cfg, "continue_motion_threshold", None) or self.settings.continue_motion_threshold,
                confirm_window=self.settings.confirm_window_frames,
                confirm_frames=self.settings.confirm_frames,
                pre_roll_sec=getattr(cam_cfg, "pre_roll_sec", None) or self.settings.pre_roll_sec,
                post_roll_sec=getattr(cam_cfg, "post_roll_sec", None) or self.settings.post_roll_sec,
                merge_gap_sec=getattr(cam_cfg, "merge_gap_sec", None) or self.settings.merge_gap_sec,
                max_clip_duration_sec=getattr(cam_cfg, "max_clip_duration_sec", None) or self.settings.max_clip_duration_sec,
                min_motion_only_sec=self.settings.min_motion_only_seconds,
                track_lost_tolerance_sec=self.settings.track_lost_tolerance_sec,
                stationary_hold_max_sec=self.settings.stationary_hold_max_sec,
                stream_gap_tolerance_sec=self.settings.stream_gap_tolerance_sec,
                target_fps=target_fps
            )
        return self.state_machines[camera_id]

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

            if self.use_synthetic and str(cam.rtsp_url).startswith("sim://"):
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

        # 4. Start Telegram interactive long-polling worker if configured
        if self.settings.telegram_bot_token:
            start_telegram_poller(
                bot_token=self.settings.telegram_bot_token,
                db=self.db,
                calibrator=self.calibrator
            )

        logger.info(f"Pipeline started with {len(self.capture_threads)} capture streams.")

    def get_camera_live_jpeg(self, camera_id: str, quality: int = 75, max_width: int = 960) -> Optional[bytes]:
        """Fetches the latest live JPEG from the camera's capture thread or ring buffer capped at max_width."""
        for t in self.capture_threads:
            if getattr(t, "config", None) and t.config.camera_id == camera_id:
                if hasattr(t, "get_latest_jpeg"):
                    jpeg = t.get_latest_jpeg(quality=quality, max_width=max_width)
                    if jpeg:
                        return jpeg

        # Fallback to ring buffer
        if camera_id in self.ring_buffers and self.ring_buffers[camera_id]:
            frame = self.ring_buffers[camera_id][-1]
            h, w = frame.shape[:2]
            if w > max_width:
                frame = cv2.resize(frame, (max_width, int(max_width * h / w)))
            ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ret:
                return jpeg.tobytes()

        return None

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

            sm = self._get_or_create_state_machine(camera_id)
            now_dt = datetime.now(timezone.utc)
            after_hours = is_time_after_hours(now_dt, cam_config.business_hours) if cam_config else True

            # Extract watch areas
            watch_polys = None
            if cam_config and getattr(cam_config, "watch_areas", None):
                watch_polys = [a.polygon for a in cam_config.watch_areas if a.polygon]
            elif cam_config and getattr(cam_config, "restricted_zones", None):
                watch_polys = [z.points for z in cam_config.restricted_zones if z.points]

            # Extract OSD exclusion polygon if configured
            osd_polys = None
            if cam_config and getattr(cam_config, "osd_exclude_polygon", None):
                osd_polys = [cam_config.osd_exclude_polygon]

            # 1. Hardened MOG2 Motion Pre-Filter
            has_motion, motion_ratio, _ = self.motion_gate.process_frame(
                camera_id, frame, watch_polygons=watch_polys, osd_polygons=osd_polys
            )

            if self.motion_gate.had_motion_dropped_outside(camera_id):
                self.db.increment_ignored_moments(camera_id)

            # Check alive coasting tracks
            alive_tracks = self.tracker.get_alive_tracks(
                max_missed_seconds=self.settings.track_lost_tolerance_sec,
                current_time=frame_time
            )

            # 2. Skip deep learning inference if completely idle
            should_run_ai = has_motion or (sm.state != ClipState.IDLE) or (len(alive_tracks) > 0)

            detections = []
            if should_run_ai:
                detections = self.detector.detect(frame)
                active_tracks = self.tracker.update(detections, timestamp=frame_time)
                alive_tracks = self.tracker.get_alive_tracks(
                    max_missed_seconds=self.settings.track_lost_tolerance_sec,
                    current_time=frame_time
                )
            else:
                self.tracker.update([], timestamp=frame_time)
                alive_tracks = []

            # Filter tracks to watch areas / ROI if configured
            in_roi = True
            has_configured_areas = bool(cam_config and getattr(cam_config, "watch_areas", None))
            if has_configured_areas:
                tracks_in_roi = []
                for trk in alive_tracks:
                    for area in cam_config.watch_areas:
                        if area.schedule == "outside_shop_hours" and not after_hours:
                            continue
                        if is_foot_in_polygon(trk.box, area.polygon):
                            tracks_in_roi.append(trk)
                            break
                in_roi = has_motion or (len(tracks_in_roi) > 0)
                alive_tracks = tracks_in_roi

            # 3. Step the Explicit Clip Lifecycle State Machine
            finalized_segment = sm.step(
                pts=frame_time,
                frame_ref=frame,
                motion_score=motion_ratio,
                detections=detections,
                tracks=alive_tracks,
                in_roi=in_roi
            )

            # Keep active_event_ids mirror updated for legacy callers
            if sm.current_event_id and sm.state in (ClipState.RECORDING, ClipState.HANGOVER):
                self.active_event_ids[camera_id] = sm.current_event_id
            else:
                self.active_event_ids.pop(camera_id, None)

            # 4. Finalize segment if completed
            if finalized_segment and not finalized_segment.is_discarded:
                self._handle_finalized_segment(finalized_segment, cam_config)

            self.frame_queue.task_done()

    def _handle_finalized_segment(
        self,
        segment: FinalizedClipSegment,
        cam_config: Optional[CameraConfig]
    ):
        """Processes finalized clip segment, writes fMP4 with faststart, generates forensic analysis, and indexes."""
        camera_id = segment.camera_id
        frames = segment.frames
        if len(frames) < 3:
            return

        fps = float(getattr(cam_config, "ai_inference_fps", 4.0) or 4.0)
        write_result = self.clip_writer.write_clip_from_frames(
            camera_id=camera_id,
            event_group_id=segment.event_group_id,
            frames=frames,
            fps=fps
        )
        clip_path = write_result.clip_path
        thumb_path = write_result.thumb_path

        start_dt = datetime.fromtimestamp(segment.start_pts, timezone.utc)
        start_time = start_dt.isoformat()
        end_time = datetime.fromtimestamp(segment.end_pts, timezone.utc).isoformat()
        duration = write_result.duration_sec

        cam_name = getattr(cam_config, "name", camera_id) or camera_id
        loc_id = getattr(cam_config, "location_id", "loc_primary") or "loc_primary"
        after_hours = is_time_after_hours(start_dt, cam_config.business_hours) if cam_config else True
        is_night_ir = bool(getattr(cam_config, "is_night_ir", False))

        watch_areas = getattr(cam_config, "watch_areas", None)
        keyframe_urls = [f"/api/clips/{segment.event_group_id}/keyframe_{i}.jpg" for i in range(len(write_result.keyframe_paths))]

        # Generate rich forensic analysis, timeline, and natural-language summary
        analysis = ClipDescriptionEngine.generate_analysis(
            camera_id=camera_id,
            camera_name=cam_name,
            start_pts=segment.start_pts,
            end_pts=segment.end_pts,
            trigger_pts=segment.trigger_pts,
            start_wall_dt=start_dt,
            frame_metas=segment.frame_metas,
            watch_areas=watch_areas,
            keyframe_urls=keyframe_urls,
            is_night_ir=is_night_ir,
            is_after_hours=after_hours,
            part_index=segment.part_index,
            parent_event_id=segment.parent_event_id
        )

        title = analysis.get("title")
        summary = analysis.get("summary")
        trigger_reason = analysis.get("trigger_reason") or segment.trigger_reason
        imp = analysis.get("importance", {})
        score = imp.get("score", segment.highest_score)
        importance_level = imp.get("level", "medium")

        tier = "alert" if (score >= self.settings.alert_score_threshold or segment.is_alert) else "review"
        clip_num = self.db.get_next_clip_number()

        # SHA-256 integrity hash
        import hashlib
        sha256_hash = ""
        if clip_path and os.path.exists(clip_path):
            try:
                with open(clip_path, "rb") as vf:
                    sha256_hash = hashlib.sha256(vf.read()).hexdigest()
            except Exception:
                pass
        if not sha256_hash:
            sha256_hash = hashlib.sha256(f"{segment.event_group_id}:{start_time}".encode()).hexdigest()

        start_ms = int(start_dt.timestamp() * 1000)
        retention_hours = getattr(self.settings, "raw_retention_hours", 72.0)
        expires_at_ms = start_ms + int(retention_hours * 3600 * 1000)
        trigger_ms = start_ms + int(max(0.0, segment.trigger_pts - segment.start_pts) * 1000)

        # Legacy reasons compatibility for existing cards and export
        reasons = []
        if after_hours:
            reasons.append({"code": "outside_shop_hours", "params": {}})
        if segment.primary_object == "person":
            reasons.append({"code": "person_detected", "params": {"confidence": round(segment.max_confidence, 2), "area": cam_name}})
            if duration >= 10.0:
                reasons.insert(0, {"code": "stayed_in_area", "params": {"seconds": int(duration), "duration": f"{int(duration)} seconds", "area": cam_name}})
        else:
            reasons.append({"code": "movement", "params": {"area": cam_name}})

        boxes = []
        for m in segment.frame_metas:
            for d in getattr(m, "detections", []):
                boxes.append({
                    "frameIdx": 0,
                    "box": getattr(d, "box", [0, 0, 1, 1]),
                    "cls": getattr(d, "label", "object"),
                    "conf": round(getattr(d, "confidence", 0.0), 2)
                })
            if boxes:
                break

        meta = {
            "pre_roll_sec": 10.0,
            "post_roll_sec": 10.0,
            "inactivity_gap_sec": 90.0,
            "motion_points": len(segment.frame_metas),
            "fps": fps,
            "reasons": reasons,
            "trigger_ms": trigger_ms,
            "camera_name": cam_name,
            "objects": [{"cls": segment.primary_object, "confidence": round(segment.max_confidence, 2)}],
            "boxes": boxes,
            "detector": {"name": "YOLOv8n-VYZN", "version": "8.0.196"},
            "analysis": analysis
        }

        record = EventRecord(
            event_group_id=segment.event_group_id,
            camera_id=camera_id,
            start_time=start_time,
            end_time=end_time,
            object_type=segment.primary_object,
            confidence=segment.max_confidence,
            score=score,
            status="raw",
            file_path=clip_path,
            thumb_path=thumb_path,
            dominant_color="unspecified",
            zone_name="general",
            location_id=loc_id,
            duration_sec=duration,
            motion_points_count=len(segment.frame_metas),
            metadata_json=json.dumps(meta),
            clip_number=clip_num,
            expires_at_ms=expires_at_ms,
            sha256=sha256_hash,
            tier=tier,
            owner_email=getattr(cam_config, "owner_email", None),
            analysis_json=json.dumps(analysis),
            title=title,
            summary=summary,
            trigger_reason=trigger_reason,
            importance_score=score,
            importance_level=importance_level,
            parent_event_id=segment.parent_event_id,
            part_index=segment.part_index
        )

        self.db.insert_event(record)
        self.db.log_audit(
            "EVENT_RECORDED",
            segment.event_group_id,
            f"Score: {score}, Obj: {segment.primary_object}, Title: {title}, Part: {segment.part_index}"
        )

        # Telegram Alerting: Fire ONCE per event, not once per fragment!
        root_event_id = segment.parent_event_id or segment.event_group_id
        if tier == "alert" and root_event_id not in self.dispatched_alert_events:
            self.dispatched_alert_events.add(root_event_id)
            self.dispatcher.dispatch(record, clip_path, thumb_path)
            logger.info(f"[ALERT DISPATCHED] Event {segment.event_group_id} alerted to Telegram.")
        else:
            logger.info(f"[CLIP ARCHIVED] Event {segment.event_group_id} saved to archive (Tier: {tier}).")

    def _finalize_event(self, camera_id: str):
        """Forces immediate finalization of active event on camera_id (backward-compatibility)."""
        sm = self.state_machines.get(camera_id)
        if sm and sm.state in (ClipState.RECORDING, ClipState.HANGOVER):
            seg = sm._finalize_current_clip(sm.last_frame_pts or time.monotonic(), close_reason="manual_finalize")
            if seg and not seg.is_discarded:
                cam_cfg = next((c for c in self.settings.cameras if c.camera_id == camera_id), None)
                self._handle_finalized_segment(seg, cam_cfg)

    def _dispatch_immediate_alert(
        self,
        camera_id: str,
        event_id: str,
        score: int,
        candidate,
        frames: list
    ):
        """
        Dispatches a Telegram/WhatsApp alert immediately when score threshold is crossed.
        Uses the frames collected so far (pre-roll + current motion frames).
        The final finalized clip will replace this once the event completes.
        """
        try:
            # Write a provisional clip from what we have so far
            if len(frames) >= 4:
                clip_path, thumb_path = self.clip_writer.write_clip_from_frames(
                    camera_id=camera_id,
                    event_group_id=event_id + "_live",
                    frames=frames[-min(len(frames), 80):],  # Use last 20s max
                    fps=4.0
                )
            else:
                clip_path, thumb_path = None, None
            obj_type = candidate.object_type if candidate else "person"
            from vyzn.core.events import EventRecord
            from datetime import datetime, timezone
            import json
            start_time = self.active_event_start_times.get(camera_id,
                         datetime.now(timezone.utc).isoformat())
            provisional_record = EventRecord(
                event_group_id=event_id,
                camera_id=camera_id,
                start_time=start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
                object_type=obj_type,
                confidence=candidate.confidence if candidate else 0.85,
                score=score,
                status="raw",
                file_path=clip_path or "",
                thumb_path=thumb_path or "",
                dominant_color="unspecified",
                zone_name="restricted_vault" if getattr(candidate, "is_in_restricted_zone", False) else "general",
                location_id="loc_primary",
                duration_sec=round(len(frames) / 4.0, 1),
                motion_points_count=self.active_event_motion_counts.get(camera_id, 1),
                metadata_json=json.dumps({"live_alert": True, "pre_roll_sec": 10.0})
            )
            self.dispatcher.dispatch(provisional_record, clip_path, thumb_path)
            logger.info(
                f"[IMMEDIATE ALERT] Dispatched live alert for {camera_id} "
                f"event {event_id} with score {score} ({len(frames)} frames)"
            )
        except Exception as e:
            logger.error(f"Immediate alert dispatch failed for {camera_id}: {e}")

    def get_telemetry_status(self) -> Dict:
        """Collects live pipeline state for the telemetry daemon."""
        return {
            "active_cameras": len([t for t in self.capture_threads if getattr(t, "is_connected", False)]),
            "queue_depth": self.frame_queue.qsize(),
            "events_active": len(self.active_event_ids),
            "config_hash": getattr(self.ota_sync, "current_config_hash", ""),
            "resource_governance": self.resource_governor.get_state()
        }

    def update_camera_zones(self, camera_id: str, zones: Optional[List[ZonePolygon]] = None, watch_areas: Optional[List[WatchAreaConfig]] = None):
        """Dynamically hot-reloads watch areas / restricted zones for a camera via atomic replacement."""
        for idx, cam in enumerate(self.settings.cameras):
            if cam.camera_id == camera_id:
                updates = {}
                if zones is not None:
                    updates["restricted_zones"] = list(zones)
                if watch_areas is not None:
                    updates["watch_areas"] = list(watch_areas)
                    # Sync restricted_zones for backward compatibility
                    updates["restricted_zones"] = [ZonePolygon(name=a.name, points=a.polygon) for a in watch_areas]

                copy_fn = getattr(cam, "model_copy", getattr(cam, "copy", None))
                if copy_fn:
                    new_cam = copy_fn(update=updates)
                else:
                    new_cam = CameraConfig(
                        camera_id=cam.camera_id,
                        name=cam.name,
                        rtsp_url=cam.rtsp_url,
                        enabled=cam.enabled,
                        target_fps=cam.target_fps,
                        is_night_ir=cam.is_night_ir,
                        restricted_zones=updates.get("restricted_zones", cam.restricted_zones),
                        watch_areas=updates.get("watch_areas", getattr(cam, "watch_areas", []))
                    )
                new_cameras = list(self.settings.cameras)
                new_cameras[idx] = new_cam
                self.settings.cameras = new_cameras

                # Update motion gate
                if getattr(new_cam, "watch_areas", None):
                    self.motion_gate.set_camera_areas(camera_id, [a.polygon for a in new_cam.watch_areas if a.polygon])
                elif getattr(new_cam, "restricted_zones", None):
                    self.motion_gate.set_camera_areas(camera_id, [z.points for z in new_cam.restricted_zones if z.points])
                else:
                    self.motion_gate.set_camera_areas(camera_id, None)

                logger.info(f"Dynamically updated watch areas for camera {camera_id} (atomic swap).")
                break

    def add_camera_stream(self, cam: CameraConfig):
        """Dynamically launches a capture thread for an adopted camera without pipeline restart."""
        self.remove_camera_stream(cam.camera_id)
        self.ring_buffers[cam.camera_id] = deque(maxlen=int(cam.target_fps * 10))

        if self.use_synthetic and str(cam.rtsp_url).startswith("sim://"):
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
        if self.running:
            thread.start()
        logger.info(f"Dynamically launched capture stream for camera '{cam.camera_id}' ({cam.name}).")

    def remove_camera_stream(self, camera_id: str):
        """Stops and unregisters the capture thread for a removed camera."""
        for t in list(self.capture_threads):
            if getattr(t, "config", None) and t.config.camera_id == camera_id:
                if hasattr(t, "stop"):
                    t.stop()
                try:
                    self.capture_threads.remove(t)
                except ValueError:
                    pass
        self.ring_buffers.pop(camera_id, None)
        self.event_buffers.pop(camera_id, None)
        self.active_event_ids.pop(camera_id, None)
        logger.info(f"Removed capture stream for camera '{camera_id}'.")

    def flush_active_events(self):
        """Forces immediate finalization of any open active events across all cameras."""
        target_cams = set(self.active_event_ids.keys()) | set(self.state_machines.keys())
        for cam_id in target_cams:
            try:
                self._finalize_event(cam_id)
            except Exception as e:
                logger.error(f"Error finalizing event for {cam_id} on flush: {e}")

    def stop(self):
        """Stops all threads and closes database."""
        self.running = False

        # Flush any active events currently in progress before terminating
        self.flush_active_events()

        for t in self.capture_threads:
            if hasattr(t, "stop"):
                t.stop()
        for t in self.capture_threads:
            t.join(timeout=2.0)

        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)

        self.ota_sync.stop()
        stop_telegram_poller()
        self.reaper.stop()
        self.cloud_sync.stop()
        self.telemetry.stop()
        self.db.close()
        logger.info("VYZN Edge Pipeline stopped cleanly.")
