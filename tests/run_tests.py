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
    test_concurrent_multi_thread_writes,
    test_db_write_guard_rejects_pre_2020_timestamps
)
from tests.test_pipeline_smoke import test_pipeline_synthetic_smoke
from tests.test_api import test_api_endpoints_and_dashboard_serving
from tests.test_whatsapp import (
    test_whatsapp_simulation_delivery,
    test_whatsapp_interactive_payload_structure,
    test_whatsapp_utility_template_structure_out_of_session,
    test_whatsapp_session_tracker_and_in_session_interactive,
    test_mobile_viewer_token_generation_and_validation
)
from tests.test_cloud_sync import test_cloud_sync_worker_marks_synced
from tests.test_zones_api import test_zones_and_snapshot_api
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
    test_hard_floor_inviolability_under_severe_camera_bias,
    test_calibrator_cannot_influence_upstream_detection
)
from tests.test_discovery import (
    test_discovery_service_model_and_probing,
    test_camera_discovery_and_adoption_endpoints
)
from tests.test_resource_governor import (
    test_resource_governor_day_night_transition,
    test_resource_governor_priority_api_stability
)
from tests.test_auth_flow import test_phase2_auth_and_telegram_flow
from tests.test_telegram_alerts import (
    test_telegram_alert_payload_structure,
    test_telegram_alert_simulation_dispatch
)
from tests.test_supabase_auth import (
    test_supabase_auth_login_valid,
    test_supabase_auth_login_invalid,
    test_supabase_auth_register_and_profile,
    test_supabase_auth_protected_me_rejects_unauthorized,
    test_camera_list_masks_credentials
)
from tests.test_appearance_and_forensics import (
    test_hsv_pixel_classification,
    test_appearance_attribute_extraction_on_crops,
    test_database_attribute_query_filtering,
    test_forensic_pack_generation_and_manifest,
    test_bandwidth_settings_api,
    test_forensic_search_endpoint
)
from tests.test_phase3_cameras import (
    test_phase3_camera_discovery_and_adoption,
    test_phase3_camera_test_probe_and_health
)
from tests.test_phase4_areas import (
    test_phase4_area_crud_and_tier_mapping,
    test_phase4_area_time_window_validation
)
from tests.test_phase5_clips import (
    test_phase5_list_clips_filter_and_pagination,
    test_phase5_download_clip_and_evidence_pack
)
from tests.test_phone_otp_and_supabase import (
    test_email_login_and_otp_dispatch,
    test_phone_verification_start_and_verify,
    test_supabase_status_endpoint
)
from tests.test_isolation_and_security import test_multi_tenant_isolation_and_security_gate


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
        ("test_db_write_guard_rejects_pre_2020_timestamps", lambda: with_tmp_path(test_db_write_guard_rejects_pre_2020_timestamps)),
        ("test_pipeline_synthetic_smoke", lambda: with_tmp_path(test_pipeline_synthetic_smoke)),
        ("test_api_endpoints_and_dashboard_serving", lambda: with_tmp_path(test_api_endpoints_and_dashboard_serving)),
        ("test_phase2_auth_and_telegram_flow", lambda: with_tmp_path(test_phase2_auth_and_telegram_flow)),
        ("test_whatsapp_simulation_delivery", lambda: test_whatsapp_simulation_delivery()),
        ("test_whatsapp_interactive_payload_structure", lambda: test_whatsapp_interactive_payload_structure()),
        ("test_whatsapp_utility_template_structure_out_of_session", lambda: test_whatsapp_utility_template_structure_out_of_session()),
        ("test_whatsapp_session_tracker_and_in_session_interactive", lambda: test_whatsapp_session_tracker_and_in_session_interactive()),
        ("test_mobile_viewer_token_generation_and_validation", lambda: test_mobile_viewer_token_generation_and_validation()),
        ("test_cloud_sync_worker_marks_synced", lambda: with_tmp_path(test_cloud_sync_worker_marks_synced)),
        ("test_zones_and_snapshot_api", lambda: with_tmp_path(test_zones_and_snapshot_api)),
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
        ("test_calibrator_cannot_influence_upstream_detection", lambda: test_calibrator_cannot_influence_upstream_detection()),
        ("test_discovery_service_model_and_probing", lambda: test_discovery_service_model_and_probing()),
        ("test_camera_discovery_and_adoption_endpoints", lambda: with_tmp_path(test_camera_discovery_and_adoption_endpoints)),
        ("test_resource_governor_day_night_transition", lambda: test_resource_governor_day_night_transition()),
        ("test_resource_governor_priority_api_stability", lambda: test_resource_governor_priority_api_stability()),
        ("test_telegram_alert_payload_structure", lambda: test_telegram_alert_payload_structure()),
        ("test_telegram_alert_simulation_dispatch", lambda: test_telegram_alert_simulation_dispatch()),
        ("test_supabase_auth_login_valid", lambda: with_tmp_path(test_supabase_auth_login_valid)),
        ("test_supabase_auth_login_invalid", lambda: with_tmp_path(test_supabase_auth_login_invalid)),
        ("test_supabase_auth_register_and_profile", lambda: with_tmp_path(test_supabase_auth_register_and_profile)),
        ("test_supabase_auth_protected_me_rejects_unauthorized", lambda: with_tmp_path(test_supabase_auth_protected_me_rejects_unauthorized)),
        ("test_camera_list_masks_credentials", lambda: with_tmp_path(test_camera_list_masks_credentials)),
        ("test_hsv_pixel_classification", lambda: test_hsv_pixel_classification()),
        ("test_appearance_attribute_extraction_on_crops", lambda: test_appearance_attribute_extraction_on_crops()),
        ("test_database_attribute_query_filtering", lambda: test_database_attribute_query_filtering()),
        ("test_forensic_pack_generation_and_manifest", lambda: test_forensic_pack_generation_and_manifest()),
        ("test_bandwidth_settings_api", lambda: test_bandwidth_settings_api()),
        ("test_forensic_search_endpoint", lambda: test_forensic_search_endpoint()),
        ("test_phase3_camera_discovery_and_adoption", lambda: with_tmp_path(test_phase3_camera_discovery_and_adoption)),
        ("test_phase3_camera_test_probe_and_health", lambda: with_tmp_path(test_phase3_camera_test_probe_and_health)),
        ("test_phase4_area_crud_and_tier_mapping", lambda: with_tmp_path(test_phase4_area_crud_and_tier_mapping)),
        ("test_phase4_area_time_window_validation", lambda: with_tmp_path(test_phase4_area_time_window_validation)),
        ("test_phase5_list_clips_filter_and_pagination", lambda: with_tmp_path(test_phase5_list_clips_filter_and_pagination)),
        ("test_phase5_download_clip_and_evidence_pack", lambda: with_tmp_path(test_phase5_download_clip_and_evidence_pack)),
        ("test_email_login_and_otp_dispatch", lambda: with_tmp_path(test_email_login_and_otp_dispatch)),
        ("test_phone_verification_start_and_verify", lambda: with_tmp_path(test_phone_verification_start_and_verify)),
        ("test_supabase_status_endpoint", lambda: with_tmp_path(test_supabase_status_endpoint)),
        ("test_multi_tenant_isolation_and_security_gate", lambda: test_multi_tenant_isolation_and_security_gate()),
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
