from datetime import datetime, timezone
from pathlib import Path
from starlette.testclient import TestClient

from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings
from vyzn.core.events import EventRecord
from vyzn.api.routes import app, init_api
from vyzn.alerts.telegram import (
    TelegramAlertProvider,
    send_telegram_threat_alert,
    process_telegram_update
)


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
    assert "🚨 VYZN Security Alert" in caption

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


def test_telegram_single_use_token_linking_and_rejection(tmp_path: Path):
    db_file = tmp_path / "tg_test.db"
    db = EventDatabase(db_file)

    user = db.get_or_create_user("alice@shop.com")
    user_id = user["id"]
    db.update_user_phone(user_id, "+919876543210", verified=False)

    # 1. Generate link token (10 min TTL)
    token = db.create_telegram_link(user_id, phone_e164="+919876543210", ttl_sec=600)
    assert token is not None

    link_row = db.get_telegram_link(token)
    assert link_row["status"] == "pending"

    # 2. First consumption: success
    ok, reason, data = db.consume_telegram_link(
        token=token,
        chat_id="chat_12345",
        telegram_user_id="tg_usr_99",
        username="alice_tg"
    )
    assert ok is True
    assert reason == "success"

    user = db.get_user_by_id(user_id)
    assert user["telegram_status"] == "linked"
    assert user["telegram_chat_id"] == "chat_12345"
    assert user["telegram_username"] == "alice_tg"
    assert user["telegram_alerts_enabled"] == 1

    # 3. Second consumption of the same token: rejected (single-use)
    ok_again, reason_again, _ = db.consume_telegram_link(
        token=token,
        chat_id="chat_12345",
        telegram_user_id="tg_usr_99"
    )
    assert ok_again is False
    assert reason_again == "already_used"


def test_telegram_expired_and_invalid_token(tmp_path: Path):
    db_file = tmp_path / "tg_expire.db"
    db = EventDatabase(db_file)

    user = db.get_or_create_user("bob@shop.com")
    user_id = user["id"]

    # Invalid token
    ok, reason, _ = db.consume_telegram_link("non_existent_token_123", "chat_99", "tg_99")
    assert ok is False
    assert reason == "invalid_token"

    # Expired token (negative TTL)
    token = db.create_telegram_link(user_id, ttl_sec=-10)
    ok_exp, reason_exp, _ = db.consume_telegram_link(token, "chat_99", "tg_99")
    assert ok_exp is False
    assert reason_exp == "expired_token"


def test_telegram_duplicate_chat_prevention(tmp_path: Path):
    db_file = tmp_path / "tg_dup.db"
    db = EventDatabase(db_file)

    # User 1 binds chat_shared
    u1 = db.get_or_create_user("owner1@shop.com")
    token1 = db.create_telegram_link(u1["id"], ttl_sec=600)
    ok1, reason1, _ = db.consume_telegram_link(token1, "chat_shared_999", "tg_usr_1", "owner1")
    assert ok1 is True

    # User 2 attempts to bind the same chat_shared
    u2 = db.get_or_create_user("owner2@shop.com")
    token2 = db.create_telegram_link(u2["id"], ttl_sec=600)
    ok2, reason2, _ = db.consume_telegram_link(token2, "chat_shared_999", "tg_usr_2", "owner2")
    assert ok2 is False
    assert reason2 == "duplicate_chat"


def test_telegram_disconnect_and_alerts_muting(tmp_path: Path):
    db_file = tmp_path / "tg_mute.db"
    db = EventDatabase(db_file)

    email = "charlie@shop.com"
    u = db.get_or_create_user(email)
    user_id = u["id"]
    token = db.create_telegram_link(user_id, ttl_sec=600)
    db.consume_telegram_link(token, "chat_charlie_777", "tg_charlie", "charlie_tg")

    provider = TelegramAlertProvider(db=db)
    event = EventRecord(
        event_group_id="ev_charlie_01",
        camera_id="cam_main",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.9,
        score=85,
        tier="alert",
        owner_email=email
    )

    # 1. Normal state: linked and alerts enabled -> sends alert
    assert provider.send_alert(event) is True

    # 2. User mutes alerts
    db.set_user_telegram_alerts(user_id, False)
    user_muted = db.get_user_by_id(user_id)
    assert user_muted["telegram_alerts_enabled"] == 0
    # Alerts must be suppressed
    assert provider.send_alert(event) is False

    # 3. User unmutes alerts
    db.set_user_telegram_alerts(user_id, True)
    assert provider.send_alert(event) is True

    # 4. User disconnects Telegram
    db.disconnect_user_telegram(user_id)
    user_disconnected = db.get_user_by_id(user_id)
    assert user_disconnected["telegram_status"] == "not_linked"
    assert user_disconnected["telegram_chat_id"] is None
    # Alerts must be suppressed
    assert provider.send_alert(event) is False


def test_telegram_webhook_and_process_update(tmp_path: Path):
    db_file = tmp_path / "tg_webhook.db"
    db = EventDatabase(db_file)

    u = db.get_or_create_user("david@shop.com")
    user_id = u["id"]
    token = db.create_telegram_link(user_id, ttl_sec=600)

    # 1. Process /start <token>
    update_start = {
        "update_id": 1001,
        "message": {
            "message_id": 501,
            "from": {"id": 888123, "first_name": "David", "username": "david_cctv"},
            "chat": {"id": 888123},
            "text": f"/start {token}"
        }
    }
    result_start = process_telegram_update(update_start, db=db)
    assert result_start is not None
    assert result_start["type"] == "telegram_linked_success"
    assert result_start["user_id"] == user_id

    # 2. Process callback triage (Not an issue)
    update_triage = {
        "update_id": 1002,
        "callback_query": {
            "id": "cq_888",
            "from": {"id": 888123, "first_name": "David"},
            "data": "not_an_issue_ev_9999"
        }
    }
    result_triage = process_telegram_update(update_triage, db=db)
    assert result_triage is not None
    assert result_triage["type"] == "callback_query"

    # 3. Process /stop
    update_stop = {
        "update_id": 1003,
        "message": {
            "message_id": 502,
            "from": {"id": 888123},
            "chat": {"id": 888123},
            "text": "/stop"
        }
    }
    result_stop = process_telegram_update(update_stop, db=db)
    assert result_stop is not None
    assert result_stop["type"] == "telegram_stopped"

    user = db.get_user_by_id(user_id)
    assert user["telegram_status"] == "not_linked"


def test_telegram_api_endpoints_workflow(tmp_path: Path):
    db_file = tmp_path / "tg_api.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_tg_api",
        data_dir=tmp_path,
        db_path=db_file,
        telegram_bot_token=""
    )
    init_api(db, settings)
    client = TestClient(app)

    # 1. Sign in to obtain session
    user = db.get_or_create_user("owner_tg@shop.com")
    session_token = db.create_session(user["id"])
    client.cookies.set("vyzn_session", session_token)

    # 2. POST /api/telegram/link
    res = client.post("/api/telegram/link")
    assert res.status_code == 200
    link_data = res.json()
    assert link_data["ok"] is True
    assert "start=" in link_data["deepLink"]
    assert "Vyzn_security_bot" in link_data["deepLink"] or link_data["botUsername"] == "Vyzn_security_bot"
    token = link_data["token"]

    # 3. GET /api/telegram/status (waiting)
    res = client.get("/api/telegram/status")
    assert res.status_code == 200
    assert res.json()["status"] == "waiting"
    assert res.json()["connected"] is False

    # 4. POST /api/telegram/webhook simulates /start <token>
    webhook_payload = {
        "update_id": 5001,
        "message": {
            "message_id": 101,
            "from": {"id": 999888, "first_name": "StoreOwner", "username": "store_tg"},
            "chat": {"id": 999888},
            "text": f"/start {token}"
        }
    }
    res = client.post("/api/telegram/webhook", json=webhook_payload)
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # 5. GET /api/telegram/status (connected)
    res = client.get("/api/telegram/status")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["status"] == "connected"
    assert status_data["connected"] is True
    assert status_data["telegram_chat_id"] == "999888"
    assert status_data["telegram_username"] == "store_tg"
    assert status_data["telegram_alerts_enabled"] is True

    # 6. POST /api/telegram/toggle-alerts (mute)
    res = client.post("/api/telegram/toggle-alerts", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["telegram_alerts_enabled"] is False

    res = client.get("/api/telegram/status")
    assert res.json()["telegram_alerts_enabled"] is False

    # 7. POST /api/telegram/toggle-alerts (unmute)
    res = client.post("/api/telegram/toggle-alerts", json={"enabled": True})
    assert res.status_code == 200
    assert res.json()["telegram_alerts_enabled"] is True

    # 8. POST /api/telegram/disconnect
    res = client.post("/api/telegram/disconnect")
    assert res.status_code == 200
    assert res.json()["status"] == "disconnected"

    res = client.get("/api/telegram/status")
    assert res.json()["status"] != "connected"
    assert res.json()["connected"] is False


