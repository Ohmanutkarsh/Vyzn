import os
import sys
import tempfile
from pathlib import Path
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vyzn.privacy.dpdp import PrivacyMasker, DPDPAuditEngine, generate_dpdp_notice
from vyzn.core.database import EventDatabase
from vyzn.core.events import EventRecord


def test_privacy_masker_blur():
    masker = PrivacyMasker(blur_kernel=31)
    frame = np.full((360, 640, 3), 100, dtype=np.uint8)
    # Add a high contrast patch inside the zone to test blur
    frame[50:150, 50:150] = 250

    # Define normalized polygon covering [0.1, 0.1] to [0.5, 0.5]
    polygon = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]]
    masked = masker.apply_mask(frame, [polygon], mode="blur")

    # Outside zone should be identical
    assert np.array_equal(frame[300:350, 500:600], masked[300:350, 500:600])

    # Inside zone, sharp edges should be smoothed/blurred
    assert not np.array_equal(frame[50:150, 50:150], masked[50:150, 50:150])


def test_privacy_masker_blackout():
    masker = PrivacyMasker()
    frame = np.full((360, 640, 3), 150, dtype=np.uint8)
    polygon = [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4], [0.2, 0.4]]
    masked = masker.apply_mask(frame, [polygon], mode="blackout")

    # Check center of masked region is 0
    center_y, center_x = int(360 * 0.3), int(640 * 0.3)
    assert np.all(masked[center_y, center_x] == 0)


def test_dpdp_audit_hash_chain():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        audit_file = os.path.join(tmpdir, "audit.jsonl")
        engine = DPDPAuditEngine(audit_file=audit_file)

        e1 = engine.log_action("ACCESS", "technician_01", {"cam": "cam_corridor"})
        e2 = engine.log_action("EXPORT", "shop_owner", {"event": "ev_123"})

        assert e1["prev_hash"] == "GENESIS_BLOCK_00000000000000000000000000000000"
        assert e2["prev_hash"] == e1["current_hash"]


def test_dpdp_sar_purge():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        audit_file = os.path.join(tmpdir, "audit.jsonl")
        db = EventDatabase(db_path)
        engine = DPDPAuditEngine(audit_file=audit_file)

        # Create dummy file to purge
        dummy_clip = Path(tmpdir) / "clip_test.mp4"
        dummy_clip.write_bytes(b"DUMMY_VIDEO_DATA_FOR_PURGE")

        ev = EventRecord(
            event_group_id="ev_purge_01",
            camera_id="cam_corridor",
            start_time="2026-09-01T10:00:00Z",
            object_type="person",
            confidence=0.85,
            score=80,
            file_path=str(dummy_clip),
            thumb_path=""
        )
        db.insert_event(ev)
        import time
        time.sleep(0.5)

        purged_count = engine.execute_sar_purge(db, camera_id="cam_corridor", actor="DPO_ADMIN")
        assert purged_count == 1
        assert not dummy_clip.exists()

        # Check DB status is purged
        purged_ev = db.get_event("ev_purge_01")
        assert purged_ev.status == "purged"
        db.close()


def test_dpdp_notice_generator():
    html = generate_dpdp_notice(business_name="Sharma Supermarket", retention_hours=72)
    assert "DPDP ACT 2023 COMPLIANT" in html
    assert "Sharma Supermarket" in html
    assert "72 hours" in html
    assert "CCTV NOTICE" in html



if __name__ == "__main__":
    test_privacy_masker_blur()
    test_privacy_masker_blackout()
    test_dpdp_audit_hash_chain()
    test_dpdp_sar_purge()
    test_dpdp_notice_generator()
    print("DPDP & Privacy tests passed!")
