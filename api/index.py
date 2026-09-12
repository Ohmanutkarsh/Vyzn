"""
Vercel Serverless Entry Point for VYZN Netra Platform.
Enables cloud hosting of VYZN Surveillance Dashboard, Fleet Portal, and Mobile Clip Viewer.
"""

import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="VYZN Netra Serverless Cloud Console", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# Demo events for cloud serverless demo
DEMO_EVENTS = [
    {
        "event_group_id": "ev_vault_breach_01",
        "camera_id": "cam_cash_counter",
        "start_time": "2026-09-12T14:15:22Z",
        "duration_sec": 14.5,
        "object_type": "person",
        "confidence": 0.94,
        "score": 92,
        "dominant_color": "red",
        "zone_name": "restricted_vault",
        "status": "raw",
        "starred": False,
        "motion_points_count": 28
    },
    {
        "event_group_id": "ev_shutter_night_02",
        "camera_id": "cam_shutter_night",
        "start_time": "2026-09-12T13:42:10Z",
        "duration_sec": 11.0,
        "object_type": "vehicle",
        "confidence": 0.89,
        "score": 78,
        "dominant_color": "black",
        "zone_name": "rear_shutter",
        "status": "raw",
        "starred": True,
        "motion_points_count": 19
    },
    {
        "event_group_id": "ev_corridor_walk_03",
        "camera_id": "cam_corridor",
        "start_time": "2026-09-12T12:05:44Z",
        "duration_sec": 9.2,
        "object_type": "person",
        "confidence": 0.85,
        "score": 42,
        "dominant_color": "blue",
        "zone_name": "main_corridor",
        "status": "raw",
        "starred": False,
        "motion_points_count": 14
    }
]

DRAFTS_STORE = {}

@app.get("/api/status")
def get_system_status():
    return {
        "system": {
            "cpu_usage_pct": 18.5,
            "ram_used_mb": 420.0,
            "disk_free_gb": 184.2,
            "disk_free_pct": 72.0,
            "platform": "Vercel Serverless Cloud Edge"
        },
        "pipeline": {
            "fps": 4.0,
            "far_pct": 0.0,
            "active_cameras": 3,
            "threat_index": 0
        },
        "offline_buffer_count": 0
    }

@app.get("/api/cameras")
def list_cameras():
    return [
        {"camera_id": "cam_corridor", "name": "Main Glass Entrance Door", "status": "ONLINE", "target_fps": 4.0},
        {"camera_id": "cam_cash_counter", "name": "Cash Counter and POS Desk", "status": "ONLINE", "target_fps": 4.0},
        {"camera_id": "cam_shutter_night", "name": "Rear Shutter and Vault Area", "status": "ONLINE", "target_fps": 4.0}
    ]

@app.get("/api/events")
def list_events(limit: int = 50, location_id: Optional[str] = None):
    return DEMO_EVENTS[:limit]

@app.get("/api/v1/locations")
def list_locations():
    return [
        {"location_id": "loc_primary", "name": "Verma Electronics and Hardware", "address": "Sector 18, Noida"},
        {"location_id": "loc_sec14", "name": "South Delhi Kirana Hub", "address": "Main Market, New Delhi"}
    ]

@app.get("/api/v1/forensics/search")
def forensic_search(
    q: Optional[str] = None,
    object_type: Optional[str] = None,
    color: Optional[str] = None,
    zone: Optional[str] = None,
    min_score: int = 0,
    limit: int = 50
):
    matches = list(DEMO_EVENTS)
    if object_type and object_type != "all":
        matches = [e for e in matches if e["object_type"] == object_type]
    if color and color != "all":
        matches = [e for e in matches if e["dominant_color"] == color]
    if zone and zone != "all":
        matches = [e for e in matches if e["zone_name"] == zone]
    if min_score > 0:
        matches = [e for e in matches if e["score"] >= min_score]
    if q:
        ql = q.lower()
        matches = [e for e in matches if ql in e["camera_id"].lower() or ql in e["zone_name"].lower() or ql in e["object_type"].lower()]
    return {
        "status": "success",
        "count": len(matches),
        "events": matches[:limit],
        "results": matches[:limit]
    }

@app.get("/api/v1/alerts/telegram/status")
def get_telegram_status():
    return {
        "configured": True,
        "poller_active": True,
        "chat_id_masked": "98765****",
        "raw_chat_id": "987654321",
        "channel_type": "telegram"
    }

@app.post("/api/v1/alerts/telegram/test-ping")
def telegram_ping():
    return {"ok": True, "bot_username": "VyznAlertBot", "latency_ms": 42}

@app.get("/api/v1/fleet/sites")
def fleet_sites(request: Request):
    return [
        {
            "site_id": "site_verma_retail",
            "name": "Verma Electronics and Hardware (Noida)",
            "status": "ONLINE",
            "config_version": 3,
            "config_hash": "c71ab89f",
            "edge_url": "https://vyzn.ai/vms/site_verma",
            "system": {"cpu_usage_pct": 14, "ram_used_mb": 410, "disk_free_pct": 74},
            "pipeline": {"active_cameras": 3}
        },
        {
            "site_id": "site_sharma_kirana",
            "name": "Sharma Supermarket (South Delhi)",
            "status": "ONLINE",
            "config_version": 2,
            "config_hash": "f419dc01",
            "edge_url": "https://vyzn.ai/vms/site_sharma",
            "system": {"cpu_usage_pct": 21, "ram_used_mb": 520, "disk_free_pct": 68},
            "pipeline": {"active_cameras": 4}
        }
    ]

@app.get("/api/v1/fleet/incidents")
def fleet_incidents():
    return [
        {
            "site_id": "site_verma_retail",
            "site_name": "Verma Electronics",
            "camera_id": "cam_cash_counter",
            "object_type": "person",
            "score": 92
        }
    ]

@app.get("/api/v1/fleet/onboarding/drafts")
def list_drafts():
    return {"status": "success", "count": len(DRAFTS_STORE), "drafts": list(DRAFTS_STORE.values())}

@app.put("/api/v1/fleet/onboarding/drafts/{draft_id}")
def save_draft(draft_id: str, payload: Dict[str, Any]):
    payload["draft_id"] = draft_id
    DRAFTS_STORE[draft_id] = payload
    return {"status": "saved", "draft": payload}

@app.get("/api/v1/fleet/onboarding/drafts/{draft_id}")
def get_draft(draft_id: str):
    if draft_id not in DRAFTS_STORE:
        raise HTTPException(status_code=404, detail="Draft not found")
    return DRAFTS_STORE[draft_id]

@app.delete("/api/v1/fleet/onboarding/drafts/{draft_id}")
def delete_draft(draft_id: str):
    DRAFTS_STORE.pop(draft_id, None)
    return {"status": "deleted", "draft_id": draft_id}

@app.post("/api/v1/fleet/onboarding/drafts/{draft_id}/test-alert")
def test_draft_alert(draft_id: str):
    if draft_id in DRAFTS_STORE:
        DRAFTS_STORE[draft_id]["test_verified"] = True
    return {
        "status": "test_delivered",
        "draft_id": draft_id,
        "target_chat": "987654321",
        "test_verified": True,
        "message": "Synthetic test alert verified delivered on Telegram!"
    }

@app.post("/api/v1/fleet/onboarding/drafts/{draft_id}/go-live")
def go_live_draft(draft_id: str):
    d = DRAFTS_STORE.get(draft_id, {})
    if not d.get("test_verified"):
        raise HTTPException(status_code=400, detail="Synthetic test alert must be verified on Telegram first.")
    return {
        "status": "online",
        "site_id": "site_" + draft_id,
        "edge_secret_preview": "vyzn_edge_secret_...",
        "message": "Site successfully provisioned and deployed online."
    }

@app.post("/api/v1/fleet/sites/{site_id}/stolen")
def report_stolen(site_id: str):
    repl_id = f"draft_repl_{site_id}_{int(time.time())}"
    DRAFTS_STORE[repl_id] = {
        "draft_id": repl_id,
        "site_name": f"Replacement for {site_id}",
        "current_step": 1,
        "test_verified": False,
        "data": {
            "identity": {"site_name": f"Replacement for {site_id}"},
            "schedule": {"hours_start": "09:00", "hours_end": "21:00", "threshold": 70}
        }
    }
    return {
        "status": "stolen_revoked",
        "site_id": site_id,
        "message": "Credentials revoked. Replacement draft prepared.",
        "replacement_draft_id": repl_id
    }



# ---------------------------------------------------------------------------
# Trial Leads Capture & Telemetry
# ---------------------------------------------------------------------------
TRIAL_LEADS: List[Dict[str, Any]] = []

class TrialLeadRequest(BaseModel):
    full_name: str
    store_name: str
    city: str
    phone: str
    cameras: str
    concern: str

@app.post("/api/v1/leads/trial")
def submit_trial_lead(lead: TrialLeadRequest):
    record = lead.model_dump()
    record["created_at"] = time.time()
    record["lead_id"] = f"lead_{int(time.time())}"
    TRIAL_LEADS.append(record)
    return {
        "status": "success",
        "instance_id": f"VYZN-TRIAL-IN-{int(time.time()) % 10000:04d}",
        "message": "Trial provisioned successfully! Credentials dispatched."
    }

# ---------------------------------------------------------------------------
# Camera Demo MJPEG Stream & Zones Mock Handlers
# ---------------------------------------------------------------------------
@app.get("/api/cameras/{camera_id}/mjpeg")
def stream_demo_mjpeg(camera_id: str):
    label = camera_id.replace("cam_", "").replace("_", " ").upper()
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
      <defs>
        <radialGradient id="scanGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#0f172a" stop-opacity="0.8"/>
          <stop offset="100%" stop-color="#020617" stop-opacity="1"/>
        </radialGradient>
      </defs>
      <rect width="640" height="360" fill="url(#scanGrad)"/>
      <circle cx="320" cy="180" r="130" stroke="#1e293b" stroke-width="1.5" fill="none"/>
      <circle cx="320" cy="180" r="70" stroke="#0ea5e9" stroke-width="1" stroke-dasharray="4 4" fill="none"/>
      <line x1="120" y1="180" x2="520" y2="180" stroke="#1e293b" stroke-width="1"/>
      <line x1="320" y1="40" x2="320" y2="320" stroke="#1e293b" stroke-width="1"/>
      <circle cx="320" cy="180" r="4" fill="#0ea5e9"/>
      <text x="24" y="36" fill="#10b981" font-family="monospace" font-size="13" font-weight="bold">● LIVE: {label}</text>
      <text x="24" y="58" fill="#64748b" font-family="monospace" font-size="11">YOLOv8 EDGE AI • ON-PREMISE • ZERO-BANDWIDTH CHOKE</text>
      <rect x="220" y="110" width="160" height="175" stroke="#0ea5e9" stroke-width="2" stroke-dasharray="6 3" fill="rgba(14,165,233,0.06)"/>
      <text x="225" y="102" fill="#38bdf8" font-family="monospace" font-size="11" font-weight="bold">PERSON: 94.2% [CASHIER / PROPRIETOR]</text>
      <text x="440" y="340" fill="#475569" font-family="monospace" font-size="10">SEC-65B CERTIFIED</text>
    </svg>'''
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/cameras/{camera_id}/zones")
def get_demo_zones(camera_id: str):
    return [
        {
            "zone_id": f"zone_{camera_id}_pos",
            "name": "Cash Counter & POS Box",
            "zone_type": "high_theft",
            "points": [[0.25, 0.45], [0.65, 0.45], [0.65, 0.85], [0.25, 0.85]],
            "schedule": "all_times"
        }
    ]

# ---------------------------------------------------------------------------
# Static File Handlers (For Direct Serverless Fallback)
# ---------------------------------------------------------------------------
@app.get("/styles.css")
def serve_root_styles():
    for p in [WORKSPACE_ROOT / "public" / "styles.css", WORKSPACE_ROOT / "frontend" / "dashboard" / "styles.css"]:
        if p.exists():
            return Response(content=p.read_text(encoding="utf-8"), media_type="text/css")
    raise HTTPException(status_code=404, detail="styles.css not found")

@app.get("/app.js")
def serve_root_js():
    for p in [WORKSPACE_ROOT / "public" / "app.js", WORKSPACE_ROOT / "frontend" / "dashboard" / "app.js"]:
        if p.exists():
            return Response(content=p.read_text(encoding="utf-8"), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

@app.get("/static/{file_path:path}")
def serve_static_file(file_path: str):
    clean_path = file_path.lstrip("/")
    candidates = [
        WORKSPACE_ROOT / "public" / "static" / clean_path,
        WORKSPACE_ROOT / "public" / clean_path,
        WORKSPACE_ROOT / "frontend" / "dashboard" / clean_path,
        WORKSPACE_ROOT / "vyzn_cloud" / "templates" / clean_path
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            mime, _ = mimetypes.guess_type(str(c))
            return Response(content=c.read_bytes(), media_type=mime or "application/octet-stream")
    raise HTTPException(status_code=404, detail=f"Static file {file_path} not found")

@app.get("/fleet", response_class=HTMLResponse)
def serve_fleet():
    fleet_file = WORKSPACE_ROOT / "vyzn_cloud" / "templates" / "fleet.html"
    if fleet_file.exists():
        return HTMLResponse(content=fleet_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>VYZN Fleet Operations</h1><p>Template not found.</p>")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = WORKSPACE_ROOT / "frontend" / "dashboard" / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>VYZN Surveillance Console</h1>")
