"""
Meta WhatsApp Cloud API (Graph API v20.0) Alert Provider.
Delivers rich interactive video message cards with quick-reply triage buttons to business owners.
"""

from __future__ import annotations
import os
import logging
import requests
from datetime import datetime, timezone
import time
from typing import Optional, Dict, Any
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord
from vyzn.api.mobile_viewer import build_viewer_url

logger = logging.getLogger("vyzn.alerts.whatsapp")


class WhatsAppSessionTracker:
    """
    Tracks inbound customer interactions to determine whether a 24-hour
    freeform customer service window is open per recipient phone.
    """
    def __init__(self):
        self._last_inbound: Dict[str, float] = {}

    def record_inbound(self, phone: str, timestamp_epoch: Optional[float] = None) -> None:
        """Records an inbound customer interaction (e.g., quick-reply tap or text message)."""
        clean_phone = self._clean_phone(phone)
        self._last_inbound[clean_phone] = timestamp_epoch or time.time()
        logger.info(f"WhatsApp 24h customer session opened for [{clean_phone}]")

    def is_session_active(self, phone: str, window_hours: float = 24.0) -> bool:
        """Returns True if an inbound message has occurred within the 24-hour session window."""
        clean_phone = self._clean_phone(phone)
        last_time = self._last_inbound.get(clean_phone)
        if not last_time:
            return False
        return (time.time() - last_time) < (window_hours * 3600.0)

    @staticmethod
    def _clean_phone(phone: str) -> str:
        return "".join(c for c in phone if c.isdigit() or c == "+")


# Global session tracker instance across the runtime
session_tracker = WhatsAppSessionTracker()


class WhatsAppCloudProvider(AlertProvider):
    """
    Sends compliance-certified security alert cards via Meta WhatsApp Cloud API.
    Enforces Meta's requirement for pre-approved Utility Templates for out-of-session
    business-initiated alerts, and freeform interactive messages once an owner responds.
    """

    GRAPH_API_URL = "https://graph.facebook.com/v20.0"

    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        recipient_phone: Optional[str] = None,
        template_name: str = "vyzn_security_alert_v1",
        base_viewer_url: str = "http://localhost:8000"
    ):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.recipient_phone = recipient_phone
        self.template_name = template_name
        self.base_viewer_url = base_viewer_url

    def build_payload(
        self,
        event: EventRecord,
        is_session_active: bool = False,
        media_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds Meta Cloud API payload:
        - If outside 24h window: Pre-approved Utility Template with dynamic variables,
          quick-reply triage buttons, and mobile viewer CTA link.
        - If inside 24h window: Freeform interactive message card.
        """
        target_phone = self.recipient_phone or "+919876543210"
        viewer_url = build_viewer_url(event.event_group_id, base_url=self.base_viewer_url)

        if not is_session_active:
            # Out-of-Session: Pre-Approved Meta Utility Template
            # Template parameters: {{1}}=camera, {{2}}=object & confidence, {{3}}=threat score, {{4}}=time
            time_str = event.start_time.split("T")[-1][:8] if "T" in event.start_time else event.start_time
            return {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target_phone,
                "type": "template",
                "template": {
                    "name": self.template_name,
                    "language": {"code": "en"},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": event.camera_id},
                                {"type": "text", "text": f"{event.object_type.upper()} ({int(event.confidence * 100)}%)"},
                                {"type": "text", "text": f"{event.score}/100"},
                                {"type": "text", "text": time_str}
                            ]
                        },
                        {
                            "type": "button",
                            "sub_type": "quick_reply",
                            "index": "0",
                            "parameters": [{"type": "payload", "payload": f"star_{event.event_group_id}"}]
                        },
                        {
                            "type": "button",
                            "sub_type": "quick_reply",
                            "index": "1",
                            "parameters": [{"type": "payload", "payload": f"false_{event.event_group_id}"}]
                        },
                        {
                            "type": "button",
                            "sub_type": "url",
                            "index": "2",
                            "parameters": [{"type": "text", "text": viewer_url.split("/v/")[-1]}]
                        }
                    ]
                }
            }

        # In-Session: Rich Interactive Message (Session Window Active)
        body_text = (
            f"🚪 *VYZN Alert — {event.camera_id}*\n"
            f"Detected: *{event.object_type.upper()}* ({event.confidence:.0%} confidence)\n"
            f"Threat Score: *{event.score}/100*\n"
            f"Time: {event.start_time}\n\n"
            f"Tap below to triage or view full clip: {viewer_url}"
        )
        interactive_payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": target_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"star_{event.event_group_id}",
                                "title": "⭐ Star Clip"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"false_{event.event_group_id}",
                                "title": "❌ False Alarm"
                            }
                        }
                    ]
                }
            }
        }
        if media_id:
            interactive_payload["interactive"]["header"] = {
                "type": "video",
                "video": {"id": media_id}
            }
        return interactive_payload

    def send_alert(
        self,
        event: EventRecord,
        video_path: str = "",
        thumb_path: str = ""
    ) -> bool:
        """
        Transmits Meta WhatsApp alert.
        Checks 24h session window; uses Utility Template if out-of-session, or interactive if in-session.
        Falls back to local simulation logging if credentials are not configured.
        """
        target_phone = self.recipient_phone or "+919876543210"
        is_active = session_tracker.is_session_active(target_phone)
        viewer_url = build_viewer_url(event.event_group_id, base_url=self.base_viewer_url)

        body_text = (
            f"🚪 *VYZN Alert — {event.camera_id}*\n"
            f"Detected: *{event.object_type.upper()}* ({event.confidence:.0%} confidence)\n"
            f"Threat Score: *{event.score}/100*\n"
            f"Time: {event.start_time}\n\n"
            f"Tap below to triage this alert:"
        )

        # Simulation Mode
        if not self.access_token or not self.phone_number_id or not self.recipient_phone:
            mode_desc = "IN-SESSION INTERACTIVE" if is_active else "UTILITY TEMPLATE"
            logger.info(
                f"[WHATSAPP SIMULATION ({mode_desc})] Target: {target_phone}\n"
                f"{body_text}\n"
                f"Buttons: [⭐ Star Clip] | [❌ False Alarm]\n"
                f"Mobile Viewer Link: {viewer_url}"
            )
            return True

        try:
            media_id = None
            if is_active and video_path and os.path.exists(video_path):
                media_id = self._upload_media(video_path, "video/mp4")

            payload = self.build_payload(event, is_session_active=is_active, media_id=media_id)
            endpoint = f"{self.GRAPH_API_URL}/{self.phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            resp = requests.post(endpoint, json=payload, headers=headers, timeout=12.0)
            if resp.status_code in [200, 201]:
                logger.info(f"Successfully delivered WhatsApp alert for event {event.event_group_id}")
                return True
            else:
                logger.error(f"WhatsApp Cloud API error ({resp.status_code}): {resp.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to dispatch WhatsApp alert: {e}")
            return False

    def send_session_followup(self, text: str) -> bool:
        """Sends a freeform follow-up message when the 24-hour session window is active."""
        target_phone = self.recipient_phone or "+919876543210"
        if not session_tracker.is_session_active(target_phone):
            logger.warning(f"Cannot send freeform follow-up to {target_phone}: 24h window closed.")
            return False

        if not self.access_token or not self.phone_number_id:
            logger.info(f"[WHATSAPP SIMULATION FOLLOW-UP] To {target_phone}: {text}")
            return True

        try:
            endpoint = f"{self.GRAPH_API_URL}/{self.phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target_phone,
                "type": "text",
                "text": {"body": text}
            }
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=10.0)
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Failed to send session follow-up: {e}")
            return False

    def _upload_media(self, file_path: str, mime_type: str) -> Optional[str]:
        """Uploads video file to Meta Graph API media endpoint and returns media ID."""
        upload_url = f"{self.GRAPH_API_URL}/{self.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f, mime_type),
                "messaging_product": (None, "whatsapp")
            }
            resp = requests.post(upload_url, headers=headers, files=files, timeout=20.0)

        if resp.status_code in [200, 201]:
            return resp.json().get("id")
        logger.error(f"WhatsApp media upload failed: {resp.text}")
        return None


def send_interactive_threat_alert(event: EventRecord, video_path: str = "", thumb_path: str = "") -> bool:
    """Convenience helper to dispatch interactive WhatsApp alert via default provider."""
    provider = WhatsAppCloudProvider()
    return provider.send_alert(event, video_path, thumb_path)

