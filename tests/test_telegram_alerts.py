import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import cv2
import numpy as np
from starlette.testclient import TestClient

from vyzn.core.database import EventDatabase
from vyzn.core.config import EdgeSettings
from vyzn.core.events import EventRecord
from vyzn.api.routes import app, init_api
from vyzn.alerts.telegram import (
    TelegramAlertProvider,
    send_telegram_threat_alert,
    process_telegram_update,
    extract_thumbnail_from_clip,
    get_alert_thumbnail_bytes,
    get_factual_event_description,
    resolve_authorized_chat_for_event
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
    assert send_telegram_threat_alert(event, bot_token="") is True


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

    provider = TelegramAlertProvider(db=db, bot_token="")
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
        telegram_bot_token="",
        telegram_webhook_secret=""
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
    assert "Vyzn_security_alert_bot" in link_data["deepLink"] or link_data["botUsername"] == "Vyzn_security_alert_bot" or "Vyzn_security_bot" in link_data["deepLink"]
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


def test_alert_eligibility_tier_filter(tmp_path: Path):
    db_file = tmp_path / "tg_tier.db"
    db = EventDatabase(db_file)
    email = "tier_test@shop.com"
    u = db.get_or_create_user(email)
    token = db.create_telegram_link(u["id"], ttl_sec=600)
    db.consume_telegram_link(token, "chat_tier_123", "tg_tier", "tier_owner")

    provider = TelegramAlertProvider(db=db, bot_token="")

    # Ineligible event: tier="review", score=40
    low_event = EventRecord(
        event_group_id="ev_low_01",
        camera_id="cam_tier",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.5,
        score=40,
        tier="review",
        owner_email=email
    )
    assert provider.send_alert(low_event) is False
    assert db.get_alert_delivery("ev_low_01", "telegram", "chat_tier_123") is None

    # Ineligible event: tier="ignore", score=10
    ignore_event = EventRecord(
        event_group_id="ev_ignore_01",
        camera_id="cam_tier",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="motion",
        confidence=0.3,
        score=10,
        tier="ignore",
        owner_email=email
    )
    assert provider.send_alert(ignore_event) is False
    assert db.get_alert_delivery("ev_ignore_01", "telegram", "chat_tier_123") is None

    # Eligible event: tier="alert", score=85
    alert_event = EventRecord(
        event_group_id="ev_alert_01",
        camera_id="cam_tier",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.92,
        score=85,
        tier="alert",
        owner_email=email
    )
    assert provider.send_alert(alert_event) is True
    deliv = db.get_alert_delivery("ev_alert_01", "telegram", "chat_tier_123")
    assert deliv is not None
    assert deliv["status"] == "delivered"


def test_alert_ingress_eligibility_and_404_handling(tmp_path: Path):
    db_file = tmp_path / "tg_ingress_err.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_ingress_test",
        data_dir=tmp_path,
        db_path=db_file,
        telegram_bot_token="",
        internal_alert_token=""
    )
    init_api(db, settings)
    client = TestClient(app)

    # 1. Non-existent event returns 404
    res = client.post("/api/v1/alerts/ingress", json={"event_id": "non_existent_event_999"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

    # 2. Insert non-alert tier event (score=45, tier="review")
    review_event = EventRecord(
        event_group_id="ev_review_99",
        camera_id="cam_test",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.6,
        score=45,
        tier="review",
        owner_email="test@shop.com"
    )
    db.insert_event(review_event)

    # Ineligible tier returns 422
    res = client.post("/api/v1/alerts/ingress", json={"event_id": "ev_review_99", "tier": "review"})
    assert res.status_code == 422
    assert "ineligible" in res.json()["detail"].lower()


def test_thumbnail_extraction_from_mp4_preserves_original_video(tmp_path: Path):
    clip_file = tmp_path / "cctv_sample.mp4"

    # Generate synthetic 1-second 4fps MP4 video
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(clip_file), fourcc, 4.0, (320, 240))
    for i in range(4):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        # Add colored shape to guarantee variance / non-black frame
        frame[40:180, 40:180] = (50 * (i + 1), 180, 220)
        writer.write(frame)
    writer.release()

    assert clip_file.exists()
    orig_size = clip_file.stat().st_size
    orig_sha = hashlib.sha256(clip_file.read_bytes()).hexdigest()

    # Extract thumbnail
    thumb_bytes = extract_thumbnail_from_clip(str(clip_file), target_time_sec=0.5)
    assert thumb_bytes is not None
    assert isinstance(thumb_bytes, bytes)
    assert len(thumb_bytes) > 200
    # Must be valid JPEG
    assert thumb_bytes.startswith(b"\xff\xd8\xff")

    # STRICT ASSERTION: Original video must NOT be deleted, truncated, or modified
    assert clip_file.exists()
    assert clip_file.stat().st_size == orig_size
    new_sha = hashlib.sha256(clip_file.read_bytes()).hexdigest()
    assert new_sha == orig_sha

    # Test error cases: non-existent file returns None
    assert extract_thumbnail_from_clip(str(tmp_path / "non_existent.mp4")) is None

    # Test error cases: 0-byte corrupted file returns None
    corrupt_file = tmp_path / "empty.mp4"
    corrupt_file.write_bytes(b"")
    assert extract_thumbnail_from_clip(str(corrupt_file)) is None


def test_negative_no_video_sent_and_text_fallback_on_missing_clip(tmp_path: Path, monkeypatch):
    import requests

    db_file = tmp_path / "tg_novideo.db"
    db = EventDatabase(db_file)
    email = "novideo@shop.com"
    u = db.get_or_create_user(email)
    token = db.create_telegram_link(u["id"], ttl_sec=600)
    db.consume_telegram_link(token, "chat_novideo_111", "tg_novideo", "novideo_tg")

    calls = []

    def mock_post(url, *args, **kwargs):
        calls.append({"url": url, "args": args, "kwargs": kwargs})
        class MockResp:
            status_code = 200
            text = '{"ok": true, "result": {"message_id": 999}}'
            def json(self):
                return {"ok": True, "result": {"message_id": 999}}
        return MockResp()

    monkeypatch.setattr(requests, "post", mock_post)

    provider = TelegramAlertProvider(bot_token="test_bot_token_123", chat_id="chat_novideo_111", db=db)

    # Event with non-existent clip path and non-existent thumb path
    missing_media_event = EventRecord(
        event_group_id="ev_missing_media_01",
        camera_id="cam_gate",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.9,
        score=88,
        tier="alert",
        owner_email=email,
        file_path=str(tmp_path / "does_not_exist.mp4"),
        thumb_path=str(tmp_path / "does_not_exist.jpg")
    )

    # Verify thumbnail bytes resolver returns None
    assert get_alert_thumbnail_bytes(missing_media_event) is None

    # Send alert
    success = provider.send_alert(missing_media_event)
    assert success is True

    # Assert exactly 1 request made, to sendMessage (text-only fallback)
    assert len(calls) == 1
    call_url = calls[0]["url"]
    assert call_url.endswith("/sendMessage")
    assert not call_url.endswith("/sendVideo")
    assert not call_url.endswith("/sendPhoto")

    # Assert caption text explains thumbnail unavailable
    sent_json = calls[0]["kwargs"].get("json", {})
    assert "Thumbnail snapshot unavailable" in sent_json.get("text", "")

    # STRICT CODEBASE ASSERTION: sendVideo is never an attribute or callable
    assert not hasattr(provider, "send_video")
    assert not hasattr(provider, "sendVideo")


def test_factual_caption_and_mobile_char_limits():
    provider = TelegramAlertProvider()

    # Case 1: Long forensic summary -> only first sentence is extracted
    event1 = EventRecord(
        event_group_id="ev_cap_01",
        camera_id="cam_front",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.91,
        score=85,
        tier="alert",
        summary="A person entered the restricted entrance area. The subject was wearing dark clothing. Secondary movement observed.",
        title="Unauthorized entry detected"
    )
    desc1 = get_factual_event_description(event1, "Front Entrance")
    assert desc1 == "A person entered the restricted entrance area."

    payload1 = provider.build_alert_payload(event1, camera_name="Front Entrance")
    caption1 = payload1["caption"]
    assert len(caption1) <= 1024
    assert "Front Entrance" in caption1
    assert "A person entered the restricted entrance area." in caption1
    # Check no raw bounding boxes or floating confidence leak
    assert "0.91" not in caption1
    assert "[" not in caption1 or "[x" not in caption1

    # Case 2: Headline fallback
    event2 = EventRecord(
        event_group_id="ev_cap_02",
        camera_id="cam_back",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="vehicle",
        confidence=0.88,
        score=75,
        tier="alert"
    )
    desc2 = get_factual_event_description(event2, "Back Yard")
    assert "vehicle" in desc2.lower() or "movement" in desc2.lower()

    payload2 = provider.build_alert_payload(event2, camera_name="Back Yard")
    assert len(payload2["caption"]) <= 1024


def test_webhook_secret_token_header_validation(tmp_path: Path):
    db_file = tmp_path / "tg_webhook_sec.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_sec_test",
        data_dir=tmp_path,
        db_path=db_file,
        telegram_webhook_secret="super_secret_webhook_token_999"
    )
    init_api(db, settings)
    client = TestClient(app)

    payload = {
        "update_id": 9001,
        "message": {
            "message_id": 1,
            "chat": {"id": 12345},
            "from": {"id": 12345},
            "text": "/help"
        }
    }

    # 1. Missing secret token header -> 403 Forbidden
    res_no_hdr = client.post("/api/telegram/webhook", json=payload)
    assert res_no_hdr.status_code == 403

    # 2. Invalid secret token header -> 403 Forbidden
    res_bad_hdr = client.post(
        "/api/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret_123"}
    )
    assert res_bad_hdr.status_code == 403

    # 3. Valid secret token header -> 200 OK
    res_ok = client.post(
        "/api/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_webhook_token_999"}
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["ok"] is True


def test_server_to_server_ingress_authentication_and_idempotency(tmp_path: Path):
    db_file = tmp_path / "tg_ingress_auth.db"
    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_ingress_auth",
        data_dir=tmp_path,
        db_path=db_file,
        internal_alert_token="internal_secret_key_888",
        telegram_bot_token=""  # simulation mode
    )
    init_api(db, settings)
    client = TestClient(app)

    # Setup authorized customer and camera
    email = "ingress_owner@shop.com"
    user = db.get_or_create_user(email)
    token = db.create_telegram_link(user["id"], ttl_sec=600)
    db.consume_telegram_link(token, "chat_ingress_888", "tg_owner", "ingress_owner")

    # Insert valid alert event
    ev = EventRecord(
        event_group_id="ev_ingress_s2s_01",
        camera_id="cam_ingress",
        start_time=datetime.now(timezone.utc).isoformat(),
        object_type="person",
        confidence=0.95,
        score=90,
        tier="alert",
        owner_email=email
    )
    db.insert_event(ev)

    # 1. Missing auth header -> 401 Unauthorized
    res_no_auth = client.post(
        "/api/v1/alerts/ingress",
        json={"event_id": "ev_ingress_s2s_01"}
    )
    assert res_no_auth.status_code == 401

    # 2. Invalid auth header -> 401 Unauthorized
    res_bad_auth = client.post(
        "/api/v1/alerts/ingress",
        json={"event_id": "ev_ingress_s2s_01"},
        headers={"Authorization": "Bearer bad_token_123"}
    )
    assert res_bad_auth.status_code == 401

    # 3. Valid auth header -> 200 OK (delivered)
    res_ok = client.post(
        "/api/v1/alerts/ingress",
        json={"event_id": "ev_ingress_s2s_01"},
        headers={"Authorization": "Bearer internal_secret_key_888"}
    )
    assert res_ok.status_code == 200
    data_ok = res_ok.json()
    assert data_ok["ok"] is True
    assert data_ok["status"] == "delivered"
    assert data_ok["recipient_chat_id"] == "chat_ingress_888"

    # 4. Repeated dispatch (idempotency check) -> status "already_delivered"
    res_repeat = client.post(
        "/api/v1/alerts/ingress",
        json={"event_id": "ev_ingress_s2s_01"},
        headers={"Authorization": "Bearer internal_secret_key_888"}
    )
    assert res_repeat.status_code == 200
    data_repeat = res_repeat.json()
    assert data_repeat["ok"] is True
    assert data_repeat["status"] == "already_delivered"


def test_telegram_bot_commands_extended(tmp_path: Path):
    db_file = tmp_path / "tg_cmds.db"
    db = EventDatabase(db_file)

    email = "cmd_tester@shop.com"
    user = db.get_or_create_user(email)
    chat_id = "chat_cmd_777"
    token = db.create_telegram_link(user["id"], ttl_sec=600)

    # 1. /help command
    update_help = {
        "update_id": 7001,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "text": "/help"
        }
    }
    res_help = process_telegram_update(update_help, db=db)
    assert res_help["type"] == "help"

    # 2. /status command prior to linking
    update_status_pre = {
        "update_id": 7002,
        "message": {
            "message_id": 2,
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "text": "/status"
        }
    }
    res_status_pre = process_telegram_update(update_status_pre, db=db)
    assert res_status_pre["type"] == "status"
    assert res_status_pre["connected"] is False

    # Link account
    db.consume_telegram_link(token, chat_id, "tg_usr_cmd", "tester")

    # 3. /status command after linking
    res_status_post = process_telegram_update(update_status_pre, db=db)
    assert res_status_post["type"] == "status"
    assert res_status_post["connected"] is True
    assert res_status_post["alerts_enabled"] is True

    # 4. /disconnect command
    update_disc = {
        "update_id": 7003,
        "message": {
            "message_id": 3,
            "chat": {"id": chat_id},
            "from": {"id": chat_id},
            "text": "/disconnect"
        }
    }
    res_disc = process_telegram_update(update_disc, db=db)
    assert res_disc["type"] == "disconnected"

    # Verify unlinked in DB
    u_after = db.get_user_by_id(user["id"])
    assert u_after["telegram_status"] == "not_linked"
    assert u_after["telegram_chat_id"] is None


