"""
Command Line Interface (CLI) runner for VYZN Edge Node & Web Dashboard.
Usage:
    python run_edge.py --simulate 3 --api --port 8000
"""

import argparse
import time
import signal
import sys
import threading
import logging
from pathlib import Path
import uvicorn

from vyzn.core.config import EdgeSettings, CameraConfig, BusinessHours, ZonePolygon
from vyzn.pipeline import EdgePipeline
from vyzn.ai.detector import MockDetector, YOLOv8Detector
from vyzn.api.routes import app as fastapi_app, init_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("vyzn.main")


def build_synthetic_settings(num_cameras: int, data_dir: Path, demo_mode: bool = False) -> EdgeSettings:
    settings = EdgeSettings(
        site_id="site_demo_hub" if demo_mode else "site_nagpur_01",
        site_name="Academic Project Evaluation Demo" if demo_mode else "Nagpur Commercial Hub",
        data_dir=data_dir,
        db_path=data_dir / "index.db",
        alert_score_threshold=70,
        raw_retention_hours=0.02 if demo_mode else 72  # ~1 minute in demo mode
    )

    import cv2, os
    webcam_available = False
    try:
        test_cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        if test_cap.isOpened():
            ret, _ = test_cap.read()
            if ret:
                webcam_available = True
        test_cap.release()
    except Exception:
        webcam_available = False

    cameras = []
    # Camera 1: Physical Camera if available, otherwise synthetic
    if webcam_available:
        cameras.append(CameraConfig(
            camera_id="cam_corridor",
            name="Main Entrance (Live Webcam 0)",
            rtsp_url="0",
            target_fps=4.0,
            is_night_ir=False,
            business_hours=BusinessHours(enabled=False)
        ))
        logger.info("[LIVE] Auto-detected physical Webcam 0. Configured as Camera 1 live feed.")
    else:
        cameras.append(CameraConfig(
            camera_id="cam_corridor",
            name="Main Store Corridor",
            rtsp_url="sim://corridor",
            target_fps=4.0,
            is_night_ir=False,
            business_hours=BusinessHours(enabled=False)
        ))

    # Camera 2: Cash Counter with Restricted Polygon Zone
    if num_cameras >= 2:
        cameras.append(CameraConfig(
            camera_id="cam_cash_counter",
            name="Cash Drawer Zone",
            rtsp_url="sim://cash_counter",
            target_fps=4.0,
            is_night_ir=False,
            business_hours=BusinessHours(enabled=True, start_hour=9, end_hour=21),
            restricted_zones=[
                ZonePolygon(
                    name="cash_drawer_box",
                    points=[[0.6, 0.4], [0.85, 0.4], [0.85, 0.7], [0.6, 0.7]]
                )
            ]
        ))

    # Camera 3: Night Shutter (IR Monochrome)
    if num_cameras >= 3:
        cameras.append(CameraConfig(
            camera_id="cam_shutter_night",
            name="Rear Shutter (Night IR)",
            rtsp_url="sim://shutter_night",
            target_fps=4.0,
            is_night_ir=True,
            business_hours=BusinessHours(enabled=False)
        ))

    settings.cameras = cameras
    return settings


def start_uvicorn_thread(host: str, port: int) -> uvicorn.Server:
    """Runs Uvicorn in a dedicated background daemon thread."""
    config = uvicorn.Config(
        app=fastapi_app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, name="Uvicorn-Server", daemon=True)
    t.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="VYZN Edge Surveillance Node & Web Console")
    parser.add_argument("--simulate", type=int, default=3, help="Number of simulated cameras (1-5)")
    parser.add_argument("--duration", type=int, default=0, help="Run duration in seconds (0 = run continuously)")
    parser.add_argument("--data-dir", type=str, default="./data/clips", help="Local directory for clips and SQLite index")
    parser.add_argument("--use-yolo", action="store_true", help="Load Ultralytics YOLOv8n instead of fast Mock detector")
    parser.add_argument("--api", action="store_true", default=True, help="Launch Web Dashboard and REST API (default: True)")
    parser.add_argument("--no-api", dest="api", action="store_false", help="Disable Web Dashboard")
    parser.add_argument("--port", type=int, default=8000, help="Web dashboard port (default: 8000)")
    parser.add_argument("--demo", action="store_true", help="Enable demo mode (1-min accelerated retention)")
    parser.add_argument("--cloud-url", type=str, default=None, help="VYZN Cloud Fleet Manager URL (e.g. http://localhost:9000)")
    parser.add_argument("--site-key", type=str, default="vyzn_edge_secret_local_default_2026", help="Site shared secret for cloud telemetry auth and OTA verification")

    args = parser.parse_args()

    data_path = Path(args.data_dir).resolve()
    settings = build_synthetic_settings(args.simulate, data_path, demo_mode=args.demo)
    if args.cloud_url:
        settings.cloud_webhook_url = args.cloud_url
        settings.cloud_auth_token = args.site_key
        logger.info(f"Cloud Observability linked: {args.cloud_url} (Site ID: {settings.site_id})")

    detector = YOLOv8Detector() if args.use_yolo else MockDetector(fixed_confidence=0.88)
    pipeline = EdgePipeline(settings=settings, detector=detector, use_synthetic=True)

    # Initialize REST API and Dashboard
    server = None
    if args.api:
        init_api(pipeline.db, settings, pipeline)
        server = start_uvicorn_thread("0.0.0.0", args.port)
        print("\n" + "=" * 70)
        print(f"[LIVE] VYZN NETRA WEB DASHBOARD LIVE AT: http://localhost:{args.port}")
        print("=" * 70 + "\n")

    def handle_signal(sig, frame):
        logger.info("\nShutdown signal received. Terminating pipeline gracefully...")
        if server:
            server.should_exit = True
        pipeline.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    pipeline.start()
    logger.info(f"Pipeline active with {args.simulate} streams. Output: {data_path}")

    start_time = time.monotonic()
    try:
        while True:
            time.sleep(1.0)
            if args.duration > 0 and (time.monotonic() - start_time >= args.duration):
                logger.info(f"Target test duration of {args.duration}s reached.")
                break
    finally:
        if server:
            server.should_exit = True
        pipeline.stop()


if __name__ == "__main__":
    main()
