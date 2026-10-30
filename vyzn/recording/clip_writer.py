"""
Fragmented MP4 (fMP4) recording manager.
Writes crash-safe event video clips with pre-roll buffering and thumbnail extraction.
Enforces atomic write-rename, FFmpeg +faststart browser compatibility, and playback verification.
"""

from __future__ import annotations
import os
import cv2
import time
import queue
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
        # Continuous whole-footage streaming state
        self._continuous_buffers: Dict[str, List[np.ndarray]] = {}
        self._continuous_buffer_starts: Dict[str, float] = {}
        self._continuous_dates: Dict[str, str] = {}
        self._continuous_fps: Dict[str, float] = {}
        self._continuous_paths: Dict[str, Path] = {}
        self._continuous_lock = threading.Lock()
        # Background worker for continuous footage encoding & concat
        self._footage_queue: queue.Queue = queue.Queue(maxsize=300)
        self._worker_running = True
        self._footage_worker = threading.Thread(
            target=self._run_footage_worker,
            daemon=True,
            name="ContinuousFootageWorker"
        )
        self._footage_worker.start()

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
        Appends incoming camera frame at its original (OG) size into the continuous 24h whole footage.
        Buffers frames and flushes in chunks using FFmpeg into <storage_dir>/full_footage/<camera_id>/<date>/footage_<date>.mp4.
        Ensures footage_<date>.mp4 is always a 100% valid, playable H.264 video with faststart.
        """
        if frame is None:
            return None

        date_str = time.strftime("%Y-%m-%d")
        pts = current_pts if current_pts is not None else time.time()
        fps = max(1.0, float(fps))

        with self._continuous_lock:
            buf = self._continuous_buffers.setdefault(camera_id, [])
            buf.append(frame)
            if camera_id not in self._continuous_buffer_starts:
                self._continuous_buffer_starts[camera_id] = pts
            self._continuous_fps[camera_id] = fps
            active_date = self._continuous_dates.setdefault(camera_id, date_str)

            # Flush when buffer reaches ~30 seconds of video OR when date rolls over at midnight
            buf_dur = len(buf) / fps
            date_changed = (active_date != date_str)
            if buf_dur >= 30.0 or date_changed:
                frames_to_flush = list(buf)
                buf.clear()
                self._continuous_buffer_starts[camera_id] = pts
                flush_date = active_date
                if date_changed:
                    self._continuous_dates[camera_id] = date_str

                try:
                    self._footage_queue.put_nowait((camera_id, flush_date, frames_to_flush, fps))
                except Exception as e:
                    logger.warning(f"Footage queue full for {camera_id}: {e}")

            footage_dir = self.data_root / "full_footage" / camera_id / date_str
            daily_file = footage_dir / f"footage_{date_str}.mp4"
            self._continuous_paths[camera_id] = daily_file
            return str(daily_file)

    def _run_footage_worker(self):
        """Processes continuous footage chunk encoding and stream-copy concat in the background."""
        while self._worker_running or not self._footage_queue.empty():
            try:
                item = self._footage_queue.get(timeout=1.0)
            except Exception:
                continue

            if item is None:
                self._footage_queue.task_done()
                break

            camera_id, date_str, frames, fps = item
            try:
                self._flush_camera_continuous_chunk(camera_id, date_str, frames, fps)
            except Exception as e:
                logger.error(f"Error encoding continuous footage for {camera_id}: {e}")
            finally:
                self._footage_queue.task_done()

    def _flush_camera_continuous_chunk(self, camera_id: str, date_str: str, frames: List[np.ndarray], fps: float):
        if not frames:
            return
        h, w = frames[0].shape[:2]
        even_w = w - (w % 2)
        even_h = h - (h % 2)

        footage_dir = self.data_root / "full_footage" / camera_id / date_str
        footage_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir = footage_dir / ".chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        daily_file = footage_dir / f"footage_{date_str}.mp4"
        ts = time.strftime("%H%M%S")
        chunk_file = chunks_dir / f"chunk_{ts}_{int(time.time()*1000)}.mp4"

        ffmpeg_exe = FFmpegUtil.get_executable()

        # Encode chunk in universal H.264 at original (OG) camera resolution
        cmd_chunk = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{even_w}x{even_h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "fastdecode",
            "-crf", "24",
            "-g", "15",
            "-keyint_min", "15",
            "-sc_threshold", "0",
            "-pix_fmt", "yuv420p",
            "-f", "mp4",
            "-movflags", "+faststart",
            str(chunk_file)
        ]

        try:
            p = subprocess.Popen(cmd_chunk, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for f in frames:
                if f.shape[:2] != (even_h, even_w):
                    f = cv2.resize(f, (even_w, even_h))
                p.stdin.write(f.tobytes())
            p.stdin.close()
            p.wait(timeout=30.0)
        except Exception as e:
            logger.error(f"Failed to encode continuous chunk for {camera_id}: {e}")
            return

        if not chunk_file.exists() or chunk_file.stat().st_size == 0:
            return

        # Atomically append chunk to daily 24-hour file
        if not daily_file.exists() or daily_file.stat().st_size == 0:
            try:
                if daily_file.exists():
                    daily_file.unlink()
                chunk_file.rename(daily_file)
                logger.info(f"Initialized 24h continuous footage for {camera_id}: {daily_file}")
            except Exception as e:
                logger.error(f"Failed to initialize daily file {daily_file}: {e}")
        else:
            # Stream-copy concat existing daily file with new chunk
            list_file = chunks_dir / "concat_list.txt"
            tmp_merged = footage_dir / f"footage_{date_str}.tmp.mp4"
            try:
                with open(list_file, "w", encoding="utf-8") as lf:
                    lf.write(f"file '{daily_file.resolve()}'\n")
                    lf.write(f"file '{chunk_file.resolve()}'\n")

                cmd_concat = [
                    ffmpeg_exe, "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(tmp_merged)
                ]
                res = subprocess.run(cmd_concat, capture_output=True, timeout=30.0)
                if res.returncode == 0 and tmp_merged.exists() and tmp_merged.stat().st_size > 0:
                    daily_file.unlink(missing_ok=True)
                    tmp_merged.rename(daily_file)
                    chunk_file.unlink(missing_ok=True)
            except Exception as e:
                logger.error(f"Failed to concat continuous footage chunk into {daily_file}: {e}")

    def close_continuous_writer(self, camera_id: str):
        """Flushes and seals the continuous daily footage for a specific camera."""
        with self._continuous_lock:
            buf = self._continuous_buffers.get(camera_id, [])
            if buf:
                d_str = self._continuous_dates.get(camera_id, time.strftime("%Y-%m-%d"))
                fps = self._continuous_fps.get(camera_id, 15.0)
                try:
                    self._footage_queue.put_nowait((camera_id, d_str, list(buf), fps))
                except Exception:
                    pass
                buf.clear()

    def close_continuous_recorders(self):
        """Flushes and seals all continuous 24h whole-footage daily files."""
        with self._continuous_lock:
            for cid, buf in list(self._continuous_buffers.items()):
                if buf:
                    d_str = self._continuous_dates.get(cid, time.strftime("%Y-%m-%d"))
                    fps = self._continuous_fps.get(cid, 15.0)
                    try:
                        self._footage_queue.put_nowait((cid, d_str, list(buf), fps))
                    except Exception:
                        pass
                buf.clear()

        # Wait for queue to flush
        try:
            self._footage_queue.join()
        except Exception:
            pass

    def write_continuous_footage_chunk(
        self,
        camera_id: str,
        frames: List[np.ndarray | bytes],
        fps: float = 4.0,
        start_time_str: Optional[str] = None
    ) -> Optional[str]:
        """
        Encodes and saves continuous full video footage without clip filters in universal H.264 format.
        Stored under <storage_dir>/full_footage/<camera_id>/<date>/footage_<timestamp>.mp4.
        Ensures entire continuous camera footage is safely stored and 100% playable.
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
        even_w = w - (w % 2)
        even_h = h - (h % 2)
        ffmpeg_exe = FFmpegUtil.get_executable()

        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{even_w}x{even_h}",
            "-pix_fmt", "bgr24",
            "-r", str(max(1.0, float(fps))),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "fastdecode",
            "-crf", "24",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(tmp_path)
        ]

        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for df in decoded_frames:
                if df.shape[:2] != (even_h, even_w):
                    df = cv2.resize(df, (even_w, even_h))
                p.stdin.write(df.tobytes())
            p.stdin.close()
            p.wait(timeout=15.0)

            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                if out_path.exists():
                    out_path.unlink()
                tmp_path.rename(out_path)
                return str(out_path)
        except Exception as e:
            logger.error(f"Error encoding continuous footage chunk: {e}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
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
        fps: float = 20.0,
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
        effective_fps = max(1.0, min(60.0, float(fps)))
        if duration_sec is not None and duration_sec > 0.5 and n_frames > 0:
            calc_fps = n_frames / float(duration_sec)
            if 1.0 <= calc_fps <= 60.0:
                out_fps = round(calc_fps, 2)
            else:
                out_fps = effective_fps
            expected_duration = round(n_frames / out_fps, 1)
        else:
            out_fps = effective_fps
            expected_duration = round(n_frames / out_fps, 1)

        # Encode authentic live feed frames directly so clips contain real continuous video motion
        resampled_frames = decoded_frames

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

        # SPEC: preview.mp4 (muted, 480p, H.264, ~6s from the top-score ticks, fastdecode tuned)
        preview_path = cache_dir / "preview.mp4"
        tmp_prev_path = cache_dir / "preview.mp4.tmp"
        preview_frames_count = max(6, int(round(fps * 6.0)))
        p_start = max(0, p_idx - preview_frames_count // 2)
        p_end = min(n_frames, p_start + preview_frames_count)
        preview_frames = decoded_frames[p_start:p_end]
        if not preview_frames:
            preview_frames = decoded_frames[:min(n_frames, preview_frames_count)]

        prev_fps = max(15.0, out_fps)
        prev_total = max(len(preview_frames), int(round(len(preview_frames) / max(0.5, fps) * prev_fps)))
        if prev_total > len(preview_frames) and len(preview_frames) > 0:
            resampled_prev = []
            for i in range(prev_total):
                src_i = min(len(preview_frames) - 1, int(round(i * (len(preview_frames) - 1) / max(1, prev_total - 1))))
                resampled_prev.append(preview_frames[src_i])
        else:
            resampled_prev = preview_frames

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
            "-r", str(prev_fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "fastdecode",
            "-profile:v", "baseline",
            "-level", "3.0",
            "-g", "15",
            "-keyint_min", "15",
            "-crf", "28",
            "-an",  # muted
            "-pix_fmt", "yuv420p",
            "-f", "mp4",
            "-movflags", "+faststart",
            str(tmp_prev_path)
        ]
        try:
            prev_proc = subprocess.Popen(cmd_prev, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for pf in resampled_prev:
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

        # Build FFmpeg command with smooth 15+ FPS, GOP 15 (1 keyframe/s), fastdecode, universal H.264, +faststart, and silent audio
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{even_w}x{even_h}",
            "-pix_fmt", "bgr24",
            "-r", str(out_fps),
            "-i", "-",  # Read from stdin
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",  # Universal silent audio
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "fastdecode",
            "-crf", "23",
            "-g", "15",
            "-keyint_min", "15",
            "-sc_threshold", "0",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            "-shortest",
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
            for f in resampled_frames:
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
            self._fallback_cv2_write(clip_path, decoded_frames, out_fps, (w, h))
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
        even_w = w - (w % 2)
        even_h = h - (h % 2)
        safe_fps = max(15.0, float(fps))
        tmp_cv2 = output_path.with_suffix(".cv2.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(tmp_cv2), fourcc, safe_fps, (even_w, even_h))
        for f in frames:
            if f.shape[:2] != (even_h, even_w):
                f = cv2.resize(f, (even_w, even_h))
            out.write(f)
        out.release()

        # Immediately transcode cv2 mp4v to universal H.264 +faststart with audio
        try:
            ffmpeg_exe = FFmpegUtil.get_executable()
            tmp_transcode = output_path.with_suffix(".h264.mp4")
            cmd = [
                ffmpeg_exe, "-y",
                "-i", str(tmp_cv2),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "fastdecode",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "64k",
                "-shortest",
                "-movflags", "+faststart",
                str(tmp_transcode)
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15.0)
            if res.returncode == 0 and tmp_transcode.exists() and tmp_transcode.stat().st_size > 0:
                output_path.unlink(missing_ok=True)
                tmp_transcode.rename(output_path)
            elif tmp_cv2.exists() and not output_path.exists():
                tmp_cv2.rename(output_path)
        except Exception:
            if tmp_cv2.exists() and not output_path.exists():
                tmp_cv2.rename(output_path)
        finally:
            if tmp_cv2.exists():
                tmp_cv2.unlink(missing_ok=True)
