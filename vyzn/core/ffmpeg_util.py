"""
FFmpeg binary locator and subprocess utilities.
Handles automatic discovery of system FFmpeg or bundled imageio_ffmpeg binary.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


class FFmpegUtil:
    _cached_exe: Optional[str] = None

    @classmethod
    def get_executable(cls) -> str:
        """
        Returns absolute path to working ffmpeg executable.
        Checks system PATH first, then falls back to imageio_ffmpeg.
        """
        if cls._cached_exe and os.path.exists(cls._cached_exe):
            return cls._cached_exe

        # 1. Check system PATH
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            cls._cached_exe = system_ffmpeg
            return system_ffmpeg

        # 2. Check imageio_ffmpeg
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and os.path.exists(exe):
                cls._cached_exe = exe
                return exe
        except ImportError:
            pass

        raise FileNotFoundError(
            "FFmpeg executable could not be found in PATH or imageio_ffmpeg. "
            "Please install ffmpeg or pip install imageio-ffmpeg."
        )

    @classmethod
    def build_fmp4_record_command(
        cls,
        input_source: str,
        output_path: Path,
        duration_sec: Optional[int] = None,
        is_rtsp: bool = True
    ) -> List[str]:
        """
        Builds crash-safe Fragmented MP4 (fMP4) recording command.
        Uses keyframe fragmentation so every recorded second is intact on crash.
        """
        exe = cls.get_executable()
        cmd = [exe, "-y"]

        if is_rtsp:
            cmd.extend([
                "-rtsp_transport", "tcp",
                "-stimeout", "5000000"  # 5-second socket timeout (microseconds)
            ])

        cmd.extend(["-i", input_source])

        if duration_sec:
            cmd.extend(["-t", str(duration_sec)])

        # Stream copy video when possible, audio disabled
        cmd.extend([
            "-c:v", "copy",
            "-an",
            "-f", "mp4",
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
            str(output_path)
        ])

        return cmd
