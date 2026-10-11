#!/usr/bin/env python3
"""
tools/score_replay.py - VYZN Scoring Replay & Calibration Analysis Tool.

Runs the ScoringEngine over stored/recorded clips and prints the tier histogram per camera.
Evaluates alignment with production targets:
  - ALERT:  ~2-5% of clips (single-digit alerts/camera/day)
  - REVIEW: ~15-30% of clips
  - LOW:    remainder (~65-80%)
Also reports verified-alert rate from user_label feedback and suggests threshold calibrations.
Never auto-applies threshold changes without manual confirmation.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Add parent directory to PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vyzn.core.database import EventDatabase
from vyzn.core.events import DetectionCandidate
from vyzn.scoring.engine import ScoringEngine
from vyzn.core.config import get_scoring_config


def run_score_replay(
    db_path: Path,
    camera_id: Optional[str] = None,
    limit: int = 1000,
    rescore: bool = False
):
    print("=" * 80)
    print(" VYZN SCORING REPLAY & CALIBRATION HARNESS (v2.0)")
    print("=" * 80)
    print(f" Database: {db_path}")
    print(f" Target Camera: {camera_id or 'ALL CAMERAS'}")
    print(f" Evaluation Limit: {limit} clips")
    print("-" * 80)

    if not db_path.exists():
        print(f"[-] Database file not found at {db_path}. Please check path.")
        return

    db = EventDatabase(db_path)
    engine = ScoringEngine()
    scoring_cfg = get_scoring_config()
    alert_thresh = scoring_cfg.get("tiers", {}).get("alert_threshold", 70)
    review_min = scoring_cfg.get("tiers", {}).get("review_min_score", 30)

    # Query events
    events_res = db.query_clips(
        camera_id=camera_id,
        limit=limit,
        status="all"
    )
    clips = events_res.get("clips", [])
    total_clips = len(clips)

    if total_clips == 0:
        print("[!] No clips found in database matching criteria.")
        return

    print(f"[+] Loaded {total_clips} clips for replay analysis.\n")

    # Track statistics per camera
    camera_stats: Dict[str, Dict[str, Any]] = {}
    total_tiers = {"alert": 0, "review": 0, "low": 0}
    feedback_stats = {
        "true_positives": 0,
        "false_alarms": 0,
        "missed_alerts": 0,
        "total_labeled": 0
    }

    before_after_samples = []

    for clip in clips:
        cam = clip.get("camera_id") or clip.get("cameraId", "unknown")
        if cam not in camera_stats:
            camera_stats[cam] = {
                "total": 0,
                "tiers": {"alert": 0, "review": 0, "low": 0},
                "scores": [],
                "user_labels": {}
            }

        camera_stats[cam]["total"] += 1

        stored_score = clip.get("score", 0)
        stored_tier = (clip.get("tier") or "low").lower()

        # If rescore flag is active, re-evaluate candidate using ScoringEngine v2.0
        if rescore:
            meta = clip.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}

            objs = clip.get("objects", [])
            primary_cls = objs[0].get("cls", "unclassified") if objs else clip.get("primary_object", "unclassified")
            conf = objs[0].get("confidence", 0.70) if objs else 0.50

            cand = DetectionCandidate(
                camera_id=cam,
                object_type=primary_cls,
                confidence=conf,
                motion_ratio=float(meta.get("motion_ratio", 0.03)),
                track_duration_sec=float(clip.get("durationSec", clip.get("duration_seconds", 5.0))),
                bounding_box=[0.1, 0.1, 0.4, 0.6],
                is_after_hours=bool("outside_shop_hours" in str(clip.get("reasons", []))),
                is_in_restricted_zone=bool(clip.get("areaName") == "Restricted Area"),
                is_night_ir=bool(clip.get("is_night_ir", False))
            )
            v2_score, should_alert, v2_breakdown = engine.evaluate(cand)
            v2_tier = v2_breakdown["tier"]
            current_tier = v2_tier
            current_score = v2_score

            if len(before_after_samples) < 10:
                before_after_samples.append({
                    "id": clip.get("id"),
                    "cam": cam,
                    "obj": primary_cls,
                    "old_score": stored_score,
                    "old_tier": stored_tier,
                    "new_score": v2_score,
                    "new_tier": v2_tier
                })
        else:
            current_tier = stored_tier
            current_score = stored_score

        if current_tier not in total_tiers:
            current_tier = "low"

        camera_stats[cam]["tiers"][current_tier] += 1
        total_tiers[current_tier] += 1
        camera_stats[cam]["scores"].append(current_score)

        # Track user feedback labels if available
        user_lbl = clip.get("user_label") or clip.get("user_triage")
        if user_lbl and user_lbl not in ("unreviewed", None):
            feedback_stats["total_labeled"] += 1
            camera_stats[cam]["user_labels"][user_lbl] = camera_stats[cam]["user_labels"].get(user_lbl, 0) + 1
            if user_lbl in ("alert", "confirmed_threat"):
                if current_tier == "alert":
                    feedback_stats["true_positives"] += 1
                else:
                    feedback_stats["missed_alerts"] += 1
            elif user_lbl in ("false_alarm", "false_positive", "not_an_issue"):
                if current_tier == "alert":
                    feedback_stats["false_alarms"] += 1

    # 1. Print Per-Camera Tier Distribution Table
    print(f"{'CAMERA':<18} | {'TOTAL':<6} | {'ALERT (>=70)':<16} | {'REVIEW (30-69)':<16} | {'LOW (<30)':<16}")
    print("-" * 80)
    for cam, st in camera_stats.items():
        tot = st["total"]
        a_cnt = st["tiers"]["alert"]
        r_cnt = st["tiers"]["review"]
        l_cnt = st["tiers"]["low"]
        a_pct = (a_cnt / tot * 100.0) if tot > 0 else 0.0
        r_pct = (r_cnt / tot * 100.0) if tot > 0 else 0.0
        l_pct = (l_cnt / tot * 100.0) if tot > 0 else 0.0

        print(
            f"{cam:<18} | {tot:<6} | {a_cnt:>4} ({a_pct:>5.1f}%)    | {r_cnt:>4} ({r_pct:>5.1f}%)    | {l_cnt:>4} ({l_pct:>5.1f}%)"
        )
    print("-" * 80)

    # 2. Global Fleet Summary
    tot_all = total_clips
    ga_pct = (total_tiers["alert"] / tot_all * 100.0) if tot_all > 0 else 0.0
    gr_pct = (total_tiers["review"] / tot_all * 100.0) if tot_all > 0 else 0.0
    gl_pct = (total_tiers["low"] / tot_all * 100.0) if tot_all > 0 else 0.0

    print(f"{'FLEET TOTAL':<18} | {tot_all:<6} | {total_tiers['alert']:>4} ({ga_pct:>5.1f}%)    | {total_tiers['review']:>4} ({gr_pct:>5.1f}%)    | {total_tiers['low']:>4} ({gl_pct:>5.1f}%)")
    print("=" * 80)

    # 3. Target Alignment Analysis
    print("\nTARGET ALIGNMENT CHECK:")
    print(f" - ALERT Target:   2.0% - 5.0%   --> Actual: {ga_pct:.1f}% ", end="")
    if 2.0 <= ga_pct <= 5.0:
        print("[OPTIMAL]")
    elif ga_pct < 2.0:
        print("[LOW - Alerting may be overly strict]")
    else:
        print("[HIGH - Potential over-scoring/alert fatigue]")

    print(f" - REVIEW Target: 15.0% - 30.0%  --> Actual: {gr_pct:.1f}% ", end="")
    if 15.0 <= gr_pct <= 30.0:
        print("[OPTIMAL]")
    else:
        print("[ACCEPTABLE]")

    print(f" - LOW Target:    65.0% - 80.0%  --> Actual: {gl_pct:.1f}%")

    # 4. User Label Accuracy & Feedback Metrics
    print("\nUSER FEEDBACK CALIBRATION METRICS:")
    if feedback_stats["total_labeled"] > 0:
        tp = feedback_stats["true_positives"]
        fa = feedback_stats["false_alarms"]
        ma = feedback_stats["missed_alerts"]
        labeled = feedback_stats["total_labeled"]
        precision = (tp / (tp + fa) * 100.0) if (tp + fa) > 0 else 100.0
        print(f" - Total Labeled Events: {labeled}")
        print(f" - True Positive Alerts: {tp}")
        print(f" - False Alarms:         {fa}")
        print(f" - Missed Alerts:        {ma}")
        print(f" - Verified Alert Precision: {precision:.1f}%")
    else:
        print(" - No user triage labels recorded yet. Collect user feedback in UI to tune precision.")

    # 5. Suggested Threshold Actions
    print("\nSUGGESTED CALIBRATIONS (Advisory Only - Never Auto-Applied):")
    if ga_pct > 6.0:
        print(f" [!] Alert rate ({ga_pct:.1f}%) exceeds 5% target ceiling.")
        print(f"     Suggestion: Raise alert_threshold from {alert_thresh} -> {min(85, alert_thresh + 5)}")
        print("     Or adjust per-camera bias in config/scoring.json.")
    elif ga_pct < 1.0 and total_clips > 50:
        print(f" [!] Alert rate ({ga_pct:.1f}%) is below 2% floor.")
        print(f"     Suggestion: Lower alert_threshold from {alert_thresh} -> {max(65, alert_thresh - 5)}")
    else:
        print(" [v] Current scoring configuration aligns with enterprise alert tier guidelines.")

    if before_after_samples:
        print("\nSAMPLE RESCORING COMPARISON (Old v1 -> New v2):")
        print(f"{'CLIP ID':<20} | {'CAMERA':<12} | {'OBJECT':<12} | {'OLD SCORE':<10} | {'NEW SCORE':<10} | {'TIER CHANGE'}")
        print("-" * 80)
        for s in before_after_samples:
            tc = f"{s['old_tier'].upper()} -> {s['new_tier'].upper()}"
            print(f"{s['id']:<20} | {s['cam']:<12} | {s['obj']:<12} | {s['old_score']:<10} | {s['new_score']:<10} | {tc}")
        print("-" * 80)

    print("\nScore replay completed successfully.\n")


def main():
    parser = argparse.ArgumentParser(description="VYZN Scoring Replay and Tier Calibration Analysis")
    parser.add_argument("--db", type=str, default="./data/clips/index.db", help="Path to clips SQLite DB")
    parser.add_argument("--camera", type=str, default=None, help="Specific camera ID to filter")
    parser.add_argument("--limit", type=int, default=1000, help="Max clips to analyze")
    parser.add_argument("--rescore", action="store_true", help="Re-evaluate candidate inputs through v2 engine")
    args = parser.parse_args()

    run_score_replay(
        db_path=Path(args.db),
        camera_id=args.camera,
        limit=args.limit,
        rescore=args.rescore
    )


if __name__ == "__main__":
    main()
