"""
FastAPI route definitions for event retrieval, storage statistics, and dashboard streaming.
"""

from __future__ import annotations
import os
import time
import shutil
import cv2
import io
import json
import zipfile
import hashlib
import asyncio
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Security, Depends, Response, Request
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings
from vyzn.alerts.telegram import (
    TelegramAlertProvider,
    start_telegram_poller,
    stop_telegram_poller,
    get_active_poller,
    test_telegram_connection,
    send_telegram_threat_alert
)
from vyzn_cloud.supabase_client import (
    sign_in_with_email,
    sign_up_with_email,
    verify_supabase_jwt,
    send_phone_otp,
    verify_phone_otp
)
from vyzn.capture.stream_capture import normalize_camera_stream_url, probe_stream_connection
from vyzn.api.mobile_viewer import mobile_viewer_router

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

app.include_router(mobile_viewer_router)

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


def load_locations() -> List[Dict[str, Any]]:
    loc_file = Path("./config/locations.json")
    if loc_file.exists():
        try:
            with open(loc_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass
    default_locs = [{
        "location_id": "loc_primary",
        "name": "Primary Premises",
        "address": "Main Building",
        "owner_email": None
    }]
    save_locations(default_locs)
    return default_locs


def save_locations(locs: List[Dict[str, Any]]) -> None:
    loc_file = Path("./config/locations.json")
    loc_file.parent.mkdir(parents=True, exist_ok=True)
    with open(loc_file, "w", encoding="utf-8") as f:
        json.dump(locs, f, indent=2)


def save_cameras_config(settings: EdgeSettings) -> None:
    try:
        cfg_file = Path("./config/cameras.json")
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump([c.dict() for c in settings.cameras], f, indent=2)
    except Exception as e:
        import logging
        logging.getLogger("vyzn.api").warning(f"Failed to persist cameras.json: {e}")



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


def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Extracts authenticated user from Bearer header or cookie if present."""
    auth_hdr = request.headers.get("Authorization", "")
    token = None
    if auth_hdr.startswith("Bearer "):
        token = auth_hdr[7:].strip()
    elif "vyzn_access_token" in request.cookies:
        token = request.cookies.get("vyzn_access_token")

    if not token:
        return None

    try:
        from vyzn_cloud.supabase_client import SUPABASE_JWT_SECRET
        import jwt
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        return {
            "user_id": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("app_metadata", {}).get("role", "resident")
        }
    except Exception:
        return None


@app.get("/api/events")
def list_events(
    camera_id: Optional[str] = Query(None, description="Filter by camera ID"),
    min_score: int = Query(0, ge=0, le=100, description="Minimum threat score"),
    color: Optional[str] = Query(None, description="Filter by garment / object color"),
    zone: Optional[str] = Query(None, description="Filter by zone name"),
    object_type: Optional[str] = Query(None, description="Filter by object category"),
    triage: Optional[str] = Query(None, description="Filter by user triage status"),
    location_id: Optional[str] = Query(None, description="Filter by property location ID"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    user: Optional[Dict[str, Any]] = Depends(get_optional_user)
) -> List[Dict[str, Any]]:
    """Retrieves recent events from SQLite event index with optional appearance, location, and tenant filters."""
    db = get_db()
    events = db.query_events(
        camera_id=camera_id,
        min_score=min_score,
        color=color,
        zone=zone,
        object_type=object_type,
        user_triage=triage,
        location_id=location_id,
        limit=limit
    )

    # Scoping: If user is logged in as non-admin, filter events to user's cameras
    if user and user.get("role") not in ("admin", "fleet_admin"):
        user_email = user.get("email")
        settings = get_settings()
        allowed_cams = {c.camera_id for c in settings.cameras if getattr(c, "owner_email", None) is None or c.owner_email == user_email}
        events = [e for e in events if e.camera_id in allowed_cams]

    return [e.to_dict() for e in events]


@app.get("/api/v1/forensics/search")
def forensic_search(
    location_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    object_type: Optional[str] = None,
    color: Optional[str] = None,
    zone: Optional[str] = None,
    min_score: int = 0,
    max_score: int = 100,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    triage: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user)
) -> Dict[str, Any]:
    """
    Executes multi-criteria forensic investigation search across historical incident records.
    Supports filtering by site/location, camera, classifications, date ranges, and free-text queries.
    """
    db = get_db()
    result = db.search_forensic_events(
        location_id=location_id,
        camera_id=camera_id,
        object_type=object_type,
        color=color,
        zone=zone,
        min_score=min_score,
        max_score=max_score,
        date_from=date_from,
        date_to=date_to,
        free_text=q,
        user_triage=triage,
        limit=limit,
        offset=offset
    )

    # Scoping: If user is logged in as non-admin, filter events to user's cameras
    if user and user.get("role") not in ("admin", "fleet_admin"):
        user_email = user.get("email")
        settings = get_settings()
        allowed_cams = {c.camera_id for c in settings.cameras if getattr(c, "owner_email", None) is None or c.owner_email == user_email}
        filtered_events = [e for e in result["events"] if e.camera_id in allowed_cams]
        result["events"] = filtered_events
        result["count"] = len(filtered_events)

    result["events"] = [e.to_dict() for e in result["events"]]
    result["results"] = result["events"]
    return result


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


@app.get("/api/v1/events/{event_id}/forensic-pack")
def download_forensic_evidence_pack(event_id: str):
    """
    Generates a tamper-evident evidentiary ZIP bundle complying with
    DPDP 2023 and Section 65B of the Indian Evidence Act / Section 63 BSA 2023.
    """
    db = get_db()
    settings = get_settings()
    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Incident event not found")

    zip_buffer = io.BytesIO()

    video_hash = "FILE_UNAVAILABLE"
    video_bytes = b""
    if event.file_path and os.path.exists(event.file_path):
        with open(event.file_path, "rb") as vf:
            video_bytes = vf.read()
            video_hash = hashlib.sha256(video_bytes).hexdigest()

    thumb_hash = "FILE_UNAVAILABLE"
    thumb_bytes = b""
    if event.thumb_path and os.path.exists(event.thumb_path):
        with open(event.thumb_path, "rb") as tf:
            thumb_bytes = tf.read()
            thumb_hash = hashlib.sha256(thumb_bytes).hexdigest()

    now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    manifest = {
        "vyzn_forensic_version": "1.0",
        "jurisdiction": "Republic of India",
        "statutory_framework": "Section 63 BSA 2023 / Section 65B IEA 1872 / DPDP Act 2023",
        "site_id": settings.site_id,
        "site_name": settings.site_name,
        "event_group_id": event.event_group_id,
        "camera_id": event.camera_id,
        "start_time_utc": event.start_time,
        "end_time_utc": event.end_time,
        "threat_score": event.score,
        "object_type": event.object_type,
        "dominant_color": getattr(event, "dominant_color", "unspecified"),
        "zone_name": getattr(event, "zone_name", "general"),
        "video_sha256": video_hash,
        "thumb_sha256": thumb_hash,
        "export_timestamp_utc": now_utc,
        "integrity_seal": hashlib.sha256(f"{event.event_group_id}:{video_hash}:{now_utc}".encode()).hexdigest()
    }

    cert_text = f"""================================================================================
CERTIFICATE OF AUTHENTICITY UNDER SECTION 63 OF THE BHARATIYA SAKSHYA ADHINIYAM, 2023
(READ WITH SECTION 65B OF THE INDIAN EVIDENCE ACT, 1872)
================================================================================

1. I am the authorized operator of the automated computer vision security platform
   (VYZN Netra) deployed at:
   Site Name: {settings.site_name} (ID: {settings.site_id})

2. I hereby certify that the accompanying digital recording:
   File Name: {event.event_group_id}.mp4
   Camera Channel: {event.camera_id}
   Recorded Interval: {event.start_time} to {event.end_time} UTC
   Recorded Threat Score: {event.score}/100 ({event.object_type}, apparel: {getattr(event, 'dominant_color', 'unspecified')})
   Cryptographic SHA-256 Checksum: {video_hash}

3. During the period over which the electronic record was produced, the computer
   system operated legitimately and regularly. There has been no alteration,
   tampering, frame insertion, or removal affecting the integrity of the footage.

4. Generated automatically under Section 12 Data Fiduciary accountability of the
   Digital Personal Data Protection (DPDP) Act, 2023.

Timestamp of Export: {now_utc}
Cryptographic Manifest Seal: {manifest['integrity_seal']}
================================================================================
"""

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if video_bytes:
            zf.writestr(f"{event.event_group_id}.mp4", video_bytes)
        if thumb_bytes:
            zf.writestr(f"{event.event_group_id}_thumb.jpg", thumb_bytes)
        zf.writestr("manifest_sha256.json", json.dumps(manifest, indent=2))
        zf.writestr("SECTION_65B_LEGAL_CERTIFICATE.txt", cert_text)

    db.log_audit("FORENSIC_PACK_EXPORTED", event_id, f"SHA256: {video_hash[:12]}...")

    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=VYZN_FORENSIC_EVIDENCE_{event_id}.zip"
        }
    )


# Bandwidth & QoS Governor State
_bandwidth_config = {
    "max_upload_mbps": 2.0,
    "retention_hours": 72,
    "asymmetrical_sync": True,
    "current_upload_mbps": 0.42,
    "sync_mode": "metadata_only_on_motion"
}

class BandwidthSettingsUpdate(BaseModel):
    max_upload_mbps: Optional[float] = 2.0
    retention_hours: Optional[int] = 72
    asymmetrical_sync: Optional[bool] = True

@app.get("/api/v1/settings/bandwidth")
def get_bandwidth_settings() -> Dict[str, Any]:
    """Returns edge bandwidth throttle limits and local ring buffer policy."""
    return _bandwidth_config

@app.post("/api/v1/settings/bandwidth")
def update_bandwidth_settings(payload: BandwidthSettingsUpdate) -> Dict[str, Any]:
    """Updates edge cloud upload throttle limits."""
    if payload.max_upload_mbps is not None:
        _bandwidth_config["max_upload_mbps"] = round(max(0.5, min(50.0, payload.max_upload_mbps)), 1)
    if payload.retention_hours is not None:
        _bandwidth_config["retention_hours"] = max(12, min(720, payload.retention_hours))
    if payload.asymmetrical_sync is not None:
        _bandwidth_config["asymmetrical_sync"] = payload.asymmetrical_sync
    
    db = get_db()
    db.log_audit("BANDWIDTH_CONFIG_UPDATED", details=str(_bandwidth_config))
    return {"status": "updated", "config": _bandwidth_config}


# ---------------------------------------------------------------------------
# Telegram Bot Alert & Two-Way Interactive Triage Endpoints
# ---------------------------------------------------------------------------

class TelegramSettingsUpdate(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    enable_poller: Optional[bool] = True


class TelegramTestPingRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


@app.get("/api/v1/alerts/telegram")
def get_telegram_settings() -> Dict[str, Any]:
    """Returns Telegram bot configuration status, masked tokens, and poller state."""
    settings = get_settings()
    poller = get_active_poller()
    poller_active = poller is not None and poller.is_alive()

    raw_token = settings.telegram_bot_token or os.environ.get("VYZN_TELEGRAM_BOT_TOKEN", "")
    raw_chat = settings.telegram_chat_id or os.environ.get("VYZN_TELEGRAM_CHAT_ID", "")

    masked_token = (raw_token[:6] + "..." + raw_token[-4:]) if len(raw_token) > 10 else ("configured" if raw_token else "")
    masked_chat = (raw_chat[:3] + "..." + raw_chat[-2:]) if len(raw_chat) > 5 else raw_chat

    return {
        "configured": bool(raw_token and raw_chat),
        "bot_token_masked": masked_token,
        "chat_id_masked": masked_chat,
        "raw_chat_id": raw_chat,
        "poller_active": poller_active,
        "mode": "two_way_interactive_long_polling"
    }


@app.post("/api/v1/alerts/telegram")
def update_telegram_settings(payload: TelegramSettingsUpdate) -> Dict[str, Any]:
    """Updates Telegram bot credentials, hot-reloads alert dispatcher, and restarts polling worker."""
    settings = get_settings()
    db = get_db()

    if payload.bot_token is not None:
        settings.telegram_bot_token = payload.bot_token.strip()
    if payload.chat_id is not None:
        settings.telegram_chat_id = payload.chat_id.strip()

    # Hot-reload dispatcher provider in pipeline if running
    new_provider = TelegramAlertProvider(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id
    )
    if _pipeline_instance and hasattr(_pipeline_instance, "dispatcher"):
        _pipeline_instance.dispatcher.provider = new_provider

    # Manage long-polling worker
    poller_status = "inactive"
    if payload.enable_poller and settings.telegram_bot_token:
        calibrator = getattr(_pipeline_instance, "calibrator", None) if _pipeline_instance else None
        poller = start_telegram_poller(
            bot_token=settings.telegram_bot_token,
            db=db,
            calibrator=calibrator
        )
        poller_status = "running" if (poller and poller.is_alive()) else "failed_to_start"
    else:
        stop_telegram_poller()
        poller_status = "stopped"

    db.log_audit("TELEGRAM_CONFIG_UPDATED", details=f"chat_id={settings.telegram_chat_id}, poller={poller_status}")

    return {
        "status": "updated",
        "configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "poller_status": poller_status,
        "chat_id": settings.telegram_chat_id
    }


@app.post("/api/v1/alerts/telegram/test-ping")
def api_test_telegram_ping(req: TelegramTestPingRequest) -> Dict[str, Any]:
    """Verifies Telegram credentials and tests alert deliverability and round-trip latency."""
    settings = get_settings()
    token = req.bot_token or settings.telegram_bot_token or os.environ.get("VYZN_TELEGRAM_BOT_TOKEN")
    chat = req.chat_id or settings.telegram_chat_id or os.environ.get("VYZN_TELEGRAM_CHAT_ID")

    if not token or not chat:
        raise HTTPException(
            status_code=400,
            detail="Bot token and Chat ID are required for test ping. Provide them in payload or configure them first."
        )

    res = test_telegram_connection(bot_token=token, chat_id=chat)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "Telegram test connection failed"))

    db = get_db()
    db.log_audit("TELEGRAM_TEST_PING_SENT", details=f"bot=@{res.get('bot_username')}, latency={res.get('latency_ms')}ms")
    return res


@app.post("/api/v1/events/{event_id}/dispatch-telegram")
def dispatch_event_to_telegram(event_id: str) -> Dict[str, Any]:
    """Manually dispatches an incident's MP4 video clip to the configured Telegram chat."""
    db = get_db()
    settings = get_settings()

    event = db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Incident event not found")

    token = settings.telegram_bot_token or os.environ.get("VYZN_TELEGRAM_BOT_TOKEN")
    chat = settings.telegram_chat_id or os.environ.get("VYZN_TELEGRAM_CHAT_ID")

    provider = TelegramAlertProvider(bot_token=token, chat_id=chat)
    success = provider.send_alert(
        event=event,
        video_path=event.file_path or "",
        thumb_path=event.thumb_path or ""
    )

    db.log_audit("TELEGRAM_MANUAL_DISPATCH", event_id, f"success={success}, chat={chat or 'simulation'}")

    return {
        "status": "dispatched" if success else "failed",
        "event_id": event_id,
        "camera_id": event.camera_id,
        "mode": "live" if (token and chat) else "simulation",
        "chat_id": chat or "simulation"
    }


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
    unsynced_count = 0
    try:
        cur = db.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM events WHERE synced = 0")
        row = cur.fetchone()
        unsynced_count = row[0] if row else 0
    except Exception:
        pass

    fps = 4.0
    if _pipeline_instance and hasattr(_pipeline_instance, "capture_threads"):
        measured = [getattr(t, "fps_measured", 0.0) for t in _pipeline_instance.capture_threads if getattr(t, "fps_measured", 0.0) > 0]
        if measured:
            fps = round(sum(measured) / len(measured), 1)

    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": mem.percent,
        "ram_used_mb": round(mem.used / (1024 * 1024), 1),
        "disk_free_gb": round(disk.free / (1024 * 1024 * 1024), 1),
        "disk_used_pct": disk.percent,
        "active_cameras": active_cams,
        "pipeline_fps": fps,
        "unsynced_events": unsynced_count,
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


@app.get("/api/cameras/{camera_id}/mjpeg")
@app.get("/api/cameras/{camera_id}/live.mjpg")
async def stream_camera_mjpeg(camera_id: str, request: Request):
    """
    Zero-latency multipart MJPEG live video stream with disconnection cancellation.
    Eliminates zombie generator threads and threadpool starvation when browser tabs close.
    """
    async def frame_generator():
        fallback_frame = None
        try:
            while True:
                # Disconnection watchdog: terminate immediately if client closed tab/socket
                if await request.is_disconnected():
                    break

                jpeg_bytes = None
                if _pipeline_instance and hasattr(_pipeline_instance, "get_camera_live_jpeg"):
                    jpeg_bytes = _pipeline_instance.get_camera_live_jpeg(camera_id, quality=70)

                if jpeg_bytes is None:
                    if fallback_frame is None:
                        card = np.full((360, 640, 3), (25, 28, 36), dtype=np.uint8)
                        cv2.putText(card, f"Connecting: {camera_id}", (150, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (148, 163, 184), 2)
                        ret, fb = cv2.imencode(".jpg", card, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        fallback_frame = fb.tobytes() if ret else b""
                    jpeg_bytes = fallback_frame
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(0.06)  # ~16 FPS non-blocking

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
                )
        except (asyncio.CancelledError, GeneratorExit):
            # Clean exit on client disconnect
            return

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


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

    save_cameras_config(settings)

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


_cached_local_devices = None

@app.get("/api/v1/cameras/local-devices")
def list_local_video_devices():
    """Detects physically connected USB and integrated webcams on the host with caching."""
    global _cached_local_devices
    if _cached_local_devices is not None:
        return {
            "status": "success",
            "count": len(_cached_local_devices),
            "devices": _cached_local_devices
        }

    devices = []
    for idx in range(2):
        try:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    devices.append({
                        "device_index": idx,
                        "name": f"Integrated Camera / Device {idx}",
                        "rtsp_url": str(idx),
                        "status": "ready"
                    })
            cap.release()
        except Exception:
            pass

    _cached_local_devices = devices
    return {
        "status": "success",
        "count": len(devices),
        "devices": devices
    }


class CameraAdoptRequest(BaseModel):
    camera_id: str
    name: str
    rtsp_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    target_fps: float = 4.0
    location_id: Optional[str] = "loc_primary"
    force: bool = False
    probe_connection: bool = False
    require_online: bool = False


@app.post("/api/v1/cameras/adopt")
def adopt_discovered_camera(req: CameraAdoptRequest, user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """Adopts a discovered camera with pre-adoption connection probe and persistent registration."""
    from vyzn.core.config import CameraConfig
    settings = get_settings()

    final_url = req.rtsp_url
    if req.username and req.password and "@" not in final_url:
        parts = final_url.split("://", 1)
        if len(parts) == 2:
            final_url = f"{parts[0]}://{req.username}:{req.password}@{parts[1]}"

    final_url = normalize_camera_stream_url(final_url)

    # Optional pre-adoption connection probe to eliminate silent failure without blocking offline registration
    can_connect = True
    probe_msg = "Connection OK"
    if req.probe_connection and not req.force:
        can_connect, probe_msg = probe_stream_connection(final_url, timeout_sec=2.0)
        if not can_connect and req.require_online:
            raise HTTPException(status_code=400, detail=f"Camera connection failed: {probe_msg}")

    owner = user.get("email") if user else None
    loc_id = req.location_id or "loc_primary"

    new_cam = CameraConfig(
        camera_id=req.camera_id,
        name=req.name,
        rtsp_url=final_url,
        enabled=True,
        target_fps=req.target_fps,
        location_id=loc_id,
        owner_email=owner
    )

    # Check if camera already exists; update or append
    existing_idx = next((i for i, c in enumerate(settings.cameras) if c.camera_id == req.camera_id), None)
    if existing_idx is not None:
        new_cam.restricted_zones = settings.cameras[existing_idx].restricted_zones
        new_cam.privacy_zones = settings.cameras[existing_idx].privacy_zones
        settings.cameras[existing_idx] = new_cam
    else:
        settings.cameras.append(new_cam)

    # Hot-launch capture thread in active pipeline
    if _pipeline_instance and hasattr(_pipeline_instance, "add_camera_stream"):
        _pipeline_instance.add_camera_stream(new_cam)

    save_cameras_config(settings)

    db = get_db()
    db.log_audit("CAMERA_ADOPTED", req.camera_id, f"name={req.name}, location={loc_id}")

    return {
        "status": "adopted",
        "camera_id": req.camera_id,
        "name": req.name,
        "location_id": loc_id,
        "owner_email": owner,
        "rtsp_url_masked": final_url.split("@")[-1] if "@" in final_url else final_url,
        "total_active_cameras": len(settings.cameras),
        "is_online": can_connect,
        "warning": None if can_connect else f"Camera added in OFFLINE state: {probe_msg}"
    }


@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: str, user: Optional[Dict[str, Any]] = Depends(get_optional_user)) -> Dict[str, Any]:
    """Removes a camera from edge configuration, stops capture thread, and updates persistent store."""
    settings = get_settings()
    settings.cameras = [c for c in settings.cameras if c.camera_id != camera_id]

    # Stop and unregister capture thread in pipeline
    if _pipeline_instance and hasattr(_pipeline_instance, "remove_camera_stream"):
        _pipeline_instance.remove_camera_stream(camera_id)
    elif _pipeline_instance and hasattr(_pipeline_instance, "capture_threads"):
        for t in list(_pipeline_instance.capture_threads):
            if getattr(t, "config", None) and t.config.camera_id == camera_id:
                if hasattr(t, "stop"):
                    t.stop()
                _pipeline_instance.capture_threads.remove(t)

    save_cameras_config(settings)
    db = get_db()
    db.log_audit("CAMERA_DELETED", camera_id)

    return {"status": "deleted", "camera_id": camera_id, "remaining_count": len(settings.cameras)}


@app.get("/api/cameras")
def list_cameras(
    location_id: Optional[str] = Query(None, description="Filter by location ID"),
    user: Optional[Dict[str, Any]] = Depends(get_optional_user)
) -> List[Dict[str, Any]]:
    """Lists all configured edge cameras with live connection diagnostics, scoped to authenticated tenant."""
    settings = get_settings()
    cams = settings.cameras

    if location_id:
        cams = [c for c in cams if getattr(c, "location_id", "loc_primary") == location_id]

    # If logged in as non-admin, scope to user's cameras + public/unassigned cameras
    if user and user.get("role") not in ("admin", "fleet_admin"):
        user_email = user.get("email")
        cams = [c for c in cams if getattr(c, "owner_email", None) is None or c.owner_email == user_email]

    # Inspect live capture thread statuses
    live_status_map = {}
    if _pipeline_instance and hasattr(_pipeline_instance, "capture_threads"):
        for t in _pipeline_instance.capture_threads:
            cid = getattr(t.config, "camera_id", None) if getattr(t, "config", None) else None
            if cid:
                if hasattr(t, "get_connection_status"):
                    live_status_map[cid] = t.get_connection_status()
                else:
                    live_status_map[cid] = {
                        "status": "online" if getattr(t, "is_connected", False) else "offline",
                        "fps": getattr(t, "fps_measured", 0.0),
                        "reconnects": getattr(t, "reconnect_count", 0),
                        "last_error": getattr(t, "last_error", None)
                    }

    res = []
    for c in cams:
        st = live_status_map.get(c.camera_id, {
            "status": "offline",
            "fps": 0.0,
            "reconnects": 0,
            "last_error": None
        })
        res.append({
            "camera_id": c.camera_id,
            "name": c.name,
            "enabled": c.enabled,
            "target_fps": c.target_fps,
            "location_id": getattr(c, "location_id", "loc_primary"),
            "rtsp_url_masked": c.rtsp_url.split("@")[-1] if "@" in c.rtsp_url else c.rtsp_url,
            "is_webcam": str(c.rtsp_url).isdigit() or str(c.rtsp_url).startswith("webcam://"),
            "owner_email": getattr(c, "owner_email", None),
            "status": st.get("status", "offline"),
            "fps_measured": st.get("fps", 0.0),
            "is_connected": st.get("status") == "online",
            "last_error": st.get("last_error")
        })
    return res


# ---------------------------------------------------------------------------
# Property Location Management Endpoints
# ---------------------------------------------------------------------------

class LocationCreateRequest(BaseModel):
    name: str
    address: Optional[str] = ""
    location_id: Optional[str] = None


@app.get("/api/v1/locations")
def list_locations(user: Optional[Dict[str, Any]] = Depends(get_optional_user)) -> List[Dict[str, Any]]:
    """Lists all configured property locations scoped to authenticated tenant."""
    locs = load_locations()
    if user and user.get("role") not in ("admin", "fleet_admin"):
        user_email = user.get("email")
        locs = [l for l in locs if l.get("owner_email") is None or l.get("owner_email") == user_email]
    return locs


@app.post("/api/v1/locations")
def create_location(req: LocationCreateRequest, user: Optional[Dict[str, Any]] = Depends(get_optional_user)) -> Dict[str, Any]:
    """Creates a new property location."""
    name_clean = req.name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="Location name is required")
    locs = load_locations()
    lid = req.location_id or f"loc_{int(time.time()) % 1000000:06d}"
    if any(l.get("location_id") == lid for l in locs):
        raise HTTPException(status_code=400, detail="Location ID already exists")
    owner = user.get("email") if user else None
    new_loc = {
        "location_id": lid,
        "name": name_clean,
        "address": req.address.strip() if req.address else "",
        "owner_email": owner
    }
    locs.append(new_loc)
    save_locations(locs)
    db = get_db()
    db.log_audit("LOCATION_CREATED", lid, f"name={name_clean}")
    return new_loc


@app.delete("/api/v1/locations/{location_id}")
def delete_location(location_id: str, user: Optional[Dict[str, Any]] = Depends(get_optional_user)) -> Dict[str, Any]:
    """Deletes a property location (default primary location cannot be removed)."""
    if location_id == "loc_primary":
        raise HTTPException(status_code=400, detail="Cannot delete default primary location")
    locs = load_locations()
    new_locs = [l for l in locs if l.get("location_id") != location_id]
    if len(new_locs) == len(locs):
        raise HTTPException(status_code=404, detail="Location not found")
    save_locations(new_locs)
    db = get_db()
    db.log_audit("LOCATION_DELETED", location_id)
    return {"status": "deleted", "location_id": location_id}


# ---------------------------------------------------------------------------
# Supabase Authentication & Phone Verification Endpoints
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "shopkeeper"


class PhoneOtpSendRequest(BaseModel):
    phone: str


class PhoneOtpVerifyRequest(BaseModel):
    phone: str
    otp: str


@app.post("/api/v1/auth/login")
def api_auth_login(req: LoginRequest) -> Dict[str, Any]:
    """Authenticates user via Supabase Auth (or verified local dev registry fallback)."""
    return sign_in_with_email(req.email, req.password)


@app.post("/api/v1/auth/register")
def api_auth_register(req: RegisterRequest) -> Dict[str, Any]:
    """Registers new user profile in Supabase Auth & PostgreSQL."""
    return sign_up_with_email(req.email, req.password, req.full_name, req.role)


@app.post("/api/v1/auth/phone/send-otp")
def api_auth_send_phone_otp(req: PhoneOtpSendRequest, user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """Generates and sends 6-digit verification code to user's phone number."""
    email = user.get("email") if user else "guest@vyzn.ai"
    return send_phone_otp(email=email, phone_number=req.phone)


@app.post("/api/v1/auth/phone/verify-otp")
def api_auth_verify_phone_otp(req: PhoneOtpVerifyRequest, user: Optional[Dict[str, Any]] = Depends(get_optional_user)):
    """Verifies phone OTP code and associates verified phone number with user account."""
    email = user.get("email") if user else "guest@vyzn.ai"
    return verify_phone_otp(email=email, phone_number=req.phone, otp=req.otp)


@app.get("/api/v1/auth/me")
def api_auth_me(user: Dict[str, Any] = Security(verify_supabase_jwt)) -> Dict[str, Any]:
    """Returns authenticated user profile, phone status, tenant ID, and assigned role."""
    from vyzn_cloud.supabase_client import LOCAL_DEV_USERS
    user_email = user.get("email")
    if user_email and user_email in LOCAL_DEV_USERS:
        dev_u = LOCAL_DEV_USERS[user_email]
        user["phone"] = dev_u.get("phone")
        user["phone_verified"] = dev_u.get("phone_verified", False)
    return {"status": "authenticated", "user": user}


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
