"""
Unit and integration tests for Telegram Bot Alert Provider & Webhook Triage.
Verifies message formatting, inline keyboard layout, simulated delivery,
and cloud callback triage processing.
"""

from datetime import datetime, timezone
from starlette.testclient import TestClient

from vyzn.core.events import EventRecord
from vyzn.alerts.telegram import TelegramAlertProvider, send_telegram_threat_alert
from vyzn_cloud.app import cloud_app, triage_log


def test_telegram_alert_payload_structure():
    provider = TelegramAlertProvider()
    event = EventRecord(
        event_group_id="ev_tel_001",
        camera_id="cam_corridor",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.92,
        score=85
    )

    payload = provider.build_alert_payload(event)
    assert "caption" in payload
    assert "reply_markup" in payload

    caption = payload["caption"]
    assert "cam_corridor" in caption
    assert "PERSON" in caption
    assert "85/100" in caption

    markup = payload["reply_markup"]
    assert "inline_keyboard" in markup
    buttons = markup["inline_keyboard"][0]
    assert len(buttons) == 2
    assert "Star Clip" in buttons[0]["text"]
    assert buttons[0]["callback_data"] == "star_ev_tel_001"
    assert "False Alarm" in buttons[1]["text"]
    assert buttons[1]["callback_data"] == "false_ev_tel_001"


def test_telegram_alert_simulation_dispatch():
    event = EventRecord(
        event_group_id="ev_tel_sim",
        camera_id="cam_vault",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.88,
        score=78
    )
    # Convenience helper in offline/simulation mode
    assert send_telegram_threat_alert(event) is True


def test_telegram_webhook_triage_and_commands():
    client = TestClient(cloud_app)
    triage_log.clear()

    # 1. Simulate shopkeeper tapping [❌ False Alarm] inline button
    cq_payload = {
        "update_id": 9991,
        "callback_query": {
            "id": "cq_12345",
            "from": {
                "id": 987654321,
                "first_name": "Ramesh",
                "username": "ramesh_kirana"
            },
            "data": "false_ev_tel_001",
            "message": {
                "message_id": 101,
                "date": 1773220000
            }
        }
    }

    res = client.post("/webhook/telegram", json=cq_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "processed"
    assert data["type"] == "callback_query"
    assert data["triage"]["button_id"] == "false_ev_tel_001"
    assert len(triage_log) == 1
    assert triage_log[0]["source"] == "telegram"
    assert triage_log[0]["button_id"] == "false_ev_tel_001"

    # 2. Simulate shopkeeper tapping [⭐ Star Clip]
    star_payload = {
        "update_id": 9992,
        "callback_query": {
            "id": "cq_12346",
            "from": {"id": 987654321, "first_name": "Ramesh"},
            "data": "star_ev_tel_001"
        }
    }
    client.post("/webhook/telegram", json=star_payload)
    assert len(triage_log) == 2
    assert triage_log[1]["title"] == "Star Clip"

    # 3. Simulate shopkeeper sending command /status
    cmd_payload = {
        "update_id": 9993,
        "message": {
            "message_id": 102,
            "from": {"id": 987654321},
            "chat": {"id": 987654321},
            "text": "/status"
        }
    }
    res_cmd = client.post("/webhook/telegram", json=cmd_payload)
    assert res_cmd.status_code == 200
    cmd_data = res_cmd.json()
    assert cmd_data["type"] == "command"
    assert cmd_data["command"] == "/status"
    assert "Fleet Status" in cmd_data["reply_text"]
