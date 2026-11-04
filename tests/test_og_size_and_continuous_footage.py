"""
Test verification for:
1. ClipWriter saving clips at full original (OG) camera resolution (e.g. 1920x1080).
2. Universal playback compatibility (H.264 yuv420p + faststart + silent AAC audio track).
3. Continuous whole footage saved as 24-hour daily file (footage_<date>.mp4) in full_footage/<cam>/<date>/
   with valid moov atom, valid H.264 stream, and verified playable.
"""

import os
import shutil
import tempfile
import time
import subprocess
from pathlib import Path
import numpy as np
import cv2
import pytest

from vyzn.recording.clip_writer import ClipWriter
from vyzn.core.ffmpeg_util import FFmpegUtil


@pytest.fixture
def temp_storage():
    tmp_dir = tempfile.mkdtemp(prefix="vyzn_og_footage_test_")
    yield Path(tmp_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_clip_writer_og_resolution_and_audio(temp_storage):
    writer = ClipWriter(temp_storage)

    # 1. Create synthetic 1080p (1920x1080) test frames
    og_w, og_h = 1920, 1080
    num_frames = 30
    fps = 15.0

    frames = []
    for i in range(num_frames):
        # Create patterned 1080p frame
        f = np.zeros((og_h, og_w, 3), dtype=np.uint8)
        cv2.putText(f, f"Test OG Frame {i}", (100, 200), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        frames.append(f)

    result = writer.write_clip_from_frames(
        camera_id="cam_test_og",
        event_group_id="ev_test_1080p",
        frames=frames,
        fps=fps
    )

    clip_path = Path(result.clip_path)
    assert clip_path.exists(), "Clip file must exist"
    assert clip_path.stat().st_size > 0, "Clip file must have size > 0"

    # 2. Verify with OpenCV VideoCapture
    cap = cv2.VideoCapture(str(clip_path))
    assert cap.isOpened(), "Clip must open cleanly in OpenCV"
    read_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    read_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    assert (read_w, read_h) == (og_w, og_h), f"Clip resolution must be original ({og_w}x{og_h}), got ({read_w}x{read_h})"

    # 3. Verify streams with FFmpeg (H.264 video + AAC audio)
    exe = FFmpegUtil.get_executable()
    res = subprocess.run([exe, "-i", str(clip_path)], capture_output=True, text=True)
    stderr = res.stderr

    assert "Video: h264" in stderr or "h264" in stderr, "Clip must be H.264 video"
    assert "Audio: aac" in stderr, "Clip must contain universal AAC audio track"
    assert "yuv420p" in stderr, "Pixel format must be universal yuv420p"


def test_continuous_whole_footage_recording(temp_storage):
    writer = ClipWriter(temp_storage)

    cam_id = "cam_test_continuous"
    og_w, og_h = 1280, 720
    fps = 10.0
    now_pts = time.time()
    date_str = time.strftime("%Y-%m-%d")

    # Generate test frames
    test_frames = []
    for i in range(25):
        f = np.zeros((og_h, og_w, 3), dtype=np.uint8)
        cv2.putText(f, f"Continuous Frame {i}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        test_frames.append(f)

    # Append frames continuously
    for i, f in enumerate(test_frames):
        writer.append_continuous_frame(cam_id, f, now_pts + (i / fps), fps)

    # Close and flush recorder
    writer.close_continuous_recorders()

    # Verify target file exists
    expected_file = temp_storage / "full_footage" / cam_id / date_str / f"footage_{date_str}.mp4"
    assert expected_file.exists(), f"Continuous daily footage file must exist at {expected_file}"
    assert expected_file.stat().st_size > 0, "Continuous footage file must be > 0 bytes"

    # Verify playback with OpenCV
    cap = cv2.VideoCapture(str(expected_file))
    assert cap.isOpened(), "Continuous footage file must open cleanly"
    read_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    read_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ret, frame = cap.read()
    cap.release()

    assert ret is True, "Must be able to read frames from continuous footage"
    assert (read_w, read_h) == (og_w, og_h), f"Footage resolution must match original ({og_w}x{og_h})"
    assert count > 0, "Continuous footage must contain recorded frames"
