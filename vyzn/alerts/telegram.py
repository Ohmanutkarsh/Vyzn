"""
Telegram Bot alert provider with video clip attachment and inline triage buttons.
Used for rapid development and Phase 1 college demo.
"""

from __future__ import annotations
import os
import logging
import requests
from typing import Optional
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord

logger = logging.getLogger("vyzn.alerts.telegram")


class TelegramAlertProvider(AlertProvider):
    """
    Sends video alert cards to Telegram with native inline keyboard triage.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None

    def send_alert(
        self,
        event: EventRecord,
        video_path: str,
        thumb_path: str
    ) -> bool:
        caption = (
            f"🔔 *Security Alert — {event.camera_id}*\n"
            f"Object: `{event.object_type.capitalize()}` (Confidence: {event.confidence:.0%})\n"
            f"Threat Score: *{event.score}/100*\n"
            f"Time: `{event.start_time}`"
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⭐ Star / Important", "callback_data": f"star:{event.event_group_id}"},
                    {"text": "❌ False Alarm", "callback_data": f"false:{event.event_group_id}"}
                ]
            ]
        }

        # Mock / local mode if no token supplied
        if not self.api_url or not self.chat_id:
            logger.info(f"[TELEGRAM SIMULATION] Alert fired for event {event.event_group_id}:\n{caption}")
            return True

        try:
            # If video file exists, send as video
            if video_path and os.path.exists(video_path):
                with open(video_path, "rb") as video_file:
                    resp = requests.post(
                        f"{self.api_url}/sendVideo",
                        data={
                            "chat_id": self.chat_id,
                            "caption": caption,
                            "parse_mode": "Markdown",
                            "reply_markup": str(inline_keyboard).replace("'", '"')
                        },
                        files={"video": video_file},
                        timeout=15.0
                    )
                return resp.status_code == 200
            else:
                resp = requests.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": caption,
                        "parse_mode": "Markdown",
                        "reply_markup": inline_keyboard
                    },
                    timeout=5.0
                )
                return resp.status_code == 200

        except Exception as e:
            logger.error(f"Failed to dispatch Telegram alert: {e}")
            return False
