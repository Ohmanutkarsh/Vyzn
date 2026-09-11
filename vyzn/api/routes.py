"""
FastAPI route definitions for event retrieval, storage statistics, and dashboard streaming.
"""

from __future__ import annotations
import os
import time
import shutil
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings

app = FastAPI(
    title="VYZN Netra API",
    description="REST & Streaming API for edge surveillance analytics and incident review",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global references injected on pipeline startup
_db_instance: Optional[EventDatabase] = None
_settings_instance: Optional[EdgeSettings] = None
_pipeline_instance: Any = None


def init_api(db: EventDatabase, settings: EdgeSettings, pipeline: Any = None):
    """Binds global database, settings, and pipeline references to the FastAPI app."""
    global _db_instance, _settings_instance, _pipeline_instance
    _db_instance = db
    _settings_instance = settings
    _pipeline_instance = pipeline


def get_db() -> EventDatabase:
    if not _db_instance:
        raise HTTPException(status_code=503, detail="Database engine not initialized")
    return _db_instance


def get_settings() -> EdgeSettings:
    if not _settings_instance:
        raise HTTPException(status_code=503, detail="Settings not initialized")
    return _settings_instance


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/status")
def get_system_status() -> Dict[str, Any]:
    """Returns live status of cameras, inference worker, and host hardware."""
    db = get_db()
    settings = get_settings()

    pipe_info = {}
    if _pipeline_instance and hasattr(_pipeline_instance, "get_telemetry_status"):
        pipe_info = _pipeline_instance.get_telemetry_status()

    usage = shutil.disk_usage(settings.data_dir)
    disk_free_pct = (usage.free / float(usage.total)) * 100.0

    return {
        "status": "online",
        "site_id": settings.site_id,
        "site_name": settings.site_name,
        "disk_free_pct": round(disk_free_pct, 1),
        "alert_threshold": settings.alert_score_threshold,
        "pipeline": pipe_info,
        "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    }


@app.get("/api/events")
def list_events(
    camera_id: Optional[str] = Query(None, description="Filter by camera ID"),
    min_score: int = Query(0, ge=0, le=100, description="Minimum threat score"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return")
) -> List[Dict[str, Any]]:
    """Retrieves recent events from SQLite event index."""
    db = get_db()
    events = db.query_events(camera_id=camera_id, min_score=min_score, limit=limit)
    return [e.to_dict() for e in events]


@app.get("/api/events/{event_id}")
def get_event_detail(event_id: str) -> Dict[str, Any]:
    """Retrieves specific event metadata."""
    db = get_db()
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event.to_dict()


@app.get("/api/events/{event_id}/clip")
def get_event_video_clip(event_id: str):
    """Serves the fragmented MP4 incident video."""
    db = get_db()
    event = db.get_event(event_id)
    if not event or not event.file_path or not os.path.exists(event.file_path):
        raise HTTPException(status_code=404, detail="Video clip file not found")
    return FileResponse(
        event.file_path,
        media_type="video/mp4",
        filename=f"{event_id}.mp4"
    )


@app.get("/api/events/{event_id}/thumb")
def get_event_thumbnail(event_id: str):
    """Serves the JPEG incident thumbnail."""
    db = get_db()
    event = db.get_event(event_id)
    if not event or not event.thumb_path or not os.path.exists(event.thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found")
    return FileResponse(
        event.thumb_path,
        media_type="image/jpeg",
        filename=f"{event_id}_thumb.jpg"
    )


@app.post("/api/events/{event_id}/star")
def toggle_star_event(event_id: str) -> Dict[str, Any]:
    """Marks an event as starred to safeguard against reaper auto-deletion."""
    db = get_db()
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    new_starred = 0 if event.starred else 1
    sql = "UPDATE events SET starred = ? WHERE event_group_id = ?"
    db.writer.queue.put((sql, (new_starred, event_id), None))
    db.log_audit("EVENT_STAR_TOGGLED", event_id, f"starred={new_starred}")
    return {"event_group_id": event_id, "starred": new_starred}


@app.get("/api/storage")
def get_storage_stats() -> Dict[str, Any]:
    """Returns local disk storage utilization and event counts by tier."""
    db = get_db()
    settings = get_settings()

    usage = shutil.disk_usage(settings.data_dir)
    used_gb = usage.used / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    free_pct = (usage.free / float(usage.total)) * 100.0

    all_events = db.query_events(limit=500)
    raw_count = sum(1 for e in all_events if e.status == "raw")
    compressed_count = sum(1 for e in all_events if e.status == "compressed")
    deleted_count = sum(1 for e in all_events if e.status == "deleted")

    return {
        "disk_used_gb": round(used_gb, 2),
        "disk_total_gb": round(total_gb, 2),
        "disk_free_pct": round(free_pct, 1),
        "raw_events_count": raw_count,
        "compressed_events_count": compressed_count,
        "deleted_events_count": deleted_count,
        "raw_retention_hours": settings.raw_retention_hours,
        "disk_safety_threshold_pct": settings.disk_safety_threshold_pct
    }


@app.get("/api/cameras/{camera_id}/mjpeg")
def stream_camera_mjpeg(camera_id: str):
    """
    Native Motion JPEG (MJPEG) stream fallback.
    Allows zero-dependency live camera viewing directly in HTML <img> tags
    without requiring external WebRTC media servers or go2rtc binaries.
    """
    def frame_generator():
        while True:
            # Check pipeline ring buffer or generate live test preview
            frame = None
            if _pipeline_instance and camera_id in _pipeline_instance.ring_buffers:
                buf = _pipeline_instance.ring_buffers[camera_id]
                if buf:
                    frame = buf[-1]

            if frame is None:
                # Generate idle test frame
                frame = np.full((360, 640, 3), 30, dtype=np.uint8)
                cv2.putText(
                    frame,
                    f"Camera [{camera_id}] Live Stream (Standby)",
                    (30, 180),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (200, 200, 200),
                    2
                )

            ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ret:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                )
            time.sleep(0.25)  # 4 fps

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


class TriageRequest(BaseModel):
    triage: str  # 'confirmed_threat' | 'false_positive' | 'unreviewed'


@app.post("/api/events/{event_id}/triage")
def set_event_triage(event_id: str, req: TriageRequest):
    """Sets user triage validation for an event."""
    db = get_db()
    if req.triage not in ("confirmed_threat", "false_positive", "unreviewed"):
        raise HTTPException(status_code=400, detail="Invalid triage status")
    db.update_event_triage(event_id, req.triage)
    return {"status": "success", "event_id": event_id, "triage": req.triage}


@app.get("/api/system/metrics")
def get_system_metrics():
    """Live hardware and pipeline metrics for dashboard observability."""
    import psutil
    db = get_db()
    triage_stats = db.get_triage_statistics()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    active_cams = len(_pipeline_instance.capture_threads) if _pipeline_instance else 0
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": mem.percent,
        "ram_used_mb": round(mem.used / (1024 * 1024), 1),
        "disk_free_gb": round(disk.free / (1024 * 1024 * 1024), 1),
        "disk_used_pct": disk.percent,
        "active_cameras": active_cams,
        "pipeline_fps": 4.0,
        "triage_stats": triage_stats
    }


class DPDPAuditRequest(BaseModel):
    camera_id: Optional[str] = None
    before_date: Optional[str] = None
    actor: str = "DPO_OFFICER"


@app.post("/api/dpdp/purge")
def execute_dpdp_purge(req: DPDPAuditRequest):
    """Executes statutory Right-to-Erasure (SAR) with cryptographic tamper-evident logging."""
    from vyzn.privacy.dpdp import DPDPAuditEngine
    db = get_db()
    engine = DPDPAuditEngine()
    purged_count = engine.execute_sar_purge(db, camera_id=req.camera_id, before_date=req.before_date, actor=req.actor)
    return {"status": "success", "purged_records": purged_count, "actor": req.actor}


@app.get("/api/dpdp/notice", response_class=HTMLResponse)
def get_dpdp_statutory_notice():
    """Returns compliant bilingual print-ready shop entrance CCTV signage."""
    from vyzn.privacy.dpdp import generate_dpdp_notice
    settings = get_settings()
    notice_html = generate_dpdp_notice(
        business_name=settings.site_name,
        retention_hours=settings.raw_retention_hours
    )
    return HTMLResponse(content=notice_html)


class ZoneCreateRequest(BaseModel):
    name: str
    points: List[List[float]]  # Normalized [[x1, y1], [x2, y2], ...]
    zone_type: str = "restricted_zone"  # 'restricted_zone' | 'privacy_mask'
    weight: int = 20
    schedule_mode: str = "restricted_all_times"
    description: str = ""


@app.get("/api/cameras/{camera_id}/snapshot.jpg")
def get_camera_snapshot(camera_id: str):
    """Returns an uncompressed JPEG still frame for visual zone polygon drawing."""
    frame = None
    if _pipeline_instance and camera_id in _pipeline_instance.ring_buffers:
        buf = _pipeline_instance.ring_buffers[camera_id]
        if buf:
            frame = buf[-1]

    if frame is None:
        frame = np.full((360, 640, 3), 45, dtype=np.uint8)
        cv2.putText(
            frame,
            f"Snapshot: {camera_id}",
            (180, 180),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2
        )

    ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    from fastapi.responses import Response
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


@app.get("/api/cameras/{camera_id}/zones")
def get_camera_zones(camera_id: str):
    """Retrieves all active restricted polygon zones and privacy masks for a specific camera."""
    settings = get_settings()
    cam = next((c for c in settings.cameras if c.camera_id == camera_id), None)
    if not cam:
        return []
    res = []
    for z in cam.restricted_zones:
        d = z.dict()
        d["zone_type"] = "restricted_zone"
        res.append(d)
    for z in getattr(cam, "privacy_zones", []):
        d = z.dict()
        d["zone_type"] = "privacy_mask"
        res.append(d)
    return res



@app.post("/api/cameras/{camera_id}/zones")
def create_camera_zone(camera_id: str, zone_req: ZoneCreateRequest):
    """
    Saves a new visual polygon zone for a camera, writes to config/zones.yaml,
    and dynamically hot-reloads the active edge pipeline without dropping capture threads.
    """
    settings = get_settings()
    cam = next((c for c in settings.cameras if c.camera_id == camera_id), None)
    if not cam:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    from vyzn.core.config import ZonePolygon
    import yaml

    new_zone = ZonePolygon(name=zone_req.name, points=zone_req.points)

    if zone_req.zone_type == "privacy_mask":
        cam.privacy_zones = [z for z in cam.privacy_zones if z.name != zone_req.name]
        cam.privacy_zones.append(new_zone)
    else:
        cam.restricted_zones = [z for z in cam.restricted_zones if z.name != zone_req.name]
        cam.restricted_zones.append(new_zone)

    # Hot-reload in pipeline
    if _pipeline_instance and hasattr(_pipeline_instance, "update_camera_zones"):
        _pipeline_instance.update_camera_zones(camera_id, cam.restricted_zones)

    # Persist to config/zones.yaml
    zones_file = Path("./config/zones.yaml")
    zones_file.parent.mkdir(parents=True, exist_ok=True)
    existing_data = {"zones": {}}
    if zones_file.exists():
        try:
            with open(zones_file, "r") as f:
                loaded = yaml.safe_load(f)
                if loaded and "zones" in loaded:
                    existing_data = loaded
        except Exception:
            pass

    existing_data["zones"][zone_req.name] = {
        "camera_id": camera_id,
        "polygon": zone_req.points,
        "zone_type": zone_req.zone_type,
        "weight": zone_req.weight,
        "schedule_mode": zone_req.schedule_mode,
        "description": zone_req.description or f"{zone_req.zone_type} on {camera_id}"
    }

    with open(zones_file, "w") as f:
        yaml.safe_dump(existing_data, f, default_flow_style=False)

    return {
        "status": "success",
        "camera_id": camera_id,
        "zone_name": zone_req.name,
        "zone_type": zone_req.zone_type,
        "vertex_count": len(zone_req.points)
    }



# ---------------------------------------------------------------------------
# Zero-Touch Camera Discovery & Adoption Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/cameras/discover")
def discover_network_cameras(
    timeout: float = Query(1.5, ge=0.5, le=5.0),
    target_ips: Optional[str] = Query(None)
):
    """
    Scans local network for ONVIF and RTSP IP cameras (CP Plus, Hikvision, Dahua).
    Enables zero-touch 1-click camera adoption without manual IP typing.
    """
    from vyzn.capture.discovery import CameraDiscoveryService
    discovery = CameraDiscoveryService(timeout_sec=timeout)
    ip_list = [ip.strip() for ip in target_ips.split(",")] if target_ips else None
    cameras = discovery.discover_all(target_ips=ip_list)
    return {
        "status": "success",
        "count": len(cameras),
        "cameras": cameras
    }


class CameraAdoptRequest(BaseModel):
    camera_id: str
    name: str
    rtsp_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    target_fps: float = 4.0


@app.post("/api/v1/cameras/adopt")
def adopt_discovered_camera(req: CameraAdoptRequest):
    """Adopts a discovered camera and registers it in the active edge configuration."""
    from vyzn.core.config import CameraConfig
    settings = get_settings()

    final_url = req.rtsp_url
    if req.username and req.password and "@" not in final_url:
        # Inject credentials into RTSP URL: rtsp://user:pass@host...
        parts = final_url.split("://", 1)
        if len(parts) == 2:
            final_url = f"{parts[0]}://{req.username}:{req.password}@{parts[1]}"

    new_cam = CameraConfig(
        camera_id=req.camera_id,
        name=req.name,
        rtsp_url=final_url,
        enabled=True,
        target_fps=req.target_fps
    )

    # Check if camera already exists; update or append
    existing_idx = next((i for i, c in enumerate(settings.cameras) if c.camera_id == req.camera_id), None)
    if existing_idx is not None:
        settings.cameras[existing_idx] = new_cam
    else:
        settings.cameras.append(new_cam)

    return {
        "status": "adopted",
        "camera_id": req.camera_id,
        "name": req.name,
        "rtsp_url_masked": final_url.split("@")[-1] if "@" in final_url else final_url,
        "total_active_cameras": len(settings.cameras)
    }


# ---------------------------------------------------------------------------
# Dashboard Static Web Serving
# ---------------------------------------------------------------------------

frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dashboard"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>VYZN Netra Dashboard</h1><p>Frontend static files not found.</p>")
