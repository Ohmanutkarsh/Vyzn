"""
Phase 5 Test Suite: Flags, Clips, Drawer, Evidence Pack, and Telegram Triage.

Covers:
1. Clip data model, sequential clip numbers, SHA-256 calculation, and SQLite persistence.
2. Compound clip querying (camera, tier, status, what, date range, pagination).
3. Flags retrieval (ordered alert then review, newest first, 12h expiry count).
4. Status update lifecycle: reviewed, not_an_issue with feedback categories, and unreviewed (Undo).
5. Evidence pack generation: ZIP structure (MP4, summary.pdf, metadata.json, HASH.txt, README.txt),
   SHA-256 match, ReportLab PDF validity, Section 63 BSA statutory notice, and 0 prohibited claims.
6. Appendix B Telegram alert push (calm format, photo, inline triage buttons) and review-tier silencing.
7. Telegram callback query triage handler (marking not_an_issue).
8. REST API endpoints: GET /api/clips, GET /api/clips/flags, GET /api/clips/{id}, PATCH /api/clips/{id},
   GET /api/clips/{id}/evidence-pack.
9. Appendix D grep gate verifying zero forbidden words in Phase 5 UI and i18n files.
"""

import os
import io
import re
import json
import time
import zipfile
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi.testclient import TestClient

from vyzn.core.config import EdgeSettings, CameraConfig, WatchAreaConfig
from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord
from vyzn.storage.evidence_pack import (
    generate_evidence_pack,
    generate_summary_pdf,
    README_TEXT
)
from vyzn.alerts.telegram import (
    format_alert_headline,
    format_alert_when,
    push_telegram_alert,
    TelegramPollingWorker
)
from vyzn.api.routes import app, init_api


@pytest.fixture
def env_setup(tmp_path):
    db_file = tmp_path / "test_clips.db"
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    db = EventDatabase(db_file)
    settings = EdgeSettings(
        site_id="site_mumbai_01",
        data_dir=clips_dir,
        db_path=db_file,
        telegram_chat_id="123456789",
        telegram_bot_token="test_bot_token_mock",
        cameras=[
            CameraConfig(
                camera_id="cam_entrance",
                name="Shop entrance",
                rtsp_url="test://entrance",
                enabled=True
            ),
            CameraConfig(
                camera_id="cam_counter",
                name="Cash counter",
                rtsp_url="test://counter",
                enabled=True
            )
        ]
    )

    init_api(db, settings)
    yield db, settings, clips_dir
    db.close()


def create_dummy_mp4() -> bytes:
    """Minimal fake MP4 byte payload for testing hashing and packing."""
    return b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08free" + (b"\xaa" * 1024)


def create_dummy_jpeg() -> bytes:
    """Minimal valid 1x1 JPEG byte stream."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    )


def make_test_event(
    event_group_id: str,
    camera_id: str = "cam_counter",
    camera_name: str = None,
    timestamp: float = None,
    tier: str = "alert",
    clip_number: int = 1,
    object_type: str = "person",
    file_path: str = "clip.mp4",
    thumb_path: str = "thumb.jpg",
    sha256: str = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    expires_at_ms: int = None,
    reasons: list = None,
    trigger_ms: int = None,
    boxes: list = None,
    detector: str = "person"
) -> EventRecord:
    t = timestamp if timestamp is not None else time.time()
    iso_start = datetime.fromtimestamp(t, timezone.utc).isoformat()
    iso_end = datetime.fromtimestamp(t + 15, timezone.utc).isoformat()
    now_ms = int(t * 1000)
    exp = expires_at_ms if expires_at_ms is not None else (now_ms + 72 * 3600 * 1000)
    resolved_cam_name = camera_name or ("Cash counter" if "counter" in camera_id else "Shop entrance")
    meta = {
        "camera_name": resolved_cam_name,
        "reasons": reasons if reasons is not None else [{
            "id": "entered_restricted_area",
            "label": f"Entered {resolved_cam_name}",
            "watch_area_name": resolved_cam_name
        }],
        "trigger_ms": trigger_ms if trigger_ms is not None else (now_ms + 3000),
        "boxes": boxes if boxes is not None else [[0.2, 0.2, 0.4, 0.4]],
        "detector": detector
    }
    return EventRecord(
        event_group_id=event_group_id,
        camera_id=camera_id,
        start_time=iso_start,
        end_time=iso_end,
        object_type=object_type,
        score=85 if tier == "alert" else 40,
        file_path=file_path,
        thumb_path=thumb_path,
        clip_number=clip_number,
        tier=tier,
        sha256=sha256,
        expires_at_ms=exp,
        metadata_json=json.dumps(meta)
    )


def test_clip_database_model_and_sequential_number(env_setup):
    """Test clip persistence, sequential numbering, SHA-256 storage, and Section 7.2 schema."""
    db, settings, clips_dir = env_setup
    now_ms = int(time.time() * 1000)

    video_data = create_dummy_mp4()
    sha256_hash = hashlib.sha256(video_data).hexdigest()

    ev1 = make_test_event(
        event_group_id="ev_001",
        camera_id="cam_counter",
        timestamp=time.time(),
        tier="alert",
        clip_number=1,
        sha256=sha256_hash,
        file_path="clip_001.mp4",
        thumb_path="thumb_001.jpg",
        reasons=[{
            "id": "entered_restricted_area",
            "label": "Entered Cash counter",
            "watch_area_name": "Cash counter"
        }]
    )
    db.insert_event(ev1)
    db.flush()

    ev2 = make_test_event(
        event_group_id="ev_002",
        camera_id="cam_entrance",
        timestamp=time.time() + 10,
        tier="review",
        clip_number=2,
        sha256=sha256_hash,
        file_path="clip_002.mp4",
        thumb_path="thumb_002.jpg",
        reasons=[{
            "id": "person_detected",
            "label": "Person in Shop entrance",
            "watch_area_name": "Shop entrance"
        }]
    )
    db.insert_event(ev2)
    db.flush()

    # Query by UUID
    retrieved = db.get_clip_by_id(ev1.event_group_id)
    assert retrieved is not None
    assert retrieved["clip_number"] == 1
    assert retrieved["camera_name"] == "Cash counter"
    assert retrieved["tier"] == "alert"
    assert retrieved["status"] == "unreviewed"
    assert retrieved["sha256"] == sha256_hash
    assert retrieved["detector"] == "person"
    assert len(retrieved["reasons"]) == 1
    assert retrieved["reasons"][0]["id"] == "entered_restricted_area"
    assert retrieved["duration_seconds"] > 0
    assert "urls" in retrieved
    assert retrieved["urls"]["video"] == f"/api/clips/{ev1.event_group_id}/video"

    # Query by clip number string: "1" and "clip-1"
    clip_by_num = db.get_clip_by_id("1")
    assert clip_by_num is not None
    assert clip_by_num["id"] == ev1.event_group_id

    clip_by_str = db.get_clip_by_id("clip-1")
    assert clip_by_str is not None
    assert clip_by_str["id"] == ev1.event_group_id

    # Verify clip 2
    clip_2 = db.get_clip_by_id("clip-2")
    assert clip_2 is not None
    assert clip_2["clip_number"] == 2
    assert clip_2["tier"] == "review"


def test_query_clips_compound_filters(env_setup):
    """Test multi-dimensional filtering across camera, tier, status, what, time ranges, and pagination."""
    db, settings, clips_dir = env_setup
    base_time = int(time.time()) - 10000

    events = [
        # 0: cam_counter, alert, unreviewed, person
        make_test_event("ev_q0", camera_id="cam_counter", timestamp=base_time + 100, tier="alert", clip_number=1, object_type="person"),
        # 1: cam_counter, review, reviewed, dog
        make_test_event("ev_q1", camera_id="cam_counter", timestamp=base_time + 200, tier="review", clip_number=2, object_type="dog"),
        # 2: cam_entrance, alert, not_an_issue, person
        make_test_event("ev_q2", camera_id="cam_entrance", timestamp=base_time + 300, tier="alert", clip_number=3, object_type="person"),
        # 3: cam_entrance, review, unreviewed, vehicle
        make_test_event("ev_q3", camera_id="cam_entrance", timestamp=base_time + 400, tier="review", clip_number=4, object_type="vehicle"),
        # 4: cam_entrance, alert, unreviewed, person
        make_test_event("ev_q4", camera_id="cam_entrance", timestamp=base_time + 500, tier="alert", clip_number=5, object_type="person"),
    ]

    for ev in events:
        db.insert_event(ev)
    db.flush()

    # Set statuses
    db.update_clip_status(events[1].event_group_id, "reviewed")
    db.update_clip_status(events[2].event_group_id, "not_an_issue", "staff_or_expected")
    db.flush()

    # Filter 1: Camera
    res = db.query_clips(camera_id="cam_counter")
    assert res["total"] == 2

    # Filter 2: Tier
    res = db.query_clips(tier="alert")
    assert res["total"] == 3

    # Filter 3: Status
    res = db.query_clips(status="unreviewed")
    assert res["total"] == 3
    res_reviewed = db.query_clips(status="reviewed")
    assert res_reviewed["total"] == 1
    res_not_issue = db.query_clips(status="not_an_issue")
    assert res_not_issue["total"] == 1

    # Filter 4: What (detector / object_type)
    res = db.query_clips(object_type="person")
    assert res["total"] == 3
    res_dog = db.query_clips(object_type="dog")
    assert res_dog["total"] == 1

    # Filter 5: Date range
    res = db.query_clips(from_ms=(base_time + 150) * 1000, to_ms=(base_time + 450) * 1000)
    assert res["total"] == 3

    # Filter 6: Compound filter (entrance + alert + unreviewed)
    res = db.query_clips(camera_id="cam_entrance", tier="alert", status="unreviewed")
    assert res["total"] == 1
    assert res["clips"][0]["clip_number"] == 5

    # Filter 7: Pagination
    res = db.query_clips(page=1, per_page=2)
    assert len(res["clips"]) == 2
    assert res["total"] == 5
    assert res["total_pages"] == 3


def test_get_unreviewed_flags_ordering_and_expiry(env_setup):
    """
    Section 6.2 Flags panel ordering test:
    - Alerts before Reviews
    - Within each group: newest first
    - 12h expiry count correctly computed
    """
    db, settings, clips_dir = env_setup
    now = time.time()
    now_ms = int(now * 1000)

    # 1. Old alert (expires in 6 hours -> under 12h threshold)
    ev_old_alert = make_test_event(
        "ev_fl_old_alert",
        camera_id="cam_counter",
        timestamp=now - 3600,
        tier="alert",
        clip_number=1,
        expires_at_ms=now_ms + (6 * 3600 * 1000)
    )
    # 2. Newer alert (expires in 48 hours)
    ev_new_alert = make_test_event(
        "ev_fl_new_alert",
        camera_id="cam_counter",
        timestamp=now - 600,
        tier="alert",
        clip_number=2,
        expires_at_ms=now_ms + (48 * 3600 * 1000)
    )
    # 3. Old review (expires in 50 hours)
    ev_old_review = make_test_event(
        "ev_fl_old_rev",
        camera_id="cam_entrance",
        timestamp=now - 1800,
        tier="review",
        clip_number=3,
        expires_at_ms=now_ms + (50 * 3600 * 1000)
    )
    # 4. Newer review (expires in 52 hours)
    ev_new_review = make_test_event(
        "ev_fl_new_rev",
        camera_id="cam_entrance",
        timestamp=now - 300,
        tier="review",
        clip_number=4,
        expires_at_ms=now_ms + (52 * 3600 * 1000)
    )
    # 5. Reviewed alert (should be omitted from flags)
    ev_reviewed = make_test_event(
        "ev_fl_reviewed",
        camera_id="cam_counter",
        timestamp=now - 100,
        tier="alert",
        clip_number=5,
        expires_at_ms=now_ms + (70 * 3600 * 1000)
    )

    for ev in [ev_old_alert, ev_new_alert, ev_old_review, ev_new_review, ev_reviewed]:
        db.insert_event(ev)
    db.flush()

    db.update_clip_status(ev_reviewed.event_group_id, "reviewed")
    db.flush()

    flags_data = db.get_unreviewed_flags(limit=5)
    flags = flags_data["flags"]
    assert len(flags) == 4
    assert flags_data["total"] == 4
    assert flags_data["expires_soon_count"] == 1  # ev_old_alert is within 12h

    # Verify strict ordering:
    # 1st: ev_new_alert (alert, timestamp now - 600)
    # 2nd: ev_old_alert (alert, timestamp now - 3600)
    # 3rd: ev_new_review (review, timestamp now - 300)
    # 4th: ev_old_review (review, timestamp now - 1800)
    assert flags[0]["id"] == ev_new_alert.event_group_id
    assert flags[0]["tier"] == "alert"
    assert flags[1]["id"] == ev_old_alert.event_group_id
    assert flags[1]["tier"] == "alert"
    assert flags[2]["id"] == ev_new_review.event_group_id
    assert flags[2]["tier"] == "review"
    assert flags[3]["id"] == ev_old_review.event_group_id
    assert flags[3]["tier"] == "review"


def test_clip_status_lifecycle_and_undo(env_setup):
    """Tests Mark as reviewed, Not an issue (with feedback reason), and 10s Undo to unreviewed."""
    db, settings, clips_dir = env_setup

    ev = make_test_event("ev_life", camera_id="cam_counter", tier="alert", clip_number=10)
    db.insert_event(ev)
    db.flush()

    clip_id = ev.event_group_id

    # Initial state
    c = db.get_clip_by_id(clip_id)
    assert c["status"] == "unreviewed"
    assert c["reviewed_at_ms"] is None

    # Step 1: Mark as reviewed
    res = db.update_clip_status(clip_id, "reviewed")
    assert res is True
    c = db.get_clip_by_id(clip_id)
    assert c["status"] == "reviewed"
    assert c["reviewed_at_ms"] is not None

    # Step 2: Undo back to unreviewed
    res = db.update_clip_status(clip_id, "unreviewed")
    assert res is True
    c = db.get_clip_by_id(clip_id)
    assert c["status"] == "unreviewed"
    assert c["reviewed_at_ms"] is None

    # Step 3: Not an issue with feedback reason
    res = db.update_clip_status(clip_id, "not_an_issue", feedback_reason="camera_glitch", feedback_other="Glitch in stream")
    assert res is True
    c = db.get_clip_by_id(clip_id)
    assert c["status"] == "not_an_issue"
    assert c["reviewed_at_ms"] is not None

    # Step 4: Undo from not_an_issue
    res = db.update_clip_status(clip_id, "unreviewed")
    assert res is True
    c = db.get_clip_by_id(clip_id)
    assert c["status"] == "unreviewed"


def test_evidence_pack_generation(env_setup):
    """
    Evidence Pack validation:
    1. ZIP filename: VYZN-clip-NNN-YYYY-MM-DD.zip
    2. File contents: clip-NNN.mp4, summary.pdf, metadata.json, HASH.txt, README.txt
    3. HASH.txt matches SHA-256 of MP4
    4. summary.pdf is a valid ReportLab PDF (%PDF-)
    5. README.txt contains Section 63 BSA 2023 notice
    6. Zero occurrences of forbidden words (e.g., 'certified', 'court-ready', 'legally admissible')
    """
    db, settings, clips_dir = env_setup

    video_bytes = create_dummy_mp4()
    thumb_bytes = create_dummy_jpeg()
    expected_sha256 = hashlib.sha256(video_bytes).hexdigest()

    clip_dict = {
        "id": "ev_evidence_test",
        "clip_number": 42,
        "camera_id": "cam_counter",
        "camera_name": "Cash counter",
        "site_id": "site_mumbai_01",
        "site_name": "Mumbai Store",
        "tier": "alert",
        "status": "reviewed",
        "started_at_ms": int(time.time() * 1000) - 20000,
        "ended_at_ms": int(time.time() * 1000),
        "trigger_ms": int(time.time() * 1000) - 17000,
        "duration_seconds": 20.0,
        "sha256": expected_sha256,
        "reasons": [
            {"id": "entered_restricted_area", "label": "Entered Cash counter", "watch_area_name": "Cash counter"},
            {"id": "outside_shop_hours", "label": "Outside shop hours (22:00-08:00)", "watch_area_name": None}
        ],
        "detector": "person",
        "boxes": [[0.1, 0.2, 0.5, 0.6]],
        "storage": "local"
    }

    zip_bytes = generate_evidence_pack(
        clip=clip_dict,
        site_name="Mumbai Store",
        video_bytes=video_bytes,
        thumb_bytes=thumb_bytes
    )

    assert len(zip_bytes) > 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "clip-042.mp4" in namelist
        assert "summary.pdf" in namelist
        assert "metadata.json" in namelist
        assert "HASH.txt" in namelist
        assert "README.txt" in namelist

        # Verify HASH.txt
        hash_content = zf.read("HASH.txt").decode("utf-8").strip()
        assert hash_content.startswith(expected_sha256)
        assert "clip-042.mp4" in hash_content

        # Verify summary.pdf
        pdf_bytes = zf.read("summary.pdf")
        assert pdf_bytes.startswith(b"%PDF-")
        assert len(pdf_bytes) > 1000

        # Verify metadata.json
        meta = json.loads(zf.read("metadata.json").decode("utf-8"))
        assert meta["clip_number"] == 42
        assert meta["sha256"] == expected_sha256
        assert meta["site_id"] == "site_mumbai_01"
        assert meta["camera_name"] == "Cash counter"
        assert len(meta["reasons"]) == 2

        # Verify README.txt statutory statement
        readme_content = zf.read("README.txt").decode("utf-8")
        assert "Section 63 of the Bharatiya Sakshya Adhiniyam, 2023" in readme_content
        assert "VYZN does not certify evidence" in readme_content

        # Prohibited claims check (Section 6.3 spec)
        prohibited = ["court-ready", "legally admissible", "guaranteed admissible"]
        for p in prohibited:
            assert p not in readme_content.lower()


def test_telegram_alert_formatting_and_review_silencing(env_setup):
    """
    Appendix B Telegram Alert Specification Test:
    - Calm alert format
    - Correct headline resolution from reasons
    - Push alerts for Alert tier
    - Strict silencing of Review-tier clips (never pushed)
    """
    db, settings, clips_dir = env_setup

    # Test Headline Formatter with EventRecords
    ev_enter = EventRecord(
        event_group_id="ev_t_enter",
        camera_id="cam_counter",
        start_time=datetime.now(timezone.utc).isoformat(),
        metadata_json=json.dumps({"reasons": [{"id": "entered_restricted_area", "watch_area_name": "Cash counter"}]})
    )
    assert format_alert_headline(ev_enter, "Cash counter") == "Person entered Cash counter"

    ev_stay = EventRecord(
        event_group_id="ev_t_stay",
        camera_id="cam_counter",
        start_time=datetime.now(timezone.utc).isoformat(),
        metadata_json=json.dumps({"reasons": [{"id": "stayed_in_area", "watch_area_name": "Cash counter", "params": {"duration": "45 seconds"}}]})
    )
    assert format_alert_headline(ev_stay, "Cash counter") == "Person stayed 45 seconds in Cash counter"

    ev_hours = EventRecord(
        event_group_id="ev_t_hours",
        camera_id="cam_counter",
        start_time=datetime.now(timezone.utc).isoformat(),
        metadata_json=json.dumps({"reasons": [{"id": "outside_shop_hours"}]})
    )
    assert format_alert_headline(ev_hours, "Cash counter") == "Movement outside shop hours"

    # Test When Formatter
    when_str = format_alert_when(time.time())
    assert "Today" in when_str

    # Test Alert-Tier Event Push
    thumb_alert_file = clips_dir / "thumb_alert.jpg"
    thumb_alert_file.write_bytes(create_dummy_jpeg())
    ev_alert = make_test_event(
        "ev_t_alert",
        camera_id="cam_counter",
        tier="alert",
        clip_number=1,
        thumb_path=str(thumb_alert_file),
        reasons=[{"id": "entered_restricted_area", "watch_area_name": "Cash counter"}]
    )

    # Mock requests post to verify Telegram payload
    posted_payloads = []

    def mock_post(url, **kwargs):
        class MockResp:
            status_code = 200
            def json(self):
                return {"ok": True, "result": {"message_id": 999}}
        posted_payloads.append((url, kwargs))
        return MockResp()

    import requests
    orig_post = requests.post
    requests.post = mock_post
    try:
        # 1. Alert tier should push
        ok = push_telegram_alert(ev_alert, settings, db, "http://localhost:8000")
        assert ok is True
        assert len(posted_payloads) == 1
        url, kwargs = posted_payloads[0]
        caption = kwargs.get("data", {}).get("caption", "") or kwargs.get("json", {}).get("caption", "") or kwargs.get("json", {}).get("text", "")
        lines = caption.strip().split("\n")
        assert "Alert" in lines[0]
        assert "Cash counter" in lines[0]
        assert "Person entered Cash counter" in lines[1]
        assert "Today" in lines[2]

        # Check inline keyboard
        raw_rm = kwargs.get("data", {}).get("reply_markup") or kwargs.get("json", {}).get("reply_markup")
        reply_markup = json.loads(raw_rm) if isinstance(raw_rm, str) else raw_rm
        buttons = reply_markup.get("inline_keyboard", [[]])[0]
        assert len(buttons) == 2
        assert buttons[0]["text"] == "Open clip"
        assert f"/clips/{ev_alert.event_group_id}" in buttons[0]["url"]
        assert buttons[1]["text"] == "Not an issue"
        assert buttons[1]["callback_data"] == f"not_an_issue_{ev_alert.event_group_id}"

        # 2. Review tier MUST NOT push
        ev_review = make_test_event("ev_t_review", camera_id="cam_counter", tier="review", clip_number=2)
        posted_payloads.clear()
        ok_review = push_telegram_alert(ev_review, settings, db, "http://localhost:8000")
        assert ok_review is False
        assert len(posted_payloads) == 0  # review tier clips are silenced
    finally:
        requests.post = orig_post


def test_telegram_callback_triage_worker(env_setup):
    """Verifies that [ Not an issue ] Telegram callback query marks clip in SQLite and edits message."""
    db, settings, clips_dir = env_setup

    ev = make_test_event("ev_triage_cb", camera_id="cam_counter", tier="alert", clip_number=7)
    db.insert_event(ev)
    db.flush()

    worker = TelegramPollingWorker(bot_token=settings.telegram_bot_token, db=db)

    edited_messages = []
    answered_callbacks = []

    def mock_post(url, **kwargs):
        if "editMessageCaption" in url or "editMessageText" in url:
            edited_messages.append(kwargs.get("json", {}))
        elif "answerCallbackQuery" in url:
            answered_callbacks.append(kwargs.get("json", {}))
        class MockResp:
            status_code = 200
            def json(self):
                return {"ok": True}
        return MockResp()

    import requests
    orig_post = requests.post
    requests.post = mock_post
    try:
        # Simulate incoming callback query
        callback_update = {
            "update_id": 1001,
            "callback_query": {
                "id": "cb_12345",
                "message": {
                    "message_id": 888,
                    "chat": {"id": 123456789},
                    "caption": "🚨 Alert · Cash counter\nPerson entered Cash counter\nToday, 9:34 pm"
                },
                "data": f"not_an_issue_{ev.event_group_id}"
            }
        }
        res = worker.handle_update(callback_update)
        assert res is not None

        # DB must be updated to not_an_issue
        c = db.get_clip_by_id(ev.event_group_id)
        assert c["status"] == "not_an_issue"

        # Message caption must be edited to Appendix B format
        assert len(edited_messages) == 1
        new_caption = edited_messages[0].get("caption") or edited_messages[0].get("text") or ""
        assert "Marked as not an issue." in new_caption

        # Callback query must be answered
        assert len(answered_callbacks) == 1
        assert answered_callbacks[0]["callback_query_id"] == "cb_12345"
    finally:
        requests.post = orig_post


def test_fastapi_clips_and_evidence_endpoints(env_setup):
    """Integration test for FastAPI Phase 5 routes."""
    db, settings, clips_dir = env_setup
    client = TestClient(app)

    # Write dummy files to clips_dir
    mp4_bytes = create_dummy_mp4()
    thumb_bytes = create_dummy_jpeg()
    video_file = clips_dir / "vid1.mp4"
    thumb_file = clips_dir / "thumb1.jpg"
    video_file.write_bytes(mp4_bytes)
    thumb_file.write_bytes(thumb_bytes)

    ev = make_test_event(
        "ev_api_101",
        camera_id="cam_counter",
        tier="alert",
        clip_number=101,
        file_path="vid1.mp4",
        thumb_path="thumb1.jpg",
        sha256=hashlib.sha256(mp4_bytes).hexdigest()
    )
    db.insert_event(ev)
    db.flush()

    # 1. GET /api/clips
    res = client.get("/api/clips")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["clips"][0]["clip_number"] == 101

    # 2. GET /api/clips/flags
    res = client.get("/api/clips/flags")
    assert res.status_code == 200
    flags_data = res.json()
    assert flags_data["total"] == 1
    assert flags_data["flags"][0]["id"] == ev.event_group_id

    # 3. GET /api/clips/{id}
    res = client.get(f"/api/clips/{ev.event_group_id}")
    assert res.status_code == 200
    assert res.json()["clip_number"] == 101

    # 4. PATCH /api/clips/{id} -> mark as reviewed
    patch_res = client.patch(f"/api/clips/{ev.event_group_id}", json={"status": "reviewed"})
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "reviewed"

    # 5. PATCH /api/clips/{id} -> not an issue
    patch_res = client.patch(f"/api/clips/{ev.event_group_id}", json={
        "status": "not_an_issue",
        "feedback_reason": "camera_glitch"
    })
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "not_an_issue"

    # 6. PATCH /api/clips/{id} -> unreviewed (Undo)
    patch_res = client.patch(f"/api/clips/{ev.event_group_id}", json={"status": "unreviewed"})
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "unreviewed"

    # 7. GET /api/clips/{id}/evidence-pack
    pack_res = client.get(f"/api/clips/{ev.event_group_id}/evidence-pack")
    assert pack_res.status_code == 200
    assert "application/zip" in pack_res.headers.get("content-type", "")
    assert "attachment; filename=" in pack_res.headers.get("content-disposition", "")
    assert "VYZN-clip-101-" in pack_res.headers["content-disposition"]
    assert pack_res.headers["content-disposition"].strip('"').endswith('.zip')

    # Verify returned evidence pack bytes
    with zipfile.ZipFile(io.BytesIO(pack_res.content), "r") as zf:
        assert "clip-101.mp4" in zf.namelist()
        assert "summary.pdf" in zf.namelist()
        assert "HASH.txt" in zf.namelist()


def test_appendix_d_forbidden_words_gate():
    """Strictly assert 0 Appendix D forbidden words in Phase 5 UI & i18n files."""
    forbidden = [
        r'\btier 4\b', r'\btier 2\b', r'\bthreat index\b', r'\bthreat weight\b',
        r'\bgeofence\b', r'\bvertex\b', r'\bpolygon\b', r'\broi\b',
        r'\bpipeline\b', r'\bfalse positive\b', r'\bincident stream\b',
        r'\bcertified\b', r'\bcourt-ready\b', r'\bsection 65b\b',
        r'\bguest mode\b', r'\bzero cloud\b', r'\bcloud choke\b',
        r'\bsovereign\b', r'\b500\+\b', r'\bdirect-show\b', r'\bfar\b'
    ]

    target_files = [
        "frontend/dashboard/overview.html",
        "frontend/dashboard/overview.js",
        "frontend/dashboard/clips.html",
        "frontend/dashboard/clips.js",
        "frontend/dashboard/components/clip-drawer.js",
        "frontend/dashboard/components/flag-row.js",
        "frontend/dashboard/components/clip-card.js",
        "frontend/dashboard/locales/en.json",
    ]

    violations = []
    for rel_path in target_files:
        full_path = Path(rel_path)
        if not full_path.exists():
            continue
        content = full_path.read_text(encoding="utf-8", errors="ignore")
        for pat in forbidden:
            matches = list(re.finditer(pat, content, re.IGNORECASE))
            for m in matches:
                snippet = content[max(0, m.start() - 20):min(len(content), m.end() + 20)]
                violations.append(f"{rel_path}: Matched '{m.group(0)}' in snippet '{snippet.strip()}'")

    assert len(violations) == 0, f"Appendix D violations found:\n" + "\n".join(violations)
