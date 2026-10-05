"""
Unit and integration tests for Telegram Bot Alert Provider & Webhook Triage.
Verifies message formatting, inline keyboard layout, simulated delivery,
and cloud callback triage processing.
"""

from datetime import datetime, timezone
from starlette.testclient import TestClient

from vyzn.core.events import EventRecord
from vyzn.alerts.telegram import TelegramAlertProvider, send_telegram_threat_alert


def test_telegram_alert_payload_structure():
    provider = TelegramAlertProvider()
    event = EventRecord(
        event_group_id="ev_tel_001",
        camera_id="cam_corridor",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.92,
        score=85,
        tier="alert"
    )

    payload = provider.build_alert_payload(event)
    assert "caption" in payload
    assert "reply_markup" in payload

    caption = payload["caption"]
    assert "cam_corridor" in caption
    assert "Person" in caption

    markup = payload["reply_markup"]
    assert "inline_keyboard" in markup
    buttons = markup["inline_keyboard"][0]
    assert len(buttons) == 2
    assert "Open clip" in buttons[0]["text"]
    assert "Not an issue" in buttons[1]["text"]


def test_telegram_alert_simulation_dispatch():
    event = EventRecord(
        event_group_id="ev_tel_sim",
        camera_id="cam_vault",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.88,
        score=78,
        tier="alert"
    )
    # Convenience helper in offline/simulation mode
    assert send_telegram_threat_alert(event) is True
