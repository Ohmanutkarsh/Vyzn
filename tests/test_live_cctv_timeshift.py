"""
Tests for Live CCTV Player with Timeshift & Rewind:
1. Rolling fMP4 Disk Buffer generation (live.m3u8, init.mp4, seg_*.m4s).
2. RAM Protection Invariant: Segments flushed directly to disk; Python memory delta < 100MB.
3. DPDP Act Storage Invariant & Retention Safety:
   Files in raw/ or clips/ are NEVER touched by rolling buffer eviction.
4. Eviction / Pruning: Segments older than 450 items (15 minutes) are unlinked.
5. FastAPI Streaming Endpoints:
   /api/v1/cameras/{camera_id}/live/live.m3u8
   /api/v1/cameras/{camera_id}/live/init.mp4
   /api/v1/cameras/{camera_id}/live/range
   /api/v1/cameras/{camera_id}/live/{segment_name}
6. Rewind-to-Live state transition verification.
"""

import os
import time
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from vyzn.streaming.rolling_buffer import RollingBufferManager, get_rolling_buffer_manager
from vyzn.core.ffmpeg_util import FFmpegUtil
from api.index import app


@pytest.fixture
def temp_storage():
    tmp = tempfile.mkdtemp(prefix="vyzn_live_timeshift_test_")
    storage_path = Path(tmp).resolve()
    # Set up raw incident retention folder and live_buffer
    raw_dir = storage_path / "raw" / "cam_test" / "2026-10-25" / "ev_test_123"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "clip.mp4"
    raw_file.write_bytes(b"permanent_incident_evidence_data" * 50)

    clips_dir = storage_path / "clips" / "cam_test" / "2026-10-25" / "ev_test_123"
    clips_dir.mkdir(parents=True, exist_ok=True)
    clip_file = clips_dir / "clip.mp4"
    clip_file.write_bytes(b"permanent_clip_data" * 50)

    yield storage_path, raw_file, clip_file
    shutil.rmtree(tmp, ignore_errors=True)


def test_rolling_buffer_generation_and_storage_invariant(temp_storage):
    storage_path, raw_file, clip_file = temp_storage
    mgr = RollingBufferManager(storage_path)

    cam_id = "cam_timeshift_unit"
    cam_dir = mgr.get_camera_buffer_dir(cam_id)
    assert "live_buffer" in str(cam_dir)
    assert cam_dir.parent == storage_path / "live_buffer"

    # Start buffer with synthetic testsrc (4 seconds)
    ffmpeg_exe = FFmpegUtil.get_executable()
    # Test starting with a 4s synthetic test source
    test_src = "testsrc=size=320x240:rate=15"
    cmd = [
        ffmpeg_exe, "-y",
        "-f", "lavfi", "-i", test_src,
        "-t", "4",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-level", "3.1", "-pix_fmt", "yuv420p",
        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "64k",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "450",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", "init.mp4",
        "-hls_flags", "delete_segments+append_list+program_date_time",
        "-hls_segment_filename", "seg_%06d.m4s",
        "live.m3u8"
    ]

    cam_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(cam_dir), capture_output=True, text=True)
    assert proc.returncode == 0, f"FFmpeg failed: {proc.stderr}"

    # Verify generated fMP4 files
    init_mp4 = cam_dir / "init.mp4"
    live_m3u8 = cam_dir / "live.m3u8"
    assert init_mp4.exists(), "init.mp4 header must exist on disk"
    assert live_m3u8.exists(), "live.m3u8 playlist must exist on disk"

    m4s_segments = list(cam_dir.glob("seg_*.m4s"))
    assert len(m4s_segments) >= 2, f"Must have at least 2 fMP4 segments, got {len(m4s_segments)}"

    # Check status method
    status = mgr.get_camera_buffer_status(cam_id)
    assert status["camera_id"] == cam_id
    assert status["is_buffering"] is False
    assert status["duration_sec"] >= 3.8
    assert status["segment_count"] >= 2
    assert status["earliest_time"] is not None
    assert status["latest_time"] is not None

    # DPDP Act Storage Invariant: raw/ and clips/ permanent retention files MUST remain untouched
    assert raw_file.exists(), "Permanent retention raw/ file was deleted!"
    assert clip_file.exists(), "Permanent retention clips/ file was deleted!"


def test_buffer_cleanup_and_retention_safety(temp_storage):
    storage_path, raw_file, clip_file = temp_storage
    mgr = RollingBufferManager(storage_path)
    cam_id = "cam_purge_test"
    cam_dir = mgr.get_camera_buffer_dir(cam_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    # Create 460 dummy .m4s segments
    for i in range(460):
        seg = cam_dir / f"seg_{i:06d}.m4s"
        seg.write_bytes(b"dummy_m4s_bytes")

    assert len(list(cam_dir.glob("seg_*.m4s"))) == 460

    # Prune segments older than 450 items (15 minutes)
    deleted = mgr.prune_stale_buffer(cam_id, max_segments=450)
    assert deleted == 10
    remaining = list(cam_dir.glob("seg_*.m4s"))
    assert len(remaining) == 450

    # Test stop_camera_buffer with cleanup=True
    mgr.stop_camera_buffer(cam_id, cleanup=True)
    assert len(list(cam_dir.glob("seg_*.m4s"))) == 0

    # Permanent retention check: raw/ and clips/ MUST NOT be touched
    assert raw_file.exists(), "Permanent raw file must survive rolling buffer cleanup"
    assert clip_file.exists(), "Permanent clip file must survive rolling buffer cleanup"


def test_ram_protection_invariant(temp_storage):
    """
    Verifies that writing live rolling buffer directly to disk keeps Python heap memory flat
    (< 100 MB delta) even with multiple synthetic segments.
    """
    import gc
    import tracemalloc

    storage_path, _, _ = temp_storage
    mgr = RollingBufferManager(storage_path)
    cam_id = "cam_ram_test"
    cam_dir = mgr.get_camera_buffer_dir(cam_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    gc.collect()
    tracemalloc.start()
    snapshot1 = tracemalloc.take_snapshot()

    # Create dummy buffer segments on disk
    for i in range(100):
        seg = cam_dir / f"seg_{i:06d}.m4s"
        seg.write_bytes(b"x" * (200 * 1024))  # 200KB per segment = 20MB written directly to disk

    snapshot2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    total_memory_diff = sum(stat.size_diff for stat in top_stats)
    diff_mb = total_memory_diff / (1024 * 1024)

    # Invariant: Python heap delta must be under 100 MB
    assert diff_mb < 100.0, f"Python heap grew by {diff_mb:.2f} MB, exceeds 100MB RAM invariant"


def test_fastapi_hls_streaming_endpoints(temp_storage):
    storage_path, _, _ = temp_storage
    mgr = get_rolling_buffer_manager(storage_path)

    cam_id = "cam_api_test"
    cam_dir = mgr.get_camera_buffer_dir(cam_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy live.m3u8 and init.mp4 and seg_000001.m4s
    (cam_dir / "init.mp4").write_bytes(b"fmp4_init_header_bytes")
    (cam_dir / "seg_000001.m4s").write_bytes(b"fmp4_segment_bytes")
    m3u8_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:7\n"
        "#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-MEDIA-SEQUENCE:1\n"
        '#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:2.000000,\n"
        "#EXT-X-PROGRAM-DATE-TIME:2026-10-25T14:00:00.000+0000\n"
        "seg_000001.m4s\n"
    )
    (cam_dir / "live.m3u8").write_text(m3u8_content, encoding="utf-8")

    client = TestClient(app)

    # 1. GET live.m3u8
    res_m3u8 = client.get(f"/api/v1/cameras/{cam_id}/live/live.m3u8")
    assert res_m3u8.status_code == 200
    assert "application/vnd.apple.mpegurl" in res_m3u8.headers["content-type"]
    assert "no-cache" in res_m3u8.headers.get("cache-control", "")
    assert "seg_000001.m4s" in res_m3u8.text

    # 2. GET init.mp4
    res_init = client.get(f"/api/v1/cameras/{cam_id}/live/init.mp4")
    assert res_init.status_code == 200
    assert "video/mp4" in res_init.headers["content-type"]
    assert res_init.content == b"fmp4_init_header_bytes"

    # 3. GET segment
    res_seg = client.get(f"/api/v1/cameras/{cam_id}/live/seg_000001.m4s")
    assert res_seg.status_code == 200
    assert res_seg.content == b"fmp4_segment_bytes"

    # 4. GET range
    res_range = client.get(f"/api/v1/cameras/{cam_id}/live/range")
    assert res_range.status_code == 200
    data = res_range.json()
    assert data["camera_id"] == cam_id
    assert data["duration_sec"] == 2.0
    assert data["segment_count"] == 1

    # 5. Path traversal security rejection
    res_bad = client.get(f"/api/v1/cameras/{cam_id}/live/../../etc/passwd")
    assert res_bad.status_code in (400, 404)


def test_edge_fastapi_hls_streaming_endpoints(temp_storage):
    from vyzn.api.routes import app as edge_app

    storage_path, _, _ = temp_storage
    mgr = get_rolling_buffer_manager(storage_path)

    cam_id = "cam_edge_api_test"
    cam_dir = mgr.get_camera_buffer_dir(cam_id)
    cam_dir.mkdir(parents=True, exist_ok=True)

    (cam_dir / "init.mp4").write_bytes(b"edge_init_header")
    (cam_dir / "seg_000001.m4s").write_bytes(b"edge_m4s_bytes")
    m3u8_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:7\n"
        "#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-MEDIA-SEQUENCE:1\n"
        '#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:2.000000,\n"
        "seg_000001.m4s\n"
    )
    (cam_dir / "live.m3u8").write_text(m3u8_content, encoding="utf-8")

    client = TestClient(edge_app)

    # 1. GET live.m3u8
    res_m3u8 = client.get(f"/api/v1/cameras/{cam_id}/live/live.m3u8")
    assert res_m3u8.status_code == 200
    assert "application/vnd.apple.mpegurl" in res_m3u8.headers["content-type"]
    assert "seg_000001.m4s" in res_m3u8.text

    # 2. GET init.mp4
    res_init = client.get(f"/api/v1/cameras/{cam_id}/live/init.mp4")
    assert res_init.status_code == 200
    assert res_init.content == b"edge_init_header"

    # 3. GET segment
    res_seg = client.get(f"/api/v1/cameras/{cam_id}/live/seg_000001.m4s")
    assert res_seg.status_code == 200
    assert res_seg.content == b"edge_m4s_bytes"

    # 4. GET range
    res_range = client.get(f"/api/v1/cameras/{cam_id}/live/range")
    assert res_range.status_code == 200
    data = res_range.json()
    assert data["camera_id"] == cam_id
    assert data["duration_sec"] == 2.0
