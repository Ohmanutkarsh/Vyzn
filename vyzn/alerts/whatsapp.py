"""
Meta WhatsApp Cloud API (Graph API v20.0) Alert Provider.
Delivers rich interactive video message cards with quick-reply triage buttons to business owners.
"""

from __future__ import annotations
import os
import logging
import requests
from typing import Optional, Dict, Any
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord

logger = logging.getLogger("vyzn.alerts.whatsapp")


class WhatsAppCloudProvider(AlertProvider):
    """
    Sends interactive security alert cards via Meta WhatsApp Cloud API.
    Provides [⭐ Star Clip] and [❌ False Alarm] buttons for instant mobile triage.
    """

    GRAPH_API_URL = "https://graph.facebook.com/v20.0"

    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        recipient_phone: Optional[str] = None
    ):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.recipient_phone = recipient_phone

    def send_alert(
        self,
        event: EventRecord,
        video_path: str,
        thumb_path: str
    ) -> bool:
        """
        Transmits interactive WhatsApp alert message.
        Falls back to local simulation logging if credentials are not configured.
        """
        body_text = (
            f"🚪 *VYZN Alert — {event.camera_id}*\n"
            f"Detected: *{event.object_type.upper()}* ({event.confidence:.0%} confidence)\n"
            f"Threat Score: *{event.score}/100*\n"
            f"Time: {event.start_time}\n\n"
            f"Tap below to triage this alert:"
        )

        # Simulation Mode
        if not self.access_token or not self.phone_number_id or not self.recipient_phone:
            logger.info(
                f"[WHATSAPP SIMULATION] Message to {self.recipient_phone or '+91-XXXXXXXXXX'}:\n"
                f"{body_text}\n"
                f"Buttons: [⭐ Star Clip] | [❌ False Alarm] (Event ID: {event.event_group_id})"
            )
            return True

        try:
            # 1. Upload Video Media to WhatsApp Media Endpoint (if file exists)
            media_id = None
            if video_path and os.path.exists(video_path):
                media_id = self._upload_media(video_path, "video/mp4")

            # 2. Build Interactive Message Payload
            endpoint = f"{self.GRAPH_API_URL}/{self.phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            interactive_payload: Dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self.recipient_phone,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {
                        "text": body_text
                    },
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

            # If media was uploaded, attach it as interactive video header
            if media_id:
                interactive_payload["interactive"]["header"] = {
                    "type": "video",
                    "video": {"id": media_id}
                }

            resp = requests.post(endpoint, json=interactive_payload, headers=headers, timeout=12.0)
            if resp.status_code in [200, 201]:
                logger.info(f"Successfully delivered WhatsApp alert for event {event.event_group_id}")
                return True
            else:
                logger.error(f"WhatsApp Cloud API error ({resp.status_code}): {resp.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to dispatch WhatsApp alert: {e}")
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

