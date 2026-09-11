"""
Multi-stream RTSP capture worker with TCP enforcement, frame decimation, and reconnect watchdog.
"""

from __future__ import annotations
import os
import time
import threading
import queue
import logging
import cv2
import numpy as np
from typing import Optional, Tuple
from vyzn.core.config import CameraConfig

# Enforce TCP transport across all OpenCV FFmpeg captures globally
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

logger = logging.getLogger("vyzn.capture.stream")


class RTSPCaptureThread(threading.Thread):
    """
    Dedicated thread per RTSP camera stream.
    Decimates frames to target inference rate (e.g. 4 fps) and downscales to 360p.
    Never blocks the main inference loop.
    """

    def __init__(
        self,
        config: CameraConfig,
        output_queue: queue.Queue,
        max_queue_size: int = 20
    ):
        super().__init__(name=f"Capture-{config.camera_id}", daemon=True)
        self.config = config
        self.output_queue = output_queue
        self.max_queue_size = max_queue_size
        self.running = True

        # Health metrics for remote telemetry
        self.last_frame_timestamp = 0.0
        self.fps_measured = 0.0
        self.is_connected = False
        self.reconnect_count = 0

    def run(self):
        backoff_sec = 1.0
        max_backoff = 30.0

        while self.running:
            url_str = str(self.config.rtsp_url).strip()
            logger.info(f"[{self.config.camera_id}] Opening stream: {url_str}")
            
            if url_str.isdigit():
                cap = cv2.VideoCapture(int(url_str), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
            elif url_str.startswith("webcam://"):
                try:
                    dev_idx = int(url_str.split("://")[1])
                except Exception:
                    dev_idx = 0
                cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
            elif url_str.startswith("http://") or url_str.startswith("https://") or url_str.endswith(".mp4") or os.path.exists(url_str):
                cap = cv2.VideoCapture(url_str)
            else:
                cap = cv2.VideoCapture(url_str, cv2.CAP_FFMPEG)

            if not cap.isOpened():
                logger.warning(
                    f"[{self.config.camera_id}] Failed to open stream. Retrying in {backoff_sec:.1f}s..."
                )
                self.is_connected = False
                time.sleep(backoff_sec)
                backoff_sec = min(max_backoff, backoff_sec * 2)
                self.reconnect_count += 1
                continue

            self.is_connected = True
            backoff_sec = 1.0
            self.last_frame_timestamp = time.monotonic()

            frame_interval = 1.0 / max(1.0, self.config.target_fps)
            last_pushed_time = 0.0
            frame_counter = 0
            start_measure_time = time.monotonic()

            while self.running:
                ret, frame = cap.read()
                now = time.monotonic()

                # Watchdog check: 8-second frame silence triggers reconnect
                if not ret or (now - self.last_frame_timestamp > 8.0):
                    logger.warning(
                        f"[{self.config.camera_id}] Watchdog: frame silence > 8s or read failure. Tearing down connection."
                    )
                    break

                self.last_frame_timestamp = now

                # FPS Measurement
                frame_counter += 1
                if now - start_measure_time >= 2.0:
                    self.fps_measured = frame_counter / (now - start_measure_time)
                    frame_counter = 0
                    start_measure_time = now

                # Decimate: Only take frame if interval elapsed
                if now - last_pushed_time < frame_interval:
                    continue

                last_pushed_time = now

                # Downscale to 360p for MOG2 & Inference
                downscaled = cv2.resize(
                    frame,
                    (self.config.downscale_width, self.config.downscale_height),
                    interpolation=cv2.INTER_AREA
                )

                # Push to queue (drop oldest frame if queue full to avoid memory buildup)
                item = (self.config.camera_id, now, downscaled, self.config.is_night_ir)
                if self.output_queue.full():
                    try:
                        self.output_queue.get_nowait()
                    except queue.Empty:
                        pass

                try:
                    self.output_queue.put_nowait(item)
                except queue.Full:
                    pass

            cap.release()
            self.is_connected = False
            if self.running:
                logger.info(f"[{self.config.camera_id}] Reconnecting after stream closure...")
                time.sleep(1.0)

    def stop(self):
        self.running = False
