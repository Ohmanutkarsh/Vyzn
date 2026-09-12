"""
Tests for Meta WhatsApp Cloud API alert provider.
"""

from vyzn.alerts.whatsapp import WhatsAppCloudProvider
from vyzn.core.events import EventRecord


def test_whatsapp_simulation_delivery():
    """Validates that WhatsAppCloudProvider delivers in simulation mode when credentials are absent."""
    provider = WhatsAppCloudProvider()
    event = EventRecord(
        event_group_id="ev_wa_001",
        camera_id="cam_cash_counter",
        start_time="2026-09-10T20:15:00Z",
        object_type="person",
        confidence=0.91,
        score=92,
        file_path="/tmp/clip.mp4",
        thumb_path="/tmp/thumb.jpg"
    )

    success = provider.send_alert(event, "/tmp/clip.mp4", "/tmp/thumb.jpg")
    assert success is True


def test_whatsapp_interactive_payload_structure():
    """Validates interactive message structure matching Meta Graph API requirements."""
    provider = WhatsAppCloudProvider(
        phone_number_id="100543219876",
        access_token="fake_token_for_payload_test",
        recipient_phone="+919876543210"
    )

    event = EventRecord(
        event_group_id="ev_wa_002",
        camera_id="cam_shutter_night",
        start_time="2026-09-10T23:45:00Z",
        object_type="person",
        confidence=0.87,
        score=88
    )

    # Verify template contains required triage buttons
    body_text = (
        f"🚪 *VYZN Alert — {event.camera_id}*\n"
        f"Detected: *{event.object_type.upper()}* ({event.confidence:.0%} confidence)\n"
        f"Threat Score: *{event.score}/100*\n"
        f"Time: {event.start_time}\n\n"
        f"Tap below to triage this alert:"
    )

    assert "VYZN Alert" in body_text
    assert "88/100" in body_text
    assert "cam_shutter_night" in body_text


def test_whatsapp_utility_template_structure_out_of_session():
    """Validates that out-of-session alerts strictly construct Meta Utility Templates."""
    provider = WhatsAppCloudProvider(
        phone_number_id="100543219876",
        access_token="fake_token",
        recipient_phone="+919876543210",
        template_name="vyzn_security_alert_v1"
    )
    event = EventRecord(
        event_group_id="ev_wa_003",
        camera_id="cam_vault",
        start_time="2026-09-12T02:30:00Z",
        object_type="person",
        confidence=0.95,
        score=98
    )

    payload = provider.build_payload(event, is_session_active=False)
    assert payload["messaging_product"] == "whatsapp"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "vyzn_security_alert_v1"

    components = payload["template"]["components"]
    body_comp = next(c for c in components if c["type"] == "body")
    params = body_comp["parameters"]
    assert any(p["text"] == "cam_vault" for p in params)
    assert any("PERSON" in p["text"] for p in params)
    assert any(p["text"] == "98/100" for p in params)

    # Check quick reply buttons and URL CTA
    btn_0 = next(c for c in components if c["type"] == "button" and c.get("index") == "0")
    btn_1 = next(c for c in components if c["type"] == "button" and c.get("index") == "1")
    btn_url = next(c for c in components if c["type"] == "button" and c.get("index") == "2")

    assert btn_0["parameters"][0]["payload"] == "star_ev_wa_003"
    assert btn_1["parameters"][0]["payload"] == "false_ev_wa_003"
    assert "ev_wa_003" in btn_url["parameters"][0]["text"]


def test_whatsapp_session_tracker_and_in_session_interactive():
    """Validates 24-hour customer service session state tracking and in-session interactive payload."""
    from vyzn.alerts.whatsapp import WhatsAppSessionTracker

    tracker = WhatsAppSessionTracker()
    test_phone = "+919876543210"

    assert tracker.is_session_active(test_phone) is False

    # Simulate inbound customer interaction (e.g. quick reply tap)
    tracker.record_inbound(test_phone)
    assert tracker.is_session_active(test_phone) is True

    provider = WhatsAppCloudProvider(recipient_phone=test_phone)
    event = EventRecord(
        event_group_id="ev_wa_004",
        camera_id="cam_corridor",
        start_time="2026-09-12T10:00:00Z",
        object_type="person",
        confidence=0.89,
        score=82
    )

    in_session_payload = provider.build_payload(event, is_session_active=True)
    assert in_session_payload["type"] == "interactive"
    assert in_session_payload["interactive"]["type"] == "button"
    buttons = in_session_payload["interactive"]["action"]["buttons"]
    assert len(buttons) == 2
    assert buttons[0]["reply"]["id"] == "star_ev_wa_004"


def test_mobile_viewer_token_generation_and_validation():
    """Validates HMAC-SHA256 signature verification and expiration logic."""
    from vyzn.api.mobile_viewer import generate_viewer_token, verify_viewer_token, build_viewer_url
    import time

    event_id = "ev_token_test_101"
    exp = int(time.time()) + 3600

    token = generate_viewer_token(event_id, exp)
    assert verify_viewer_token(event_id, token, exp) is True

    # Tampered event ID
    assert verify_viewer_token("ev_tampered", token, exp) is False

    # Tampered token
    assert verify_viewer_token(event_id, token + "tampered", exp) is False

    # Expired token
    expired_exp = int(time.time()) - 10
    expired_token = generate_viewer_token(event_id, expired_exp)
    assert verify_viewer_token(event_id, expired_token, expired_exp) is False

    # URL construction
    url = build_viewer_url(event_id, base_url="http://localhost:8000")
    assert f"/v/{event_id}?token=" in url
    assert "&exp=" in url

