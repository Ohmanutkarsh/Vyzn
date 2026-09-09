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
