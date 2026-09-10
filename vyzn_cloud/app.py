"""
Cloud Webhook Receiver and Fleet Management FastAPI service.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response, Query
from pydantic import BaseModel

from vyzn_cloud.watchdog import DeadManWatchdog

logger = logging.getLogger("vyzn_cloud.app")

cloud_app = FastAPI(
    title="VYZN Netra Cloud Fleet Manager",
    description="Receives remote telemetry heartbeats, monitors uptime, and handles WhatsApp triage webhooks",
    version="1.0.0"
)

watchdog = DeadManWatchdog(silence_threshold_sec=180.0)

# In-memory store for WhatsApp triage actions received
triage_log: list[Dict[str, Any]] = []


class TelemetryHeartbeatPayload(BaseModel):
    site_id: str
    timestamp: str
    system: Dict[str, Any]
    pipeline: Optional[Dict[str, Any]] = None


@cloud_app.get("/health")
def cloud_health():
    return {"status": "healthy", "service": "vyzn-cloud"}


@cloud_app.post("/api/v1/telemetry/heartbeat")
def receive_edge_heartbeat(payload: TelemetryHeartbeatPayload):
    """Ingests 60-second JSON heartbeat from an active edge box."""
    watchdog.record_heartbeat(payload.site_id, payload.dict())
    return {
        "status": "acknowledged",
        "site_id": payload.site_id,
        "config_version": "1.0.0"
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


@cloud_app.get("/api/v1/triage-log")
def get_triage_log():
    """Returns log of interactive responses from shopkeepers."""
    return triage_log
