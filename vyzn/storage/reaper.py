"""
Storage Reaper Daemon with 72-hour tiered retention and 85% disk safety guardrail.
"""

from __future__ import annotations
import os
import shutil
import time
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from vyzn.core.database import EventDatabase

logger = logging.getLogger("vyzn.storage.reaper")


class StorageReaperDaemon(threading.Thread):
    """
    Background daemon running periodic cleanup sweeps.
    Enforces 72h tiered retention and protects edge box from disk exhaustion.
    """

    def __init__(
        self,
        db: EventDatabase,
        data_root: Path,
        sweep_interval_sec: int = 300,
        raw_retention_hours: int = 72,
        disk_safety_threshold_pct: float = 85.0
    ):
        super().__init__(name="Storage-Reaper", daemon=True)
        self.db = db
        self.data_root = data_root
        self.sweep_interval_sec = sweep_interval_sec
        self.raw_retention_hours = raw_retention_hours
        self.disk_safety_threshold_pct = disk_safety_threshold_pct
        self.running = True

    def run(self):
        logger.info("Storage reaper daemon started.")
        while self.running:
            try:
                self.perform_sweep()
            except Exception as e:
                logger.error(f"Error during reaper sweep: {e}")

            # Sleep in small slices to allow rapid shutdown
            for _ in range(self.sweep_interval_sec):
                if not self.running:
                    break
                time.sleep(1.0)

    def check_disk_usage_pct(self) -> float:
        """Returns disk usage percentage for data directory."""
        usage = shutil.disk_usage(self.data_root)
        used_pct = (usage.used / float(usage.total)) * 100.0
        return used_pct

    def perform_sweep(self):
        usage_pct = self.check_disk_usage_pct()
        logger.info(f"Reaper sweep running. Current disk usage: {usage_pct:.1f}%")

        emergency_mode = usage_pct >= self.disk_safety_threshold_pct
        if emergency_mode:
            logger.warning(
                f"DISK SAFETY GUARDRAIL TRIGGERED: Usage {usage_pct:.1f}% exceeds threshold {self.disk_safety_threshold_pct}%! Initiating aggressive cleanup."
            )

        now = datetime.now(timezone.utc)
        retention_cutoff = (now - timedelta(hours=self.raw_retention_hours)).isoformat()

        # Query all events needing review
        events = self.db.query_events(limit=200)

        for ev in events:
            # Skip starred events
            if ev.starred:
                continue

            # Check if crossed 72h cutoff or emergency disk space trigger
            is_past_cutoff = ev.start_time < retention_cutoff

            if (is_past_cutoff or emergency_mode) and ev.status == "raw":
                if ev.score < 40:
                    # Low value noise: Delete video file
                    if ev.file_path and os.path.exists(ev.file_path):
                        try:
                            os.remove(ev.file_path)
                            logger.info(f"Purged raw clip for low-score event {ev.event_group_id} (Score: {ev.score})")
                        except OSError as e:
                            logger.error(f"Failed to delete {ev.file_path}: {e}")

                    self.db.update_event_status(ev.event_group_id, "deleted")
                    self.db.log_audit("PURGE_LOW_SCORE", ev.event_group_id, f"Score: {ev.score}")

                elif 40 <= ev.score < 70 and not emergency_mode:
                    # Medium value: Mark as compressed
                    self.db.update_event_status(ev.event_group_id, "compressed")
                    self.db.log_audit("TIER_COMPRESSED", ev.event_group_id, f"Score: {ev.score}")

    def stop(self):
        self.running = False
