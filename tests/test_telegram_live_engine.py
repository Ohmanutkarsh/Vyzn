"""
Unit and integration tests for Telegram Alert Provider, CGNAT Long-Polling Worker,
Two-Way Inline Keyboard Triage, and Cloud Fleet Reverse Proxy.
"""

import os
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from vyzn.alerts.telegram import (
    TelegramAlertProvider,
    TelegramPollingWorker,
    start_telegram_poller,
    stop_telegram_poller,
    get_active_poller,
    test_telegram_connection,
    send_telegram_threat_alert
)
from vyzn.core.events import EventRecord
from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings
from vyzn.scoring.calibrator import AdaptiveCalibrator
from vyzn.api.routes import app, init_api
from vyzn_cloud.app import cloud_app
from vyzn_cloud.watchdog import DeadManWatchdog
import vyzn_cloud.fleet_routes as fleet_routes


def test_telegram_alert_payload_and_simulation():
    """Verifies Telegram alert caption construction and simulation fallback."""
    provider = TelegramAlertProvider()
    
    event = EventRecord(
        event_group_id="ev_tele_test_01",
        camera_id="cam_vault",
        start_time="2026-09-11T20:00:00Z",
        end_time="2026-09-11T20:00:15Z",
        score=92,
        object_type="person",
        confidence=0.94,
        dominant_color="red",
        zone_name="secure_vault",
        starred=0
    )

    payload = provider.build_alert_payload(event)
    caption = payload["caption"]
    markup = payload["reply_markup"]

    # Verify formatting
    assert "`cam_vault` (secure_vault)" in caption
    assert "*92/100*" in caption
    assert "`PERSON`" in caption
    assert "RED" in caption

    # Verify inline keyboard triage buttons
    buttons = markup["inline_keyboard"][0]
    assert len(buttons) == 2
    assert buttons[0]["callback_data"] == "star_ev_tele_test_01"
    assert "Star Clip" in buttons[0]["text"]
    assert buttons[1]["callback_data"] == "false_ev_tele_test_01"
    assert "False Alarm" in buttons[1]["text"]

    # In simulation mode (no token/chat), send_alert returns True without network error
    assert provider.send_alert(event) is True


def test_telegram_worker_callbacks(tmp_path: Path):
    """Verifies that long-polling callback queries update DB and recalibrate AI."""
    db_path = tmp_path / "test_poller.db"
    db = EventDatabase(db_path)
    calibrator = AdaptiveCalibrator(db=db)

    # Insert test incident
    ev = EventRecord(
        event_group_id="ev_poll_42",
        camera_id="cam_front",
        start_time="2026-09-11T21:00:00Z",
        end_time="2026-09-11T21:00:10Z",
        score=78,
        object_type="person",
        dominant_color="blue",
        zone_name="general",
        starred=0,
        user_triage="unreviewed"
    )
    db.insert_event(ev)
    time.sleep(0.15)

    worker = TelegramPollingWorker(bot_token="123456:FAKE_TOKEN", db=db, calibrator=calibrator)

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200

        # 1. Simulate user tapping [⭐ Star Clip] in Telegram
        star_update = {
            "update_id": 1001,
            "callback_query": {
                "id": "cq_star_1",
                "data": "star_ev_poll_42",
                "from": {"first_name": "Vikram"}
            }
        }
        res_star = worker.handle_update(star_update)
        assert res_star is not None
        assert "evidence" in res_star["result"]
        time.sleep(0.15)

        saved_ev = db.get_event("ev_poll_42")
        assert saved_ev.starred == 1

        # 2. Simulate user tapping [❌ False Alarm] in Telegram
        false_update = {
            "update_id": 1002,
            "callback_query": {
                "id": "cq_false_2",
                "data": "false_ev_poll_42",
                "from": {"first_name": "Vikram"}
            }
        }
        res_false = worker.handle_update(false_update)
        assert res_false is not None
        assert "calibrated" in res_false["result"]
        time.sleep(0.15)

        saved_ev2 = db.get_event("ev_poll_42")
        assert saved_ev2.user_triage == "false_positive"

    db.close()


def test_telegram_api_settings_and_test_ping(tmp_path: Path):
    """Verifies Telegram configuration, ping validation, and dispatch endpoints."""
    db_path = tmp_path / "api_tele.db"
    db = EventDatabase(db_path)
    settings = EdgeSettings(data_dir=tmp_path, db_path=db_path)
    init_api(db=db, settings=settings)

    client = TestClient(app)

    # 1. Initial GET
    resp = client.get("/api/v1/alerts/telegram")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert "poller_active" in data

    # 2. POST update config
    resp = client.post("/api/v1/alerts/telegram", json={
        "bot_token": "1234567890:AAH_test_token_string_abc",
        "chat_id": "-100987654321",
        "enable_poller": False
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "updated"
    assert data["configured"] is True
    assert settings.telegram_bot_token == "1234567890:AAH_test_token_string_abc"
    assert settings.telegram_chat_id == "-100987654321"

    # Verify masking in GET
    resp2 = client.get("/api/v1/alerts/telegram")
    data2 = resp2.json()
    assert data2["configured"] is True
    assert data2["bot_token_masked"].startswith("123456...")

    # 3. Test Ping validation endpoint
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        # Mock getMe
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "ok": True,
            "result": {"username": "VyznNetraSecurityBot"}
        }
        # Mock sendMessage
        mock_post.return_value.status_code = 200

        ping_resp = client.post("/api/v1/alerts/telegram/test-ping", json={
            "bot_token": "1234567890:AAH_test_token_string_abc",
            "chat_id": "-100987654321"
        })
        assert ping_resp.status_code == 200
        ping_data = ping_resp.json()
        assert ping_data["ok"] is True
        assert ping_data["bot_username"] == "VyznNetraSecurityBot"
        assert ping_data["latency_ms"] >= 0

    # 4. Manual Event Dispatch
    ev = EventRecord(
        event_group_id="ev_dispatch_test",
        camera_id="cam_main",
        start_time="2026-09-11T21:30:00Z",
        end_time="2026-09-11T21:30:10Z",
        score=85,
        object_type="person",
        dominant_color="black",
        zone_name="counter"
    )
    db.insert_event(ev)
    time.sleep(0.15)

    # In test mode with mocked requests
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        disp_resp = client.post("/api/v1/events/ev_dispatch_test/dispatch-telegram")
        assert disp_resp.status_code == 200
        assert disp_resp.json()["status"] == "dispatched"

    db.close()


def test_cloud_fleet_reverse_proxy():
    """Verifies that the Cloud Fleet manager proxies requests to edge nodes through CGNAT."""
    watchdog = DeadManWatchdog()
    watchdog.record_heartbeat(
        site_id="site_proxy_test",
        payload={"timestamp": "2026-09-11T22:00:00Z", "api_port": 8000},
        client_host="127.0.0.1"
    )
    fleet_routes.set_watchdog(watchdog)

    client = TestClient(cloud_app)

    # 1. Successful proxy mock
    with patch("httpx.AsyncClient.request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"status": "edge_online", "site": "site_proxy_test"}'
        mock_response.headers = {"content-type": "application/json"}
        mock_req.return_value = mock_response

        resp = client.get("/fleet/proxy/site_proxy_test/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "edge_online"

    # 2. Unreachable edge handles error gracefully with 502 HTML fallback
    with patch("httpx.AsyncClient.request", side_effect=Exception("Connection refused")):
        resp2 = client.get("/fleet/proxy/site_proxy_test/api/status")
        assert resp2.status_code == 502
        assert "Edge Gateway Unreachable" in resp2.text
