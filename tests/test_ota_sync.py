"""
Unit tests for OTA Configuration Synchronization:
Verifies HMAC signature tamper detection, semantic geometry validation,
wholesale atomic list swap, and automatic rollback to last-known-good on failure.
"""

from pathlib import Path
from vyzn.core.config import EdgeSettings, CameraConfig, ZonePolygon
from vyzn.core.database import EventDatabase
from vyzn.telemetry.ota_sync import (
    compute_config_hash,
    verify_hmac_signature,
    validate_semantic_config,
    OTASyncWorker
)
from vyzn_cloud.security import generate_config_hmac


def test_canonical_hash_and_hmac_tamper_detection():
    secret = "test_shared_secret_4491"
    valid_config = {
        "alert_score_threshold": 75,
        "cameras": {
            "cam_front": {
                "restricted_zones": [
                    {"name": "cash_drawer", "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]]}
                ]
            }
        }
    }

    # Generate legitimate HMAC
    signature = generate_config_hmac("site_test", valid_config)
    # Patch site secret for verification
    assert verify_hmac_signature("fallback_default_secret_2026", valid_config, signature) is True

    # Tamper with coordinate by 0.01 (attacker stealthily shrinking zone)
    tampered_config = {
        "alert_score_threshold": 75,
        "cameras": {
            "cam_front": {
                "restricted_zones": [
                    {"name": "cash_drawer", "points": [[0.1, 0.1], [0.39, 0.1], [0.4, 0.4], [0.1, 0.4]]}
                ]
            }
        }
    }
    # Tampered config MUST fail verification
    assert verify_hmac_signature("fallback_default_secret_2026", tampered_config, signature) is False


def test_semantic_geometry_validation():
    # 1. Reject < 3 points
    bad_points = {
        "alert_score_threshold": 70,
        "cameras": {
            "cam_1": {"restricted_zones": [{"name": "line", "points": [[0.1, 0.1], [0.9, 0.9]]}]}
        }
    }
    try:
        validate_semantic_config(bad_points)
        assert False, "Should have rejected < 3 points"
    except ValueError as e:
        assert "< 3 vertices" in str(e)

    # 2. Reject out of bounds coordinates
    oob_points = {
        "alert_score_threshold": 70,
        "cameras": {
            "cam_1": {"restricted_zones": [{"name": "oob", "points": [[-0.2, 0.1], [0.5, 0.1], [0.5, 0.5]]}]}
        }
    }
    try:
        validate_semantic_config(oob_points)
        assert False, "Should have rejected out of bounds coordinate"
    except ValueError as e:
        assert "outside normalized range" in str(e)

    # 3. Reject degenerate zero-area polygon
    collinear = {
        "alert_score_threshold": 70,
        "cameras": {
            "cam_1": {"restricted_zones": [{"name": "collinear", "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]]}]}
        }
    }
    try:
        validate_semantic_config(collinear)
        assert False, "Should have rejected zero-area polygon"
    except ValueError as e:
        assert "near-zero area" in str(e)

    # 4. Reject dangerous threshold (< 50 or > 80)
    bad_thresh_low = {"alert_score_threshold": 20, "cameras": {}}
    try:
        validate_semantic_config(bad_thresh_low)
        assert False, "Should have rejected low threshold"
    except ValueError as e:
        assert "outside safe operating bounds" in str(e)

    bad_thresh_high = {"alert_score_threshold": 95, "cameras": {}}
    try:
        validate_semantic_config(bad_thresh_high)
        assert False, "Should have rejected high threshold"
    except ValueError as e:
        assert "outside safe operating bounds" in str(e)


def test_wholesale_atomic_zone_swap_and_rollback(tmp_path):
    # Setup mock pipeline and settings
    cam = CameraConfig(
        camera_id="cam_01",
        name="Front",
        rtsp_url="rtsp://dummy",
        restricted_zones=[ZonePolygon(name="old_zone", points=[[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]])]
    )
    settings = EdgeSettings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        cameras=[cam]
    )
    db = EventDatabase(settings.db_path)

    class MockScoringEngine:
        alert_threshold = 70

    class MockPipeline:
        def __init__(self, s):
            self.settings = s
            self.scoring_engine = MockScoringEngine()
            self.update_calls = []

        def update_camera_zones(self, camera_id, zones):
            self.update_calls.append((camera_id, zones))
            for idx, c in enumerate(self.settings.cameras):
                if c.camera_id == camera_id:
                    new_cam = CameraConfig(
                        camera_id=c.camera_id,
                        name=c.name,
                        rtsp_url=c.rtsp_url,
                        restricted_zones=list(zones)
                    )
                    new_cams = list(self.settings.cameras)
                    new_cams[idx] = new_cam
                    self.settings.cameras = new_cams

    pipeline = MockPipeline(settings)
    worker = OTASyncWorker(
        settings=settings,
        pipeline=pipeline,
        db=db,
        config_path=tmp_path / "zones.yaml"
    )

    # Create dummy initial file
    worker.config_path.write_text("initial_config: true\n")

    # 1. Apply Valid OTA Payload
    new_zones = [[0.6, 0.6], [0.9, 0.6], [0.9, 0.9], [0.6, 0.9]]
    ota_payload = {
        "config_version": 2,
        "config": {
            "alert_score_threshold": 80,
            "cameras": {
                "cam_01": {
                    "restricted_zones": [{"name": "safe_vault", "points": new_zones}]
                }
            }
        }
    }
    ota_payload["config_hash"] = compute_config_hash(ota_payload["config"])
    ota_payload["signature"] = generate_config_hmac("site_local_default", ota_payload["config"])

    success = worker.apply_ota_payload(ota_payload)
    assert success is True
    assert settings.alert_score_threshold == 80
    assert pipeline.scoring_engine.alert_threshold == 80
    assert settings.cameras[0].restricted_zones[0].name == "safe_vault"
    assert worker.current_config_version == 2

    # Verify audit log entry
    audits = db.fetch_all("SELECT action, details FROM audit_log WHERE action = 'OTA_CONFIG_APPLIED'")
    assert len(audits) == 1
    assert "Version: 2" in audits[0]["details"]

    # 2. Test Rollback to Last-Known-Good on Runtime Failure
    class FailingPipeline(MockPipeline):
        def update_camera_zones(self, camera_id, zones):
            raise RuntimeError("Simulated camera hardware lockup during reload")

    failing_pipeline = FailingPipeline(settings)
    failing_worker = OTASyncWorker(
        settings=settings,
        pipeline=failing_pipeline,
        db=db,
        config_path=tmp_path / "zones.yaml"
    )
    fail_payload = {
        "config_version": 3,
        "config": {
            "alert_score_threshold": 78,
            "cameras": {
                "cam_01": {
                    "restricted_zones": [{"name": "crash_zone", "points": new_zones}]
                }
            }
        }
    }
    fail_payload["config_hash"] = compute_config_hash(fail_payload["config"])
    fail_payload["signature"] = generate_config_hmac("site_local_default", fail_payload["config"])

    fail_success = failing_worker.apply_ota_payload(fail_payload)
    assert fail_success is False, "Expected failure on crashing pipeline"

    # Verify rollback was logged
    rb_audits = db.fetch_all("SELECT action FROM audit_log WHERE action = 'OTA_ROLLBACK_TRIGGERED'")
    assert len(rb_audits) == 1

    db.close()