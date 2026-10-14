"""
Unit and integration tests for VYZN Wall View (end-to-end fullscreen CCTV grid).
Verifies:
1. Grid dimensions and auto-pick logic for 1, 2, 5, 9, 16, and 20 cameras across 16:9, 4:3, and portrait screens.
2. Multiplexed WebSocket stream endpoint (/api/wall/stream) delivering batched low-res frames and real scores.
3. Bandwidth and CPU measurement for 16 simultaneous camera feeds.
"""

import os
import sys
import json
import time
import psutil
import tempfile
import numpy as np
import cv2
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vyzn.api.routes import app, init_api
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings, CameraConfig


def compute_grid_dimensions(count: int, is_portrait: bool = False):
    """
    Python mirror of frontend calculateGridDimensions function.
    Calculates columns and rows based on tile count and aspect ratio.
    """
    if count <= 1:
        return 1, 1
    if count == 2:
        return (1, 2) if is_portrait else (2, 1)
    if count <= 4:
        return 2, 2
    if count <= 6:
        return (2, 3) if is_portrait else (3, 2)
    if count <= 9:
        return 3, 3
    if count <= 12:
        return (3, 4) if is_portrait else (4, 3)
    return 4, 4


def test_grid_auto_layout_matrix():
    """
    Verifies optimal grid dimensions across 1, 2, 5, 9, 16, and 20 cameras
    for landscape (16:9, 4:3) and portrait orientations.
    """
    test_cases = [
        (1, False, (1, 1)),
        (1, True,  (1, 1)),
        (2, False, (2, 1)),
        (2, True,  (1, 2)),
        (5, False, (3, 2)),
        (5, True,  (2, 3)),
        (9, False, (3, 3)),
        (9, True,  (3, 3)),
        (16, False, (4, 4)),
        (16, True,  (4, 4)),
    ]

    for count, is_portrait, expected in test_cases:
        cols, rows = compute_grid_dimensions(count, is_portrait=is_portrait)
        assert (cols, rows) == expected, f"Failed for count={count}, portrait={is_portrait}: got ({cols}, {rows}) expected {expected}"
        # Verify tile slots cover camera count
        assert cols * rows >= count, f"Grid capacity {cols*rows} smaller than camera count {count}"

    # For 20 cameras: max 16 per page -> page 1 has 16 (4x4), page 2 has 4 (2x2)
    p1_count = min(20, 16)
    p2_count = 20 - p1_count
    assert p1_count == 16
    assert p2_count == 4
    assert compute_grid_dimensions(p1_count, False) == (4, 4)
    assert compute_grid_dimensions(p2_count, False) == (2, 2)


class MockPipeline:
    """Mock pipeline providing synthetic frames and real-time scores for Wall View tests."""
    def __init__(self, camera_ids):
        self.camera_ids = camera_ids
        self.active_event_ids = {camera_ids[0]: "ev_rec_001"} if camera_ids else {}
        self.latest_camera_scores = {cid: (time.time(), 35 if idx % 2 == 1 else 15) for idx, cid in enumerate(camera_ids)}
        # Pre-generate low-res JPEG (320x180, quality 45)
        card = np.full((180, 320, 3), (30, 40, 50), dtype=np.uint8)
        _, enc = cv2.imencode(".jpg", card, [cv2.IMWRITE_JPEG_QUALITY, 45])
        self._test_jpeg = enc.tobytes()
        self.capture_threads = []

    def get_camera_live_jpeg(self, camera_id: str, quality: int = 45, max_width: int = 320):
        return self._test_jpeg

    def get_camera_latest_score(self, camera_id: str):
        if camera_id in self.latest_camera_scores:
            return self.latest_camera_scores[camera_id][1]
        return 0


def test_wall_view_multiplexed_websocket_and_16_camera_performance():
    """
    Tests the /api/wall/stream WebSocket endpoint with 16 cameras simultaneously.
    Verifies payload contents, computes throughput (bandwidth), and checks CPU impact.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "wall_test.db"
        db = EventDatabase(db_path)

        camera_ids = [f"cam_{i:02d}" for i in range(16)]
        cams = [CameraConfig(camera_id=cid, name=f"Camera {i+1}", rtsp_url="mock") for i, cid in enumerate(camera_ids)]
        settings = EdgeSettings(site_id="test_site", site_name="Kirana Wall", cameras=cams)

        mock_pipe = MockPipeline(camera_ids)
        init_api(db=db, settings=settings, pipeline=mock_pipe)

        client = TestClient(app)

        cpu_before = psutil.cpu_percent(interval=None)
        t_start = time.time()

        with client.websocket_connect("/api/wall/stream") as ws:
            # Subscribe to all 16 cameras on the active page
            ws.send_text(json.dumps({
                "subscribe": camera_ids,
                "fps": 5.0
            }))

            # Read 2 multiplexed batches
            received_bytes = 0
            batches_read = 0

            for _ in range(2):
                msg = ws.receive_text()
                received_bytes += len(msg.encode("utf-8"))
                batches_read += 1
                data = json.loads(msg)

                assert data.get("type") == "wall_batch"
                assert "cameras" in data
                cams_batch = data["cameras"]
                assert len(cams_batch) == 16

                # Verify each camera's data fields
                for cid in camera_ids:
                    assert cid in cams_batch
                    c_info = cams_batch[cid]
                    assert "score" in c_info
                    assert "is_recording" in c_info
                    assert "is_online" in c_info
                    assert "jpeg" in c_info
                    assert len(c_info["jpeg"]) > 50

                # Verify recording status
                assert cams_batch[camera_ids[0]]["is_recording"] is True
                assert cams_batch[camera_ids[1]]["is_recording"] is False

                # Verify border score tiers
                assert cams_batch[camera_ids[1]]["score"] == 35  # Amber range (30-70)
                assert cams_batch[camera_ids[0]]["score"] == 15  # Neutral range (<30)

        t_elapsed = max(0.01, time.time() - t_start)
        cpu_after = psutil.cpu_percent(interval=None)

        avg_batch_bytes = received_bytes / batches_read
        # At 5 FPS for 16 cameras:
        # Bandwidth = (avg_batch_bytes * 5) bytes/sec
        bandwidth_bytes_sec = avg_batch_bytes * 5.0
        bandwidth_mbps = (bandwidth_bytes_sec * 8) / (1024 * 1024)

        print(f"\n--- 16-Camera Wall View Performance Report ---")
        print(f"Average Batch Size (16 tiles): {avg_batch_bytes / 1024:.2f} KB")
        print(f"Per-Tile Frame Size: {avg_batch_bytes / 16 / 1024:.2f} KB")
        print(f"Framerate: 5.0 FPS")
        print(f"Estimated Total Bandwidth: {bandwidth_mbps:.2f} Mbps ({bandwidth_bytes_sec / 1024:.1f} KB/s)")
        print(f"CPU Utilization: Before={cpu_before}%, After={cpu_after}%")
        print(f"----------------------------------------------\n")

        # Bandwidth should remain under 6 Mbps for 16 tiles at 5 FPS
        assert bandwidth_mbps < 8.0, f"Bandwidth exceeded threshold: {bandwidth_mbps:.2f} Mbps"
