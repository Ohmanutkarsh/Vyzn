"""
Telegram Bot Alert Provider with Rich Media (Video/Photo) and Inline Keyboard Triage.
Delivers instant security cards with quick-reply buttons ([⭐ Star Clip] / [❌ False Alarm])
to business owners without Meta Business verification delays or per-conversation fees.
"""

from __future__ import annotations
import os
import json
import logging
import requests
from typing import Optional, Dict, Any
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord

logger = logging.getLogger("vyzn.alerts.telegram")


class TelegramAlertProvider(AlertProvider):
    """
    Sends interactive video or photo alert cards to Telegram with native inline keyboard triage.
    Supports single chats, broadcast channels, and multi-owner monitoring groups.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None

    def build_alert_payload(self, event: EventRecord) -> Dict[str, Any]:
        """Generates standard Telegram caption and inline keyboard markup."""
        caption = (
            f"🚨 *VYZN Netra — Security Alert*\n"
            f"📍 *Camera:* `{event.camera_id}`\n"
            f"🎯 *Object:* `{event.object_type.upper()}` ({event.confidence:.0%} confidence)\n"
            f"⚡ *Threat Score:* *{event.score}/100*\n"
            f"🕒 *Timestamp:* `{event.start_time}`\n\n"
            f"Tap below to triage this incident:"
        )

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⭐ Star Clip (Evidence)", "callback_data": f"star_{event.event_group_id}"},
                    {"text": "❌ False Alarm", "callback_data": f"false_{event.event_group_id}"}
                ]
            ]
        }
        return {
            "caption": caption,
            "reply_markup": inline_keyboard
        }

    def send_alert(
        self,
        event: EventRecord,
        video_path: str = "",
        thumb_path: str = ""
    ) -> bool:
        """
        Transmits rich interactive alert to Telegram.
        Falls back to local simulation logging when bot credentials are not configured.
        """
        payload = self.build_alert_payload(event)
        caption = payload["caption"]
        reply_markup = payload["reply_markup"]

        # Simulation Mode
        if not self.api_url or not self.chat_id:
            logger.info(
                f"[TELEGRAM SIMULATION] Alert to {self.chat_id or 'Chat-ID-Unset'}:\n"
                f"{caption}\n"
                f"Buttons: [⭐ Star Clip] | [❌ False Alarm] (Event ID: {event.event_group_id})"
            )
            return True

        try:
            # 1. Prefer Video Clip if available
            if video_path and os.path.exists(video_path):
                with open(video_path, "rb") as vf:
                    resp = requests.post(
                        f"{self.api_url}/sendVideo",
                        data={
                            "chat_id": self.chat_id,
                            "caption": caption,
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(reply_markup)
                        },
                        files={"video": vf},
                        timeout=15.0
                    )
                return resp.status_code == 200

            # 2. Fallback to Photo / Snapshot if available
            elif thumb_path and os.path.exists(thumb_path):
                with open(thumb_path, "rb") as pf:
                    resp = requests.post(
                        f"{self.api_url}/sendPhoto",
                        data={
                            "chat_id": self.chat_id,
                            "caption": caption,
                            "parse_mode": "Markdown",
                            "reply_markup": json.dumps(reply_markup)
                        },
                        files={"photo": pf},
                        timeout=10.0
                    )
                return resp.status_code == 200

            # 3. Fallback to Text Message
            else:
                resp = requests.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": caption,
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup
                    },
                    timeout=5.0
                )
                return resp.status_code == 200

        except Exception as e:
            logger.error(f"Failed to dispatch Telegram alert: {e}")
            return False


def send_telegram_threat_alert(
    event: EventRecord,
    video_path: str = "",
    thumb_path: str = "",
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None
) -> bool:
    """Convenience helper to dispatch interactive Telegram alert via configured provider."""
    token = bot_token or os.environ.get("VYZN_TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.environ.get("VYZN_TELEGRAM_CHAT_ID")
    provider = TelegramAlertProvider(bot_token=token, chat_id=chat)
    return provider.send_alert(event, video_path, thumb_path)
