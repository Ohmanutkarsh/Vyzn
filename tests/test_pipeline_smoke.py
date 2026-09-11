"""
End-to-end smoke test for multi-camera EdgePipeline.
"""

import time
import os
from pathlib import Path
from vyzn.core.config import EdgeSettings, CameraConfig, BusinessHours
from vyzn.ai.detector import MockDetector
from vyzn.pipeline import EdgePipeline


def test_pipeline_synthetic_smoke(tmp_path: Path):
    data_dir = tmp_path / "smoke_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = EdgeSettings(
        site_id="site_test_smoke",
        data_dir=data_dir,
        db_path=data_dir / "index.db",
        alert_score_threshold=65,
        telemetry_interval_sec=5
    )

    settings.cameras = [
        CameraConfig(
            camera_id="cam_test_01",
            name="Test Camera 1",
            rtsp_url="sim://test1",
            target_fps=5.0,
            business_hours=BusinessHours(enabled=False)
        ),
        CameraConfig(
            camera_id="cam_test_02",
            name="Test Camera 2",
            rtsp_url="sim://test2",
            target_fps=5.0,
            business_hours=BusinessHours(enabled=False)
        )
    ]

    detector = MockDetector(fixed_confidence=0.85)
    pipeline = EdgePipeline(settings=settings, detector=detector, use_synthetic=True)

    try:
        pipeline.start()
        # Run pipeline for 7 seconds to allow synthetic motion and events to process
        time.sleep(7.0)

        # Verify SQLite index has recorded events
        events = []
        for _ in range(12):
            events = pipeline.db.query_events(limit=10)
            if len(events) > 0:
                break
            time.sleep(0.3)

        assert len(events) > 0, "Expected at least one recorded event in SQLite"

        # Check recorded event details
        first_event = events[0]
        assert first_event.score > 0
        assert first_event.camera_id in ["cam_test_01", "cam_test_02"]

        # Verify files exist on disk
        assert os.path.exists(first_event.thumb_path), f"Thumbnail not found: {first_event.thumb_path}"

    finally:
        pipeline.stop()
