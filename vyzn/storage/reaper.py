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
    Background storage manager daemon enforcing FIFO quota rotation and 72h retention.
    Enforces maximum storage capacity (GB) and 85% disk safety threshold.
    """

    def __init__(
        self,
        db: EventDatabase,
        data_root: Path,
        sweep_interval_sec: int = 300,
        raw_retention_hours: int = 72,
        disk_safety_threshold_pct: float = 85.0,
        max_quota_gb: float = 20.0
    ):
        super().__init__(name="Storage-Reaper", daemon=True)
        self.db = db
        self.data_root = data_root
        self.sweep_interval_sec = sweep_interval_sec
        self.raw_retention_hours = raw_retention_hours
        self.disk_safety_threshold_pct = disk_safety_threshold_pct
        self.max_quota_gb = max_quota_gb
        self.running = True

    def run(self):
        logger.info(f"Storage manager daemon started (Quota: {self.max_quota_gb:.1f} GB, Guardrail: {self.disk_safety_threshold_pct}%).")
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
        """Returns host disk usage percentage for the storage partition."""
        usage = shutil.disk_usage(self.data_root)
        return (usage.used / float(usage.total)) * 100.0

    def get_total_video_bytes(self) -> int:
        """Calculates total size in bytes of all recorded MP4 and JPEG evidence on disk."""
        total = 0
        raw_dir = self.data_root / "raw"
        if raw_dir.exists():
            for root, _, files in os.walk(raw_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        return total

    def perform_sweep(self):
        """
        Dual-Criteria Garbage Collection:
        1. FIFO Quota Rotation: If total recorded bytes exceed max_quota_gb,
           purges oldest un-starred MP4s first until below target ceiling.
        2. Emergency Guardrail: If host disk usage >= 85%, aggressively purges oldest un-starred events.
        3. 72-Hour Tiered Retention: Compresses or deletes un-starred noise older than retention window.
        """
        usage_pct = self.check_disk_usage_pct()
        total_bytes = self.get_total_video_bytes()
        max_quota_bytes = int(self.max_quota_gb * (1024 ** 3))

        logger.info(
            f"Storage sweep running. Partition usage: {usage_pct:.1f}%, Video data: {total_bytes / (1024**2):.1f} MB / {self.max_quota_gb*1024:.0f} MB quota."
        )

        emergency_disk = usage_pct >= self.disk_safety_threshold_pct
        quota_exceeded = total_bytes > max_quota_bytes

        # --- A. FIFO Quota & Emergency Rotation ---
        if quota_exceeded or emergency_disk:
            trigger_reason = "DISK_GUARDRAIL_TRIGGERED" if emergency_disk else "MAX_QUOTA_EXCEEDED"
            logger.warning(
                f"{trigger_reason}: Used {total_bytes / (1024**3):.2f} GB (max: {self.max_quota_gb:.1f} GB, disk: {usage_pct:.1f}%). Initiating FIFO purge of oldest clips."
            )

            # Target ceiling: reclaim down to 85% of quota
            target_bytes = int(max_quota_bytes * 0.85)

            # Fetch oldest events in strict FIFO order (ORDER BY start_time ASC)
            oldest_events = self.db.query_events(limit=500)
            oldest_events.sort(key=lambda e: e.start_time)

            for ev in oldest_events:
                if total_bytes <= target_bytes and not emergency_disk:
                    break
                if ev.starred:
                    continue  # Starred evidence is permanently protected from FIFO reaper

                # Delete physical video file and thumbnail
                freed = 0
                if ev.file_path and os.path.exists(ev.file_path):
                    try:
                        freed += os.path.getsize(ev.file_path)
                        os.remove(ev.file_path)
                    except OSError:
                        pass

                if ev.thumb_path and os.path.exists(ev.thumb_path):
                    try:
                        freed += os.path.getsize(ev.thumb_path)
                        os.remove(ev.thumb_path)
                    except OSError:
                        pass

                total_bytes = max(0, total_bytes - freed)
                self.db.update_event_status(ev.event_group_id, "deleted")
                self.db.log_audit("FIFO_QUOTA_PURGE", ev.event_group_id, f"Freed {freed // 1024} KB. Reason: {trigger_reason}")

        # --- B. Standard 72h Tiered Retention ---
        now = datetime.now(timezone.utc)
        retention_cutoff = (now - timedelta(hours=self.raw_retention_hours)).isoformat()
        recent_events = self.db.query_events(limit=200)

        for ev in recent_events:
            if ev.starred or ev.status == "deleted":
                continue

            is_past_cutoff = ev.start_time < retention_cutoff
            if is_past_cutoff and ev.status == "raw":
                if ev.score < 40:
                    if ev.file_path and os.path.exists(ev.file_path):
                        try:
                            os.remove(ev.file_path)
                        except OSError:
                            pass
                    self.db.update_event_status(ev.event_group_id, "deleted")
                    self.db.log_audit("PURGE_LOW_SCORE", ev.event_group_id, f"Score: {ev.score}")
                elif 40 <= ev.score < 70:
                    self.db.update_event_status(ev.event_group_id, "compressed")
                    self.db.log_audit("TIER_COMPRESSED", ev.event_group_id, f"Score: {ev.score}")

    def stop(self):
        self.running = False


# Alias for clean architecture
StorageManager = StorageReaperDaemon
