from __future__ import annotations
import os
import time
import threading
import queue
import logging
from collections import deque
import cv2
import numpy as np
from typing import Optional, Tuple, List
from vyzn.core.config import CameraConfig

# Enforce TCP transport across all OpenCV FFmpeg captures globally
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

logger = logging.getLogger("vyzn.capture.stream")


def normalize_camera_stream_url(url: str) -> str:
    """Auto-formats smartphone and RTSP camera URLs to valid stream endpoints."""
    url = str(url).strip()
    if ":8080" in url and not any(p in url for p in ["/video", "/shot.jpg", "/videofeed"]):
        url = url.rstrip("/") + "/video"
    elif ":4747" in url and not any(p in url for p in ["/video", "/mjpegfeed"]):
        url = url.rstrip("/") + "/video"
    return url


def probe_stream_connection(url_str: str, timeout_sec: float = 3.5) -> Tuple[bool, str]:
    """Tests if a camera URL or device index can be opened and read."""
    norm_url = normalize_camera_stream_url(url_str)
    try:
        if norm_url.isdigit():
            cap = cv2.VideoCapture(int(norm_url), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        elif norm_url.startswith("http://") or norm_url.startswith("https://"):
            cap = cv2.VideoCapture(norm_url)
        elif norm_url.startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;3000000"
            cap = cv2.VideoCapture(norm_url, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(norm_url)

        if not cap or not cap.isOpened():
            return False, f"Cannot connect to '{norm_url}'. Check device IP, Wi-Fi, and ensure camera server is running."

        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return False, f"Connected to '{norm_url}', but failed to read initial video frame."

        return True, "Connection successful"
    except Exception as e:
        return False, f"Connection probe error for '{norm_url}': {str(e)}"


class RTSPCaptureThread(threading.Thread):
    """
    Dedicated thread per RTSP/Webcam stream with Dual-Loop Architecture:
    Loop 1: High-FPS ingest (15-30 FPS) with RAM-aware compressed JPEG ring buffer.
    Loop 2 (Decimation): Passes 2-4 FPS to the shared YOLO inference worker.
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

        # Dual-loop frame rates
        self.capture_fps = float(getattr(config, "capture_fps", 15.0) or 15.0)
        self.ai_inference_fps = float(getattr(config, "ai_inference_fps", getattr(config, "target_fps", 4.0)) or 4.0)

        # Health metrics for remote telemetry & UI
        self.last_frame_timestamp = 0.0
        self.fps_measured = 0.0
        self.is_connected = False
        self.status = "connecting"  # 'online' | 'connecting' | 'offline' | 'error'
        self.last_error = ""
        self.reconnect_count = 0

        # RAM-Aware Ring Buffer (stores 10 seconds of compact JPEG bytes, ~30KB/frame)
        self.ring_buffer: deque[bytes] = deque(maxlen=int(self.capture_fps * 10))
        self._ring_lock = threading.Lock()

        # Latest frame buffer for live MJPEG streaming
        self.latest_frame: Optional[np.ndarray] = None
        self._latest_lock = threading.Lock()

    def get_connection_status(self) -> Dict[str, Any]:
        """Returns structured connection diagnostics for API endpoints and UI."""
        return {
            "camera_id": self.config.camera_id,
            "status": self.status,
            "is_connected": self.is_connected,
            "fps_measured": round(self.fps_measured, 1),
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count
        }

    def get_latest_jpeg(self, quality: int = 75) -> Optional[bytes]:
        """Returns compressed JPEG bytes of the most recent live frame or diagnostics card."""
        with self._latest_lock:
            if self.latest_frame is None:
                card = np.full((360, 640, 3), (20, 24, 33), dtype=np.uint8)
                color = (40, 160, 220) if self.status == "connecting" else (50, 50, 220)
                status_text = f"Status: {self.status.upper()}"
                cv2.putText(card, f"Camera: {self.config.name}", (40, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(card, status_text, (40, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
                if self.last_error:
                    cv2.putText(card, self.last_error[:65], (40, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1)
                ret, jpeg = cv2.imencode(".jpg", card, [cv2.IMWRITE_JPEG_QUALITY, quality])
                return jpeg.tobytes() if ret else None
            frame = self.latest_frame.copy()

        h, w = frame.shape[:2]
        if w > 854:
            frame = cv2.resize(frame, (854, int(854 * h / w)))
        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return jpeg.tobytes() if ret else None

    def get_ring_buffer_copy(self) -> List[bytes]:
        """Thread-safe snapshot of compressed JPEG frames in the 10-second ring buffer."""
        with self._ring_lock:
            return list(self.ring_buffer)

    def run(self):
        backoff_sec = 1.0
        max_backoff = 30.0

        while self.running:
            url_str = normalize_camera_stream_url(str(self.config.rtsp_url).strip())
            self.status = "connecting"
            logger.info(f"[{self.config.camera_id}] Opening stream: {url_str}")

            # Configure capture backend and transport options
            if url_str.startswith("rtsp://"):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
            else:
                os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)

            if url_str.isdigit():
                cap = cv2.VideoCapture(int(url_str), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
            elif url_str.startswith("webcam://"):
                try:
                    dev_idx = int(url_str.split("://")[1])
                except Exception:
                    dev_idx = 0
                cap = cv2.VideoCapture(dev_idx, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
            elif url_str.startswith("http://") or url_str.startswith("https://"):
                # Phone camera / IP Webcam / MJPEG stream
                cap = cv2.VideoCapture(url_str)
            elif url_str.endswith(".mp4") or os.path.exists(url_str):
                cap = cv2.VideoCapture(url_str)
            else:
                cap = cv2.VideoCapture(url_str, cv2.CAP_FFMPEG)

            if not cap or not cap.isOpened():
                self.status = "error"
                self.is_connected = False
                self.last_error = f"Cannot open stream: {url_str}. Check device IP, Wi-Fi, and app."
                logger.warning(
                    f"[{self.config.camera_id}] Failed to open stream ({self.last_error}). Retrying in {backoff_sec:.1f}s..."
                )
                time.sleep(backoff_sec)
                backoff_sec = min(max_backoff, backoff_sec * 2)
                self.reconnect_count += 1
                continue

            self.status = "online"
            self.is_connected = True
            self.last_error = ""
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
                    self.status = "offline"
                    self.is_connected = False
                    self.last_error = "Watchdog: 8s frame silence / read failure"
                    logger.warning(
                        f"[{self.config.camera_id}] Watchdog: frame silence > 8s or read failure. Tearing down connection."
                    )
                    break

                self.last_frame_timestamp = now
                with self._latest_lock:
                    self.latest_frame = frame

                # Compress downscaled frame to JPEG for RAM-aware ring buffer (~30KB/frame)
                h, w = frame.shape[:2]
                target_w, target_h = self.config.downscale_width, self.config.downscale_height
                if (w, h) != (target_w, target_h):
                    buf_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                else:
                    buf_frame = frame

                ret_enc, jpeg_bytes = cv2.imencode(".jpg", buf_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ret_enc:
                    with self._ring_lock:
                        self.ring_buffer.append(jpeg_bytes.tobytes())

                # FPS Measurement
                frame_counter += 1
                if now - start_measure_time >= 2.0:
                    self.fps_measured = frame_counter / (now - start_measure_time)
                    frame_counter = 0
                    start_measure_time = now

                # Dual-loop Decimation: Only pass 2-4 FPS to shared YOLO inference worker
                inference_interval = 1.0 / max(1.0, self.ai_inference_fps)
                if now - last_pushed_time < inference_interval:
                    continue

                last_pushed_time = now

                # Downscale to 360p for MOG2 & Inference
                downscaled = buf_frame

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
