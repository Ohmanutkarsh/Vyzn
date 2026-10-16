# ==============================================================================
# BLOCK 1: IMPORTING SYSTEM LIBRARIES & VYZN MODULES
# In programming, "import" means bringing in pre-built tools so we don't have to
# reinvent the wheel. Here we import:
# - os, sys, time: Tools to talk to your computer operating system and clocks.
# - threading: Allows multiple tasks to run at the exact same time (like recording
#              video while simultaneously running a website).
# - uvicorn: The web server that hosts your CCTV dashboard website.
# - vyzn modules: Our custom AI, video capture, database, and alerting brains.
# ==============================================================================
import os
import argparse
import time
import signal
import sys
import threading
import logging
from pathlib import Path
import uvicorn

# Load sensitive environment variables (like Telegram Bot Tokens) from a .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from vyzn.core.config import EdgeSettings, CameraConfig, BusinessHours
from vyzn.pipeline import EdgePipeline
from vyzn.ai.detector import MockDetector, YOLOv8Detector
from vyzn.api.routes import app as fastapi_app, init_api

# ==============================================================================
# BLOCK 2: CONFIGURE TERMINAL LOGGING (STATUS PRINTOUTS)
# This controls how messages look when printed to your terminal/command prompt.
# It attaches the exact time (HH:MM:SS) and log level (INFO/WARNING/ERROR) to
# every event so you can see what the CCTV system is doing in real-time.
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("vyzn.main")


# ==============================================================================
# BLOCK 3: CAMERA & HARDWARE AUTO-DETECTION
# This function figures out which cameras are available:
# 1. First, it checks if you already saved cameras in 'config/cameras.json'.
# 2. If not, it checks if your laptop or computer has a physical USB/webcam.
# 3. If no physical camera exists, it generates simulated synthetic cameras
#    so you can test the entire website and AI even without physical hardware!
# ==============================================================================
def build_synthetic_settings(num_cameras: int, data_dir: Path, demo_mode: bool = False) -> EdgeSettings:
    # In simple terms: check if the user selected a custom storage directory in the Settings UI
    storage_cfg = Path("./config/storage.json")
    if storage_cfg.exists():
        try:
            import json
            with open(storage_cfg, "r") as f:
                cfg_data = json.load(f)
                if cfg_data.get("storage_dir"):
                    cand = Path(cfg_data["storage_dir"])
                    try:
                        cand.mkdir(parents=True, exist_ok=True)
                        test_f = cand / ".perm_check"
                        test_f.write_text("ok")
                        test_f.unlink()
                        data_dir = cand
                        logger.info(f"Using user-configured storage directory: {data_dir}")
                    except Exception:
                        logger.warning(f"Configured storage path '{cand}' is not accessible in this environment; using default: {data_dir}")
        except Exception as e:
            logger.warning(f"Error reading config/storage.json: {e}")

    # Set default system parameters (where video is saved, alert score threshold)
    settings = EdgeSettings(
        site_id="site_demo_hub" if demo_mode else "site_primary_01",
        site_name="My Primary Location",
        data_dir=data_dir,
        db_path=data_dir / "index.db",
        alert_score_threshold=70,
        raw_retention_hours=0.02 if demo_mode else 72
    )
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    # Read the Telegram token and chat ID so alerts can be sent to your phone
    settings.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("VYZN_TELEGRAM_BOT_TOKEN") or "8921915999:AAEEdYYsUz_xwAo0b342w8TEw0NsjG362js"
    settings.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("VYZN_TELEGRAM_CHAT_ID") or None

    # Step A: Check if the user already configured cameras through the website
    cfg_file = Path("./config/cameras.json")
    if cfg_file.exists():
        try:
            import json
            with open(cfg_file, "r") as f:
                saved = json.load(f)
                if isinstance(saved, list):
                    cameras = [CameraConfig(**item) for item in saved]
                    logger.info(f"Loaded {len(cameras)} persistent cameras from config/cameras.json")
                    settings.cameras = cameras
                    return settings
        except Exception as e:
            logger.warning(f"Error reading config/cameras.json: {e}")

    # Step B: Check if your computer has a built-in webcam or connected USB camera
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
    if webcam_available:
        # If webcam is working, adopt it as Camera 1 so you can test right away
        cameras.append(CameraConfig(
            camera_id="cam_webcam_0",
            name="Laptop / USB Camera (Device 0)",
            rtsp_url="0",
            target_fps=4.0,
            is_night_ir=False,
            business_hours=BusinessHours(enabled=False)
        ))
        logger.info("[LIVE] Auto-detected physical Webcam 0. Configured as Camera 1 live feed.")
    elif num_cameras > 0:
        # Otherwise, fall back to simulated test video feeds
        cameras.append(CameraConfig(
            camera_id="cam_main",
            name="Primary Entrance Camera",
            rtsp_url="sim://corridor",
            target_fps=4.0,
            is_night_ir=False,
            business_hours=BusinessHours(enabled=False)
        ))

    settings.cameras = cameras
    return settings


# ==============================================================================
# BLOCK 4: RUNNING THE WEB SERVER IN THE BACKGROUND (DAEMON THREAD)
# In normal Python, a web server blocks everything else from running.
# By putting Uvicorn into a "daemon thread" (background worker), our CCTV
# camera recording pipeline and our website can run at the same time smoothly.
# ==============================================================================
def start_uvicorn_thread(host: str, port: int) -> uvicorn.Server:
    """Runs Uvicorn web server in a dedicated background daemon thread."""
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


# ==============================================================================
# BLOCK 5: MAIN ENTRYPOINT & CONTINUOUS MONITORING LOOP
# This is the master function that runs when you type 'python run_edge.py':
# 1. Reads command line flags (--port, --simulate, --use-yolo).
# 2. Starts the Edge Pipeline (motion detection, YOLO AI, threat scoring).
# 3. Starts the Web API server so you can open http://localhost:8000 in your browser.
# 4. Listens for Ctrl+C so it cleanly saves all video clips before exiting.
# ==============================================================================
def main():
    # 5.1 Read Command Line Options
    parser = argparse.ArgumentParser(description="VYZN Edge Surveillance Node & Web Console")
    parser.add_argument("--simulate", type=int, default=3, help="Number of simulated cameras (1-5)")
    parser.add_argument("--duration", type=int, default=0, help="Run duration in seconds (0 = run continuously)")
    parser.add_argument("--data-dir", type=str, default="./data/clips", help="Local directory for clips and SQLite index")
    parser.add_argument("--use-yolo", action="store_true", help="Load Ultralytics YOLOv8n instead of fast Mock detector")
    parser.add_argument("--api", action="store_true", default=True, help="Launch Web Dashboard and REST API (default: True)")
    parser.add_argument("--no-api", dest="api", action="store_false", help="Disable Web Dashboard")
    default_port = int(os.environ.get("PORT", 8000))
    parser.add_argument("--port", type=int, default=default_port, help=f"Web dashboard port (default: {default_port})")
    parser.add_argument("--demo", action="store_true", help="Enable demo mode (1-min accelerated retention)")
    parser.add_argument("--cloud-url", type=str, default=None, help="VYZN Cloud Fleet Manager URL (e.g. http://localhost:9000)")
    parser.add_argument("--site-key", type=str, default="vyzn_edge_secret_local_default_2026", help="Site shared secret for cloud telemetry auth and OTA verification")

    args = parser.parse_args()

    # 5.2 Build Settings & File Paths
    data_path = Path(args.data_dir).resolve()
    settings = build_synthetic_settings(args.simulate, data_path, demo_mode=args.demo)
    if args.cloud_url:
        settings.cloud_webhook_url = args.cloud_url
        settings.cloud_auth_token = args.site_key
        logger.info(f"Cloud Observability linked: {args.cloud_url} (Site ID: {settings.site_id})")

    # 5.3 Select AI Detector Model (Real YOLOv8 neural network vs Fast Mock test detector)
    if args.use_yolo:
        detector = YOLOv8Detector()
    else:
        has_real_cams = any(not str(c.rtsp_url).startswith("sim://") and not str(c.rtsp_url).startswith("test://") for c in settings.cameras)
        if has_real_cams:
            try:
                detector = YOLOv8Detector()
                logger.info("Real camera detected: using neural network YOLOv8Detector.")
            except Exception as e:
                logger.warning(f"Could not load YOLOv8, falling back to dynamic MockDetector: {e}")
                detector = MockDetector(fixed_confidence=None)
        else:
            detector = MockDetector(fixed_confidence=None)
    pipeline = EdgePipeline(settings=settings, detector=detector, use_synthetic=True)

    # 5.4 Launch Web Dashboard (FastAPI + Uvicorn)
    server = None
    if args.api:
        init_api(pipeline.db, settings, pipeline)
        server = start_uvicorn_thread("0.0.0.0", args.port)
        print("\n" + "=" * 70)
        print(f"[LIVE] VYZN NETRA WEB DASHBOARD LIVE AT: http://localhost:{args.port}")
        print("=" * 70 + "\n")

    # 5.5 Graceful Shutdown Handler (Pressing Ctrl+C stops threads cleanly without video corruption)
    def handle_signal(sig, frame):
        logger.info("\nShutdown signal received. Terminating pipeline gracefully...")
        if server:
            server.should_exit = True
        pipeline.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # 5.6 Start Camera Stream Capturing & AI Analysis
    pipeline.start()
    logger.info(f"Pipeline active with {args.simulate} streams. Output: {data_path}")

    # 5.7 Continuous Running Loop (keeps the program alive until user quits)
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
