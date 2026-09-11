"""
Cloud Webhook Receiver and Fleet Management FastAPI service.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response, Query
from pydantic import BaseModel

from vyzn_cloud.watchdog import DeadManWatchdog
from vyzn_cloud.fleet_routes import fleet_router, set_watchdog, MANAGED_CONFIGS
from vyzn_cloud.cloud_ingest import cloud_ingest_router

logger = logging.getLogger("vyzn_cloud.app")

cloud_app = FastAPI(
    title="VYZN Netra Cloud Fleet Manager",
    description="Receives remote telemetry heartbeats, monitors uptime, and handles WhatsApp triage webhooks",
    version="1.0.0"
)

watchdog = DeadManWatchdog(silence_threshold_sec=180.0)
set_watchdog(watchdog)
cloud_app.include_router(fleet_router)
cloud_app.include_router(cloud_ingest_router)

# In-memory store for WhatsApp triage actions received
triage_log: list[Dict[str, Any]] = []


class TelemetryHeartbeatPayload(BaseModel):
    site_id: str
    timestamp: str
    system: Dict[str, Any]
    pipeline: Optional[Dict[str, Any]] = None
    config_hash: Optional[str] = None


@cloud_app.get("/health")
def cloud_health():
    return {"status": "healthy", "service": "vyzn-cloud"}


@cloud_app.post("/api/v1/telemetry/heartbeat")
def receive_edge_heartbeat(payload: TelemetryHeartbeatPayload):
    """Ingests 60-second JSON heartbeat from an active edge box and signals OTA updates."""
    watchdog.record_heartbeat(payload.site_id, payload.dict())

    managed = MANAGED_CONFIGS.get(payload.site_id)
    new_config_available = False
    latest_version = 1
    if managed and payload.config_hash:
        cloud_hash = managed.get("config_hash")
        latest_version = managed.get("config_version", 1)
        if cloud_hash and cloud_hash != payload.config_hash:
            new_config_available = True

    return {
        "status": "acknowledged",
        "site_id": payload.site_id,
        "config_version": latest_version,
        "new_config_available": new_config_available
    }


@cloud_app.get("/api/v1/sites")
def list_fleet_sites():
    """Returns real-time status of all deployed edge boxes across shops."""
    return watchdog.get_all_sites()


@cloud_app.get("/webhook/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """Handles Meta WhatsApp developer webhook challenge verification."""
    EXPECTED_TOKEN = "vyzn_secure_webhook_token_2026"
    if hub_mode == "subscribe" and hub_verify_token == EXPECTED_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@cloud_app.post("/webhook/whatsapp")
async def receive_whatsapp_interactive_reply(request: Request):
    """
    Receives interactive quick-reply triage buttons tapped by shopkeepers in WhatsApp.
    Triage responses: [⭐ Star Clip] or [❌ False Alarm].
    """
    body = await request.json()
    logger.info(f"Incoming WhatsApp webhook callback: {body}")

    try:
        entries = body.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    if msg.get("type") == "interactive":
                        button_reply = msg.get("interactive", {}).get("button_reply", {})
                        btn_id = button_reply.get("id", "")
                        sender = msg.get("from", "")

                        triage_entry = {
                            "sender": sender,
                            "button_id": btn_id,
                            "title": button_reply.get("title", ""),
                            "timestamp": msg.get("timestamp")
                        }
                        triage_log.append(triage_entry)
                        logger.info(f"Shopkeeper {sender} triaged event: {btn_id}")

    except Exception as e:
        logger.error(f"Error parsing WhatsApp webhook payload: {e}")

    return {"status": "processed"}


@cloud_app.post("/webhook/telegram")
async def receive_telegram_webhook(request: Request):
    """
    Receives Telegram Bot updates (inline keyboard triage clicks & bot commands).
    Triage responses: [⭐ Star Clip] or [❌ False Alarm].
    """
    import time
    body = await request.json()
    logger.info(f"Incoming Telegram webhook callback: {body}")

    # 1. Handle Inline Keyboard Triage Button Clicks (callback_query)
    if "callback_query" in body:
        cq = body["callback_query"]
        cb_data = cq.get("data", "")
        sender_id = str(cq.get("from", {}).get("id", "unknown"))
        sender_name = cq.get("from", {}).get("first_name", "User")

        triage_entry = {
            "source": "telegram",
            "sender": sender_id,
            "sender_name": sender_name,
            "button_id": cb_data,
            "title": "Star Clip" if "star" in cb_data else "False Alarm",
            "timestamp": cq.get("message", {}).get("date", int(time.time()))
        }
        triage_log.append(triage_entry)
        logger.info(f"Telegram user {sender_name} ({sender_id}) triaged event: {cb_data}")

        return {
            "status": "processed",
            "type": "callback_query",
            "triage": triage_entry
        }

    # 2. Handle Text Commands (e.g. /status, /help, /start)
    if "message" in body:
        msg = body["message"]
        text = msg.get("text", "").strip()

        if text.startswith("/status"):
            active_sites = watchdog.get_all_sites()
            return {
                "status": "processed",
                "type": "command",
                "command": "/status",
                "active_sites_count": len(active_sites),
                "reply_text": f"VYZN Netra Fleet Status: {len(active_sites)} site(s) monitored."
            }
        elif text.startswith("/help") or text.startswith("/start"):
            return {
                "status": "processed",
                "type": "command",
                "command": text,
                "reply_text": "Welcome to VYZN Netra AI Surveillance Bot. You will receive after-hours threat alerts here."
            }

    return {"status": "acknowledged"}


@cloud_app.get("/api/v1/triage-log")
def get_triage_log():
    """Returns log of interactive responses from shopkeepers."""
    return triage_log
