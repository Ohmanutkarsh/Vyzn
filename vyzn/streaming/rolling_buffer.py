"""
Rolling fMP4 Disk Buffer for Live CCTV Streaming & Timeshift.

Implements a 15-minute rolling FIFO ring buffer written directly to disk as
Fragmented MP4 (.m4s + init.mp4) segments via an FFmpeg HLS daemon.

Key Architectural Guarantees:
1. DPDP Act Storage Invariant:
   - Rolling buffer path: <storage_dir>/live_buffer/{camera_id}/ (15-min rolling window).
   - Permanent event retention: <storage_dir>/raw/ or <storage_dir>/clips/ (never touched or deleted).
2. RAM Protection Invariant:
   - Zero video segments stored in Python heap memory.
   - FFmpeg flushes segments directly to NVMe/SSD disk in 2-second chunks.
3. Subprocess Safety:
   - Clean startup, termination, and orphaned segment eviction.
"""

from __future__ import annotations
import os
import re
import time
import shutil
import logging
import datetime
import threading
import subprocess
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple

from vyzn.core.ffmpeg_util import FFmpegUtil

logger = logging.getLogger("vyzn.streaming.buffer")

_GLOBAL_BUFFER_MANAGER: Optional[RollingBufferManager] = None
_GLOBAL_LOCK = threading.Lock()


def get_default_storage_dir() -> Path:
    """Resolves primary storage directory from config/storage.json or default."""
    cfg_file = Path("config/storage.json")
    if cfg_file.exists():
        try:
            import json
            with open(cfg_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("storage_dir"):
                    p = Path(d["storage_dir"])
                    p.mkdir(parents=True, exist_ok=True)
                    return p
        except Exception:
            pass
    fallback = Path("./data/clips")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_rolling_buffer_manager(storage_dir: Optional[Path] = None) -> RollingBufferManager:
    """Returns singleton instance of RollingBufferManager."""
    global _GLOBAL_BUFFER_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_BUFFER_MANAGER is None:
            resolved_dir = storage_dir or get_default_storage_dir()
            _GLOBAL_BUFFER_MANAGER = RollingBufferManager(resolved_dir)
        elif storage_dir and _GLOBAL_BUFFER_MANAGER.storage_dir != Path(storage_dir):
            _GLOBAL_BUFFER_MANAGER.storage_dir = Path(storage_dir)
        return _GLOBAL_BUFFER_MANAGER


class RollingBufferManager:
    """
    Manages live camera rolling buffer daemons.
    Each camera receives an isolated directory under <storage_dir>/live_buffer/<cam_id>/.
    Segments older than 450 items (15 minutes @ 2s/segment) are automatically unlinked.
    """

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir).resolve()
        self.live_buffer_root = self.storage_dir / "live_buffer"
        self.live_buffer_root.mkdir(parents=True, exist_ok=True)

        self._processes: Dict[str, subprocess.Popen] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._start_times: Dict[str, float] = {}
        self._lock = threading.Lock()

    def get_camera_buffer_dir(self, camera_id: str) -> Path:
        """Returns safe, validated directory path for camera rolling buffer."""
        clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(camera_id).strip())
        target = (self.live_buffer_root / clean_id).resolve()
        # Invariant security check: ensure target stays inside live_buffer_root
        if not str(target).startswith(str(self.live_buffer_root)):
            raise ValueError(f"Path traversal detected for camera_id: {camera_id}")
        return target

    def is_buffer_running(self, camera_id: str) -> bool:
        """Checks if FFmpeg daemon for camera is actively running."""
        with self._lock:
            p = self._processes.get(camera_id)
            if p is not None:
                if p.poll() is None:
                    return True
                # Process died
                self._processes.pop(camera_id, None)
            return False

    def start_camera_buffer(
        self,
        camera_id: str,
        rtsp_url: str,
        copy_codec: bool = False
    ) -> bool:
        """
        Starts rolling fMP4 HLS buffer daemon for camera.
        Cleans old stale files on startup and spawns FFmpeg background process.
        """
        with self._lock:
            # If already running, return True
            existing = self._processes.get(camera_id)
            if existing is not None and existing.poll() is None:
                return True

            cam_dir = self.get_camera_buffer_dir(camera_id)
            cam_dir.mkdir(parents=True, exist_ok=True)

            # Clean stale buffer files from previous runs
            self._cleanup_buffer_dir(cam_dir)

            ffmpeg_exe = FFmpegUtil.get_executable()

            # Build command
            cmd: List[str] = [ffmpeg_exe, "-y"]

            # Input flags
            url_str = str(rtsp_url).strip()
            if url_str.startswith("rtsp://") or url_str.startswith("rtsps://"):
                cmd.extend([
                    "-rtsp_transport", "tcp",
                    "-stimeout", "5000000"  # 5-second socket timeout
                ])
            elif url_str.isdigit() or url_str == "0":
                # Local webcam on Windows
                if os.name == "nt":
                    # If passed as 0, use dshow default webcam or direct index
                    cmd.extend(["-f", "dshow", "-i", "video=0"])
                else:
                    cmd.extend(["-f", "v4l2", "-i", f"/dev/video{url_str}"])
            else:
                pass

            if not (url_str.isdigit() and os.name == "nt"):
                cmd.extend(["-i", url_str])

            # Video encoding: copy vs transcode
            if copy_codec:
                cmd.extend(["-c:v", "copy"])
            else:
                cmd.extend([
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-tune", "zerolatency",
                    "-profile:v", "baseline",
                    "-level", "3.1",
                    "-pix_fmt", "yuv420p",
                    "-g", "30",
                    "-keyint_min", "30",
                    "-sc_threshold", "0"
                ])

            # Audio encoding: aac or copy if present
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "64k"
            ])

            # Fragmented MP4 HLS output configuration (15-minute rolling window = 450 segments @ 2s)
            init_file = "init.mp4"
            playlist_file = "live.m3u8"
            segment_pattern = "seg_%06d.m4s"

            cmd.extend([
                "-f", "hls",
                "-hls_time", "2",
                "-hls_list_size", "450",
                "-hls_segment_type", "fmp4",
                "-hls_fmp4_init_filename", init_file,
                "-hls_flags", "delete_segments+append_list+program_date_time",
                "-hls_segment_filename", segment_pattern,
                playlist_file
            ])

            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cam_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self._processes[camera_id] = proc
                self._configs[camera_id] = {"rtsp_url": rtsp_url, "copy_codec": copy_codec}
                self._start_times[camera_id] = time.time()
                logger.info(f"Started rolling buffer daemon for camera '{camera_id}' (PID {proc.pid}) at {cam_dir}")
                return True
            except Exception as e:
                logger.error(f"Failed to start rolling buffer daemon for '{camera_id}': {e}")
                return False

    def ensure_camera_buffer(
        self,
        camera_id: str,
        rtsp_url: str,
        copy_codec: bool = False
    ) -> bool:
        """Ensures rolling buffer daemon is active for camera."""
        if self.is_buffer_running(camera_id):
            return True
        return self.start_camera_buffer(camera_id, rtsp_url, copy_codec)

    def stop_camera_buffer(self, camera_id: str, cleanup: bool = True) -> bool:
        """
        Safely terminates FFmpeg daemon for camera.
        If cleanup=True, unlinks temporary .m4s and playlist files in camera's live_buffer dir.
        Strictly guarantees permanent retention folders (raw, clips, full_footage) are NEVER touched.
        """
        with self._lock:
            proc = self._processes.pop(camera_id, None)
            self._configs.pop(camera_id, None)
            self._start_times.pop(camera_id, None)

        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except (subprocess.TimeoutExpired, Exception):
                try:
                    proc.kill()
                except Exception:
                    pass

        if cleanup:
            try:
                cam_dir = self.get_camera_buffer_dir(camera_id)
                self._cleanup_buffer_dir(cam_dir)
            except Exception as e:
                logger.warning(f"Error cleaning buffer dir for '{camera_id}': {e}")

        logger.info(f"Stopped rolling buffer daemon for camera '{camera_id}' (cleanup={cleanup})")
        return True

    def stop_all(self, cleanup: bool = False):
        """Stops all running camera buffer daemons."""
        with self._lock:
            cids = list(self._processes.keys())
        for cid in cids:
            self.stop_camera_buffer(cid, cleanup=cleanup)

    def get_camera_buffer_status(self, camera_id: str) -> Dict[str, Any]:
        """
        Reads camera live.m3u8 playlist and returns:
        - duration_sec: total playable duration in rolling window
        - earliest_time: earliest timestamp in playlist
        - latest_time: latest timestamp in playlist (live edge)
        - is_live: True if daemon is running and has active segments
        - segment_count: number of segments currently available
        """
        cam_dir = self.get_camera_buffer_dir(camera_id)
        playlist_path = cam_dir / "live.m3u8"
        is_running = self.is_buffer_running(camera_id)

        default_status = {
            "camera_id": camera_id,
            "is_buffering": True,
            "is_live": False,
            "duration_sec": 0.0,
            "segment_count": 0,
            "earliest_time": None,
            "latest_time": None,
            "segments": []
        }

        if not playlist_path.exists() or playlist_path.stat().st_size == 0:
            return default_status

        try:
            with open(playlist_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return default_status

        durations: List[float] = []
        program_times: List[float] = []
        segment_files: List[str] = []

        curr_pdt: Optional[float] = None
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
                # Parse ISO-8601 timestamp
                pdt_str = line.split(":", 1)[1]
                try:
                    dt = datetime.datetime.fromisoformat(pdt_str)
                    curr_pdt = dt.timestamp()
                except Exception:
                    pass
            elif line.startswith("#EXTINF:"):
                try:
                    dur = float(line.split(":")[1].split(",")[0])
                    durations.append(dur)
                    if curr_pdt is not None:
                        program_times.append(curr_pdt)
                        curr_pdt += dur
                except Exception:
                    pass
            elif line.endswith(".m4s"):
                segment_files.append(line)

        if not durations or not segment_files:
            return default_status

        total_dur = sum(durations)
        now = time.time()

        if program_times and len(program_times) == len(durations):
            earliest_t = program_times[0]
            latest_t = program_times[-1] + durations[-1]
        else:
            latest_t = now
            earliest_t = max(0.0, now - total_dur)

        return {
            "camera_id": camera_id,
            "is_buffering": False,
            "is_live": is_running and len(segment_files) > 0,
            "duration_sec": round(total_dur, 2),
            "segment_count": len(segment_files),
            "earliest_time": round(earliest_t, 3),
            "latest_time": round(latest_t, 3),
            "segments": segment_files[-10:]  # Return latest 10 segment names
        }

    def prune_stale_buffer(self, camera_id: str, max_segments: int = 450) -> int:
        """
        Safety eviction invariant:
        Ensures local .m4s segments in live_buffer/{camera_id}/ never exceed max_segments (15 minutes).
        Deletes oldest orphaned .m4s files.
        Never touches any files outside of live_buffer/{camera_id}/.
        """
        cam_dir = self.get_camera_buffer_dir(camera_id)
        if not cam_dir.exists():
            return 0

        # Safety invariant assertion
        assert "live_buffer" in str(cam_dir), "Critical: refusing to prune outside of live_buffer"

        m4s_files = sorted(cam_dir.glob("seg_*.m4s"), key=lambda p: p.name)
        deleted = 0
        if len(m4s_files) > max_segments:
            to_delete = m4s_files[:len(m4s_files) - max_segments]
            for p in to_delete:
                try:
                    p.unlink(missing_ok=True)
                    deleted += 1
                except Exception:
                    pass
        return deleted

    def _cleanup_buffer_dir(self, cam_dir: Path):
        """Removes temporary files inside a single camera live_buffer directory."""
        # Strict invariant assertion
        resolved = cam_dir.resolve()
        assert str(resolved).startswith(str(self.live_buffer_root)), "Refusing to delete outside live_buffer"

        for p in cam_dir.iterdir():
            if p.is_file() and (p.name.endswith(".m4s") or p.name.endswith(".m3u8") or p.name.endswith(".mp4")):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
