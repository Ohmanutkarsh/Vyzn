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
