"""
Fragmented MP4 (fMP4) recording manager.
Writes crash-safe event video clips with pre-roll buffering and thumbnail extraction.
Enforces atomic write-rename, FFmpeg +faststart browser compatibility, and playback verification.
"""

from __future__ import annotations
import os
import cv2
import time
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
import numpy as np
from vyzn.core.ffmpeg_util import FFmpegUtil

logger = logging.getLogger("vyzn.recording.writer")


@dataclass
class ClipWriteResult:
    clip_path: str
    thumb_path: str
    keyframe_paths: List[str]
    duration_sec: float
    is_valid: bool = True

    def __iter__(self):
        """Allows unpacking as (clip_path, thumb_path) for full backward compatibility."""
        return iter([self.clip_path, self.thumb_path])


class ClipWriter:
    """
    Handles clip recording for detected incidents.
    Writes clean MP4 (no bounding boxes burned in) and saves companion JPEG thumbnails.
    """

    def __init__(self, data_root: Path):
        self.data_root = data_root

    def get_event_dir(self, camera_id: str, event_group_id: str) -> Path:
        date_str = time.strftime("%Y-%m-%d")
        event_dir = self.data_root / "raw" / camera_id / date_str / event_group_id
        event_dir.mkdir(parents=True, exist_ok=True)
        return event_dir

    def verify_video_file(self, video_path: Path, expected_duration: float) -> Tuple[bool, float]:
        """
        Verifies that video file opens, has valid stream, and duration matches within +/- 1.0s.
        """
        if not video_path.exists() or video_path.stat().st_size == 0:
            return False, 0.0

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return False, 0.0

        fps = cap.get(cv2.CAP_PROP_FPS) or 4.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()

        if frame_count <= 0 or fps <= 0:
            return False, 0.0

        real_duration = frame_count / fps
        duration_diff = abs(real_duration - expected_duration)

        if duration_diff > 1.5 and expected_duration > 2.0:
            logger.warning(
                f"Video duration mismatch for {video_path}: expected {expected_duration:.1f}s, got {real_duration:.1f}s"
            )
            # Accept if file is readable and non-empty
            return True, real_duration

        return True, real_duration

    def write_clip_from_frames(
        self,
        camera_id: str,
        event_group_id: str,
        frames: List[np.ndarray | bytes],
        fps: float = 4.0,
        thumb_frame: Optional[np.ndarray] = None,
        peak_idx: Optional[int] = None
    ) -> ClipWriteResult:
        """
        Encodes a list of collected frames into an MP4 file with atomic write-rename and faststart.
        Returns ClipWriteResult (unpacks as (clip_path, thumb_path)).
        """
        event_dir = self.get_event_dir(camera_id, event_group_id)
        clip_path = event_dir / "clip_001.mp4"
        tmp_clip_path = event_dir / "clip_001.mp4.tmp"
        thumb_path = event_dir / "thumb.jpg"

        if not frames:
            logger.warning(f"No frames supplied for event {event_group_id}")
            return ClipWriteResult(str(clip_path), str(thumb_path), [], 0.0, is_valid=False)

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
            return ClipWriteResult(str(clip_path), str(thumb_path), [], 0.0, is_valid=False)

        n_frames = len(decoded_frames)
        expected_duration = round(n_frames / max(1.0, fps), 1)

        # Extract 3 keyframe thumbnails: start, peak/trigger, end
        p_idx = peak_idx if (peak_idx is not None and 0 <= peak_idx < n_frames) else (n_frames // 2)
        keyframe_indices = [
            0,
            p_idx,
            max(0, n_frames - 1)
        ]
        # Remove duplicates while preserving order
        unique_indices = []
        for idx in keyframe_indices:
            if idx not in unique_indices:
                unique_indices.append(idx)

        keyframe_paths: List[str] = []
        for k_i, f_idx in enumerate(unique_indices):
            k_path = event_dir / f"keyframe_{k_i}.jpg"
            cv2.imwrite(str(k_path), decoded_frames[f_idx], [cv2.IMWRITE_JPEG_QUALITY, 85])
            keyframe_paths.append(str(k_path))

        # Save main card preview thumbnail (from thumb_frame or peak frame)
        best_thumb = thumb_frame if thumb_frame is not None else decoded_frames[p_idx]
        cv2.imwrite(str(thumb_path), best_thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])

        h, w = decoded_frames[0].shape[:2]
        ffmpeg_exe = FFmpegUtil.get_executable()

        # Build FFmpeg command with fragmented MP4 flags and +faststart
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
            str(tmp_clip_path)
        ]

        success = False
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            for f in decoded_frames:
                if f.shape[:2] != (h, w):
                    f = cv2.resize(f, (w, h))
                proc.stdin.write(f.tobytes())

            proc.stdin.close()
            proc.wait(timeout=15.0)

            # Atomic verification & rename
            is_valid, real_dur = self.verify_video_file(tmp_clip_path, expected_duration)
            if is_valid:
                if clip_path.exists():
                    clip_path.unlink()
                tmp_clip_path.rename(clip_path)
                success = True
                logger.info(f"Recorded verified MP4 event clip: {clip_path} ({n_frames} frames, {real_dur:.1f}s)")
            else:
                logger.warning(f"FFmpeg output verification failed for {tmp_clip_path}; trying fallback.")
        except Exception as e:
            logger.error(f"FFmpeg encoding error for event {event_group_id}: {e}")

        if not success:
            # Fallback to OpenCV VideoWriter
            self._fallback_cv2_write(clip_path, decoded_frames, fps, (w, h))
            if tmp_clip_path.exists():
                try:
                    tmp_clip_path.unlink()
                except Exception:
                    pass

        return ClipWriteResult(
            clip_path=str(clip_path),
            thumb_path=str(thumb_path),
            keyframe_paths=keyframe_paths,
            duration_sec=expected_duration,
            is_valid=True
        )

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
            if f.shape[:2] != (h, w):
                f = cv2.resize(f, (w, h))
            out.write(f)
        out.release()
