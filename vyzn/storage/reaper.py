# ==============================================================================
# VYZN STORAGE REAPER DAEMON (THE AUTOMATIC HARD DRIVE CLEANER)
#
# WHY THIS EXISTS (FOR NON-PROGRAMMERS):
# CCTV cameras record massive amounts of video data every single day. If we never
# deleted old, useless footage (like trees blowing in the wind), your hard drive
# would fill up in a week and crash the whole computer.
#
# The "Storage Reaper" runs quietly in the background like an automatic janitor:
# 1. 72-Hour Rule: Any low-importance footage (Score < 30) is deleted after 72 hours.
# 2. Safety Rule: Important clips (Alerts, Reviews, or Starred clips) are KEPT SAFE.
# 3. Emergency Guardrail: If your hard drive hits 85% full, it cleans up older clips
#    first so the cameras never stop recording.
# ==============================================================================

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


# ==============================================================================
# CLASS: StorageReaperDaemon
# A "daemon thread" means this runs in the background 24/7 without slowing down
# the live camera video or the website.
# ==============================================================================
class StorageReaperDaemon(threading.Thread):
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
        self.db = db                                     # Connects to our SQLite event database
        self.data_root = data_root                       # Folder where videos (.mp4) are saved
        self.sweep_interval_sec = sweep_interval_sec     # Runs every 5 minutes (300 seconds)
        self.raw_retention_hours = raw_retention_hours   # 72 hours default retention
        self.disk_safety_threshold_pct = disk_safety_threshold_pct # 85% disk safety guardrail
        self.max_quota_gb = max_quota_gb                 # Maximum space allowed for video clips (e.g., 20 GB)
        self.running = True

    # --------------------------------------------------------------------------
    # The Background Loop: Runs every few minutes while VYZN is active
    # --------------------------------------------------------------------------
    def run(self):
        logger.info(f"Storage manager daemon started (Quota: {self.max_quota_gb:.1f} GB, Guardrail: {self.disk_safety_threshold_pct}%).")
        while self.running:
            try:
                # Perform the cleanup check
                self.perform_sweep()
            except Exception as e:
                logger.error(f"Error during reaper sweep: {e}")

            # Wait 5 minutes before checking again (can be stopped quickly if shutting down)
            for _ in range(self.sweep_interval_sec):
                if not self.running:
                    break
                time.sleep(1.0)

    # --------------------------------------------------------------------------
    # Helper: Check how full the hard drive is (e.g. 74% full)
    # --------------------------------------------------------------------------
    def check_disk_usage_pct(self) -> float:
        usage = shutil.disk_usage(self.data_root)
        return (usage.used / float(usage.total)) * 100.0

    # --------------------------------------------------------------------------
    # Helper: Add up the total size of all saved video files (.mp4) in bytes
    # --------------------------------------------------------------------------
    def get_total_video_bytes(self) -> int:
        total = 0
        for sub in ("full_footage", "clips", "raw"):
            target_dir = self.data_root / sub
            if target_dir.exists():
                for root, _, files in os.walk(target_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            total += os.path.getsize(fp)
                        except OSError:
                            pass
        return total

    # ==========================================================================
    # purge_expired_full_footage(): 72-Hour Continuous Whole Footage Purge
    # --------------------------------------------------------------------------
    # Per user instruction:
    # 1. Whole continuous footage is retained for strictly 72 hours.
    # 2. After 72 hours, continuous footage files are automatically deleted.
    # 3. Only the last 72 hours of continuous footage are kept.
    # 4. Cut incident clips (Score >= 30) are kept lifelong in 'clips/'.
    # ==========================================================================
    def purge_expired_full_footage(self) -> int:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()
        retention_seconds = float(self.raw_retention_hours * 3600.0)
        freed_bytes = 0
        deleted_count = 0

        for folder_name in ("full_footage", "raw"):
            target_dir = self.data_root / folder_name
            if not target_dir.exists():
                continue

            for root, dirs, files in os.walk(target_dir, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(fp)
                        file_age = now_ts - mtime
                        is_expired = file_age > retention_seconds
                        if not is_expired:
                            parent_name = os.path.basename(root)
                            try:
                                folder_dt = datetime.strptime(parent_name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                                if (now - folder_dt).total_seconds() > retention_seconds:
                                    is_expired = True
                            except ValueError:
                                pass

                        if is_expired:
                            size = os.path.getsize(fp)
                            os.remove(fp)
                            freed_bytes += size
                            deleted_count += 1
                            logger.info(f"Purged expired continuous footage (> {self.raw_retention_hours}h): {fp} ({size // 1024} KB)")
                    except OSError as e:
                        logger.warning(f"Failed to remove expired continuous footage {fp}: {e}")

                # Clean up empty date or camera directories
                try:
                    if not os.listdir(root) and os.path.abspath(root) != os.path.abspath(str(target_dir)):
                        os.rmdir(root)
                except OSError:
                    pass

        if deleted_count > 0:
            self.db.log_audit(
                "PURGE_FULL_FOOTAGE_72H",
                "system",
                f"Auto-deleted {deleted_count} continuous footage files older than {self.raw_retention_hours}h (Freed: {freed_bytes // (1024*1024)} MB)"
            )
        return freed_bytes

    # ==========================================================================
    # perform_sweep(): The Cleanup Brain
    # This executes three distinct checks:
    # 1. 72-HOUR CONTINUOUS FOOTAGE PURGE: Deletes whole camera footage older than 72 hours.
    # 2. EMERGENCY ROTATION: If hard drive is critically full (>= 85%), purges oldest
    #    continuous footage first, followed by unstarred low-priority clips.
    # 3. 72-HOUR LOW-TIER PURGE: Purges any expired low-tier clips.
    #    All cut clips (Score >= 30) have lifelong retention and are NEVER expired.
    # ==========================================================================
    def perform_sweep(self):
        # --- STEP 1: Standard 72-Hour Continuous Whole Footage Purge ---
        self.purge_expired_full_footage()

        usage_pct = self.check_disk_usage_pct()
        total_bytes = self.get_total_video_bytes()
        max_quota_bytes = int(self.max_quota_gb * (1024 ** 3))

        logger.info(
            f"Storage sweep running. Partition usage: {usage_pct:.1f}%, Video data: {total_bytes / (1024**2):.1f} MB / {self.max_quota_gb*1024:.0f} MB quota."
        )

        emergency_disk = usage_pct >= self.disk_safety_threshold_pct
        quota_exceeded = total_bytes > max_quota_bytes

        # --- STEP 2: Emergency Cleanup If Hard Drive Is Too Full ---
        # Prioritize purging oldest continuous full footage first before touching cut incident clips!
        if quota_exceeded or emergency_disk:
            trigger_reason = "DISK_GUARDRAIL_TRIGGERED" if emergency_disk else "MAX_QUOTA_EXCEEDED"
            logger.warning(
                f"{trigger_reason}: Used {total_bytes / (1024**3):.2f} GB (max: {self.max_quota_gb:.1f} GB, disk: {usage_pct:.1f}%). Initiating emergency FIFO purge."
            )

            target_bytes = int(max_quota_bytes * 0.85)

            # Sub-step 2A: Emergency purge of oldest continuous footage
            for sub in ("full_footage", "raw"):
                if total_bytes <= target_bytes and not emergency_disk:
                    break
                sub_dir = self.data_root / sub
                if not sub_dir.exists():
                    continue
                footage_files = []
                for root, _, files in os.walk(sub_dir):
                    for f in files:
                        p = os.path.join(root, f)
                        try:
                            footage_files.append((p, os.path.getmtime(p), os.path.getsize(p)))
                        except OSError:
                            pass
                footage_files.sort(key=lambda x: x[1])  # oldest first
                for fp, _, fsize in footage_files:
                    if total_bytes <= target_bytes and not emergency_disk:
                        break
                    try:
                        os.remove(fp)
                        total_bytes = max(0, total_bytes - fsize)
                        self.db.log_audit("FIFO_EMERGENCY_FOOTAGE_PURGE", "system", f"Emergency purged continuous footage {fp} ({fsize // 1024} KB)")
                    except OSError:
                        pass
                usage_pct = self.check_disk_usage_pct()
                emergency_disk = usage_pct >= self.disk_safety_threshold_pct

            # Sub-step 2B: If still exceeded, FIFO purge of unstarred/unpinned events
            if quota_exceeded or emergency_disk:
                oldest_events = self.db.query_events(limit=500)
                oldest_events.sort(key=lambda e: e.start_time)

                for ev in oldest_events:
                    if total_bytes <= target_bytes and not emergency_disk:
                        break
                    if ev.starred or getattr(ev, "is_pinned", 0):
                        continue

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
                    usage_pct = self.check_disk_usage_pct()
                    emergency_disk = usage_pct >= self.disk_safety_threshold_pct

        # --- STEP 3: Standard 72-Hour Low-Tier Database Purge ---
        # Note: Only 'low' tier clips expire. Cut clips (Score >= 30, tier 'review' or 'alert')
        # are kept lifelong and are NEVER deleted by this routine!
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        retention_cutoff = (now - timedelta(hours=self.raw_retention_hours)).isoformat()

        conn = self.db._get_read_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT event_group_id, file_path, thumb_path, score, tier, is_pinned, starred, expires_at_ms, start_time
                FROM events
                WHERE tier = 'low'
                  AND status != 'deleted'
                  AND is_pinned = 0
                  AND starred = 0
                  AND (
                    (expires_at_ms IS NOT NULL AND expires_at_ms <= ?)
                    OR (expires_at_ms IS NULL AND start_time < ?)
                  )
                LIMIT 300
            """, (now_ms, retention_cutoff))
            expired_low_rows = cursor.fetchall()
        finally:
            conn.close()

        for row in expired_low_rows:
            ev_id = row["event_group_id"]
            fp = row["file_path"]
            tp = row["thumb_path"]

            freed = 0
            if fp and os.path.exists(fp):
                try:
                    freed += os.path.getsize(fp)
                    os.remove(fp)
                except OSError:
                    pass
            if tp and os.path.exists(tp):
                try:
                    freed += os.path.getsize(tp)
                    os.remove(tp)
                except OSError:
                    pass

            self.db.update_event_status(ev_id, "deleted")
            self.db.log_audit("PURGE_LOW_TIER_72H", ev_id, f"Auto-deleted expired low-tier clip (Score: {row['score']}, Freed: {freed // 1024} KB)")

    def stop(self):
        self.running = False


# Alias for clean architecture
StorageManager = StorageReaperDaemon
