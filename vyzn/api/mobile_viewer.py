"""
VYZN Mobile Clip Viewer — Standalone Tokenized Web Destination.
Serves a lightweight, zero-login mobile HTML5 playback and triage interface
accessible directly via pre-approved WhatsApp Utility Template CTA links.
"""

from __future__ import annotations
import hmac
import hashlib
import time
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("vyzn.api.mobile_viewer")

mobile_viewer_router = APIRouter()

DEFAULT_VIEWER_SECRET = "vyzn_viewer_hmac_secret_2026_production"


def generate_viewer_token(event_group_id: str, exp_epoch: int, secret: str = DEFAULT_VIEWER_SECRET) -> str:
    """Generates an HMAC-SHA256 cryptographic signature for time-limited clip access."""
    message = f"{event_group_id}:{exp_epoch}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_viewer_token(event_group_id: str, token: str, exp_epoch: int, secret: str = DEFAULT_VIEWER_SECRET) -> bool:
    """Validates signature authenticity and checks whether token has expired."""
    current_time = int(time.time())
    if current_time > exp_epoch:
        logger.warning(f"Expired clip viewer token for {event_group_id} (expired at {exp_epoch}, current {current_time})")
        return False

    expected = generate_viewer_token(event_group_id, exp_epoch, secret)
    return hmac.compare_digest(token, expected)


def build_viewer_url(
    event_group_id: str,
    base_url: str = "http://localhost:8000",
    valid_hours: int = 48,
    secret: str = DEFAULT_VIEWER_SECRET
) -> str:
    """Constructs a complete signed mobile clip viewer URL for inclusion in alerts."""
    exp_epoch = int(time.time()) + (valid_hours * 3600)
    token = generate_viewer_token(event_group_id, exp_epoch, secret)
    return f"{base_url.rstrip('/')}/v/{event_group_id}?token={token}&exp={exp_epoch}"


@mobile_viewer_router.get("/v/{event_group_id}", response_class=HTMLResponse)
def get_mobile_clip_viewer(
    event_group_id: str,
    token: str = Query(..., description="Cryptographic HMAC-SHA256 signature"),
    exp: int = Query(..., description="Expiration epoch timestamp")
):
    """
    Renders standalone mobile clip viewer for WhatsApp recipients.
    Does not require app installation, passwords, or complex authentication.
    """
    if not verify_viewer_token(event_group_id, token, exp):
        return HTMLResponse(
            content="""<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Access Expired — VYZN</title>
                <style>
                    body { background: #0b0f19; color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; padding: 20px; text-align: center; }
                    .card { background: #161e2e; border: 1px solid #283548; padding: 32px 24px; border-radius: 16px; max-width: 380px; width: 100%; }
                    .icon { font-size: 48px; margin-bottom: 16px; }
                    h2 { margin: 0 0 12px; font-size: 20px; color: #ef4444; }
                    p { color: #94a3b8; font-size: 14px; line-height: 1.5; margin-bottom: 24px; }
                    a { color: #38bdf8; text-decoration: none; font-weight: 600; font-size: 14px; }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="icon">🔒</div>
                    <h2>Link Expired or Invalid</h2>
                    <p>For your security, direct incident replay links expire after 48 hours. Please open the VYZN Cockpit or contact your security installer.</p>
                </div>
            </body>
            </html>""",
            status_code=403
        )

    # Fetch event metadata from local SQLite database
    from vyzn.api.routes import get_db
    db = get_db()
    conn = db._get_read_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM events WHERE event_group_id = ?", (event_group_id,))
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        camera_id = "Security Camera"
        score = 85
        object_type = "PERSON"
        confidence = 0.90
        start_time = "Recent Incident"
        zone_name = "Perimeter"
        user_triage = "unreviewed"
        starred = 0
    else:
        d = dict(row)
        camera_id = d.get("camera_id", "Camera")
        score = d.get("score", 75)
        object_type = (d.get("object_type") or "unclassified").upper()
        confidence = float(d.get("confidence") or 0.85)
        start_time = d.get("start_time", "Recent")
        zone_name = d.get("zone_name", "general")
        user_triage = d.get("user_triage", "unreviewed")
        starred = int(d.get("starred") or 0)

    # Determine severity styling
    if score >= 85:
        tier_label = "CRITICAL THREAT"
        tier_color = "#ef4444"
        badge_bg = "rgba(239, 68, 68, 0.15)"
    elif score >= 66:
        tier_label = "SUSPICIOUS"
        tier_color = "#f59e0b"
        badge_bg = "rgba(245, 158, 11, 0.15)"
    elif score >= 36:
        tier_label = "ELEVATED"
        tier_color = "#38bdf8"
        badge_bg = "rgba(56, 189, 248, 0.15)"
    else:
        tier_label = "NORMAL"
        tier_color = "#94a3b8"
        badge_bg = "rgba(148, 163, 184, 0.15)"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>VYZN Alert — {camera_id}</title>
    <style>
        :root {{
            --bg-base: #0a0d14;
            --bg-card: #121824;
            --border: #20293a;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-red: #ef4444;
            --accent-amber: #f59e0b;
            --accent-green: #10b981;
            --accent-blue: #38bdf8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{
            background: var(--bg-base);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 12px;
        }}
        .container {{
            max-width: 480px;
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 4px;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 800;
            font-size: 16px;
            letter-spacing: 0.5px;
        }}
        .brand-pill {{
            background: linear-gradient(135deg, #2563eb, #7c3aed);
            color: white;
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 6px;
            font-weight: 700;
        }}
        .video-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
        }}
        .video-wrap {{
            position: relative;
            width: 100%;
            background: #000;
            aspect-ratio: 16 / 9;
        }}
        video {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }}
        .meta-bar {{
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .meta-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .cam-title {{
            font-size: 15px;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .tier-badge {{
            font-size: 11px;
            font-weight: 800;
            color: {tier_color};
            background: {badge_bg};
            border: 1px solid {tier_color}44;
            padding: 4px 10px;
            border-radius: 9999px;
            letter-spacing: 0.5px;
        }}
        .specs-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            background: rgba(255, 255, 255, 0.03);
            padding: 10px 12px;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .spec-item {{
            display: flex;
            flex-direction: column;
            gap: 2px;
        }}
        .spec-label {{
            font-size: 10px;
            text-transform: uppercase;
            color: var(--text-muted);
            letter-spacing: 0.5px;
        }}
        .spec-value {{
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
        }}
        .action-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .action-prompt {{
            font-size: 13px;
            color: var(--text-muted);
            text-align: center;
            font-weight: 500;
        }}
        .btn-row {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }}
        .triage-btn {{
            padding: 14px 12px;
            border-radius: 12px;
            border: 1px solid transparent;
            font-size: 14px;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .btn-star {{
            background: #f59e0b22;
            color: #fbbf24;
            border-color: #f59e0b55;
        }}
        .btn-star:active {{
            background: #f59e0b44;
            transform: scale(0.98);
        }}
        .btn-false {{
            background: #ef444422;
            color: #f87171;
            border-color: #ef444455;
        }}
        .btn-false:active {{
            background: #ef444444;
            transform: scale(0.98);
        }}
        .btn-call {{
            grid-column: span 2;
            background: #10b98122;
            color: #34d399;
            border-color: #10b98155;
            text-decoration: none;
            text-align: center;
        }}
        .status-pill {{
            padding: 10px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            text-align: center;
            display: none;
        }}
        .toast {{
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%);
            background: #1e293b;
            color: #f8fafc;
            border: 1px solid #334155;
            padding: 10px 18px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            display: none;
            box-shadow: 0 10px 20px rgba(0,0,0,0.4);
            z-index: 100;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="brand">
                <span>🛡️ VYZN NETRA</span>
                <span class="brand-pill">LIVE ALERT</span>
            </div>
            <span style="font-size: 12px; color: var(--text-muted); font-weight: 500;">{start_time.split("T")[-1][:8] if "T" in start_time else start_time}</span>
        </div>

        <div class="video-card">
            <div class="video-wrap">
                <video id="incident-video" controls autoplay playsinline preload="auto" poster="/api/events/{event_group_id}/thumb">
                    <source src="/api/events/{event_group_id}/clip" type="video/mp4">
                    Your browser does not support HTML5 video streaming.
                </video>
            </div>
            <div class="meta-bar">
                <div class="meta-top">
                    <div class="cam-title">📹 {camera_id}</div>
                    <div class="tier-badge">{tier_label} ({score}/100)</div>
                </div>
                <div class="specs-grid">
                    <div class="spec-item">
                        <span class="spec-label">Target</span>
                        <span class="spec-value">{object_type}</span>
                    </div>
                    <div class="spec-item">
                        <span class="spec-label">Confidence</span>
                        <span class="spec-value">{int(confidence * 100)}%</span>
                    </div>
                    <div class="spec-item">
                        <span class="spec-label">Zone</span>
                        <span class="spec-value">{zone_name}</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="action-card" id="action-container">
            <div class="action-prompt">One-Tap Incident Triage</div>
            <div id="triage-status-pill" class="status-pill"></div>
            <div class="btn-row" id="triage-buttons">
                <button class="triage-btn btn-star" onclick="submitTriage('star')">
                    ⭐ Star Clip
                </button>
                <button class="triage-btn btn-false" onclick="submitTriage('false_positive')">
                    ❌ False Alarm
                </button>
                <a class="triage-btn btn-call" href="tel:+919876543210">
                    📞 Call Security / Installer
                </a>
            </div>
        </div>
    </div>

    <div id="toast" class="toast"></div>

    <script>
        const eventId = "{event_group_id}";
        const authToken = "{token}";
        const authExp = {exp};
        let currentTriage = "{user_triage}";
        let isStarred = {starred};

        function showToast(msg) {{
            const t = document.getElementById("toast");
            t.textContent = msg;
            t.style.display = "block";
            setTimeout(() => t.style.display = "none", 3000);
        }}

        function updateUIState(action) {{
            const pill = document.getElementById("triage-status-pill");
            pill.style.display = "block";
            if (action === "star" || action === "confirmed_threat") {{
                pill.style.background = "rgba(245, 158, 11, 0.15)";
                pill.style.color = "#fbbf24";
                pill.style.border = "1px solid #f59e0b44";
                pill.textContent = "⭐ Preserved in Starred Evidentiary Vault";
            }} else if (action === "false_positive") {{
                pill.style.background = "rgba(239, 68, 68, 0.15)";
                pill.style.color = "#f87171";
                pill.style.border = "1px solid #ef444444";
                pill.textContent = "❌ Triaged as False Alarm (Calibrator updated)";
            }}
        }}

        if (currentTriage !== "unreviewed" || isStarred) {{
            updateUIState(isStarred ? "star" : currentTriage);
        }}

        async function submitTriage(action) {{
            try {{
                const res = await fetch(`/v/${{eventId}}/triage?action=${{action}}&token=${{authToken}}&exp=${{authExp}}`, {{
                    method: "POST"
                }});
                const data = await res.json();
                if (res.ok) {{
                    updateUIState(action);
                    showToast(action === "star" ? "⭐ Clip starred and preserved!" : "❌ False alarm recorded");
                }} else {{
                    showToast("Error: " + (data.detail || "Unable to save triage"));
                }}
            }} catch (err) {{
                showToast("Network error: " + err.message);
            }}
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@mobile_viewer_router.post("/v/{event_group_id}/triage")
def submit_mobile_triage(
    event_group_id: str,
    action: str = Query(..., description="'star' or 'false_positive'"),
    token: str = Query(..., description="HMAC-SHA256 signature"),
    exp: int = Query(..., description="Expiration epoch timestamp")
):
    """Permits tokenized 1-tap mobile triage directly from WhatsApp mobile viewer."""
    if not verify_viewer_token(event_group_id, token, exp):
        raise HTTPException(status_code=403, detail="Viewer token invalid or expired.")

    if action not in ["star", "false_positive", "confirmed_threat"]:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'star' or 'false_positive'.")

    from vyzn.api.routes import get_db, _pipeline_instance
    db = get_db()

    user_triage = "confirmed_threat" if action in ["star", "confirmed_threat"] else "false_positive"
    is_starred = 1 if action == "star" else 0

    db.update_event_triage(event_group_id, user_triage)
    if is_starred:
        db.toggle_event_star(event_group_id, 1)

    db.log_audit("MOBILE_TRIAGE", event_group_id, f"action={action}, via=whatsapp_mobile_viewer")

    # Feed false alarms back into active camera calibrator
    if user_triage == "false_positive" and _pipeline_instance:
        conn = db._get_read_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT camera_id, object_type, confidence, score, start_time FROM events WHERE event_group_id = ?", (event_group_id,))
            row = cur.fetchone()
            if row and hasattr(_pipeline_instance, "calibrator"):
                d = dict(row)
                from vyzn.core.events import DetectionCandidate
                cand = DetectionCandidate(
                    camera_id=d["camera_id"],
                    object_type=d["object_type"],
                    confidence=float(d["confidence"]),
                    motion_ratio=0.05
                )
                _pipeline_instance.calibrator.record_triage_feedback(
                    camera_id=d["camera_id"],
                    candidate=cand,
                    is_false_alarm=True,
                    human_label=d["object_type"]
                )
        except Exception as e:
            logger.warning(f"Failed to feed false alarm into calibrator: {e}")
        finally:
            conn.close()

    return {
        "status": "success",
        "action": action,
        "event_group_id": event_group_id,
        "user_triage": user_triage,
        "starred": is_starred
    }
