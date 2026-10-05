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
from datetime import datetime, timezone, timedelta
import zoneinfo
from typing import Optional, Dict, Any
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord
from vyzn.api.mobile_viewer import build_viewer_url

logger = logging.getLogger("vyzn.alerts.telegram")


def normalize_phone(phone: Optional[str]) -> str:
    """Normalizes phone numbers to standard E.164 +91XXXXXXXXXX format for Indian numbers."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    return f"+{digits}" if digits else ""


def format_alert_headline(event: EventRecord, camera_name: str = "") -> str:
    """Computes plain-language headline according to Section 6.3 headline table."""
    meta = {}
    if getattr(event, "metadata_json", None):
        try:
            meta = json.loads(event.metadata_json) if isinstance(event.metadata_json, str) else dict(event.metadata_json)
        except Exception:
            pass
    reasons = meta.get("reasons") or getattr(event, "reasons", [])
    area_name = getattr(event, "zone_name", None)
    if area_name in ("general", "unspecified", "", None):
        area_name = None

    if reasons and isinstance(reasons, list) and len(reasons) > 0:
        primary = reasons[0]
        code = primary.get("code") or primary.get("id")
        params = primary.get("params", {})
        area = params.get("area") or primary.get("watch_area_name") or area_name or camera_name or "Camera view"
        if code == "entered_restricted_area":
            return f"Person entered {area}"
        elif code == "stayed_in_area":
            dur = params.get("duration") or f"{params.get('seconds', 60)} seconds"
            return f"Person stayed {dur} in {area}"
        elif code == "outside_shop_hours":
            return "Movement outside shop hours"
        elif code == "person_detected":
            return f"Person in {area}"
        elif code == "movement":
            return f"Movement in {area}"

    if getattr(event, "object_type", "") == "person":
        dur = int(getattr(event, "duration_sec", 0))
        if dur >= 10 and area_name:
            return f"Person stayed {dur} seconds in {area_name}"
        elif area_name:
            return f"Person in {area_name}"
        return "Person detected in camera view"
    return f"Movement in {area_name or 'camera view'}"


def format_alert_when(dt_or_str: Any, time_zone_str: str = "Asia/Kolkata") -> str:
    """Formats event time into calm Indian storekeeper format: 'Today, 9:34 pm'."""
    try:
        tz = zoneinfo.ZoneInfo(time_zone_str)
    except Exception:
        tz = timezone.utc

    if isinstance(dt_or_str, (int, float)):
        epoch_sec = dt_or_str / 1000.0 if dt_or_str > 1e11 else dt_or_str
        dt = datetime.fromtimestamp(epoch_sec, tz)
    elif isinstance(dt_or_str, str):
        try:
            dt = datetime.fromisoformat(dt_or_str.replace("Z", "+00:00")).astimezone(tz)
        except Exception:
            dt = datetime.now(tz)
    else:
        dt = datetime.now(tz)

    now = datetime.now(tz)
    time_str = dt.strftime("%I:%M %p").lstrip("0").lower()
    if dt.date() == now.date():
        return f"Today, {time_str}"
    elif dt.date() == (now - timedelta(days=1)).date():
        return f"Yesterday, {time_str}"
    else:
        return f"{dt.strftime('%a %d %b')}, {time_str}"


def push_telegram_alert(
    event: EventRecord,
    settings: Any,
    db: Optional[Any] = None,
    base_url: str = "http://localhost:8000"
) -> bool:
    """
    Dispatches Appendix B alert using TelegramAlertProvider.
    Enforces rule: Review-tier clips are never pushed.
    """
    provider = TelegramAlertProvider(
        bot_token=getattr(settings, "telegram_bot_token", None),
        chat_id=getattr(settings, "telegram_chat_id", None)
    )
    thumb_path = getattr(event, "thumb_path", "")
    video_path = getattr(event, "clip_path", "") or getattr(event, "file_path", "")
    camera_name = getattr(event, "camera_name", None) or ""
    if not camera_name:
        meta = {}
        if getattr(event, "metadata_json", None):
            try:
                meta = json.loads(event.metadata_json) if isinstance(event.metadata_json, str) else dict(event.metadata_json)
                camera_name = meta.get("camera_name", "")
            except Exception:
                pass
    if not camera_name and db and getattr(event, "camera_id", None):
        if hasattr(db, "get_camera"):
            cam = db.get_camera(event.camera_id)
            if cam and isinstance(cam, dict):
                camera_name = cam.get("name", "")
        if not camera_name and hasattr(settings, "cameras"):
            for c in getattr(settings, "cameras", []):
                if getattr(c, "camera_id", None) == event.camera_id:
                    camera_name = getattr(c, "name", "")
                    break

    return provider.send_alert(
        event=event,
        video_path=video_path,
        thumb_path=thumb_path,
        base_url=base_url,
        camera_name=camera_name
    )


class TelegramAlertProvider(AlertProvider):
    """
    Sends interactive video or photo alert cards to Telegram with native inline keyboard triage.
    Supports single chats, broadcast channels, and multi-owner monitoring groups.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None

    def build_alert_payload(
        self,
        event: EventRecord,
        base_url: str = "http://localhost:8000",
        camera_name: str = ""
    ) -> Dict[str, Any]:
        """Generates Appendix B Telegram alert message and inline keyboard markup."""
        cam_display = camera_name or getattr(event, "camera_name", None) or event.camera_id
        headline = format_alert_headline(event, cam_display)
        when_str = format_alert_when(event.start_time)

        caption = f"🚨 Alert · {cam_display}\n{headline}\n{when_str}"

        clip_id = str(event.event_group_id)
        clip_url = f"{base_url.rstrip('/')}/clips/{clip_id}"

        inline_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Open clip", "url": clip_url},
                    {"text": "Not an issue", "callback_data": f"not_an_issue_{clip_id}"}
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
        thumb_path: str = "",
        base_url: str = "http://localhost:8000",
        camera_name: str = ""
    ) -> bool:
        """
        Transmits Appendix B alert to Telegram with photo thumbnail and inline buttons.
        Review-tier clips are never pushed.
        """
        # Rule: Review-tier clips are never pushed
        if getattr(event, "tier", "review") != "alert":
            logger.info(
                f"[TELEGRAM ALERT FILTER] Skipping push for {event.event_group_id}: "
                f"tier='{getattr(event, 'tier', 'review')}', only 'alert' tier is pushed."
            )
            return False

        payload = self.build_alert_payload(event, base_url=base_url, camera_name=camera_name)
        caption = payload["caption"]
        reply_markup = payload["reply_markup"]

        # Simulation Mode
        if not self.api_url or not self.chat_id:
            logger.info(
                f"[TELEGRAM SIMULATION] Alert to {self.chat_id or 'Chat-ID-Unset'}:\n"
                f"{caption}\n"
                f"Buttons: [Open clip] | [Not an issue] (Event ID: {event.event_group_id})"
            )
            return True

        try:
            # 1. Attach clip thumbnail as photo per Appendix B
            if thumb_path and os.path.exists(thumb_path):
                with open(thumb_path, "rb") as pf:
                    resp = requests.post(
                        f"{self.api_url}/sendPhoto",
                        data={
                            "chat_id": self.chat_id,
                            "caption": caption,
                            "reply_markup": json.dumps(reply_markup)
                        },
                        files={"photo": pf},
                        timeout=10.0
                    )
                return resp.status_code == 200

            # 2. Fallback to video if thumbnail unavailable
            elif video_path and os.path.exists(video_path):
                with open(video_path, "rb") as vf:
                    resp = requests.post(
                        f"{self.api_url}/sendVideo",
                        data={
                            "chat_id": self.chat_id,
                            "caption": caption,
                            "reply_markup": json.dumps(reply_markup)
                        },
                        files={"video": vf},
                        timeout=15.0
                    )
                return resp.status_code == 200

            # 3. Fallback to text message
            else:
                resp = requests.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": caption,
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
            elif data.startswith("not_an_issue_"):
                event_id = data.replace("not_an_issue_", "")
                if self.db:
                    if hasattr(self.db, "update_clip_status"):
                        self.db.update_clip_status(event_id, "not_an_issue")
                    else:
                        self.db.update_event_triage(event_id, "not_an_issue")
                    self.db.log_audit("TELEGRAM_TRIAGE_NOT_AN_ISSUE", event_id, f"Operator: {user_name}")
                reply_text = "Marked as not an issue."
                # Edit message to reflect status per Appendix B
                msg = cq.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                msg_id = msg.get("message_id")
                if chat_id and msg_id:
                    try:
                        if msg.get("photo") or "caption" in msg:
                            requests.post(
                                f"{self.api_url}/editMessageCaption",
                                json={"chat_id": chat_id, "message_id": msg_id, "caption": reply_text},
                                timeout=5.0
                            )
                        else:
                            requests.post(
                                f"{self.api_url}/editMessageText",
                                json={"chat_id": chat_id, "message_id": msg_id, "text": reply_text},
                                timeout=5.0
                            )
                    except Exception as e:
                        logger.debug(f"Failed to edit Telegram message: {e}")
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

        # 2. Incoming chat message processing (/start, contact sharing, /stop)
        if "message" in update:
            msg = update["message"]
            chat_id = msg.get("chat", {}).get("id")
            from_user = msg.get("from", {})
            from_id = from_user.get("id")
            username = from_user.get("username")
            text = (msg.get("text") or "").strip()

            # Handle /start <token> command
            if text.startswith("/start"):
                parts = text.split()
                if len(parts) > 1 and self.db:
                    token = parts[1].strip()
                    link = self.db.get_telegram_link(token)
                    now_ms = int(time.time() * 1000)
                    if link and now_ms <= link.get("expires_at_ms", 0) and link.get("status") != "linked":
                        self.db.update_telegram_link_chat(token, str(chat_id))
                        # Prompt with native contact-sharing keyboard
                        try:
                            requests.post(
                                f"{self.api_url}/sendMessage",
                                json={
                                    "chat_id": chat_id,
                                    "text": "Please tap the button below to share your mobile number so VYZN can connect your alerts.",
                                    "reply_markup": {
                                        "keyboard": [[{"text": "📱 Share my number", "request_contact": True}]],
                                        "resize_keyboard": True,
                                        "one_time_keyboard": True
                                    }
                                },
                                timeout=5.0
                            )
                        except Exception as e:
                            logger.error(f"Failed to send contact prompt: {e}")
                        return {"type": "start_token", "token": token, "chat_id": chat_id}
                    else:
                        try:
                            requests.post(
                                f"{self.api_url}/sendMessage",
                                json={
                                    "chat_id": chat_id,
                                    "text": "This link has expired or is invalid. Please request a new link on VYZN."
                                },
                                timeout=5.0
                            )
                        except Exception:
                            pass
                        return {"type": "start_token_expired", "chat_id": chat_id}
                else:
                    try:
                        requests.post(
                            f"{self.api_url}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "Welcome to VYZN Netra. To connect alerts, use the link provided in your VYZN setup page."
                            },
                            timeout=5.0
                        )
                    except Exception:
                        pass
                    return {"type": "start_regular", "chat_id": chat_id}

            # Handle contact message
            if "contact" in msg and self.db:
                contact = msg["contact"]
                contact_user_id = contact.get("user_id")

                # Anti-spoofing check: contact shared must match the sender's Telegram user ID
                if contact_user_id is not None and str(contact_user_id) != str(from_id):
                    try:
                        requests.post(
                            f"{self.api_url}/sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "⚠️ Please share your own mobile number using the 'Share my number' button.",
                                "reply_markup": {"remove_keyboard": True}
                            },
                            timeout=5.0
                        )
                    except Exception:
                        pass
                    return {"type": "contact_user_mismatch", "chat_id": chat_id}

                # Retrieve pending link for this chat_id
                link = self.db.get_telegram_link_by_chat_id(str(chat_id))
                shared_phone = normalize_phone(contact.get("phone_number"))

                if link:
                    expected_phone = normalize_phone(link.get("phone_e164"))
                    if shared_phone == expected_phone:
                        # Match: connect Telegram to user account
                        self.db.update_user_telegram(
                            user_id=link["user_id"],
                            chat_id=str(chat_id),
                            telegram_user_id=str(from_id),
                            username=username
                        )
                        self.db.update_telegram_link_status(link["token"], "linked")
                        try:
                            requests.post(
                                f"{self.api_url}/sendMessage",
                                json={
                                    "chat_id": chat_id,
                                    "text": "Connected. VYZN alerts will arrive here.",
                                    "reply_markup": {"remove_keyboard": True}
                                },
                                timeout=5.0
                            )
                        except Exception:
                            pass
                        return {"type": "telegram_linked_success", "user_id": link["user_id"], "chat_id": chat_id}
                    else:
                        # Mismatch
                        self.db.update_telegram_link_status(link["token"], "mismatch")
                        try:
                            requests.post(
                                f"{self.api_url}/sendMessage",
                                json={
                                    "chat_id": chat_id,
                                    "text": f"The number shared in Telegram ({shared_phone}) doesn't match the mobile number registered on VYZN.\n\nPlease share the number of this Telegram account, or change your mobile number.",
                                    "reply_markup": {"remove_keyboard": True}
                                },
                                timeout=5.0
                            )
                        except Exception:
                            pass
                        return {"type": "telegram_linked_mismatch", "user_id": link["user_id"], "chat_id": chat_id}

            # Handle /stop command
            if text == "/stop" and self.db:
                self.db.update_user_telegram_blocked(str(chat_id))
                try:
                    requests.post(
                        f"{self.api_url}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": "Alerts stopped. VYZN will no longer send notifications to this chat.",
                            "reply_markup": {"remove_keyboard": True}
                        },
                        timeout=5.0
                    )
                except Exception:
                    pass
                return {"type": "telegram_stopped", "chat_id": chat_id}

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
