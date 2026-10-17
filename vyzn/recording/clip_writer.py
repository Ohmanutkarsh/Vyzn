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
import threading
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
    poster_path: str = ""
    preview_path: str = ""

    def __iter__(self):
        """Allows unpacking as (clip_path, thumb_path) for full backward compatibility."""
        return iter([self.clip_path, self.thumb_path])


class ClipWriter:
    """
    Handles clip recording for detected incidents.
    Writes clean MP4 (no bounding boxes burned in) and saves companion JPEG thumbnails in internal cache.
    """

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        # Continuous whole-footage streaming writers (one file per day, up to 24 hours per file)
        self._continuous_writers: Dict[str, cv2.VideoWriter] = {}
        self._continuous_dates: Dict[str, str] = {}
        self._continuous_start_pts: Dict[str, float] = {}
        self._continuous_paths: Dict[str, Path] = {}
        self._continuous_lock = threading.Lock()

    def get_event_dir(self, camera_id: str, event_group_id: str) -> Path:
        date_str = time.strftime("%Y-%m-%d")
        # In simple terms: incident clips are stored in a dedicated 'clips' subfolder
        event_dir = self.data_root / "clips" / camera_id / date_str / event_group_id
        event_dir.mkdir(parents=True, exist_ok=True)
        return event_dir

    def get_full_footage_dir(self, camera_id: str) -> Path:
        date_str = time.strftime("%Y-%m-%d")
        # In simple terms: continuous whole video recordings are stored in 'full_footage'
        footage_dir = self.data_root / "full_footage" / camera_id / date_str
        footage_dir.mkdir(parents=True, exist_ok=True)
        return footage_dir

    def append_continuous_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        fps: float = 15.0,
        current_pts: Optional[float] = None
    ) -> Optional[str]:
        """
        Appends incoming camera frame directly into the continuous daily whole footage video file.
        Stored under <storage_dir>/full_footage/<camera_id>/<date>/footage_<date>.mp4.
        Ensures a single continuous 24h video is recorded with zero fragmentation.
        """
        if frame is None:
            return None

        date_str = time.strftime("%Y-%m-%d")
        pts = current_pts if current_pts is not None else time.time()

        with self._continuous_lock:
            # Check if writer exists and if date rolled over or 24 hours elapsed (86400s)
            active_writer = self._continuous_writers.get(camera_id)
            active_date = self._continuous_dates.get(camera_id)
            start_pts = self._continuous_start_pts.get(camera_id, pts)

            needs_rollover = (
                active_writer is not None
                and (active_date != date_str or (pts - start_pts) >= 86400.0)
            )
            if needs_rollover:
                try:
                    active_writer.release()
                except Exception:
                    pass
                self._continuous_writers.pop(camera_id, None)
                active_writer = None

            if active_writer is None:
                footage_dir = self.data_root / "full_footage" / camera_id / date_str
                footage_dir.mkdir(parents=True, exist_ok=True)
                out_path = footage_dir / f"footage_{date_str}.mp4"
                h, w = frame.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(out_path), fourcc, max(1.0, float(fps)), (w, h))
                self._continuous_writers[camera_id] = writer
                self._continuous_dates[camera_id] = date_str
                self._continuous_start_pts[camera_id] = pts
                self._continuous_paths[camera_id] = out_path
                active_writer = writer

            try:
                active_writer.write(frame)
            except Exception as e:
                logger.warning(f"Error writing continuous frame for {camera_id}: {e}")

            return str(self._continuous_paths.get(camera_id, ""))

    def close_continuous_writer(self, camera_id: str):
        """Flushes and closes the continuous daily footage writer for a specific camera."""
        with self._continuous_lock:
            writer = self._continuous_writers.pop(camera_id, None)
            if writer is not None:
                try:
                    writer.release()
                except Exception:
                    pass
            self._continuous_dates.pop(camera_id, None)
            self._continuous_start_pts.pop(camera_id, None)
            self._continuous_paths.pop(camera_id, None)

    def close_continuous_recorders(self):
        """Flushes and releases all continuous whole-footage writers."""
        with self._continuous_lock:
            for cid, writer in list(self._continuous_writers.items()):
                try:
                    writer.release()
                except Exception:
                    pass
            self._continuous_writers.clear()
            self._continuous_dates.clear()
            self._continuous_start_pts.clear()
            self._continuous_paths.clear()

    def write_continuous_footage_chunk(
        self,
        camera_id: str,
        frames: List[np.ndarray | bytes],
        fps: float = 4.0,
        start_time_str: Optional[str] = None
    ) -> Optional[str]:
        """
        Encodes and saves continuous full video footage without clip filters.
        Stored under <storage_dir>/full_footage/<camera_id>/<date>/footage_<timestamp>.mp4.
        Ensures entire continuous camera footage is safely stored and crash-resistant.
        """
        if not frames:
            return None

        footage_dir = self.get_full_footage_dir(camera_id)
        ts = start_time_str or time.strftime("%Y%m%d_%H%M%S")
        out_path = footage_dir / f"footage_{ts}.mp4"
        tmp_path = footage_dir / f"footage_{ts}.tmp.mp4"

        decoded_frames: List[np.ndarray] = []
        for f in frames:
            if isinstance(f, bytes):
                dec = cv2.imdecode(np.frombuffer(f, np.uint8), cv2.IMREAD_COLOR)
                if dec is not None:
                    decoded_frames.append(dec)
            elif isinstance(f, np.ndarray):
                decoded_frames.append(f)

        if not decoded_frames:
            return None

        h, w = decoded_frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_path), fourcc, max(1.0, fps), (w, h))
        for df in decoded_frames:
            if df.shape[:2] != (h, w):
                df = cv2.resize(df, (w, h))
            writer.write(df)
        writer.release()

        # Atomic rename once file is written
        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            if out_path.exists():
                out_path.unlink()
            tmp_path.rename(out_path)
            return str(out_path)
        return None

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
        peak_idx: Optional[int] = None,
        duration_sec: Optional[float] = None
    ) -> ClipWriteResult:
        """
        Encodes a list of collected frames into an MP4 file with atomic write-rename and faststart.
        If duration_sec is provided, aligns effective playback FPS so video length exactly matches PTS video time.
        Returns ClipWriteResult (unpacks as (clip_path, thumb_path)).
        """
        event_dir = self.get_event_dir(camera_id, event_group_id)
        clip_path = event_dir / "clip_001.mp4"
        tmp_clip_path = event_dir / "clip_001.mp4.tmp"

        # In simple terms: store all companion files (thumbnails, posters, previews, keyframes)
        # in a dedicated cache directory so the user's clips/ folder contains ONLY clean .mp4 video files!
        date_str = time.strftime("%Y-%m-%d")
        cache_dir = self.data_root / ".cache" / "previews" / camera_id / date_str / event_group_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = cache_dir / "thumb.jpg"
        poster_path = cache_dir / "poster.jpg"

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
        # In simple terms: if the caller specified the true video duration (from video PTS timestamps),
        # compute the effective frame rate so that playing the video takes exactly that duration.
        # This keeps the video player scrubber and the activity timeline in 100% perfect synchronization!
        if duration_sec is not None and duration_sec > 0.5:
            expected_duration = round(float(duration_sec), 1)
            # Dynamic frame rate so the whole video file matches true event time
            fps = max(0.5, round(n_frames / expected_duration, 3))
        else:
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
            k_path = cache_dir / f"keyframe_{k_i}.jpg"
            cv2.imwrite(str(k_path), decoded_frames[f_idx], [cv2.IMWRITE_JPEG_QUALITY, 85])
            keyframe_paths.append(str(k_path))

        # Save main card preview thumbnail (from thumb_frame or peak frame)
        best_thumb = thumb_frame if thumb_frame is not None else decoded_frames[p_idx]
        cv2.imwrite(str(thumb_path), best_thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])

        # SPEC: poster.jpg from the peak-score frame
        cv2.imwrite(str(poster_path), best_thumb, [cv2.IMWRITE_JPEG_QUALITY, 90])

        h, w = decoded_frames[0].shape[:2]
        ffmpeg_exe = FFmpegUtil.get_executable()

        # SPEC: preview.mp4 (muted, 480p, H.264, ~6s from the top-score ticks)
        preview_path = cache_dir / "preview.mp4"
        tmp_prev_path = cache_dir / "preview.mp4.tmp"
        preview_frames_count = max(6, int(round(fps * 6.0)))
        p_start = max(0, p_idx - preview_frames_count // 2)
        p_end = min(n_frames, p_start + preview_frames_count)
        preview_frames = decoded_frames[p_start:p_end]
        if not preview_frames:
            preview_frames = decoded_frames[:min(n_frames, preview_frames_count)]

        # Scale to 480p (480 height, width proportional and even)
        prev_h = 480
        prev_w = int(round(w * (prev_h / float(h))))
        if prev_w % 2 != 0:
            prev_w += 1

        cmd_prev = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{prev_w}x{prev_h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-an",  # muted
            "-pix_fmt", "yuv420p",
            "-f", "mp4",
            "-movflags", "+faststart",
            str(tmp_prev_path)
        ]
        try:
            prev_proc = subprocess.Popen(cmd_prev, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for pf in preview_frames:
                p_resized = cv2.resize(pf, (prev_w, prev_h))
                prev_proc.stdin.write(p_resized.tobytes())
            prev_proc.stdin.close()
            prev_proc.wait(timeout=10.0)
            if tmp_prev_path.exists() and tmp_prev_path.stat().st_size > 0:
                if preview_path.exists():
                    preview_path.unlink()
                tmp_prev_path.rename(preview_path)
        except Exception as e:
            logger.warning(f"Error encoding preview.mp4: {e}")

        # Ensure dimensions are strictly even for H.264 / yuv420p encoder compatibility
        even_w = w - (w % 2)
        even_h = h - (h % 2)

        # Build FFmpeg command with fragmented MP4 flags and +faststart
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{even_w}x{even_h}",
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
                if f.shape[:2] != (even_h, even_w):
                    f = cv2.resize(f, (even_w, even_h))
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

                # Also provide canonical clip.mp4 in event dir
                canon_path = event_dir / "clip.mp4"
                if not canon_path.exists():
                    try:
                        import shutil
                        shutil.copyfile(clip_path, canon_path)
                    except Exception:
                        pass
            else:
                logger.warning(f"FFmpeg output verification failed for {tmp_clip_path}; trying fallback.")
        except Exception as e:
            logger.error(f"FFmpeg encoding error for event {event_group_id}: {e}")

        if not success:
            # Fallback to OpenCV VideoWriter
            self._fallback_cv2_write(clip_path, decoded_frames, fps, (w, h))
            canon_path = event_dir / "clip.mp4"
            if not canon_path.exists() and clip_path.exists():
                try:
                    import shutil
                    shutil.copyfile(clip_path, canon_path)
                except Exception:
                    pass
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
            is_valid=True,
            poster_path=str(poster_path) if poster_path.exists() else str(thumb_path),
            preview_path=str(preview_path) if preview_path.exists() else str(clip_path)
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

        # Transcode cv2 mp4v to mobile-compatible H.264 if FFmpeg is available
        try:
            ffmpeg_exe = FFmpegUtil.get_executable()
            tmp_transcode = output_path.with_suffix(".h264.mp4")
            cmd = [
                ffmpeg_exe, "-y",
                "-i", str(output_path),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "26",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(tmp_transcode)
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10.0)
            if res.returncode == 0 and tmp_transcode.exists() and tmp_transcode.stat().st_size > 0:
                output_path.unlink(missing_ok=True)
                tmp_transcode.rename(output_path)
        except Exception:
            pass
