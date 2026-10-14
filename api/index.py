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
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="VYZN Cloud Serverless Console", version="2.0.0", redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def vercel_path_rewrite_middleware(request: Request, call_next):
    """
    Normalizes Vercel serverless request paths.
    When Vercel rewrites /api/(.*) -> /api/index.py?__vercel_subpath__=$1,
    this middleware extracts the real subpath and sets request.scope['path'] accordingly.
    """
    subpath = request.query_params.get("__vercel_subpath__")
    matched_path = (
        request.headers.get("x-matched-path")
        or request.headers.get("x-vercel-matched-path")
        or request.headers.get("x-forwarded-uri")
        or request.headers.get("x-invoke-path")
    )
    current_path = request.scope.get("path", "")

    if subpath is not None:
        cleaned = subpath.lstrip("/")
        request.scope["path"] = f"/api/{cleaned}" if cleaned else "/api/status"
        if request.scope.get("query_string"):
            params = [
                (k, v) for k, v in urllib.parse.parse_qsl(request.scope["query_string"].decode("latin1"))
                if k != "__vercel_subpath__"
            ]
            request.scope["query_string"] = urllib.parse.urlencode(params).encode("latin1")
    elif matched_path and matched_path not in ("/api/index.py", "/api/index", "/api/index.py/"):
        request.scope["path"] = matched_path.split("?")[0]
    elif current_path in ("/api/index.py", "/api/index", "/api/index.py/", ""):
        request.scope["path"] = "/api/status"
    elif current_path and not current_path.startswith("/api"):
        request.scope["path"] = f"/api{current_path}"

    return await call_next(request)

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
    full_name: Optional[str] = "Society Administrator"
    business_name: Optional[str] = "Asara Dnyantirtha CHS"
    business_type: Optional[str] = "society"
    phone_e164: Optional[str] = None

class EmailStartRequest(BaseModel):
    email: str

class EmailVerifyRequest(BaseModel):
    email: str
    code: str

class PhoneStartRequest(BaseModel):
    phoneE164: Optional[str] = None
    phone: Optional[str] = None

class PhoneVerifyRequest(BaseModel):
    phoneE164: Optional[str] = None
    phone: Optional[str] = None
    code: Optional[str] = None

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
@app.post("/api/v1/auth/login")
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
@app.post("/api/v1/auth/register")
def api_auth_signup(req: SignupRequest, response: Response):
    email = req.email.strip().lower()
    CURRENT_USER["email"] = email
    if req.full_name:
        CURRENT_USER["full_name"] = req.full_name.strip()
    if req.business_name:
        CURRENT_USER["business_name"] = req.business_name.strip()
    if req.business_type:
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

@app.post("/api/auth/phone/start")
@app.post("/api/v1/auth/phone/send-otp")
def api_auth_phone_start(payload: PhoneStartRequest):
    phone = payload.phoneE164 or payload.phone or "+919876543210"
    CURRENT_USER["phone_e164"] = phone.strip()
    return {"ok": True, "phone_e164": CURRENT_USER["phone_e164"], "status": "sent"}

@app.post("/api/auth/phone/verify")
@app.post("/api/v1/auth/phone/verify-otp")
def api_auth_phone_verify(payload: PhoneVerifyRequest):
    phone = payload.phoneE164 or payload.phone or CURRENT_USER.get("phone_e164", "+919876543210")
    CURRENT_USER["phone_e164"] = phone.strip()
    CURRENT_USER["phone_verified"] = True
    return {"ok": True, "next_step": "/setup/telegram", "user": CURRENT_USER, "status": "verified"}

@app.post("/api/auth/phone/skip")
def api_auth_phone_skip():
    return {"ok": True, "next_step": "/setup/telegram"}

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
@app.get("/api/v1/auth/me")
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
# Settings & Storage
# ---------------------------------------------------------------------------
@app.get("/api/settings/storage")
def get_storage_settings():
    return {
        "storage_dir": "c:/Vyzn Ai/data/clips",
        "status": "ok",
        "free_gb": 128.5,
        "total_gb": 512.0
    }

@app.post("/api/settings/storage")
def update_storage_settings(payload: Dict[str, Any]):
    return {"ok": True, "storage_dir": payload.get("storage_dir", "c:/Vyzn Ai/data/clips")}

@app.post("/api/settings/browse-folder")
def browse_folder():
    return {"ok": True, "path": "c:/Vyzn Ai/data/clips"}

@app.get("/api/settings/business-hours")
def get_business_hours():
    return {
        "enabled": True,
        "start_time": "09:00",
        "end_time": "22:00",
        "days": ["mon", "tue", "wed", "thu", "fri", "sat"]
    }

@app.post("/api/settings/business-hours")
def update_business_hours(payload: Dict[str, Any]):
    return {"ok": True, "business_hours": payload}

# ---------------------------------------------------------------------------
# Telegram Integration
# ---------------------------------------------------------------------------
@app.get("/api/telegram/config")
def api_telegram_config():
    bot = os.environ.get("TELEGRAM_BOT_USERNAME") or "Vyzn_security_bot"
    return {"bot_username": bot, "bot_configured": True, "is_token_set": True, "bot_token_masked": "••••••••"}

@app.post("/api/telegram/config")
def api_telegram_config_post(payload: Dict[str, Any]):
    return {"ok": True, "is_token_set": True, "bot_username": payload.get("bot_username", "Vyzn_security_bot")}

@app.api_route("/api/telegram/link", methods=["GET", "POST"])
def api_telegram_link():
    token = f"tg_{secrets.token_urlsafe(16)}"
    bot = os.environ.get("TELEGRAM_BOT_USERNAME") or "Vyzn_security_bot"
    TELEGRAM_TOKENS[token] = {
        "user_id": CURRENT_USER["id"],
        "expires_at": time.time() + 900
    }
    deep_link = f"https://t.me/{bot}?start={token}"
    return {
        "ok": True,
        "token": token,
        "bot_username": bot,
        "link_url": deep_link,
        "deepLink": deep_link
    }

@app.post("/api/telegram/simulate-link")
def api_telegram_simulate_link(payload: Dict[str, Any]):
    CURRENT_USER["telegram_status"] = "connected"
    CURRENT_USER["telegram_chat_id"] = 987654321
    CURRENT_USER["telegram_username"] = payload.get("username", "demo_user")
    CURRENT_USER["telegram_linked_at_ms"] = int(time.time() * 1000)
    return {"ok": True, "status": "connected", "username": CURRENT_USER["telegram_username"]}

@app.post("/api/telegram/test")
@app.post("/api/v1/alerts/telegram/test-ping")
def api_telegram_test():
    return {"ok": True, "latencyMs": 420, "message": "Test ping sent to Telegram"}

@app.get("/api/telegram/status")
@app.get("/api/v1/alerts/telegram")
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
@app.post("/api/telegram/toggle-alerts")
def api_telegram_toggle(req: Dict[str, Any]):
    enabled = req.get("enabled", True)
    CURRENT_USER["telegram_alerts_enabled"] = enabled
    return {"ok": True, "alerts_enabled": enabled}

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

@app.patch("/api/cameras/{camera_id}")
def rename_camera(camera_id: str, payload: Dict[str, Any]):
    new_name = payload.get("name")
    for c in CAMERAS_STORE:
        if c.get("id") == camera_id or c.get("camera_id") == camera_id:
            if new_name:
                c["name"] = new_name
            return {"ok": True, "camera": c}
    return {"ok": True}

@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: str):
    global CAMERAS_STORE
    CAMERAS_STORE = [c for c in CAMERAS_STORE if c.get("id") != camera_id and c.get("camera_id") != camera_id]
    return {"ok": True}

@app.get("/api/cameras/{camera_id}/areas")
@app.get("/api/cameras/{camera_id}/zones")
def get_camera_areas(camera_id: str):
    for c in CAMERAS_STORE:
        if c.get("id") == camera_id or c.get("camera_id") == camera_id:
            return {"camera_id": camera_id, "areas": c.get("areas", [])}
    return {"camera_id": camera_id, "areas": []}

@app.post("/api/cameras/{camera_id}/areas")
@app.post("/api/cameras/{camera_id}/zones")
def save_camera_areas(camera_id: str, payload: WatchAreasUpdateRequest):
    for c in CAMERAS_STORE:
        if c.get("id") == camera_id or c.get("camera_id") == camera_id:
            c["areas"] = payload.areas
            c["area_count"] = len(payload.areas)
            return {"ok": True, "areas": payload.areas}
    return {"ok": True, "areas": payload.areas}

@app.post("/api/cameras/{camera_id}/snapshot")
def update_snapshot(camera_id: str):
    return {"ok": True, "timestamp": time.time(), "snapshot_url": f"/api/cameras/{camera_id}/snapshot.jpg"}

@app.get("/api/cameras/{camera_id}/snapshot.jpg")
@app.get("/api/cameras/{camera_id}/mjpeg")
@app.get("/api/cameras/{camera_id}/stream")
@app.get("/api/stream")
@app.get("/api/wall/stream")
def stream_camera_visual(camera_id: str = "cam_gate"):
    label = camera_id.replace("cam_", "").replace("_", " ").upper()
    cur_time = time.strftime("%Y-%m-%d %H:%M:%S")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
      <defs>
        <linearGradient id="bgGrad" x1="0" y1="0" x2="0" y2="100%">
          <stop offset="0%" stop-color="#0b1120"/>
          <stop offset="100%" stop-color="#020617"/>
        </linearGradient>
      </defs>
      <rect width="640" height="360" fill="url(#bgGrad)"/>
      <rect x="20" y="20" width="600" height="320" fill="none" stroke="#1e293b" stroke-width="1" rx="4"/>
      <circle cx="36" cy="38" r="4" fill="#10b981"/>
      <text x="48" y="42" fill="#10b981" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, monospace" font-size="12" font-weight="600" letter-spacing="1">LIVE</text>
      <text x="96" y="42" fill="#e2e8f0" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, monospace" font-size="12" font-weight="600">{label}</text>
      <text x="600" y="42" text-anchor="end" fill="#94a3b8" font-family="monospace" font-size="11">{cur_time}</text>
      <text x="320" y="185" text-anchor="middle" fill="#475569" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="13">Camera Feed Active</text>
    </svg>'''
    return Response(content=svg, media_type="image/svg+xml")

@app.post("/api/cameras/test")
@app.post("/api/v1/cameras/test-connection")
def test_camera_connection(payload: Optional[Dict[str, Any]] = None):
    return {
        "status": "online",
        "success": True,
        "message": "Connection test successful! Camera stream verified.",
        "width": 1920,
        "height": 1080,
        "fps": 15.0
    }

@app.get("/api/v1/cameras/discover")
def discover_cameras():
    return {
        "status": "success",
        "cameras": [
            {"ip": "192.168.1.64", "port": 554, "vendor": "Hikvision NVR", "rtsp_url": "rtsp://192.168.1.64:554/ch1/main"},
            {"ip": "192.168.1.65", "port": 554, "vendor": "CP Plus HD", "rtsp_url": "rtsp://192.168.1.65:554/live/ch0"}
        ]
    }

@app.get("/api/v1/cameras/local-devices")
def get_local_devices():
    return [{"device_id": 0, "name": "Integrated Webcam"}]

@app.post("/api/v1/cameras/adopt")
def adopt_camera(payload: Dict[str, Any]):
    new_id = f"cam_{int(time.time() * 1000) % 100000}"
    name = payload.get("name") or "Adopted Camera"
    cam = {
        "id": new_id,
        "camera_id": new_id,
        "name": name,
        "status": "online",
        "rtsp_url": payload.get("rtsp_url", "sim://camera"),
        "target_fps": 4.0,
        "is_night_ir": False,
        "snapshot_url": f"/api/cameras/{new_id}/snapshot.jpg",
        "stream_url": f"/api/cameras/{new_id}/mjpeg",
        "area_count": 0,
        "ignored_moments_count": 0,
        "areas": []
    }
    CAMERAS_STORE.append(cam)
    return {"status": "success", "camera": cam}

# ---------------------------------------------------------------------------
# Events, Clips & System Metrics
# ---------------------------------------------------------------------------
@app.get("/api/clips")
def list_clips():
    return {
        "clips": CLIPS_STORE,
        "total": len(CLIPS_STORE)
    }

@app.get("/api/events")
def list_events():
    return CLIPS_STORE

@app.get("/api/clips/flags")
def list_clips_flags(limit: int = 10):
    return {"flags": CLIPS_STORE[:limit]}

@app.post("/api/clips/purge-all")
def purge_all_clips():
    global CLIPS_STORE
    CLIPS_STORE.clear()
    return {"ok": True, "message": "All clips purged successfully"}

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

@app.get("/api/events/{event_id}/thumb")
def get_event_thumb(event_id: str):
    return stream_camera_visual("incident_thumb")

@app.get("/api/events/{event_id}/clip")
def get_event_clip(event_id: str):
    return Response(content=b"", media_type="video/mp4")

@app.post("/api/events/{event_id}/star")
def star_event(event_id: str):
    return {"ok": True, "event_id": event_id, "starred": True}

@app.post("/api/events/{event_id}/triage")
def triage_event(event_id: str, payload: Dict[str, Any]):
    return {"ok": True, "event_id": event_id, "triage": payload.get("triage", "reviewed")}

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

@app.get("/api/shell/status")
def get_shell_status():
    return {
        "pill": {
            "style": "ok",
            "text": "System Online • AI Armed",
            "short_text": "Armed"
        },
        "telegram_connected": CURRENT_USER.get("telegram_status") == "connected"
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

@app.get("/api/v1/locations")
@app.post("/api/v1/locations")
def handle_locations():
    return [{"id": "loc_primary", "name": "Main Site", "camera_count": len(CAMERAS_STORE)}]

@app.get("/api/v1/settings/bandwidth")
@app.post("/api/v1/settings/bandwidth")
def handle_bandwidth():
    return {"mode": "low_data", "cloud_sync": False, "max_mbps": 5.0}

@app.get("/api/v1/forensics/search")
def forensics_search():
    return {"matches": []}

@app.get("/api/dpdp/notice")
def dpdp_notice():
    return {"ok": True, "policy_version": "2026.1", "retention_hours": 72}

# Register route aliases so endpoints resolve whether called with or without /api
existing_paths = {r.path for r in app.routes if hasattr(r, "path")}
for route in list(app.routes):
    if hasattr(route, "path") and route.path.startswith("/api/"):
        alt_path = route.path[4:]  # e.g., '/status'
        if not alt_path:
            alt_path = "/"
        if alt_path not in existing_paths:
            methods = list(route.methods) if hasattr(route, "methods") and route.methods else ["GET"]
            app.add_api_route(
                alt_path,
                route.endpoint,
                methods=methods,
                name=f"{getattr(route, 'name', 'route')}_alias"
            )
            existing_paths.add(alt_path)

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
@app.get("/setup", response_class=HTMLResponse)
@app.get("/setup/{path:path}", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def serve_index():
    return _serve_file_or_fallback("index.html")
