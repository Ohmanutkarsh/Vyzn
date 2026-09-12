"""
Fragmented MP4 (fMP4) recording manager.
Writes crash-safe event video clips with pre-roll buffering and thumbnail extraction.
"""

from __future__ import annotations
import os
import cv2
import time
import subprocess
import logging
from pathlib import Path
from typing import List, Optional
import numpy as np
from vyzn.core.ffmpeg_util import FFmpegUtil

logger = logging.getLogger("vyzn.recording.writer")


class ClipWriter:
    """
    Handles clip recording for detected incidents.
    Writes clean MP4 (no bounding boxes burned in) and saves companion JPEG thumbnail.
    """

    def __init__(self, data_root: Path):
        self.data_root = data_root

    def get_event_dir(self, camera_id: str, event_group_id: str) -> Path:
        date_str = time.strftime("%Y-%m-%d")
        event_dir = self.data_root / "raw" / camera_id / date_str / event_group_id
        event_dir.mkdir(parents=True, exist_ok=True)
        return event_dir

    def write_clip_from_frames(
        self,
        camera_id: str,
        event_group_id: str,
        frames: List[np.ndarray | bytes],
        fps: float = 4.0,
        thumb_frame: Optional[np.ndarray] = None
    ) -> tuple[str, str]:
        """
        Encodes a list of collected frames (numpy arrays or JPEG byte buffers) into an MP4 file.
        Returns (clip_path, thumb_path).
        """
        event_dir = self.get_event_dir(camera_id, event_group_id)
        clip_path = event_dir / "clip_001.mp4"
        thumb_path = event_dir / "thumb.jpg"

        if not frames:
            logger.warning(f"No frames supplied for event {event_group_id}")
            return str(clip_path), str(thumb_path)

        # Normalize frames: decode JPEG bytes to BGR arrays if needed
        decoded_frames: List[np.ndarray] = []
        for f in frames:
            if isinstance(f, bytes):
                dec = cv2.imdecode(np.frombuffer(f, np.uint8), cv2.IMREAD_COLOR)
                if dec is not None:
                    decoded_frames.append(dec)
            elif isinstance(f, np.ndarray):
                decoded_frames.append(f)

        if not decoded_frames:
            logger.warning(f"No valid frames decoded for event {event_group_id}")
            return str(clip_path), str(thumb_path)

        # Save thumbnail
        best_thumb = thumb_frame if thumb_frame is not None else decoded_frames[len(decoded_frames) // 2]
        cv2.imwrite(str(thumb_path), best_thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])

        h, w = decoded_frames[0].shape[:2]
        ffmpeg_exe = FFmpegUtil.get_executable()

        # Build FFmpeg command with fragmented MP4 flags
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{w}x{h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",  # Read from stdin
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-pix_fmt", "yuv420p",
            "-f", "mp4",
            "-movflags", "+faststart",
            str(clip_path)
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            for f in decoded_frames:
                # Ensure frame matches dimensions
                if f.shape[:2] != (h, w):
                    f = cv2.resize(f, (w, h))
                proc.stdin.write(f.tobytes())

            proc.stdin.close()
            proc.wait(timeout=10.0)
            logger.info(f"Recorded MP4 event clip: {clip_path} ({len(decoded_frames)} frames)")
        except Exception as e:
            logger.error(f"FFmpeg encoding error for event {event_group_id}: {e}")
            # Fallback to cv2.VideoWriter if subprocess fails
            self._fallback_cv2_write(clip_path, decoded_frames, fps, (w, h))

        return str(clip_path), str(thumb_path)

    def _fallback_cv2_write(
        self,
        output_path: Path,
        frames: List[np.ndarray],
        fps: float,
        size: tuple[int, int]
    ):
        w, h = size
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))
        for f in frames:
            out.write(f)
        out.release()
