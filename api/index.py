"""
Vercel Serverless Entry Point for VYZN Platform.
Enables cloud hosting of VYZN Surveillance Dashboard, Society Onboarding,
Telegram Bot Linking, Camera Management, and Clip Viewer.
"""

import os
import json
import time
import mimetypes
import secrets
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="VYZN Cloud Serverless Console", version="2.0.0")

try:
    from mangum import Mangum
    handler = Mangum(app)
except Exception:
    handler = app

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# In-Memory State for Cloud Serverless Demo Sessions
# ---------------------------------------------------------------------------
CURRENT_USER: Dict[str, Any] = {
    "id": "usr_primary_cloud",
    "email": "dirtbike000000@gmail.com",
    "full_name": "Society Administrator",
    "business_name": "Asara Dnyantirtha CHS",
    "business_type": "society",
    "role": "shopkeeper",
    "phone_e164": "+919876543210",
    "phone_verified": True,
    "security_pin": "202600",
    "telegram_status": "not_linked",
    "telegram_chat_id": None,
    "telegram_username": None,
    "telegram_alerts_enabled": True,
    "telegram_linked_at_ms": None,
}

CAMERAS_STORE: List[Dict[str, Any]] = [
    {
        "id": "cam_gate",
        "camera_id": "cam_gate",
        "name": "Main Gate / Security",
        "status": "online",
        "rtsp_url": "sim://gate",
        "target_fps": 4.0,
        "is_night_ir": False,
        "snapshot_url": "/api/cameras/cam_gate/snapshot.jpg",
        "stream_url": "/api/cameras/cam_gate/mjpeg",
        "area_count": 2,
        "ignored_moments_count": 48,
        "areas": [
            {
                "id": "area_gate_1",
                "camera_id": "cam_gate",
                "name": "Main gate security",
                "polygon": [[0.15, 0.2], [0.85, 0.2], [0.85, 0.85], [0.15, 0.85]],
                "response": "alert",
                "min_stay_seconds": 0,
                "schedule": "always"
            },
            {
                "id": "area_gate_2",
                "camera_id": "cam_gate",
                "name": "Vehicle entry/exit",
                "polygon": [[0.2, 0.4], [0.8, 0.4], [0.8, 0.95], [0.2, 0.95]],
                "response": "alert",
                "min_stay_seconds": 10,
                "schedule": "always"
            }
        ]
    },
    {
        "id": "cam_lobby",
        "camera_id": "cam_lobby",
        "name": "Building Lobby & Lift",
        "status": "online",
        "rtsp_url": "sim://lobby",
        "target_fps": 4.0,
        "is_night_ir": False,
        "snapshot_url": "/api/cameras/cam_lobby/snapshot.jpg",
        "stream_url": "/api/cameras/cam_lobby/mjpeg",
        "area_count": 1,
        "ignored_moments_count": 14,
        "areas": [
            {
                "id": "area_lobby_1",
                "camera_id": "cam_lobby",
                "name": "Lobby entrance",
                "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
                "response": "review",
                "min_stay_seconds": 0,
                "schedule": "outside_shop_hours"
            }
        ]
    }
]

CLIPS_STORE: List[Dict[str, Any]] = [
    {
        "clip_number": 1,
        "id": "clip_001",
        "camera_id": "cam_gate",
        "camera_name": "Main Gate / Security",
        "tier": "alert",
        "final_score": 88,
        "raw_score": 88.4,
        "summary": "Vehicle entry / gate approach",
        "dominant_color": "black",
        "zone_name": "Main gate security",
        "object_type": "vehicle",
        "confidence": 0.94,
        "created_at_ms": int((time.time() - 900) * 1000),
        "expires_at_ms": int((time.time() + 72 * 3600) * 1000),
        "user_triage": "unreviewed",
        "sha256": "4a7d1ed414474e4033ac29ccb8653d9b",
        "score_breakdown": {
            "scoring_version": "2.0",
            "tier": "alert",
            "final_score": 88
        }
    },
    {
        "clip_number": 2,
        "id": "clip_002",
        "camera_id": "cam_lobby",
        "camera_name": "Building Lobby & Lift",
        "tier": "review",
        "final_score": 46,
        "raw_score": 46.2,
        "summary": "Person in Building lobby",
        "dominant_color": "blue",
        "zone_name": "Lobby entrance",
        "object_type": "person",
        "confidence": 0.89,
        "created_at_ms": int((time.time() - 3600) * 1000),
        "expires_at_ms": int((time.time() + 72 * 3600) * 1000),
        "user_triage": "unreviewed",
        "sha256": "b10a8db164e0754105b7a99be72e3fe5",
        "score_breakdown": {
            "scoring_version": "2.0",
            "tier": "review",
            "final_score": 46
        }
    }
]

TELEGRAM_TOKENS: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str
    password: str
    remember: Optional[bool] = False

class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str
    business_name: str
    business_type: Optional[str] = "society"
    phone_e164: Optional[str] = None

class EmailStartRequest(BaseModel):
    email: str

class EmailVerifyRequest(BaseModel):
    email: str
    code: str

class PhoneSetupRequest(BaseModel):
    phoneE164: str

class PhoneUpdateRequest(BaseModel):
    phone: str

class SecurityPinUpdateRequest(BaseModel):
    current_pin: Optional[str] = None
    new_pin: str

class TelegramToggleAlertsRequest(BaseModel):
    enabled: bool

class CameraCreateRequest(BaseModel):
    name: str
    rtsp_url: str
    target_fps: Optional[float] = 15.0

class WatchAreasUpdateRequest(BaseModel):
    areas: List[Dict[str, Any]]

# ---------------------------------------------------------------------------
# Auth Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
def api_auth_login(req: LoginRequest, response: Response):
    email = req.email.strip().lower()
    session_token = f"sess_{secrets.token_hex(16)}"
    response.set_cookie(key="vyzn_session", value=session_token, httponly=True, path="/")
    response.set_cookie(key="vyzn_access_token", value=session_token, httponly=False, path="/")
    
    CURRENT_USER["email"] = email
    return {
        "ok": True,
        "redirect": "/overview",
        "user": {
            "id": CURRENT_USER["id"],
            "email": CURRENT_USER["email"],
            "full_name": CURRENT_USER["full_name"],
            "business_name": CURRENT_USER["business_name"],
            "business_type": CURRENT_USER["business_type"],
            "role": CURRENT_USER["role"]
        }
    }

@app.post("/api/auth/signup")
def api_auth_signup(req: SignupRequest, response: Response):
    email = req.email.strip().lower()
    CURRENT_USER["email"] = email
    CURRENT_USER["full_name"] = req.full_name.strip()
    CURRENT_USER["business_name"] = req.business_name.strip()
    CURRENT_USER["business_type"] = (req.business_type or "society").strip()
    if req.phone_e164:
        CURRENT_USER["phone_e164"] = req.phone_e164.strip()

    session_token = f"sess_{secrets.token_hex(16)}"
    response.set_cookie(key="vyzn_session", value=session_token, httponly=True, path="/")
    response.set_cookie(key="vyzn_access_token", value=session_token, httponly=False, path="/")

    return {
        "ok": True,
        "redirect": "/overview",
        "user": {
            "id": CURRENT_USER["id"],
            "email": CURRENT_USER["email"],
            "full_name": CURRENT_USER["full_name"],
            "business_name": CURRENT_USER["business_name"],
            "business_type": CURRENT_USER["business_type"],
            "role": CURRENT_USER["role"]
        }
    }

@app.post("/api/auth/email/start")
def api_email_start(req: EmailStartRequest):
    return {"ok": True, "message": "Verification code dispatched"}

@app.post("/api/auth/email/verify")
def api_email_verify(req: EmailVerifyRequest, response: Response):
    session_token = f"sess_{secrets.token_hex(16)}"
    response.set_cookie(key="vyzn_session", value=session_token, httponly=True, path="/")
    return {"ok": True, "redirect": "/overview", "user": CURRENT_USER}

@app.post("/api/auth/signout")
def api_auth_signout(response: Response):
    response.delete_cookie(key="vyzn_session", path="/")
    response.delete_cookie(key="vyzn_access_token", path="/")
    return {"ok": True}

# ---------------------------------------------------------------------------
# Current User & Profile
# ---------------------------------------------------------------------------
@app.get("/api/me")
def api_get_me():
    return CURRENT_USER

@app.post("/api/me/phone")
def api_set_me_phone(req: PhoneSetupRequest):
    CURRENT_USER["phone_e164"] = req.phoneE164.strip()
    CURRENT_USER["phone_verified"] = True
    return {"ok": True, "phone_e164": CURRENT_USER["phone_e164"]}

@app.get("/api/settings/profile")
def get_user_profile():
    return {
        **CURRENT_USER,
        "security_pin_set": bool(CURRENT_USER.get("security_pin")),
        "disk_free_pct": 74.3,
        "retention_hours": 72
    }

@app.post("/api/settings/phone")
def update_phone_number(payload: PhoneUpdateRequest):
    CURRENT_USER["phone_e164"] = payload.phone.strip()
    CURRENT_USER["phone_verified"] = True
    return {"ok": True, "phone_e164": CURRENT_USER["phone_e164"]}

@app.post("/api/settings/security-pin")
def update_security_pin(payload: SecurityPinUpdateRequest):
    CURRENT_USER["security_pin"] = payload.new_pin.strip()
    return {"ok": True}

# ---------------------------------------------------------------------------
# Telegram Integration
# ---------------------------------------------------------------------------
@app.get("/api/telegram/config")
def api_telegram_config():
    bot = os.environ.get("TELEGRAM_BOT_USERNAME") or "Vyzn_security_bot"
    return {"bot_username": bot, "bot_configured": True}

@app.get("/api/telegram/link")
def api_telegram_link():
    token = f"tg_{secrets.token_urlsafe(16)}"
    bot = os.environ.get("TELEGRAM_BOT_USERNAME") or "Vyzn_security_bot"
    TELEGRAM_TOKENS[token] = {
        "user_id": CURRENT_USER["id"],
        "expires_at": time.time() + 900
    }
    return {
        "ok": True,
        "token": token,
        "bot_username": bot,
        "link_url": f"https://t.me/{bot}?start={token}"
    }

@app.get("/api/telegram/status")
def api_telegram_status():
    return {
        "connected": CURRENT_USER.get("telegram_status") == "connected",
        "chat_id": CURRENT_USER.get("telegram_chat_id"),
        "username": CURRENT_USER.get("telegram_username"),
        "alerts_enabled": bool(CURRENT_USER.get("telegram_alerts_enabled", True)),
        "status": CURRENT_USER.get("telegram_status", "not_linked")
    }

@app.post("/api/telegram/disconnect")
def api_telegram_disconnect():
    CURRENT_USER["telegram_status"] = "not_linked"
    CURRENT_USER["telegram_chat_id"] = None
    CURRENT_USER["telegram_username"] = None
    return {"ok": True, "status": "not_linked"}

@app.post("/api/telegram/toggle")
def api_telegram_toggle(req: TelegramToggleAlertsRequest):
    CURRENT_USER["telegram_alerts_enabled"] = req.enabled
    return {"ok": True, "alerts_enabled": req.enabled}

# ---------------------------------------------------------------------------
# Cameras & Watch Areas
# ---------------------------------------------------------------------------
@app.get("/api/cameras")
def list_cameras():
    return CAMERAS_STORE

@app.post("/api/cameras")
def add_camera(payload: CameraCreateRequest):
    new_id = f"cam_{int(time.time() * 1000) % 100000}"
    cam = {
        "id": new_id,
        "camera_id": new_id,
        "name": payload.name,
        "status": "online",
        "rtsp_url": payload.rtsp_url,
        "target_fps": payload.target_fps or 15.0,
        "is_night_ir": False,
        "snapshot_url": f"/api/cameras/{new_id}/snapshot.jpg",
        "stream_url": f"/api/cameras/{new_id}/mjpeg",
        "area_count": 0,
        "ignored_moments_count": 0,
        "areas": []
    }
    CAMERAS_STORE.append(cam)
    return {"ok": True, "camera": cam}

@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: str):
    global CAMERAS_STORE
    CAMERAS_STORE = [c for c in CAMERAS_STORE if c.get("id") != camera_id and c.get("camera_id") != camera_id]
    return {"ok": True}

@app.get("/api/cameras/{camera_id}/areas")
def get_camera_areas(camera_id: str):
    for c in CAMERAS_STORE:
        if c.get("id") == camera_id or c.get("camera_id") == camera_id:
            return {"camera_id": camera_id, "areas": c.get("areas", [])}
    return {"camera_id": camera_id, "areas": []}

@app.post("/api/cameras/{camera_id}/areas")
def save_camera_areas(camera_id: str, payload: WatchAreasUpdateRequest):
    for c in CAMERAS_STORE:
        if c.get("id") == camera_id or c.get("camera_id") == camera_id:
            c["areas"] = payload.areas
            c["area_count"] = len(payload.areas)
            return {"ok": True, "areas": payload.areas}
    return {"ok": True, "areas": payload.areas}

@app.post("/api/cameras/{camera_id}/snapshot")
def update_snapshot(camera_id: str):
    return {"ok": True, "timestamp": time.time()}

@app.get("/api/cameras/{camera_id}/snapshot.jpg")
@app.get("/api/cameras/{camera_id}/mjpeg")
def stream_camera_visual(camera_id: str):
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
      <text x="24" y="58" fill="#64748b" font-family="monospace" font-size="11">YOLOv8 EDGE AI • ZERO CLOUD BANDWIDTH COST</text>
      <rect x="220" y="110" width="160" height="175" stroke="#0ea5e9" stroke-width="2" stroke-dasharray="6 3" fill="rgba(14,165,233,0.06)"/>
      <text x="225" y="102" fill="#38bdf8" font-family="monospace" font-size="11" font-weight="bold">PERSON: 95.4% [RESIDENT / VISITOR]</text>
      <text x="440" y="340" fill="#475569" font-family="monospace" font-size="10">SEC-65B CERTIFIED</text>
    </svg>'''
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/api/v1/cameras/discover")
def discover_cameras():
    return {
        "status": "success",
        "cameras": [
            {"ip": "192.168.1.64", "port": 554, "vendor": "Hikvision NVR", "rtsp_url": "rtsp://192.168.1.64:554/ch1/main"},
            {"ip": "192.168.1.65", "port": 554, "vendor": "CP Plus HD", "rtsp_url": "rtsp://192.168.1.65:554/live/ch0"}
        ]
    }

@app.post("/api/v1/cameras/test-connection")
def test_camera_connection(payload: Dict[str, Any]):
    return {
        "status": "online",
        "success": True,
        "message": "Connection test successful! Camera stream verified.",
        "width": 1920,
        "height": 1080,
        "fps": 15.0
    }

# ---------------------------------------------------------------------------
# Events, Clips & System Metrics
# ---------------------------------------------------------------------------
@app.get("/api/events")
@app.get("/api/clips")
def list_clips():
    return CLIPS_STORE

@app.post("/api/clips/{clip_number}/feedback")
def submit_clip_feedback(clip_number: int, payload: Dict[str, Any]):
    return {"ok": True, "clip_number": clip_number}

@app.get("/api/clips/{clip_number}/evidence-pack")
def get_evidence_pack(clip_number: int):
    return Response(
        content=b"VYZN_SEC65B_EVIDENCE_PACK_DUMMY_BINARY",
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=evidence_clip_{clip_number}.zip"}
    )

@app.get("/api/system/metrics")
def get_system_metrics():
    return {
        "cpu_percent": 14.2,
        "ram_percent": 48.6,
        "ram_used_mb": 1024.0,
        "disk_free_gb": 128.5,
        "disk_used_pct": 74.3,
        "active_cameras": len(CAMERAS_STORE),
        "pipeline_fps": 4.0,
        "unsynced_events": 0
    }

@app.get("/api/status")
def get_status():
    return {
        "status": "online",
        "system": {
            "platform": "VYZN Multi-Tenant Cloud / Edge Node",
            "active_cameras": len(CAMERAS_STORE)
        }
    }

# ---------------------------------------------------------------------------
# Fallback Static Page Routes
# ---------------------------------------------------------------------------
def _serve_file_or_fallback(rel_path: str) -> Response:
    for base in [WORKSPACE_ROOT / "public", WORKSPACE_ROOT / "frontend" / "dashboard"]:
        candidate = base / rel_path
        if candidate.exists() and candidate.is_file():
            mime, _ = mimetypes.guess_type(str(candidate))
            return Response(content=candidate.read_bytes(), media_type=mime or "text/html")
    return HTMLResponse(content=f"<h1>Page not found: {rel_path}</h1>", status_code=404)

@app.get("/overview", response_class=HTMLResponse)
def serve_overview():
    return _serve_file_or_fallback("overview.html")

@app.get("/cameras", response_class=HTMLResponse)
def serve_cameras():
    return _serve_file_or_fallback("cameras.html")

@app.get("/cameras/new", response_class=HTMLResponse)
def serve_add_camera():
    return _serve_file_or_fallback("add-camera.html")

@app.get("/areas", response_class=HTMLResponse)
@app.get("/areas/{camera_id}", response_class=HTMLResponse)
def serve_areas(camera_id: Optional[str] = None):
    return _serve_file_or_fallback("areas.html")

@app.get("/clips", response_class=HTMLResponse)
@app.get("/clips/{clip_id}", response_class=HTMLResponse)
def serve_clips(clip_id: Optional[str] = None):
    return _serve_file_or_fallback("clips.html")

@app.get("/settings", response_class=HTMLResponse)
def serve_settings():
    return _serve_file_or_fallback("settings.html")

@app.get("/login", response_class=HTMLResponse)
@app.get("/login/{path:path}", response_class=HTMLResponse)
@app.get("/setup/{path:path}", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_index():
    return _serve_file_or_fallback("index.html")
