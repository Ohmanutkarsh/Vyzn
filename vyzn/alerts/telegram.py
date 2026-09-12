"""
Telegram Bot Alert Provider with Rich Media (Video/Photo) and Inline Keyboard Triage.
Delivers instant security cards with quick-reply buttons ([⭐ Star Clip] / [❌ False Alarm])
to business owners without Meta Business verification delays or per-conversation fees.
Includes CGNAT-immune long-polling worker for two-way interactive triage callbacks.
"""

from __future__ import annotations
import os
import json
import time
import logging
import threading
import requests
from typing import Optional, Dict, Any
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord
from vyzn.api.mobile_viewer import build_viewer_url

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
        color_str = f" • Apparel: {event.dominant_color.upper()}" if getattr(event, "dominant_color", "unspecified") != "unspecified" else ""
        zone_str = f" ({event.zone_name})" if getattr(event, "zone_name", "general") != "general" else ""
        caption = (
            f"🚨 *VYZN Netra — Security Alert*\n"
            f"📍 *Camera:* `{event.camera_id}`{zone_str}\n"
            f"🎯 *Object:* `{event.object_type.upper()}` ({event.confidence:.0%} conf{color_str})\n"
            f"⚡ *Threat Score:* *{event.score}/100*\n"
            f"🕒 *Timestamp:* `{event.start_time}`\n\n"
            f"Tap below to triage this incident:"
        )

        viewer_url = build_viewer_url(event.event_group_id)
        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⭐ Star Clip (Evidence)", "callback_data": f"star_{event.event_group_id}"},
                    {"text": "❌ False Alarm (Calibrate)", "callback_data": f"false_{event.event_group_id}"}
                ],
                [
                    {"text": "▶️ View Forensic Clip", "url": viewer_url}
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


class TelegramPollingWorker(threading.Thread):
    """
    Long-polling worker that receives Telegram callback queries and commands
    without requiring public open ports or public domain webhooks (works behind Indian CGNAT).
    """

    def __init__(
        self,
        bot_token: str,
        db: Optional[Any] = None,
        calibrator: Optional[Any] = None
    ):
        super().__init__(name="Telegram-Polling-Worker", daemon=True)
        self.bot_token = bot_token
        self.db = db
        self.calibrator = calibrator
        self.running = False
        self.last_update_id = 0
        self.api_url = f"https://api.telegram.org/bot{bot_token}"

    def run(self):
        self.running = True
        logger.info("Telegram long-polling worker started.")
        while self.running:
            try:
                params = {"offset": self.last_update_id + 1, "timeout": 20}
                resp = requests.get(f"{self.api_url}/getUpdates", params=params, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        self.last_update_id = max(self.last_update_id, update.get("update_id", 0))
                        self.handle_update(update)
                elif resp.status_code in (401, 404):
                    logger.warning(f"Telegram Bot Token invalid or unauthorized (HTTP {resp.status_code}). Pausing poller.")
                    time.sleep(30)
                else:
                    time.sleep(2)
            except Exception as e:
                logger.debug(f"Telegram poll tick non-fatal error: {e}")
                time.sleep(3)

    def stop(self):
        self.running = False

    def handle_update(self, update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Processes an incoming Telegram update and executes actions."""
        # 1. Inline button callback query
        if "callback_query" in update:
            cq = update["callback_query"]
            cq_id = cq.get("id")
            data = cq.get("data", "")
            user_name = cq.get("from", {}).get("first_name", "Operator")

            reply_text = "Action acknowledged."
            if data.startswith("star_"):
                event_id = data.replace("star_", "")
                if self.db:
                    self.db.update_event_star(event_id, 1)
                    self.db.log_audit("TELEGRAM_TRIAGE_STARRED", event_id, f"Operator: {user_name}")
                reply_text = f"⭐ Event {event_id} protected as evidence!"
            elif data.startswith("false_"):
                event_id = data.replace("false_", "")
                if self.db:
                    self.db.update_event_triage(event_id, "false_positive")
                    self.db.log_audit("TELEGRAM_TRIAGE_FALSE_ALARM", event_id, f"Operator: {user_name}")
                    ev = self.db.get_event(event_id)
                    if ev and self.calibrator:
                        self.calibrator.record_triage(ev.camera_id, is_threat=False)
                reply_text = "❌ False alarm recorded. AI sensitivity auto-calibrated!"

            try:
                requests.post(
                    f"{self.api_url}/answerCallbackQuery",
                    json={"callback_query_id": cq_id, "text": reply_text, "show_alert": False},
                    timeout=5.0
                )
            except Exception:
                pass

            return {"type": "callback_query", "action": data, "result": reply_text}

        return None


_active_poller: Optional[TelegramPollingWorker] = None

def start_telegram_poller(bot_token: str, db: Optional[Any] = None, calibrator: Optional[Any] = None) -> Optional[TelegramPollingWorker]:
    """Starts or re-launches the global Telegram long-polling worker."""
    global _active_poller
    stop_telegram_poller()
    if not bot_token:
        return None
    _active_poller = TelegramPollingWorker(bot_token=bot_token, db=db, calibrator=calibrator)
    _active_poller.start()
    return _active_poller

def stop_telegram_poller():
    """Stops the active Telegram long-polling worker."""
    global _active_poller
    if _active_poller and _active_poller.is_alive():
        _active_poller.stop()
        _active_poller = None

def get_active_poller() -> Optional[TelegramPollingWorker]:
    return _active_poller


def test_telegram_connection(bot_token: str, chat_id: str) -> Dict[str, Any]:
    """
    Validates bot token against Telegram getMe and sends a test notification
    to verify chat deliverability and latency.
    """
    start_t = time.time()
    if not bot_token or not chat_id:
        return {"ok": False, "error": "Bot token or Chat ID is missing"}

    try:
        me_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=6.0)
        if me_res.status_code != 200:
            return {"ok": False, "error": f"Invalid bot token (HTTP {me_res.status_code})"}

        bot_data = me_res.json().get("result", {})
        bot_username = bot_data.get("username", "VYZNBot")

        msg = (
            f"🚀 *VYZN Netra Test Alert*\n"
            f"Status: *Connected & Operational*\n"
            f"Bot: `@{bot_username}`\n"
            f"Time: `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`\n"
            f"Two-Way Triage: *Active (Long Polling)*"
        )

        send_res = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=8.0
        )

        latency_ms = round((time.time() - start_t) * 1000, 1)
        if send_res.status_code == 200:
            return {
                "ok": True,
                "bot_username": bot_username,
                "latency_ms": latency_ms,
                "message": f"Verified! Ping delivered in {latency_ms}ms"
            }
        else:
            return {"ok": False, "error": f"Failed to deliver to chat {chat_id} (HTTP {send_res.status_code}): {send_res.text}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


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
