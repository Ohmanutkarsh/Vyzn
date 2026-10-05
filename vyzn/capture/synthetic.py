"""
Synthetic multi-camera feed generator for Phase 0 benchmarking and test automation.
Simulates 2-5 concurrent camera streams without requiring physical RTSP hardware.
"""

from __future__ import annotations
import time
import threading
import queue
from collections import deque
import numpy as np
import cv2
from typing import List, Tuple, Optional
from vyzn.core.config import CameraConfig


class SyntheticCameraThread(threading.Thread):
    """
    Simulates a live IP camera stream by programmatically rendering frames
    with realistic background noise, daylight/night lighting, and moving objects.
    """

    def __init__(
        self,
        config: CameraConfig,
        output_queue: queue.Queue,
        motion_profile: str = "walking_person"  # 'walking_person' | 'cash_counter' | 'night_intruder' | 'static'
    ):
        super().__init__(name=f"Synthetic-{config.camera_id}", daemon=True)
        self.config = config
        self.output_queue = output_queue
        self.motion_profile = motion_profile
        self.running = True
        self.last_frame_timestamp = 0.0
        self.fps_measured = config.target_fps
        self.is_connected = True
        self.latest_frame: Optional[np.ndarray] = None
        self._latest_lock = threading.Lock()
        self.ring_buffer: deque[bytes] = deque(maxlen=int(config.target_fps * 10))
        self._ring_lock = threading.Lock()

    def get_latest_jpeg(self, quality: int = 75) -> Optional[bytes]:
        with self._latest_lock:
            if self.latest_frame is None:
                return None
            frame = self.latest_frame.copy()
        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return jpeg.tobytes() if ret else None

    def get_ring_buffer_copy(self) -> List[bytes]:
        with self._ring_lock:
            return list(self.ring_buffer)

    def run(self):
        w = self.config.downscale_width
        h = self.config.downscale_height
        fps = max(1.0, self.config.target_fps)
        delay = 1.0 / fps

        step = 0
        obj_x = 50.0
        obj_y = float(h // 2)
        direction = 1

        while self.running:
            start_time = time.monotonic()
            step += 1

            # Base background
            if self.config.is_night_ir:
                # Dark monochrome IR grain
                frame = np.full((h, w, 3), 40, dtype=np.uint8)
                noise = np.random.randint(-8, 8, (h, w, 3), dtype=np.int16)
                frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            else:
                # Daylight interior
                frame = np.full((h, w, 3), (210, 220, 215), dtype=np.uint8)
                # Simulated shop floor tile pattern
                frame[h // 2:, :] = (180, 190, 185)

            # Render motion scenario
            if self.motion_profile == "walking_person":
                # Moving simulated silhouette across frame
                obj_x += direction * 6.0
                if obj_x > w - 80 or obj_x < 40:
                    direction *= -1

                # Draw a simulated human bounding area
                cv2.rectangle(
                    frame,
                    (int(obj_x), int(obj_y) - 60),
                    (int(obj_x) + 40, int(obj_y) + 60),
                    (60, 60, 60) if self.config.is_night_ir else (40, 50, 120),
                    -1
                )
                # Head circle
                cv2.circle(
                    frame,
                    (int(obj_x) + 20, int(obj_y) - 80),
                    18,
                    (50, 50, 50) if self.config.is_night_ir else (200, 180, 160),
                    -1
                )

            elif self.motion_profile == "cash_counter":
                # Person loitering inside the cash drawer zone (fixed at center right)
                cx, cy = int(w * 0.7), int(h * 0.5)
                # Small breathing/hand motion
                offset = int(np.sin(step * 0.2) * 5)
                cv2.rectangle(
                    frame,
                    (cx - 25 + offset, cy - 50),
                    (cx + 25 + offset, cy + 50),
                    (50, 80, 50),
                    -1
                )

            elif self.motion_profile == "night_intruder":
                # Sustained movement after step 20
                if (step % 60) > 20:
                    ix = int(w * 0.3) + int((step % 60) * 2)
                    iy = int(h * 0.4)
                    cv2.rectangle(frame, (ix, iy), (ix + 35, iy + 70), (120, 120, 120), -1)

            # Timestamp and queue push
            now = time.time()
            self.last_frame_timestamp = now
            with self._latest_lock:
                self.latest_frame = frame

            ret_enc, jpeg_bytes = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ret_enc:
                with self._ring_lock:
                    self.ring_buffer.append(jpeg_bytes.tobytes())

            item = (self.config.camera_id, now, frame, self.config.is_night_ir)

            if self.output_queue.full():
                try:
                    self.output_queue.get_nowait()
                except queue.Empty:
                    pass

            try:
                self.output_queue.put_nowait(item)
            except queue.Full:
                pass

            elapsed = time.monotonic() - start_time
            sleep_time = max(0.001, delay - elapsed)
            time.sleep(sleep_time)

    def stop(self):
        self.running = False
