"""
Standalone test runner for VYZN test suite (compatible with standard Python library).
"""

import sys
import os
import tempfile
import traceback
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_scoring import (
    test_after_hours_intruder_high_score,
    test_unclassified_motion_nuisance_penalty,
    test_hard_floor_for_valid_detection,
    test_layer_0_business_hours_suppression,
    test_layer_0_restricted_zone_trigger,
    test_point_in_polygon
)
from tests.test_tracker import (
    test_iou_calculation,
    test_tracker_continuity_and_coasting
)
from tests.test_motion_gate import test_mog2_static_vs_motion
from tests.test_database import (
    test_database_crud_operations,
    test_concurrent_multi_thread_writes
)
from tests.test_pipeline_smoke import test_pipeline_synthetic_smoke
from tests.test_api import test_api_endpoints_and_dashboard_serving
from tests.test_whatsapp import (
    test_whatsapp_simulation_delivery,
    test_whatsapp_interactive_payload_structure
)
from tests.test_cloud_sync import test_cloud_sync_worker_marks_synced
from tests.test_zones_api import test_zones_and_snapshot_api
from tests.test_cloud_backend import (

    test_dead_man_watchdog_detects_silence,
    test_cloud_webhook_heartbeat_and_triage
)
from tests.test_onnx_detector import (
    test_onnx_detector_initialization_and_fallback,
    test_detector_factory
)
from tests.test_privacy_and_dpdp import (
    test_privacy_masker_blur,
    test_privacy_masker_blackout,
    test_dpdp_audit_hash_chain,
    test_dpdp_sar_purge,
    test_dpdp_notice_generator
)
from tests.test_benchmark_suite import test_benchmark_execution
from tests.test_triage_and_metrics_api import test_triage_and_metrics_endpoints
from tests.test_adaptive_calibrator import (
    test_calibrator_sample_gating_and_bayesian_estimation,
    test_anti_gaming_slew_rate_limiter,
    test_rolling_window_decays_old_nuisance,
    test_hard_floor_inviolability_under_severe_camera_bias
)
from tests.test_ota_sync import (
    test_canonical_hash_and_hmac_tamper_detection,
    test_semantic_geometry_validation,
    test_wholesale_atomic_zone_swap_and_rollback
)
from tests.test_fleet_portal import (
    test_fleet_portal_authentication_enforcement,
    test_fleet_tenant_scoping_and_remote_config_dispatch,
    test_stolen_device_site_key_revocation,
    test_installer_key_revocation,
    test_fleet_portal_html_rendering
)
from tests.test_e2e_fleet_sync import test_end_to_end_fleet_observability_and_ota_closed_loop


def run_all():
    tests = [
        ("test_after_hours_intruder_high_score", lambda: test_after_hours_intruder_high_score()),
        ("test_unclassified_motion_nuisance_penalty", lambda: test_unclassified_motion_nuisance_penalty()),
        ("test_hard_floor_for_valid_detection", lambda: test_hard_floor_for_valid_detection()),
        ("test_layer_0_business_hours_suppression", lambda: test_layer_0_business_hours_suppression()),
        ("test_layer_0_restricted_zone_trigger", lambda: test_layer_0_restricted_zone_trigger()),
        ("test_point_in_polygon", lambda: test_point_in_polygon()),
        ("test_iou_calculation", lambda: test_iou_calculation()),
        ("test_tracker_continuity_and_coasting", lambda: test_tracker_continuity_and_coasting()),
        ("test_mog2_static_vs_motion", lambda: test_mog2_static_vs_motion()),
        ("test_database_crud_operations", lambda: with_tmp_path(test_database_crud_operations)),
        ("test_concurrent_multi_thread_writes", lambda: with_tmp_path(test_concurrent_multi_thread_writes)),
        ("test_pipeline_synthetic_smoke", lambda: with_tmp_path(test_pipeline_synthetic_smoke)),
        ("test_api_endpoints_and_dashboard_serving", lambda: with_tmp_path(test_api_endpoints_and_dashboard_serving)),
        ("test_whatsapp_simulation_delivery", lambda: test_whatsapp_simulation_delivery()),
        ("test_whatsapp_interactive_payload_structure", lambda: test_whatsapp_interactive_payload_structure()),
        ("test_cloud_sync_worker_marks_synced", lambda: with_tmp_path(test_cloud_sync_worker_marks_synced)),
        ("test_zones_and_snapshot_api", lambda: with_tmp_path(test_zones_and_snapshot_api)),
        ("test_dead_man_watchdog_detects_silence", lambda: test_dead_man_watchdog_detects_silence()),
        ("test_cloud_webhook_heartbeat_and_triage", lambda: test_cloud_webhook_heartbeat_and_triage()),
        ("test_onnx_detector_initialization_and_fallback", lambda: test_onnx_detector_initialization_and_fallback()),
        ("test_detector_factory", lambda: test_detector_factory()),
        ("test_privacy_masker_blur", lambda: test_privacy_masker_blur()),
        ("test_privacy_masker_blackout", lambda: test_privacy_masker_blackout()),
        ("test_dpdp_audit_hash_chain", lambda: test_dpdp_audit_hash_chain()),
        ("test_dpdp_sar_purge", lambda: test_dpdp_sar_purge()),
        ("test_dpdp_notice_generator", lambda: test_dpdp_notice_generator()),
        ("test_benchmark_execution", lambda: test_benchmark_execution()),
        ("test_triage_and_metrics_endpoints", lambda: test_triage_and_metrics_endpoints()),
        ("test_calibrator_sample_gating_and_bayesian_estimation", lambda: with_tmp_path(test_calibrator_sample_gating_and_bayesian_estimation)),
        ("test_anti_gaming_slew_rate_limiter", lambda: test_anti_gaming_slew_rate_limiter()),
        ("test_rolling_window_decays_old_nuisance", lambda: with_tmp_path(test_rolling_window_decays_old_nuisance)),
        ("test_hard_floor_inviolability_under_severe_camera_bias", lambda: test_hard_floor_inviolability_under_severe_camera_bias()),
        ("test_canonical_hash_and_hmac_tamper_detection", lambda: test_canonical_hash_and_hmac_tamper_detection()),
        ("test_semantic_geometry_validation", lambda: test_semantic_geometry_validation()),
        ("test_wholesale_atomic_zone_swap_and_rollback", lambda: with_tmp_path(test_wholesale_atomic_zone_swap_and_rollback)),
        ("test_fleet_portal_authentication_enforcement", lambda: test_fleet_portal_authentication_enforcement()),
        ("test_fleet_tenant_scoping_and_remote_config_dispatch", lambda: test_fleet_tenant_scoping_and_remote_config_dispatch()),
        ("test_stolen_device_site_key_revocation", lambda: test_stolen_device_site_key_revocation()),
        ("test_installer_key_revocation", lambda: test_installer_key_revocation()),
        ("test_fleet_portal_html_rendering", lambda: test_fleet_portal_html_rendering()),
        ("test_end_to_end_fleet_observability_and_ota_closed_loop", lambda: with_tmp_path(test_end_to_end_fleet_observability_and_ota_closed_loop)),
    ]


    passed = 0
    failed = 0

    print("=" * 70)
    print("VYZN AUTOMATED TEST SUITE EXECUTION")
    print("=" * 70)

    for name, test_fn in tests:
        try:
            print(f"RUNNING: {name} ... ", end="", flush=True)
            test_fn()
            print("PASSED [OK]")
            passed += 1
        except Exception as e:
            print("FAILED [ERROR]")
            traceback.print_exc()
            failed += 1

    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests.")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)


def with_tmp_path(fn):
    # ignore_cleanup_errors=True prevents Windows [WinError 32] from lingering sqlite WAL handles
    try:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        fn(Path(tmp.name))
    finally:
        try:
            tmp.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    run_all()
